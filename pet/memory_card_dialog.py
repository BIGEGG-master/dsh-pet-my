# -*- coding: utf-8 -*-
"""右键菜单「查看记忆卡」：她记住的文字与照片，带她自己写的备注。

只做**看**与少量整理（改一行备注、删掉一张），不是编辑器：新增入口在聊天里
（发图就存、说「记住：…」就进对话记忆），面板这里再开一个「写一条」只是给
不想打字进对话框的用户一条路。

视觉语言与待办面板 / 网络信息窗同一套令牌（卡片 12px 圆角、7px 圆角控件、
强调色 #0a84ff、明暗跟随系统调色板），不发明新样式。
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
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import memory_card as cards_mod

log = logging.getLogger(__name__)

_THUMB = QSize(150, 116)
_GRID = QSize(166, 186)


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
    QLabel#memoryCardEmpty {{ color: {hint}; font-size: 13px; }}
    QLineEdit, QComboBox, QPlainTextEdit, QTextBrowser {{
        background: {card};
        color: {text};
        border: 1px solid {border};
        border-radius: 7px;
        padding: 4px 8px;
    }}
    QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {{ border: 1px solid {accent}; }}
    QListWidget {{
        background: {card};
        border: 1px solid {border};
        border-radius: 12px;
        padding: 6px;
    }}
    QListWidget::item {{
        color: {text};
        border-radius: 8px;
        padding: 4px;
    }}
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


class _TextCardDialog(QDialog):
    """写一条文字卡：正文 + 备注（备注留空就用正文首行）。"""

    def __init__(self, config_dir, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config_dir = config_dir
        self.setWindowTitle("写一条记忆")
        self.setObjectName("memoryCardEditor")
        self.resize(460, 320)
        self.setStyleSheet(_stylesheet(self))
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        title = QLabel("写一条记忆", self)
        title.setObjectName("memoryCardTitle")
        root.addWidget(title)
        hint = QLabel("备注这一行会显示在卡片上，留空就用正文首行。", self)
        hint.setObjectName("memoryCardHint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.body = QPlainTextEdit(self)
        self.body.setPlaceholderText("想记住的事…")
        root.addWidget(self.body, stretch=1)
        self.note = QLineEdit(self)
        self.note.setPlaceholderText("备注（可选，最多 80 字）")
        root.addWidget(self.note)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消", self)
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存", self)
        save.setProperty("accent", True)
        save.setDefault(True)
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    def _save(self) -> None:
        text = self.body.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "记忆卡", "正文还是空的呢嘟。")
            return
        card = cards_mod.add_text(
            self._config_dir, text, note=self.note.text(), source="manual"
        )
        if card is None:
            QMessageBox.warning(self, "记忆卡", "这张卡没存上（可能卡片已满），稍后再试嘟。")
            return
        self.accept()


class CardDetailDialog(QDialog):
    """单张卡片：照片看大图 / 文字看全文，备注可改，卡可删。"""

    changed = Signal()

    def __init__(self, config_dir, card: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config_dir = config_dir
        self._card = card
        self.setWindowTitle(str(card.get("note") or "记忆卡"))
        self.setObjectName("memoryCardDetail")
        self.setMinimumSize(420, 340)
        self.setStyleSheet(_stylesheet(self))

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(8)

        meta = QLabel(
            f"{'照片' if card.get('kind') == 'photo' else '文字'} · "
            f"{str(card.get('created_at') or '')[:16].replace('T', ' ')}",
            self,
        )
        meta.setObjectName("memoryCardHint")
        root.addWidget(meta)

        if card.get("kind") == "photo":
            self._photo = QLabel(self)
            self._photo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            path = cards_mod.photo_abs_path(config_dir, card)
            if path is None:
                self._photo.setText("照片副本找不到了（可能被手动删掉）")
                self._photo.setObjectName("memoryCardHint")
            else:
                pixmap = scaled_pixmap(path, QSize(520, 380))
                if pixmap.isNull():
                    self._photo.setText("这张图打不开（格式不被支持）")
                    self._photo.setObjectName("memoryCardHint")
                else:
                    self._photo.setPixmap(pixmap)
            root.addWidget(self._photo, stretch=1)
            if str(card.get("text") or "").strip():
                caption = QLabel(str(card.get("text")), self)
                caption.setWordWrap(True)
                root.addWidget(caption)
        else:
            viewer = QTextBrowser(self)
            viewer.setPlainText(str(card.get("text") or ""))
            root.addWidget(viewer, stretch=1)

        note_row = QHBoxLayout()
        note_label = QLabel("备注", self)
        note_label.setObjectName("memoryCardHint")
        self._note_edit = QLineEdit(str(card.get("note") or ""), self)
        self._note_edit.setMaxLength(cards_mod.MAX_NOTE_CHARS)
        self._note_edit.setPlaceholderText("她给这条记忆写的一句话")
        note_row.addWidget(note_label)
        note_row.addWidget(self._note_edit, stretch=1)
        root.addLayout(note_row)

        buttons = QHBoxLayout()
        self._delete_btn = QPushButton("删除这张卡", self)
        self._delete_btn.clicked.connect(self._delete)
        buttons.addWidget(self._delete_btn)
        buttons.addStretch(1)
        save = QPushButton("保存备注", self)
        save.setProperty("accent", True)
        save.clicked.connect(self._save_note)
        close = QPushButton("关闭", self)
        close.clicked.connect(self.accept)
        buttons.addWidget(save)
        buttons.addWidget(close)
        root.addLayout(buttons)

    def _save_note(self) -> None:
        if cards_mod.update_note(self._config_dir, str(self._card["id"]), self._note_edit.text()):
            self._card["note"] = self._note_edit.text().strip()
            self.changed.emit()
        else:
            QMessageBox.warning(self, "记忆卡", "备注没存上，稍后再试嘟。")

    def _delete(self) -> None:
        confirm = QMessageBox.question(
            self,
            "记忆卡",
            "要把这张卡删掉吗？删了就找不回来了嘟。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        if cards_mod.delete_card(self._config_dir, str(self._card["id"])):
            self.changed.emit()
            self.accept()
        else:
            QMessageBox.warning(self, "记忆卡", "没删掉，稍后再试嘟。")


class MemoryCardDialog(QDialog):
    """记忆卡面板：搜索 / 类型筛选 / 卡片网格 / 双击详情。"""

    def __init__(self, config_dir, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config_dir = config_dir
        self._cards: list[dict] = []
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
        self._search.setPlaceholderText("搜备注或正文…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)
        self._kind = QComboBox(self)
        self._kind.addItem("全部", "all")
        self._kind.addItem("只看文字", "text")
        self._kind.addItem("只看照片", "photo")
        self._kind.currentIndexChanged.connect(self._apply_filter)
        self._add_btn = QPushButton("写一条", self)
        self._add_btn.clicked.connect(self._add_text_card)
        toolbar.addWidget(self._search, stretch=1)
        toolbar.addWidget(self._kind)
        toolbar.addWidget(self._add_btn)
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
        """重读索引并刷新统计（新增/删除/改备注之后调一次）。"""
        self._cards = cards_mod.load_cards(self._config_dir)
        counts = cards_mod.stats(self._config_dir)
        self._hint.setText(
            f"一共 {counts['total']} 张：{counts['text']} 段文字、{counts['photo']} 张照片。"
            "双击任意一张看全文或大图；备注可以自己改。"
        )
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self._search.text()
        kind = str(self._kind.currentData() or "all")
        matched = cards_mod.filter_cards(self._cards, query=query, kind=kind)
        self._list.clear()
        for card in matched:
            item = QListWidgetItem(self._list)
            item.setData(Qt.ItemDataRole.UserRole, card["id"])
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            note = str(card.get("note") or "").strip()
            line = note or cards_mod.summary(card, 24)
            day = cards_mod.card_day(card)
            item.setText(f"{line}\n{day}")
            item.setToolTip(
                (note + "\n\n" if note else "") + cards_mod.summary(card, 200)
            )
            if card.get("kind") == "photo":
                path = cards_mod.photo_abs_path(self._config_dir, card)
                if path is not None:
                    pixmap = scaled_pixmap(path, _THUMB)
                    if not pixmap.isNull():
                        item.setIcon(pixmap)
            if not card.get("note"):
                item.setForeground(self.palette().color(QPalette.ColorRole.PlaceholderText))
        has_items = bool(matched)
        self._list.setVisible(has_items)
        self._empty.setVisible(not has_items)
        if not has_items:
            self._empty.setText(
                "还没有记忆卡嘟。\n发一张照片给嘟嘟、或者点上面的「写一条」，就会出现在这里。"
                if not query
                else "没有找到匹配的卡片嘟。"
            )

    def _card_by_id(self, card_id: str) -> dict | None:
        for card in self._cards:
            if card["id"] == card_id:
                return card
        return None

    def _open_item(self, item: QListWidgetItem) -> None:
        card = self._card_by_id(str(item.data(Qt.ItemDataRole.UserRole) or ""))
        if card is None:
            return
        dialog = CardDetailDialog(self._config_dir, card, self)
        dialog.changed.connect(self.reload)
        dialog.finished.connect(lambda _result, d=dialog: self._forget_detail(d))
        self._details.append(dialog)
        dialog.show()

    def _forget_detail(self, dialog: CardDetailDialog) -> None:
        if dialog in self._details:
            self._details.remove(dialog)

    def _add_text_card(self) -> None:
        editor = _TextCardDialog(self._config_dir, self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self.reload()

    # ------------------------------------------------------------ 测试/排查面
    @property
    def item_count(self) -> int:
        return self._list.count()
