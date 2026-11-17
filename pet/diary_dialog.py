# -*- coding: utf-8 -*-
"""右键菜单「嘟嘟的日记」：把每天的对话读成一篇日记，可按时回顾、按词查找。

数据来自真实会话（``pet/diary.py``，只读）。左侧按天列，右侧是那天的日记；
顶部搜索框跨全部天数找一句话，点命中就跳到那天。导出成 txt 便于存档。

视觉语言与记忆卡 / 待办面板同一套令牌，不发明新样式。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from . import diary as diary_mod

log = logging.getLogger(__name__)

_RANGES = (
    ("全部时间", 0),
    ("最近 7 天", 7),
    ("最近 30 天", 30),
    ("最近 90 天", 90),
)


def _stylesheet(widget: QWidget) -> str:
    dark = widget.palette().color(QPalette.ColorRole.Window).lightness() < 128
    if dark:
        window, card, border, divider = "#202024", "#2a2a30", "#3a3a42", "#33333a"
        text, hint, hover = "#e0e0e6", "#9a9aa3", "#303036"
    else:
        window, card, border, divider = "#fcfcfd", "#ffffff", "#e2e4e8", "#eceef1"
        text, hint, hover = "#252525", "#777777", "#f4f5f6"
    accent = "#0a84ff"
    return f"""
    QDialog {{ background: {window}; color: {text}; font-size: 13px; }}
    QLabel#diaryTitle {{ font-size: 15px; font-weight: 600; color: {text}; }}
    QLabel#diaryHint {{ color: {hint}; font-size: 12px; }}
    QLineEdit, QComboBox {{
        background: {card};
        color: {text};
        border: 1px solid {border};
        border-radius: 7px;
        padding: 4px 8px;
    }}
    QLineEdit:focus, QComboBox:focus {{ border: 1px solid {accent}; }}
    QListWidget {{
        background: {card};
        border: 1px solid {border};
        border-radius: 12px;
        padding: 6px;
    }}
    QListWidget::item {{ color: {text}; border-radius: 8px; padding: 6px; }}
    QListWidget::item:selected {{ background: {hover}; color: {text}; }}
    QTextBrowser {{
        background: {card};
        color: {text};
        border: 1px solid {border};
        border-radius: 12px;
        padding: 14px 16px;
    }}
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
        background: {accent}; color: #ffffff; border: 1px solid {accent};
    }}
    """


class DiaryDialog(QDialog):
    """非模态日记窗：日期列表 + 日记正文 + 跨天搜索 + 导出。"""

    def __init__(self, config_dir, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config_dir = config_dir
        self._current_day = ""
        self._searching = False

        self.setWindowTitle("嘟嘟的日记")
        self.setObjectName("diaryDialog")
        self.resize(820, 580)
        self.setMinimumSize(620, 420)
        self.setStyleSheet(_stylesheet(self))
        self._build_ui()
        self.reload()

    # ------------------------------------------------------------ 构建
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title = QLabel("嘟嘟的日记", self)
        title.setObjectName("diaryTitle")
        root.addWidget(title)
        self._hint = QLabel("", self)
        self._hint.setObjectName("diaryHint")
        self._hint.setWordWrap(True)
        root.addWidget(self._hint)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self._search = QLineEdit(self)
        self._search.setPlaceholderText("搜一句话、一个词（跨全部天数）…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search)
        self._range = QComboBox(self)
        for label, days in _RANGES:
            self._range.addItem(label, days)
        self._range.currentIndexChanged.connect(self.reload)
        self._export_btn = QPushButton("导出这一天", self)
        self._export_btn.clicked.connect(self._export)
        toolbar.addWidget(self._search, stretch=1)
        toolbar.addWidget(self._range)
        toolbar.addWidget(self._export_btn)
        root.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._days = QListWidget(splitter)
        self._days.setMinimumWidth(220)
        self._days.currentItemChanged.connect(self._on_day_selected)
        self._text = QTextBrowser(splitter)
        splitter.addWidget(self._days)
        splitter.addWidget(self._text)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 550])
        root.addWidget(splitter, stretch=1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("关闭", self)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        root.addLayout(buttons)

    # ------------------------------------------------------------ 数据
    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().showEvent(event)
        # 每次打开都重读：刚聊完的那几句应该已经写进今天的日记了
        self.reload()

    def reload(self) -> None:
        summaries = diary_mod.day_summaries(self._config_dir)
        span = int(self._range.currentData() or 0)
        if span > 0:
            edge = (date.today() - timedelta(days=span - 1)).isoformat()
            summaries = [item for item in summaries if item.day >= edge]
        self._searching = False
        self._fill_days(summaries)
        if summaries:
            self._hint.setText(
                f"一共 {len(summaries)} 天有对话。左边按天列，右边是当天的日记；"
                "上面可以搜一句话，跨全部天数找。"
            )
            self._select_day(summaries[0].day)
        else:
            self._current_day = ""
            self._text.setPlainText("")
            self._hint.setText(
                "这段时间还没有对话嘟。等哥哥来聊几句，这里就会有日记了。"
            )

    def _fill_days(self, summaries) -> None:
        self._days.blockSignals(True)
        self._days.clear()
        for item in summaries:
            node = QListWidgetItem(
                f"{item.label}\n{item.turns} 次 · {item.first_at}–{item.last_at}"
            )
            node.setData(Qt.ItemDataRole.UserRole, item.day)
            self._days.addItem(node)
        self._days.blockSignals(False)

    def _select_day(self, day: str) -> None:
        for row in range(self._days.count()):
            item = self._days.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == day:
                self._days.setCurrentItem(item)
                return
        if self._days.count():
            self._days.setCurrentRow(0)

    def _on_day_selected(self, current: QListWidgetItem | None, _previous=None) -> None:
        if current is None:
            return
        day = str(current.data(Qt.ItemDataRole.UserRole) or "")
        if day:
            self._show_day(day)

    def _show_day(self, day: str) -> None:
        self._current_day = day
        entry = diary_mod.build_entry(self._config_dir, day)
        if entry is None:
            self._text.setPlainText("这一天的记录不在了（会话文件可能被清理过）嘟。")
            return
        self._text.setPlainText(entry.text)
        # 日记正文用略松的行距，读起来像一篇东西而不是日志
        document = self._text.document()
        document.setDocumentMargin(6)
        cursor_font = QFont(self._text.font())
        cursor_font.setPointSizeF(max(10.5, cursor_font.pointSizeF()))
        self._text.setFont(cursor_font)

    # ------------------------------------------------------------ 搜索
    def _on_search(self, text: str) -> None:
        query = str(text or "").strip()
        if not query:
            if self._searching:
                self.reload()
            return
        hits = diary_mod.search(self._config_dir, query)
        self._searching = True
        self._days.blockSignals(True)
        self._days.clear()
        for hit in hits:
            node = QListWidgetItem(f"{hit.when} · {hit.role}\n{hit.snippet}")
            node.setData(Qt.ItemDataRole.UserRole, hit.day)
            node.setToolTip(hit.snippet)
            self._days.addItem(node)
        self._days.blockSignals(False)
        if not hits:
            self._hint.setText(f"没有找到「{query}」嘟。")
            self._text.setPlainText("")
            self._current_day = ""
            return
        days = len({hit.day for hit in hits})
        self._hint.setText(f"「{query}」找到 {len(hits)} 句，分布在 {days} 天。点一条看当天的日记。")
        self._days.setCurrentRow(0)
        self._show_day(str(hits[0].day))

    # ------------------------------------------------------------ 导出
    def _export(self) -> None:
        if not self._current_day:
            QMessageBox.information(self, "嘟嘟的日记", "先选一天再导出嘟。")
            return
        text = diary_mod.render_day(self._config_dir, self._current_day)
        if not text:
            QMessageBox.information(self, "嘟嘟的日记", "这一天的日记是空的嘟。")
            return
        default_name = f"嘟嘟日记-{self._current_day}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, "导出日记", default_name, "文本文件 (*.txt)"
        )
        if not path:
            return
        try:
            # utf-8-sig：Windows 记事本双击打开不会整篇乱码
            with open(path, "w", encoding="utf-8-sig", newline="\n") as handle:
                handle.write(text)
        except OSError as exc:
            QMessageBox.warning(self, "嘟嘟的日记", f"导出失败：{exc}")
            return
        QMessageBox.information(self, "嘟嘟的日记", f"导出好了嘟：\n{path}")

    # ------------------------------------------------------------ 测试/排查面
    @property
    def current_day(self) -> str:
        return self._current_day

    @property
    def day_count(self) -> int:
        return self._days.count()
