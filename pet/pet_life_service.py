# -*- coding: utf-8 -*-
"""养成系统的运行时服务：心跳、落盘、把纯逻辑的结果变成 Qt 信号。

**分层**（与 ``pet/todo/`` 同款）：

- ``pet_life.py``：纯规则，不认识 Qt；
- 本模块：持 Config、跑 60s QTimer、调纯规则、把结果发成信号；
- ``AppShell``：把信号接到 ``show_bubble`` / 动画 / 托盘；
- ``pet_life_dialog`` / ``pet_life_hud``：只读状态、只发动作请求。

服务**不直接弹气泡、不直接播动画**：它只发信号（``story`` / ``need_raised`` /
``job_finished``）。这样服务可以在没有窗口的测试里跑，也避免 Qt 控件与数据层
互相持有。

写盘节流：``tick`` 每分钟一次，本身就等于一次落盘节奏；动作类调用立即落盘
（用户点完就该落盘，进程崩了不该丢）。
"""
from __future__ import annotations

import logging
import time
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from . import pet_life as L
from . import pet_life_data as D

log = logging.getLogger(__name__)

#: 心跳间隔（毫秒）。与 todo/voice_chime 的 20s/30s 同量级：属性是小时级变化，
#: 一分钟一拍已经足够细，也避免频繁唤醒 GUI 线程。
TICK_INTERVAL_MS = 60_000

#: 配置键（顶层，不进 ``chat``：``set_chat_settings`` 会整棵覆盖 chat）
CONFIG_KEY = "pet_life"


class PetLifeService(QObject):
    """一个进程一份（只服务主宠：子肥鱼不建服务）。"""

    #: 数值有任何变化（HUD 重绘 / 面板刷新用）
    changed = Signal()
    #: 她想说一句话（喂食 / 玩耍 / 商店 / 睡觉醒来）——AppShell 接 show_bubble
    story = Signal(str)
    #: 自主需求（饥饿/口渴/困/闷）：(需求键, 台词)——AppShell 接 show_bubble + 动画
    need_raised = Signal(str, str)
    #: 工作完成：(台词, 收入)
    job_finished = Signal(str, int)
    #: 升级：(新等级)。只在真的跨过等级线时发一次
    level_up = Signal(int)
    #: 学会自主技能：(技能 id)。同样只在"刚解锁"那一拍发一次
    skill_unlocked = Signal(str)
    #: 睡眠状态变化：(是否在睡)。睡觉姿态常驻靠它进/出
    sleep_changed = Signal(bool)

    def __init__(self, config, parent: QObject | None = None) -> None:
        # 防御：调用方偶尔会传测试桩（不是 QObject）。PySide 对非法 parent 是硬报错，
        # 而"养成服务构不出来"不该连累桌宠启动——退化成一个无父对象。
        super().__init__(parent if isinstance(parent, QObject) else None)
        self._config = config
        self._state = L.normalize(config.get(CONFIG_KEY))
        self._timer: QTimer | None = None
        # 起床/入睡这类"状态转换台词"只在真的发生时发一次（避免每次 tick 复读）
        self._last_saved = 0.0
        # 初始指纹 = 刚读进来的状态：启动那一次心跳**不写盘**（盘上本来就是最新的）。
        # 只有真的结算了离线变化（币变了 / 工作结完）才落盘。
        self._last_fingerprint: tuple | None = None
        self._last_fingerprint = self._fingerprint()
    # ------------------------------------------------------------ 生命周期
    def start(self) -> None:
        """按第一个 interval 开始心跳（幂等）。"""
        if self._timer is not None:
            if not self._timer.isActive():
                self._timer.start()
            return
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_INTERVAL_MS)
        self._timer.timeout.connect(self.tick)
        self._timer.start()
        # 启动即结算一次：能立刻发现"离线期间已完成的工作"，也能立刻进入睡眠态
        self.tick(emit=self._emit_on_startup)

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    @property
    def running(self) -> bool:
        return self._timer is not None and self._timer.isActive()

    # ------------------------------------------------------------ 读
    @property
    def state(self) -> dict[str, Any]:
        return self._state

    def prompt_text(self) -> str:
        """给 AI 的状态注入段（未启用时为空串）。"""
        return L.prompt_text(self._state)

    def hud_rows(self):
        return L.hud_rows(self._state)

    def flags(self) -> dict[str, bool]:
        return L.flags(self._state)

    def job_progress(self) -> float:
        return L.job_progress(self._state)

    def level(self) -> int:
        return L.level_for(self._state.get("xp"))

    def xp_progress(self) -> dict:
        """``{"level", "into", "need", "next_at", "xp"}``（面板画经验条用）。"""
        return L.level_progress(self._state.get("xp"))

    def skills(self) -> list[str]:
        """已解锁技能 id（由等级派生）。"""
        return L.unlocked_skills(self.level())

    def all_skills(self) -> list[tuple[str, dict, bool]]:
        """技能清单 ``[(id, 表项, 是否已解锁)]``，顺序按解锁等级。"""
        level = self.level()
        items = sorted(D.SKILLS.items(), key=lambda pair: (pair[1]["level"], pair[0]))
        return [(sid, spec, level >= int(spec["level"])) for sid, spec in items]

    def autonomy(self) -> bool:
        return bool(self._state.get("autonomy", True))

    def current_job(self) -> dict | None:
        """当前工作的静态描述（名称/描述/收入），没在干活返回 None。"""
        job = self._state.get("job")
        if not isinstance(job, dict):
            return None
        spec = D.JOBS.get(str(job.get("id") or ""))
        if spec is None:
            return None
        return {"id": str(job.get("id")), **spec}

    # ------------------------------------------------------------ 心跳
    def tick(self, *, emit: Any = None) -> None:
        """推进一次。``emit`` 是"要不要发信号"的钩子：默认发，启动那一拍降噪。"""
        notify = self._emit if emit is None else emit
        if not bool(self._state.get("enabled", True)):
            # 关闭时只推进时间戳（不写盘：一分钟一次的空转 IO 没意义）。
            # 内存里的时间戳一直在走，重新启用时不会突然按"离线很久"扣一次。
            self._state["last_tick_at"] = time.time()
            return
        result = L.apply_tick(self._state)
        if result.get("slept"):
            notify(self.story, D.SLEEP_LINE)
            notify(self.sleep_changed, True)
        if result.get("woke"):
            if result.get("napped"):
                # 主动小睡到点：收益在结算里，台词要把数报出来
                gain = int(round(float(result.get("nap_gain") or 0.0)))
                notify(self.story, D.NAP_DONE_LINE.format(energy=gain))
            else:
                notify(self.story, D.WAKE_LINE)
            notify(self.sleep_changed, False)

        done = L.settle_job(self._state)
        if done is not None:
            notify(self.job_finished, done["line"], int(done["coins"]))
            self._announce_level(notify, done)

        # 技能解锁播报（由等级派生，播过就盖戳；不播报的进程里也不会重播）
        self._announce_skills(notify)

        # 自主技能：解锁后她会在心跳里自己动（打工 / 买东西），
        # 台词走 story 气泡，和用户手动点的动作同一条通道。
        auto = L.auto_action(self._state)
        if auto is not None:
            line = str(auto.get("line") or "")
            if line:
                notify(self.story, line)

        for key in L.due_needs(self._state):
            notify(self.need_raised, key, L.need_line(key))

        # ``_persist`` 内部**每拍都**把状态同步进 config 内存（写盘仍按指纹节流）：
        # 聊天侧注入走 ``config.get("pet_life")``，只在真落盘时才同步的话，
        # 对话看到的是上一次落盘的状态——那是"精力 26 却说不困"的第二个来源。
        self._persist()
        notify(self.changed)

    def _announce_level(self, notify, result: dict) -> None:
        """经验结算结果里带了升级就播一次。"""
        if "level_after" not in result and "level_before" not in result:
            return  # 不是经验结算（喂食/喝水/商店），没有升级可言
        before = int(result.get("level_before") or 1)
        after = int(result.get("level_after") or before)
        if after > before:
            notify(self.level_up, after)
            notify(self.story, L.level_up_line(after))

    def _announce_skills(self, notify) -> None:
        for skill_id in L.take_new_skills(self._state):
            notify(self.skill_unlocked, skill_id)
            line = L.skill_unlock_line(skill_id)
            if line:
                notify(self.story, line)

    def _emit(self, signal, *args) -> None:
        try:
            signal.emit(*args)
        except Exception:  # 槽里抛异常不该打断心跳
            log.exception("养成服务信号投递失败: %s", getattr(signal, "name", signal))

    def _emit_on_startup(self, signal, *args) -> None:
        """启动那一拍：只发"需要立刻知道的"（工作完成、睡醒），不刷自主需求。

        刚开机就弹"哥哥我饿了"会显得很吵；等下一个整点拍再说。
        """
        if any(signal is target for target in (
            self.job_finished, self.changed, self.level_up, self.skill_unlocked,
            self.sleep_changed,
        )):
            self._emit(signal, *args)

    # ------------------------------------------------------------ 动作
    def feed(self) -> bool:
        result = L.feed(self._state)
        return self._after_action(result, "feed")

    def drink(self) -> bool:
        result = L.drink(self._state)
        return self._after_action(result, "drink")

    def play(self, act_id: str) -> bool:
        result = L.play(self._state, act_id)
        return self._after_action(result, "play")

    def start_nap(self) -> bool:
        """「去睡觉」：躺下，``NAP_MINUTES`` 分钟后自动醒并结算精力。"""
        result = L.start_nap(self._state)
        ok = bool(result.get("ok"))
        if not ok:
            reason = str(result.get("reason") or "")
            if reason:
                self._emit(self.story, reason)
            return False
        line = str(result.get("line") or "")
        if line:
            self._emit(self.story, line)
        self._persist(force=True)
        self._emit(self.sleep_changed, True)
        self._emit(self.changed)
        return True

    def wake_up(self) -> bool:
        """叫醒她（手动）。小睡中按已睡时长比例结算精力。"""
        result = L.wake_up(self._state)
        ok = bool(result.get("ok"))
        if not ok:
            reason = str(result.get("reason") or "")
            if reason:
                self._emit(self.story, reason)
            return False
        line = str(result.get("line") or "")
        if line:
            self._emit(self.story, line)
        self._persist(force=True)
        self._emit(self.sleep_changed, False)
        self._emit(self.changed)
        return True

    def nap_remaining(self) -> float:
        """小睡还要多少秒（没在睡 = 0）。"""
        return L.nap_remaining(self._state)

    def napping(self) -> bool:
        return L.is_napping(self._state)

    def start_job(self, job_id: str) -> bool:
        result = L.start_job(self._state, job_id)
        ok = bool(result.get("ok"))
        if not ok:
            reason = str(result.get("reason") or "")
            if reason:
                self._emit(self.story, reason)
            return False
        self._persist(force=True)
        self._emit(self.changed)
        return True

    def cancel_job(self) -> bool:
        if not L.cancel_job(self._state):
            return False
        self._emit(self.story, D.JOB_CANCELLED_LINE)
        self._persist(force=True)
        self._emit(self.changed)
        return True

    def buy(self, item_id: str) -> bool:
        result = L.buy(self._state, item_id)
        ok = bool(result.get("ok"))
        if not ok:
            reason = str(result.get("reason") or "")
            if reason:
                self._emit(self.story, reason)
            return ok
        quip = str(result.get("quip") or "")
        extra = str(result.get("extra_line") or "")
        line = " ".join(part for part in (quip, extra) if part)
        if line:
            self._emit(self.story, line)
        self._persist(force=True)
        self._emit(self.changed)
        return ok

    def _after_action(self, result: dict, kind: str) -> bool:
        ok = bool(result.get("ok"))
        if not ok:
            reason = str(result.get("reason") or "")
            if reason:
                self._emit(self.story, reason)
            return False
        quip = str(result.get("quip") or "")
        if quip:
            self._emit(self.story, quip)
        # 玩耍也会给经验（升级/解锁技能都要播报），所以这两步放在落盘之前：
        # ``take_new_skills`` 会改写 announced_skills，盖戳必须一起落盘。
        self._announce_level(self._emit, result)
        self._announce_skills(self._emit)
        self._persist(force=True)
        self._emit(self.changed)
        return True

    # ------------------------------------------------------------ 开关与展示位
    def set_enabled(self, enabled: bool) -> None:
        """总开关。关闭时立刻中断工作（不结算：避免"开了就关"白拿钱）。"""
        enabled = bool(enabled)
        if bool(self._state.get("enabled", True)) == enabled:
            return
        self._state["enabled"] = enabled
        if not enabled and isinstance(self._state.get("job"), dict):
            L.cancel_job(self._state)
        self._persist(force=True)
        self._emit(self.changed)

    def enabled(self) -> bool:
        return bool(self._state.get("enabled", True))

    def set_autonomy(self, enabled: bool) -> None:
        """自主技能总开关：关掉后她不再自己打工/买东西（纯手养）。

        "她替我花钱"这件事必须有否决权，所以单独一个开关，而不是塞进技能解锁里。
        """
        enabled = bool(enabled)
        if bool(self._state.get("autonomy", True)) == enabled:
            return
        self._state["autonomy"] = enabled
        self._persist(force=True)
        self._emit(self.changed)

    def hud_mode(self) -> str:
        return str(self._state.get("hud") or "follow_pet")

    def hud_position(self) -> tuple[int, int, str]:
        """状态条上次被拖动到的位置：(x, y, edge)。``x/y <= 0`` = 从未拖动。"""
        state = self._state
        try:
            x = int(state.get("hud_x", -1))
            y = int(state.get("hud_y", -1))
        except (TypeError, ValueError):
            x = y = -1
        edge = str(state.get("hud_edge") or "none")
        return x, y, edge

    def set_hud_position(self, x: int, y: int, edge: str) -> None:
        """用户拖动/吸附后记住位置（强制落盘：用户刚摆好的位置不该丢）。"""
        state = self._state
        state["hud_x"] = int(x)
        state["hud_y"] = int(y)
        state["hud_edge"] = str(edge or "none")
        self._persist(force=True)

    def set_hud_mode(self, mode: str) -> None:
        if mode not in ("follow_pet", "follow_island", "off"):
            mode = "follow_pet"
        self._state["hud"] = mode
        self._persist(force=True)
        self._emit(self.changed)

    def reset(self) -> None:
        """恢复出厂（面板上的"重新养一只"）。"""
        self._state = L.defaults()
        self._persist(force=True)
        self._emit(self.changed)

    # ------------------------------------------------------------ 落盘
    def _fingerprint(self) -> tuple:
        """「值得落盘的」状态指纹。

        为什么不带 ``last_tick_at``：它每分钟都变，带上就等于每分钟写一次配置；
        而桌宠 legacy 拓扑按 ``config-slot-0.json`` 的 mtime 判「档案是否变了」，
        频繁写盘会让它反复走重建分支。属性是慢变量（每小时个位数），指纹稳定 =
        不写盘。

        冷却时间戳必须进指纹：否则重启能绕过喂食/喝水冷却。
        """
        state = self._state
        job = state.get("job")
        return (
            round(float(state.get("hunger") or 0.0), 1),
            round(float(state.get("thirst") or 0.0), 1),
            round(float(state.get("mood") or 0.0), 1),
            round(float(state.get("energy") or 0.0), 1),
            round(float(state.get("health") or 0.0), 1),
            round(float(state.get("coins") or 0.0), 0),
            bool(state.get("sleeping")),
            round(float(state.get("nap_started_at") or 0.0), 0),
            round(float(state.get("nap_until") or 0.0), 0),
            bool(state.get("enabled", True)),
            str(state.get("hud") or ""),
            str(job.get("id")) if isinstance(job, dict) else None,
            round(float(state.get("last_feed_at") or 0.0), 0),
            round(float(state.get("last_drink_at") or 0.0), 0),
            len(state.get("last_event_at") or {}),
            # 经验与技能播报也必须进指纹：否则"打了工但经验没落盘"、
            # "解锁播报盖了戳却没写盘（重启又播一遍）"都会发生。
            round(float(state.get("xp") or 0.0), 0),
            tuple(sorted(str(item) for item in (state.get("announced_skills") or []))),
            bool(state.get("autonomy", True)),
            tuple(sorted(
                (str(key), round(float(value or 0.0), 0))
                for key, value in (state.get("last_auto_at") or {}).items()
            )),
        )

    def _sync_memory(self) -> None:
        """把当前状态同步进 config 的**内存**（不写盘）。

        聊天侧（``pet/chat/*``）注入状态时读的是 ``config.get("pet_life")``，
        所以这份内存副本必须每一拍都跟上；写盘节奏仍由 ``_persist`` 的指纹管住
        （legacy 拓扑按 config mtime 判档案变化，不能每分钟写一次）。
        """
        try:
            self._config.set(CONFIG_KEY, self._state)
        except Exception:
            log.exception("养成状态内存同步失败")

    def _persist(self, *, force: bool = False) -> None:
        """落盘。``force=True`` 用于用户动作（点了就该落，崩了不该丢）。"""
        fingerprint = self._fingerprint()
        # 先同步内存：即使这一拍不需要写盘，聊天侧也应当看到最新状态。
        self._sync_memory()
        if not force and fingerprint == self._last_fingerprint:
            return
        try:
            if not self._config.save():
                log.warning("养成状态写盘失败（内存值继续用，下次心跳再试）")
                return
            self._last_fingerprint = fingerprint
            self._last_saved = time.time()
        except Exception:
            log.exception("养成状态写盘异常")


def prompt_text_from_config(config) -> str:
    """给聊天层用的**只读**入口：按盘上状态生成注入段，不构造服务、不落盘。

    聊天窗口（``pet/chat/widgets.py``）可能在服务没起来的进程里跑（无 chat 变体、
    设置进程、测试），所以它只读不算：状态坏了就当没有注入，绝不影响发消息。
    """
    try:
        return L.prompt_text(L.normalize(config.get(CONFIG_KEY)))
    except Exception:
        log.debug("养成状态读取失败，本轮不注入", exc_info=True)
        return ""