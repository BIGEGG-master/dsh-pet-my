# -*- coding: utf-8 -*-
"""右键菜单「查看记忆卡」：把深层记忆（``memory.json``）摊开给人看。

**这里不是第二个记忆系统**：面板读的就是 ``ChatMemory.load()`` 那一份条目，
显示的层 / 命中次数 / 日期都是记忆模块自己的字段，删除走 ``ChatMemory.remove``。
它做的事只有三件：聚合（多角色）、把照片附件显示出来、提供搜索与按层筛选。

照片是记忆条目的一部分（``photo`` 字段 + ``memory-photos/`` 目录），由她自己
判断要不要记（``pet/chat/photo_memory.py``）——面板不提供"写一条"。
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QImageReader, QPalette, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import memory_card as cards_mod

log = logging.getLogger(__name__)

_THUMB = QSize(150, 116)
_GRID = QSize(166, 186)

#: 层筛选下拉的选项（与记忆模块的层名一一对应）。
_LAYER_CHOICES = (
    ("全部", "all"),
    ("偏好", "user"),
    ("事实", "fact"),
    ("教训", "lesson"),
    ("话题", "topic"),
)


def _stylesheet(widget: QWidget) -> str:
    """与 network_info_dialog 同一套令牌，随明暗主题切换。"""
    dark = widget.palette().color(QPalette.ColorRole.Window).lightness() < 128
    if dark:
        window, card, border, divider = "#202024", "#2a2a30", "#3a3a42", "#33333a"
        text, hint, hover = "#e0e0e6", "#9a9aa3", "#303036"
    else:
        window, card, border, divider = "#fcfcfd", "#ffffff", "#e2e4e8", "#eceef1"
        text, hint, hover = "#252525", "#777777", "#f4f5f6"
    accent = "#0a84ff"
    return f"""
    QDialog, QWidget#memoryCardBody {{
        background: {window};
        color: {text};
        font-size: 13px;
    }}
    QLabel#memoryCardTitle {{ font-size: 15px; font-weight: 600; color: {text}; }}
    QLabel#memoryCardHint {{ color: {hint}; font-size: 12px; }}
    QLabel#memoryCardFeeling {{ color: {hint}; font-size: 12px; font-style: italic; }}
    QLabel#memoryCardEmpty {{ color: {hint}; font-size: 13px; }}
    QLineEdit, QComboBox, QTextBrowser {{
        background: {card};
        color: {text};
        border: 1px solid {border};
        border-radius: 7px;
        padding: 4px 8px;
    }}
    QLineEdit:focus, QComboBox:focus, QTextBrowser:focus {{ border: 1px solid {accent}; }}
    QListWidget {{
        background: {card};
        border: 1px solid {border};
        border-radius: 12px;
        padding: 6px;
    }}
    QListWidget::item {{ color: {text}; border-radius: 8px; padding: 4px; }}
    QListWidget::item:selected {{ background: {hover}; color: {text}; }}
    QPushButton {{
        background: {card};
        color: {text};
        border: 1px solid {border};
        border-radius: 7px;
        min-height: 26px;
        padding: 3px 14px;
    }}
    QPushButton:hover {{ background: {hover}; }}
    QPushButton:focus {{ border: 1px solid {accent}; }}
    QPushButton:disabled {{ color: {hint}; border-color: {divider}; }}
    QPushButton[accent="true"] {{
        background: {accent};
        color: #ffffff;
        border: 1px solid {accent};
    }}
    """


def scaled_pixmap(path, size: QSize) -> QPixmap:
    """按目标尺寸解码缩略图（先缩放再解码，20MB 的原图也不会撑爆内存）。"""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    source = reader.size()
    if source.isValid() and source.width() > 0 and source.height() > 0:
        scale = min(size.width() / source.width(), size.height() / source.height(), 1.0)
        reader.setScaledSize(
            QSize(max(1, int(source.width() * scale)), max(1, int(source.height() * scale)))
        )
    image = reader.read()
    return QPixmap.fromImage(image) if not image.isNull() else QPixmap()


def _line(item: cards_mod.MemoryItem, limit: int = 24) -> str:
    text = " ".join(item.text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class MemoryCardDialog(QDialog):
    """记忆卡面板：搜索 / 按层筛选 / 卡片网格 / 双击详情。"""

    def __init__(self, config_dir, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config_dir = config_dir
        self._items: list[cards_mod.MemoryItem] = []
        self._details: list[CardDetailDialog] = []

        self.setWindowTitle("记忆卡")
        self.setObjectName("memoryCardDialog")
        self.resize(720, 560)
        self.setMinimumSize(560, 420)
        self.setStyleSheet(_stylesheet(self))
        self._build_ui()
        self.reload()

    # ------------------------------------------------------------ 构建
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title = QLabel("嘟嘟的记忆卡", self)
        title.setObjectName("memoryCardTitle")
        root.addWidget(title)
        self._hint = QLabel("", self)
        self._hint.setObjectName("memoryCardHint")
        self._hint.setWordWrap(True)
        root.addWidget(self._hint)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._search = QLineEdit(self)
        self._search.setPlaceholderText("搜她说记住的事…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)
        self._layer = QComboBox(self)
        for label, key in _LAYER_CHOICES:
            self._layer.addItem(label, key)
        self._layer.currentIndexChanged.connect(self._apply_filter)
        self._refresh_btn = QPushButton("刷新", self)
        self._refresh_btn.clicked.connect(self.reload)
        toolbar.addWidget(self._search, stretch=1)
        toolbar.addWidget(self._layer)
        toolbar.addWidget(self._refresh_btn)
        root.addLayout(toolbar)

        self._list = QListWidget(self)
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setIconSize(_THUMB)
        self._list.setGridSize(_GRID)
        self._list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._list.setMovement(QListWidget.Movement.Static)
        self._list.setWordWrap(True)
        self._list.setUniformItemSizes(True)
        self._list.setSpacing(4)
        self._list.setIconSize(_THUMB)
        self._list.itemDoubleClicked.connect(self._open_item)
        root.addWidget(self._list, stretch=1)

        self._empty = QLabel("", self)
        self._empty.setObjectName("memoryCardEmpty")
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.hide()
        root.addWidget(self._empty)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("关闭", self)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        root.addLayout(buttons)

    # ------------------------------------------------------------ 数据
    def reload(self) -> None:
        """重读记忆（就是 she 会被注入的那一份）。"""
        self._items = cards_mod.iter_items(self._config_dir)
        counts = cards_mod.layer_counts(self._items)
        photos = sum(1 for item in self._items if item.photo is not None)
        self._hint.setText(
            f"她一共记住 {len(self._items)} 条："
            f"偏好 {counts.get('user', 0)}、事实 {counts.get('fact', 0)}、"
            f"教训 {counts.get('lesson', 0)}、话题 {counts.get('topic', 0)}；"
            f"其中 {photos} 条带照片。这些就是她聊天时会想起来的记忆，"
            "记不记由她在对话里自己判断，不是这里手动写的。"
        )
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self._search.text()
        layer = str(self._layer.currentData() or "all")
        matched = cards_mod.filter_items(self._items, query=query, layer=layer)
        self._list.clear()
        for item in matched:
            node = QListWidgetItem(self._list)
            node.setData(Qt.ItemDataRole.UserRole, item.entry_id)
            node.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            day = item.created_at[:10]
            lines = [_line(item), f"{item.layer_label} · {day}"]
            if item.feeling:
                feeling = " ".join(item.feeling.split())
                lines.append("「" + (feeling if len(feeling) <= 16 else feeling[:15] + "…") + "」")
            node.setText("\n".join(lines))
            tooltip = f"{item.text}\n\n{item.layer_label} · 命中 {item.hits} 次 · {day}"
            if item.feeling:
                tooltip += f"\n\n她的感受：{item.feeling}"
            if item.archived:
                tooltip += "\n（已归档：不再注入，但还留着）"
            node.setToolTip(tooltip)
            if item.photo is not None:
                pixmap = scaled_pixmap(item.photo, _THUMB)
                if not pixmap.isNull():
                    node.setIcon(pixmap)
        has_items = bool(matched)
        self._list.setVisible(has_items)
        self._empty.setVisible(not has_items)
        if not has_items:
            self._empty.setText(
                "她还什么都没记住嘟。\n聊过几轮、或者发一张图给她，她自己判断要不要记下来。"
                if not query
                else "没有找到匹配的记忆嘟。"
            )

    def _item_by_id(self, entry_id: str) -> cards_mod.MemoryItem | None:
        for item in self._items:
            if item.entry_id == entry_id:
                return item
        return None

    def _open_item(self, node: QListWidgetItem) -> None:
        item = self._item_by_id(str(node.data(Qt.ItemDataRole.UserRole) or ""))
        if item is None:
            return
        dialog = CardDetailDialog(self._config_dir, item, self)
        dialog.changed.connect(self.reload)
        dialog.finished.connect(lambda _result, d=dialog: self._forget_detail(d))
        self._details.append(dialog)
        dialog.show()

    def _forget_detail(self, dialog: "CardDetailDialog") -> None:
        if dialog in self._details:
            self._details.remove(dialog)

    # ------------------------------------------------------------ 测试/排查面
    @property
    def item_count(self) -> int:
        return self._list.count()


class CardDetailDialog(QDialog):
    """一条记忆：有照片看大图，没照片看全文；能删（等于让她忘掉）。"""

    changed = Signal()

    def __init__(self, config_dir, item: cards_mod.MemoryItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config_dir = config_dir
        self._item = item
        self.setWindowTitle(item.layer_label)
        self.setObjectName("memoryCardDetail")
        self.setMinimumSize(420, 340)
        self.setStyleSheet(_stylesheet(self))

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        meta_text = (
            f"{item.layer_label} · 命中 {item.hits} 次 · "
            f"{item.created_at[:16].replace('T', ' ')}"
        )
        if item.archived:
            meta_text += " · 已归档"
        meta = QLabel(meta_text, self)
        meta.setObjectName("memoryCardHint")
        root.addWidget(meta)

        if item.photo is not None:
            photo = QLabel(self)
            photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pixmap = scaled_pixmap(item.photo, QSize(520, 380))
            if pixmap.isNull():
                photo.setText("这张图打不开了（格式不被支持）")
            else:
                photo.setPixmap(pixmap)
            root.addWidget(photo, stretch=1)

        viewer = QTextBrowser(self)
        viewer.setPlainText(item.text)
        root.addWidget(viewer, stretch=1 if item.photo is None else 0)

        if item.feeling:
            feeling = QLabel(f"她的感受：{item.feeling}", self)
            feeling.setObjectName("memoryCardFeeling")
            feeling.setWordWrap(True)
            root.addWidget(feeling)

        buttons = QHBoxLayout()
        self._delete_btn = QPushButton("删掉这条记忆", self)
        self._delete_btn.clicked.connect(self._delete)
        buttons.addWidget(self._delete_btn)
        buttons.addStretch(1)
        close = QPushButton("关闭", self)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        root.addLayout(buttons)

    def _delete(self) -> None:
        confirm = QMessageBox.question(
            self,
            "记忆卡",
            "删掉之后她就真的不记得这件事了嘟（记忆文件里也会消失）。确定吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        if cards_mod.delete_item(self._config_dir, self._item):
            self.changed.emit()
            self.accept()
        else:
            QMessageBox.warning(self, "记忆卡", "没删掉，稍后再试嘟。")
