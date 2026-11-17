# -*- coding: utf-8 -*-
"""养成状态 HUD：可拖动、可贴边、鼠标离开自动缩回边缘的悬浮小面板。

交互契约（用户要的三件事）：

1. **按住拖动**：左键按住面板任意位置拖动，松手落位；
2. **贴边吸附**：松手时离屏幕某条边 < ``SNAP_DISTANCE`` 就吸附到那条边；
3. **悬停展开 / 移开缩回**：贴边状态下鼠标移开 ``AUTO_COLLAPSE_MS`` 后缩成
   一条细把手，鼠标移回把手上自动展开。

只有"被拖动过"的面板才参与贴边与缩回——跟随桌宠模式下面板就在她旁边，
缩回屏幕边缘反而找不到它。位置记在 ``pet_life.hud_x/hud_y/hud_edge``，
由服务落盘（HUD 自己不写配置，保持"只呈现"的分层）。

**为什么不用灵动岛那套**：岛的内容层走位图缓存、卡片高度是硬算术、
第三方段拿不到 QPainter；这里要的是"可拖的小窗"，独立窗天然合适。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import QWidget

from . import pet_life_data as D

#: 面板尺寸（px，未乘 DPR）。宽度要放得下"健康 100"这类最长一行。
HUD_WIDTH = 176
HUD_ROW_HEIGHT = 15
HUD_PADDING = 10
HUD_GAP = 6
#: 与锚点（桌宠身体 / 岛胶囊）之间的间距
ANCHOR_GAP = 8
#: 缩回后的窄条厚度
COLLAPSED_THICKNESS = 18
#: 松手时离边缘多近算"吸附"（px）
SNAP_DISTANCE = 60
#: 鼠标移开多久缩回（毫秒）
AUTO_COLLAPSE_MS = 2500

_EDGES = ("left", "right", "top", "bottom", "none")

#: 阈值配色：>=60 绿、>=30 黄、其余红（与 pet_life.status_level 的分段同源意图）
_OK = QColor("#39c26a")
_WARN = QColor("#e8a33d")
_BAD = QColor("#e5533d")


def _bar_color(value: float) -> QColor:
    if value >= 60:
        return _OK
    if value >= 30:
        return _WARN
    return _BAD


def _is_dark(widget: QWidget) -> bool:
    return widget.palette().color(QPalette.ColorRole.Window).lightness() < 128


class PetLifeHud(QWidget):
    """可交互状态条。数据由 ``update_state`` 推，位置由 ``set_anchor`` / 拖动决定。"""

    #: 用户拖动/吸附后要落盘的位置：(x, y, edge)
    position_changed = Signal(int, int, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("petLifeHud")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        if hasattr(Qt.WidgetAttribute, "WA_MacAlwaysShowToolWindow"):
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)

        self._rows: list[tuple[str, str, float]] = [
            (key, D.STATUS_LABELS[key], 0.0) for key in D.STATUS_KEYS
        ]
        self._coins = 0
        self._level = 0
        self._badges: list[str] = []
        self._anchor: QRect | None = None

        # ---- 交互状态 ----
        #: 自由位置（拖动过的位置）；None = 跟随锚点
        self._free_pos: QPoint | None = None
        self._edge: str = "none"
        self._collapsed = False
        self._drag_offset: QPoint | None = None
        self._dragging = False
        self._hover = False
        self._hover_at = 0.0

        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(AUTO_COLLAPSE_MS)
        self._collapse_timer.timeout.connect(self._maybe_collapse)

        self.setFixedSize(self._preferred_size())
        self.setToolTip("按住可拖动；贴到屏幕边缘后鼠标移开会自动缩回")

    # ------------------------------------------------------------ 数据
    def update_state(
        self,
        rows,
        coins: float,
        *,
        sleeping: bool = False,
        working: bool = False,
        sick: bool = False,
        level: int = 0,
        napping: bool = False,
        nap_minutes: int = 0,
    ) -> None:
        self._rows = list(rows)
        self._coins = float(coins)
        # ``level=0`` = 调用方不知道（老调用面），底行就不显示等级
        self._level = max(0, int(level or 0))
        badges: list[str] = []
        if sick:
            badges.append("病倒")
        if napping:
            # 小睡带倒计时（醒来给精力，用户想知道还剩多久）
            badges.append(f"小睡 {max(0, int(nap_minutes))} 分")
        elif sleeping:
            badges.append("睡觉中")
        if working:
            badges.append("工作中")
        self._badges = badges
        if not self._collapsed:
            size = self._preferred_size()
            if size != self.size():
                self.setFixedSize(size)
                self._place()
        self.update()

    def _expanded_size(self) -> QSize:
        rows = len(self._rows)
        height = HUD_PADDING * 2 + rows * HUD_ROW_HEIGHT + HUD_GAP + HUD_ROW_HEIGHT
        return QSize(HUD_WIDTH, height)

    def _preferred_size(self) -> QSize:
        return self._collapsed_size() if self._collapsed else self._expanded_size()

    def _collapsed_size(self) -> QSize:
        expanded = self._expanded_size()
        if self._edge in ("left", "right"):
            return QSize(COLLAPSED_THICKNESS, expanded.height())
        if self._edge in ("top", "bottom"):
            return QSize(expanded.width(), COLLAPSED_THICKNESS)
        # 没贴边（理论上不会缩回）：退化成小方点
        return QSize(COLLAPSED_THICKNESS, COLLAPSED_THICKNESS)

    # ------------------------------------------------------------ 定位
    def restore_position(self, x, y, edge: str) -> None:
        """从配置恢复上次拖动的位置（``x``/``y`` 非正数 = 从未拖动过）。"""
        edge = str(edge or "none")
        self._edge = edge if edge in _EDGES else "none"
        try:
            px, py = int(x), int(y)
        except (TypeError, ValueError):
            px = py = -1
        if px > 0 or py > 0:
            self._free_pos = QPoint(px, py)
        self._place()

    def set_anchor(self, rect: QRect | None) -> None:
        """锚点（桌宠身体 / 岛胶囊，全局坐标）。``None`` = 隐藏。

        自由位置优先：用户拖动过就停在原地，不再跟着桌宠跑——否则他刚摆好
        位置，桌宠一走面板又飘走了。
        """
        self._anchor = QRect(rect) if rect is not None else None
        if self._anchor is None:
            self.hide()
            self._collapse_timer.stop()
            return
        self._place()
        if not self.isVisible():
            self.show()

    def _place(self) -> None:
        if self._free_pos is not None:
            x, y = self._free_pos.x(), self._free_pos.y()
        else:
            anchor = self._anchor
            if anchor is None:
                return
            x = anchor.right() + ANCHOR_GAP
            y = anchor.center().y() - self.height() // 2
        screen = self.screen()
        if screen is not None:
            area = screen.availableGeometry()
            if self._free_pos is None and x + self.width() > area.right():
                anchor = self._anchor
                if anchor is not None:
                    x = anchor.left() - ANCHOR_GAP - self.width()
            x = max(area.left(), min(x, area.right() - self.width() + 1))
            y = max(area.top(), min(y, area.bottom() - self.height() + 1))
        self.move(QPoint(int(x), int(y)))
        if self._free_pos is not None and (self._free_pos.x() != int(x) or self._free_pos.y() != int(y)):
            # 被屏幕边界钳过：把钳制后的位置当成真实位置，免得反复算错
            self._free_pos = QPoint(int(x), int(y))

    # ------------------------------------------------------------ 贴边 / 缩回
    def _nearest_edge(self) -> str:
        screen = self.screen()
        if screen is None:
            return "none"
        area = screen.availableGeometry()
        rect = self.geometry()
        distances = {
            "left":  abs(rect.left() - area.left()),
            "right": abs(area.right() - rect.right()),
            "top":   abs(rect.top() - area.top()),
            "bottom": abs(area.bottom() - rect.bottom()),
        }
        edge = min(distances, key=lambda key: distances[key])
        return edge if distances[edge] <= SNAP_DISTANCE else "none"

    def _align_to_edge(self) -> None:
        """把窗口贴到当前 ``_edge`` 那条边上（保持另一个轴向不动）。"""
        screen = self.screen()
        if screen is None or self._free_pos is None:
            return
        area = screen.availableGeometry()
        rect = self.geometry()
        x, y = rect.left(), rect.top()
        if self._edge == "left":
            x = area.left()
        elif self._edge == "right":
            x = area.right() - self.width() + 1
        elif self._edge == "top":
            y = area.top()
        elif self._edge == "bottom":
            y = area.bottom() - self.height() + 1
        self.move(QPoint(int(x), int(y)))
        self._free_pos = QPoint(int(x), int(y))

    def _collapse(self) -> None:
        if self._collapsed or self._edge == "none":
            return
        # 记住展开态的左/上角，展开时按同一基准还原（贴右边的靠右对齐）
        self._free_pos = QPoint(self.x(), self.y())
        self._collapsed = True
        self.setFixedSize(self._collapsed_size())
        if self._edge == "right":
            screen = self.screen()
            if screen is not None:
                self.move(QPoint(screen.availableGeometry().right() - self.width() + 1, self.y()))
                self._free_pos = QPoint(self.x(), self.y())
        elif self._edge == "bottom":
            screen = self.screen()
            if screen is not None:
                self.move(QPoint(self.x(), screen.availableGeometry().bottom() - self.height() + 1))
                self._free_pos = QPoint(self.x(), self.y())
        self.update()

    def _expand(self) -> None:
        if not self._collapsed:
            return
        self._collapsed = False
        self.setFixedSize(self._expanded_size())
        if self._edge == "right":
            screen = self.screen()
            if screen is not None:
                self.move(QPoint(screen.availableGeometry().right() - self.width() + 1, self.y()))
        elif self._edge == "bottom":
            screen = self.screen()
            if screen is not None:
                self.move(QPoint(self.x(), screen.availableGeometry().bottom() - self.height() + 1))
        elif self._edge == "left":
            self.move(QPoint(self.screen().availableGeometry().left() if self.screen() else self.x(), self.y()))
        elif self._edge == "top":
            self.move(QPoint(self.x(), self.screen().availableGeometry().top() if self.screen() else self.y()))
        if self.screen() is not None and self._edge != "none":
            self._free_pos = QPoint(self.x(), self.y())
        self.update()

    def _maybe_collapse(self) -> None:
        if self._hover or self._dragging:
            return
        if self._edge == "none":
            return
        self._collapse()

    def _schedule_collapse(self) -> None:
        if self._edge == "none":
            return
        self._collapse_timer.start()

    # ------------------------------------------------------------ 鼠标
    def enterEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self._hover = True
        self._collapse_timer.stop()
        if self._collapsed:
            self._expand()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self._hover = False
        if not self._dragging:
            self._schedule_collapse()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        if self._collapsed:
            self._expand()
        self._dragging = True
        self._collapse_timer.stop()
        self._drag_offset = event.globalPosition().toPoint() - self.pos()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if not self._dragging or self._drag_offset is None:
            super().mouseMoveEvent(event)
            return
        target = event.globalPosition().toPoint() - self._drag_offset
        screen = self.screen()
        if screen is not None:
            area = screen.availableGeometry()
            target.setX(max(area.left(), min(target.x(), area.right() - self.width() + 1)))
            target.setY(max(area.top(), min(target.y(), area.bottom() - self.height() + 1)))
        self.move(target)
        self._free_pos = QPoint(target)
        self._anchor = None  # 一旦手动拖动就脱离跟随
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.button() != Qt.MouseButton.LeftButton or not self._dragging:
            super().mouseReleaseEvent(event)
            return
        self._dragging = False
        self._drag_offset = None
        self.unsetCursor()
        self._free_pos = QPoint(self.pos())
        self._edge = self._nearest_edge()
        if self._edge != "none":
            self._align_to_edge()
        self.position_changed.emit(self.x(), self.y(), self._edge)
        if not self._hover:
            self._schedule_collapse()
        event.accept()

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = _is_dark(self)
        card = QColor(28, 28, 32, 232) if dark else QColor(252, 252, 253, 238)
        border = QColor(255, 255, 255, 26) if dark else QColor(0, 0, 0, 22)
        text = QColor("#e6e6ea") if dark else QColor("#252525")
        hint = QColor("#9a9aa3") if dark else QColor("#777777")
        track = QColor(255, 255, 255, 26) if dark else QColor(0, 0, 0, 18)

        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(border)
        painter.setBrush(card)
        painter.drawRoundedRect(rect, 10, 10)

        if self._collapsed:
            self._paint_handle(painter, hint)
            painter.end()
            return

        font = QFont(self.font())
        font.setPixelSize(10)
        small = QFont(font)
        small.setPixelSize(9)
        metrics = QFontMetrics(font)

        left = HUD_PADDING
        value_width = max(metrics.horizontalAdvance("100"), metrics.horizontalAdvance("8888"))
        bar_left = left + metrics.horizontalAdvance("健康") + 6
        bar_right = self.width() - HUD_PADDING - value_width - 6
        bar_width = max(24, bar_right - bar_left)

        y = HUD_PADDING
        for _key, label, value in self._rows:
            painter.setFont(font)
            painter.setPen(text)
            painter.drawText(
                QRectF(left, y, bar_left - left, HUD_ROW_HEIGHT),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
                label,
            )
            bar_top = y + (HUD_ROW_HEIGHT - 5) / 2.0
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(track)
            painter.drawRoundedRect(QRectF(bar_left, bar_top, bar_width, 5), 2.5, 2.5)
            fill = max(0.0, min(100.0, float(value)))
            if fill > 0:
                painter.setBrush(_bar_color(fill))
                painter.drawRoundedRect(
                    QRectF(bar_left, bar_top, max(2.0, bar_width * fill / 100.0), 5), 2.5, 2.5
                )
            painter.setPen(hint)
            painter.drawText(
                QRectF(bar_right + 6, y, value_width, HUD_ROW_HEIGHT),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                f"{int(round(fill))}",
            )
            y += HUD_ROW_HEIGHT

        # 底行：等级 + 嘟嘟币 + 状态徽标
        y += HUD_GAP
        painter.setFont(small)
        painter.setPen(text)
        money = f"嘟嘟币 {int(round(self._coins))}"
        bottom = f"Lv.{self._level}　{money}" if self._level > 0 else money
        # 徽标在右侧，等级+币在左侧：两者挤在一起时优先保住徽标（它才是"正在发生什么"）
        small_metrics = QFontMetrics(small)
        badge = "·".join(self._badges) if self._badges else ""
        avail = self.width() - HUD_PADDING * 2
        if badge:
            avail -= small_metrics.horizontalAdvance(badge) + 8
        painter.drawText(
            QRectF(left, y, avail, HUD_ROW_HEIGHT),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            small_metrics.elidedText(bottom, Qt.TextElideMode.ElideRight, max(24, int(avail))),
        )
        if self._badges:
            painter.setPen(hint)
            painter.drawText(
                QRectF(left, y, self.width() - HUD_PADDING * 2, HUD_ROW_HEIGHT),
                int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight),
                badge,
            )
        painter.end()

    def _paint_handle(self, painter: QPainter, hint: QColor) -> None:
        """缩回态：画一个抓得住的小把手（三条短横线 = 可拖动的心智模型）。"""
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(hint)
        center_x = self.width() / 2.0
        center_y = self.height() / 2.0
        if self._edge in ("left", "right"):
            # 竖条：三条竖线
            for offset in (-4, 0, 4):
                painter.drawRoundedRect(
                    QRectF(center_x - 1, center_y + offset - 3, 2, 6), 1, 1
                )
            return
        for offset in (-4, 0, 4):
            painter.drawRoundedRect(
                QRectF(center_x + offset - 3, center_y - 1, 6, 2), 1, 1
            )


def hud_anchor_rect(body_rect: QRect, *, mode: str, island_rect: QRect | None = None) -> QRect | None:
    """按展示位配置算锚点：``follow_pet`` 用桌宠身体，``follow_island`` 用岛胶囊。"""
    if mode == "off":
        return None
    if mode == "follow_island":
        return island_rect if island_rect is not None else body_rect
    return body_rect