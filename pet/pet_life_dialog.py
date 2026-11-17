# -*- coding: utf-8 -*-
"""「嘟嘟的生活」面板：属性详情 + 工作 / 玩耍 / 商店。

结构照 ``pet/network_info_dialog.py`` 与 ``pet/todo/panel.py`` 的既有视觉语言：
卡片 12px 圆角 + 1px 边框、控件 7px 圆角、强调色 ``#0a84ff``、明暗跟随系统调色板。

**面板只发请求，不改数值**：每个按钮都调 ``service.xxx()``，服务改完状态发
``changed``，本窗口收到后重画。这样"谁改了数值"永远只有一处（避免 UI 与
服务各自算一遍导致对不上）。
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPalette
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import pet_life_data as D

log = logging.getLogger(__name__)


def _styles(widget: QWidget) -> str:
    dark = widget.palette().color(QPalette.ColorRole.Window).lightness() < 128
    if dark:
        window, card, border, divider = "#202024", "#2a2a30", "#3a3a42", "#33333a"
        text, hint, hover = "#e0e0e6", "#9a9aa3", "#303036"
    else:
        window, card, border, divider = "#fcfcfd", "#ffffff", "#e2e4e8", "#eceef1"
        text, hint, hover = "#252525", "#777777", "#f4f5f6"
    accent = "#0a84ff"
    return f"""
    QDialog, QWidget#petLifeBody {{ background: {window}; color: {text}; font-size: 13px; }}
    QLabel#petLifeTitle {{ font-size: 15px; font-weight: 600; color: {text}; }}
    QLabel#petLifeHint {{ color: {hint}; font-size: 12px; }}
    QLabel[role="group"] {{ font-size: 12px; font-weight: 600; color: {hint}; }}
    QLabel[role="name"] {{ font-size: 13px; font-weight: 600; color: {text}; }}
    QLabel[role="desc"] {{ font-size: 12px; color: {hint}; }}
    QFrame[card="true"] {{ background: {card}; border: 1px solid {border}; border-radius: 12px; }}
    QFrame[divider="true"] {{ background: {divider}; border: none; max-height: 1px; }}
    QPushButton {{
        background: {card}; color: {text}; border: 1px solid {border};
        border-radius: 7px; min-height: 26px; padding: 3px 12px;
    }}
    QPushButton:hover {{ background: {hover}; }}
    QPushButton:focus {{ border: 1px solid {accent}; }}
    QPushButton:disabled {{ color: {hint}; border-color: {divider}; }}
    QPushButton[accent="true"] {{ background: {accent}; color: #ffffff; border: 1px solid {accent}; }}
    QPushButton[accent="true"]:disabled {{ background: {divider}; color: {hint}; border-color: {divider}; }}
    QScrollArea {{ border: none; background: transparent; }}
    """


class _StatBar(QWidget):
    """一条属性：名字 + 进度条 + 数值（自绘，和 HUD 同一套配色意图）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[tuple[str, str, float]] = []
        self.setMinimumHeight(15 * max(1, len(D.STATUS_KEYS)))

    def set_rows(self, rows) -> None:
        self._rows = list(rows)
        self.setMinimumHeight(18 * max(1, len(self._rows)))
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt 命名
        return QSize(320, 18 * max(1, len(self._rows)))

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if not self._rows:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        text = QColor("#e0e0e6") if dark else QColor("#252525")
        track = QColor(255, 255, 255, 28) if dark else QColor(0, 0, 0, 18)
        font = QFont(self.font())
        font.setPixelSize(11)
        painter.setFont(font)
        metrics = painter.fontMetrics()

        label_w = metrics.horizontalAdvance("健康") + 8
        value_w = metrics.horizontalAdvance("100") + 8
        bar_left = label_w
        bar_right = max(bar_left + 30, self.width() - value_w)
        row_h = 18
        for index, (key, label, value) in enumerate(self._rows):
            y = index * row_h
            painter.setPen(text)
            painter.drawText(
                QRectF(0, y, label_w, row_h),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                label,
            )
            top = y + (row_h - 6) / 2.0
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(track)
            painter.drawRoundedRect(QRectF(bar_left, top, bar_right - bar_left, 6), 3, 3)
            fill = max(0.0, min(100.0, float(value)))
            if fill > 0:
                from .pet_life_hud import _bar_color

                painter.setBrush(_bar_color(fill))
                painter.drawRoundedRect(
                    QRectF(bar_left, top, max(2.0, (bar_right - bar_left) * fill / 100.0), 6),
                    3,
                    3,
                )
            painter.setPen(text)
            painter.drawText(
                QRectF(bar_right + 4, y, value_w, row_h),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                f"{int(round(fill))}",
            )
        painter.end()


class _XpBar(QWidget):
    """等级经验条：「Lv.N」+ 细进度条 + 「本级/总数」。

    自绘而不是 QProgressBar：面板里已经有一条自绘的属性条（``_StatBar``），
    同一套配色与像素高度才不会有"外来控件"的割裂感。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._progress: dict = {"level": 1, "into": 0.0, "need": 0.0, "next_at": 0.0, "xp": 0.0}
        self.setMinimumHeight(20)

    def set_progress(self, progress: dict) -> None:
        self._progress = dict(progress or {})
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt 命名
        return QSize(320, 20)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = self.palette().color(QPalette.ColorRole.Window).lightness() < 128
        text = QColor("#e0e0e6") if dark else QColor("#252525")
        hint = QColor("#9a9aa3") if dark else QColor("#777777")
        track = QColor(255, 255, 255, 28) if dark else QColor(0, 0, 0, 18)

        font = QFont(self.font())
        font.setPixelSize(11)
        painter.setFont(font)
        metrics = painter.fontMetrics()

        level = int(self._progress.get("level") or 1)
        into = float(self._progress.get("into") or 0.0)
        need = float(self._progress.get("need") or 0.0)
        ratio = (into / need) if need > 0 else 1.0
        ratio = max(0.0, min(1.0, ratio))

        level_text = f"Lv.{level}"
        value_text = "已满级" if need <= 0 else f"{int(round(into))}/{int(round(need))}"
        level_w = metrics.horizontalAdvance("Lv.88") + 6
        value_w = metrics.horizontalAdvance("888/888") + 6
        row_h = 20

        painter.setPen(text)
        painter.drawText(
            QRectF(0, 0, level_w, row_h),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            level_text,
        )
        bar_left = level_w
        bar_right = max(bar_left + 30, self.width() - value_w)
        top = (row_h - 6) / 2.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(bar_left, top, bar_right - bar_left, 6), 3, 3)
        if ratio > 0:
            painter.setBrush(QColor("#0a84ff"))
            painter.drawRoundedRect(
                QRectF(bar_left, top, max(2.0, (bar_right - bar_left) * ratio), 6), 3, 3
            )
        painter.setPen(hint)
        painter.drawText(
            QRectF(bar_right + 4, 0, value_w, row_h),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
            value_text,
        )
        painter.end()


class _OfferRow(QFrame):
    """工作 / 玩耍 / 商店的通用一行：名称、说明、右侧按钮。"""

    def __init__(
        self,
        name: str,
        desc: str,
        button_text: str,
        callback,
        *,
        accent: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("card", True)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(12, 9, 12, 9)
        outer.setSpacing(10)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        title = QLabel(name, self)
        title.setProperty("role", "name")
        detail = QLabel(desc, self)
        detail.setProperty("role", "desc")
        detail.setWordWrap(True)
        texts.addWidget(title)
        texts.addWidget(detail)
        outer.addLayout(texts, 1)
        self.button = QPushButton(button_text, self)
        if accent:
            self.button.setProperty("accent", True)
        self.button.clicked.connect(callback)
        outer.addWidget(self.button, 0, Qt.AlignmentFlag.AlignVCenter)


def _effects_text(effects: dict) -> str:
    parts = []
    for key, value in effects.items():
        if key == "coins":
            continue
        label = D.STATUS_LABELS.get(key, key)
        sign = "+" if value > 0 else ""
        parts.append(f"{label}{sign}{value}")
    return "、".join(parts)


class PetLifeDialog(QDialog):
    """非模态单例（由 ``AppShell.open_pet_life`` 持有）。"""

    def __init__(self, service, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self.setWindowTitle("嘟嘟的生活")
        self.setObjectName("petLifeDialog")
        self.setModal(False)
        self.resize(520, 640)
        self.setMinimumSize(440, 480)
        self.setStyleSheet(_styles(self))
        self._build()
        self._service.changed.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------ 构建
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        title = QLabel("嘟嘟的生活", self)
        title.setObjectName("petLifeTitle")
        root.addWidget(title)
        self._hint = QLabel("", self)
        self._hint.setObjectName("petLifeHint")
        self._hint.setWordWrap(True)
        root.addWidget(self._hint)

        stats_card = QFrame(self)
        stats_card.setProperty("card", True)
        stats_layout = QVBoxLayout(stats_card)
        stats_layout.setContentsMargins(12, 10, 12, 10)
        stats_layout.setSpacing(6)
        self._xp = _XpBar(stats_card)
        stats_layout.addWidget(self._xp)
        self._bars = _StatBar(stats_card)
        stats_layout.addWidget(self._bars)
        self._job_line = QLabel("", stats_card)
        self._job_line.setObjectName("petLifeHint")
        self._job_line.setWordWrap(True)
        stats_layout.addWidget(self._job_line)
        root.addWidget(stats_card)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        body = QWidget(scroll)
        body.setObjectName("petLifeBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        body_layout.addWidget(self._group_label("生活", body))
        self._nap_row = _OfferRow(
            "睡觉",
            f"躺下眯 {int(round(D.NAP_MINUTES))} 分钟，醒来精神 +{int(round(D.NAP_ENERGY))}"
            "（精力掉到 15 她也会自己睡）",
            "去睡觉",
            lambda _checked=False: self._toggle_sleep(),
            parent=body,
        )
        body_layout.addWidget(self._nap_row)

        body_layout.addWidget(self._group_label("工作（每次 10 分钟，可中断）", body))
        self._job_rows: dict[str, _OfferRow] = {}
        for job_id, spec in D.JOBS.items():
            row = _OfferRow(
                f"{spec['name']}　+{spec['coins']} 币",
                f"{spec['desc']}（{_effects_text(spec['effects'])}，+{D.JOB_XP.get(job_id, 0)} 经验）",
                "开始",
                lambda _checked=False, jid=job_id: self._service.start_job(jid),
                parent=body,
            )
            self._job_rows[job_id] = row
            body_layout.addWidget(row)

        body_layout.addWidget(self._group_label("玩耍", body))
        self._play_rows: dict[str, _OfferRow] = {}
        for act_id, spec in D.PLAY_ACTS.items():
            row = _OfferRow(
                spec["name"],
                f"{spec['desc']}（{_effects_text(spec['effects'])}，+{D.PLAY_XP.get(act_id, 0)} 经验）",
                "去玩",
                lambda _checked=False, aid=act_id: self._service.play(aid),
                parent=body,
            )
            self._play_rows[act_id] = row
            body_layout.addWidget(row)

        body_layout.addWidget(self._group_label("大肥鲸杂货铺", body))
        self._shop_rows: dict[str, _OfferRow] = {}
        for item_id, spec in D.SHOP_ITEMS.items():
            row = _OfferRow(
                f"{spec['name']}　{spec['price']} 币",
                f"{spec['desc']}（{_effects_text(spec['effects'])}）",
                "购买",
                lambda _checked=False, iid=item_id: self._service.buy(iid),
                parent=body,
            )
            self._shop_rows[item_id] = row
            body_layout.addWidget(row)

        body_layout.addWidget(self._group_label("技能（等级到了自动学会，学会后她自己会动）", body))
        self._skill_rows: dict[str, _OfferRow] = {}
        for skill_id, spec in D.SKILLS.items():
            row = _OfferRow(
                f"{spec['name']}　Lv.{spec['level']} 解锁",
                str(spec["desc"]),
                "未解锁",
                lambda _checked=False: None,
                parent=body,
            )
            row.button.setEnabled(False)
            self._skill_rows[skill_id] = row
            body_layout.addWidget(row)
        self._autonomy_btn = QPushButton("自主技能：已开启", body)
        self._autonomy_btn.clicked.connect(self._toggle_autonomy)
        body_layout.addWidget(self._autonomy_btn)

        body_layout.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self._hud_btn = QPushButton("状态条：跟随桌宠", self)
        self._hud_btn.clicked.connect(self._cycle_hud)
        footer.addWidget(self._hud_btn)
        self._enable_btn = QPushButton("关闭养成", self)
        self._enable_btn.clicked.connect(self._toggle_enabled)
        footer.addWidget(self._enable_btn)
        footer.addStretch(1)
        self._reset_btn = QPushButton("重新养一只", self)
        self._reset_btn.clicked.connect(self._reset)
        footer.addWidget(self._reset_btn)
        close = QPushButton("关闭", self)
        close.setProperty("accent", True)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        root.addLayout(footer)

    def _group_label(self, text: str, parent: QWidget) -> QLabel:
        label = QLabel(text, parent)
        label.setProperty("role", "group")
        return label

    # ------------------------------------------------------------ 刷新
    def refresh(self) -> None:
        try:
            self._bars.set_rows(self._service.hud_rows())
            progress = self._service.xp_progress()
            self._xp.set_progress(progress)
            flags = self._service.flags()
            coins = int(round(float(self._service.state.get("coins", 0))))
            bits = [f"Lv.{int(progress['level'])}", f"嘟嘟币 {coins}"]
            if flags["sick"]:
                bits.append("病倒了（先喂点吃的）")
            elif flags["sleeping"]:
                if flags["napping"]:
                    remain = int(round(self._service.nap_remaining() / 60.0))
                    bits.append(f"正在小睡（还有 {max(0, remain)} 分钟）")
                else:
                    bits.append("正在睡觉")
            elif flags["working"]:
                job = self._service.current_job()
                name = job["name"] if job else "工作"
                percent = int(round(self._service.job_progress() * 100))
                bits.append(f"正在{name}（{percent}%）")
            else:
                bits.append("闲着")
            if not flags["enabled"]:
                bits.append("养成系统已关闭")
            self._hint.setText("　·　".join(bits))
            self._job_line.setVisible(flags["working"])
            if flags["working"]:
                self._job_line.setText(
                    f"工作进度 {int(round(self._service.job_progress() * 100))}%，"
                    "到点会自动结算；中途关闭养成就作废。"
                )
            busy = flags["working"]
            self._nap_row.button.setText("叫醒她" if flags["sleeping"] else "去睡觉")
            self._nap_row.button.setEnabled(flags["enabled"] and not busy)
            for row in self._job_rows.values():
                row.button.setEnabled(not busy and flags["enabled"])
            for row in self._play_rows.values():
                row.button.setEnabled(not busy and flags["enabled"])
            for row in self._shop_rows.values():
                row.button.setEnabled(flags["enabled"])
            self._enable_btn.setText("关闭养成" if flags["enabled"] else "开启养成")
            self._hud_btn.setText(f"状态条：{self._hud_label()}")
            for skill_id, _spec, unlocked in self._service.all_skills():
                row = self._skill_rows.get(skill_id)
                if row is not None:
                    row.button.setText("已学会" if unlocked else "未解锁")
            autonomy = self._service.autonomy()
            self._autonomy_btn.setText(
                "自主技能：已开启（点此关闭，她就只听你的）" if autonomy
                else "自主技能：已关闭（点此开启，让她自己动）"
            )
            self._autonomy_btn.setEnabled(flags["enabled"])
        except Exception:
            log.exception("养成面板刷新失败")

    def _hud_label(self) -> str:
        return {
            "follow_pet": "跟随桌宠",
            "follow_island": "贴在灵动岛",
            "off": "已隐藏",
        }.get(self._service.hud_mode(), "跟随桌宠")

    # ------------------------------------------------------------ 动作
    def _cycle_hud(self) -> None:
        order = ("follow_pet", "follow_island", "off")
        try:
            index = order.index(self._service.hud_mode())
        except ValueError:
            index = 0
        self._service.set_hud_mode(order[(index + 1) % len(order)])

    def _toggle_enabled(self) -> None:
        self._service.set_enabled(not self._service.enabled())

    def _toggle_autonomy(self) -> None:
        self._service.set_autonomy(not self._service.autonomy())

    def _toggle_sleep(self) -> None:
        """「去睡觉 / 叫醒她」：睡着她就是叫醒，不然就躺下眯一会儿。"""
        if self._service.state.get("sleeping"):
            self._service.wake_up()
        else:
            self._service.start_nap()

    def _reset(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self,
            "重新养一只",
            "会把属性、嘟嘟币和进行中的工作全部清零，确定吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._service.reset()

    # ------------------------------------------------------------ 测试面
    @property
    def service(self):
        return self._service