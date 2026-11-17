# -*- coding: utf-8 -*-
"""养成系统的**纯逻辑**（零 Qt、零 IO）：夹紧、衰减、睡觉、工作结算、商店、动作、状态文案。

设计约束（照 ``pet/diary.py`` 的写法，理由相同）：

- **纯函数 + 就地改 dict**：状态就是一个 ``dict``，从 ``config.get("pet_life")`` 拿出来
  的原始 JSON。所有函数就地修改并返回结构化结果，不持有 Config、不发信号——
  这样任何一条规则都能被单测直接钉住，也不需要构造 Qt 应用。
- **绝不抛异常**：数值来自用户可手改的 JSON，坏值一律当默认值。养成是锦上添花，
  它出错不能连累桌宠启动。
- **时间用 epoch 秒**（``time.time()``）而非 monotonic：要跨进程重启生效
  （离线 3 小时回来该掉属性，工作该结算完）。
"""
from __future__ import annotations

import random
import time
from typing import Any

from . import pet_life_data as D

#: 存档结构版本（只写不读：为将来迁移留锚点，v1 不消费）
SCHEMA_VERSION = 1


# ---------------------------------------------------------------- 基础


def defaults() -> dict[str, Any]:
    """一份全新的养成状态。"""
    return {
        "schema": SCHEMA_VERSION,
        "enabled": True,
        "hunger": 80,
        "thirst": 80,
        "mood": 90,
        "energy": 60,
        "health": 100,
        "coins": 100,
        "sleeping": False,
        "hud": "follow_pet",
        # 状态条被拖动后的自由位置与贴边方向（-1 = 从未拖动，继续跟随桌宠）。
        # 放这里而不是另开配置键：它就是养成面板的展示状态，整值提交不会丢。
        "hud_x": -1,
        "hud_y": -1,
        "hud_edge": "none",
        # 主动小睡（「去睡觉」生活动作）：nap_until>0 表示这一觉有**到点时间**，
        # 到点自动醒并一次性结算精力；0 = 自动入睡（靠 WAKE_THRESHOLD 滞回醒）。
        "nap_started_at": 0.0,
        "nap_until": 0.0,
        "job": None,
        "last_tick_at": 0.0,
        "last_feed_at": 0.0,
        "last_drink_at": 0.0,
        "last_event_at": {},
        "owned": [],
        # 经验值：**唯一真值**。等级一律由它派生（``level_for``），不另存 ``level``
        # ——两个字段各自落盘迟早会不同步，而"等级对不上经验"是最难查的那种错。
        "xp": 0.0,
        # 已经播报过"学会某技能"的技能 id：解锁播报只该发生一次，
        # 而解锁状态本身是从等级派生的（见 ``unlocked_skills``）。
        "announced_skills": [],
        # 自主行为冷却戳（``{"work": ts, "shop": ts}``）。放这里而不是另开配置键：
        # 它就是养成状态的一部分，整值提交不会丢。
        "last_auto_at": {},
        # 自主技能总开关（用户可以在面板上关掉，让"她自己动"变成纯手养）。
        "autonomy": True,
    }


def _num(value: Any, default: float) -> float:
    """把任意 JSON 值转成有限浮点数；bool 不算数字（JSON 里 true 不是 1）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):  # NaN / inf
        return default
    return number


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def normalize(raw: Any) -> dict[str, Any]:
    """把盘上的原始值归一成可用状态（类型兜底 + 区间夹紧）。

    未知键**保留**：向前兼容（新版本写的字段被旧版本读到再存回去时不该丢）。
    默认值取 ``defaults()`` 而不是 ``update(raw)`` 之后的值——否则坏值会顶掉
    自己的兜底（NaN 会一路漂过 clamp）。
    """
    base = defaults()
    state = dict(base)
    if not isinstance(raw, dict):
        return state
    state.update(raw)
    state["schema"] = SCHEMA_VERSION
    for key in D.STATUS_KEYS:
        state[key] = clamp(_num(raw.get(key), base[key]))
    state["coins"] = max(0.0, _num(raw.get("coins"), base["coins"]))
    state["enabled"] = bool(raw.get("enabled", True))
    state["sleeping"] = bool(raw.get("sleeping", False))
    state["hud"] = str(raw.get("hud") or "follow_pet")
    if state["hud"] not in ("follow_pet", "follow_island", "off"):
        state["hud"] = "follow_pet"
    state["last_tick_at"] = max(0.0, _num(raw.get("last_tick_at"), 0.0))
    state["last_feed_at"] = max(0.0, _num(raw.get("last_feed_at"), 0.0))
    state["last_drink_at"] = max(0.0, _num(raw.get("last_drink_at"), 0.0))
    state["nap_started_at"] = max(0.0, _num(raw.get("nap_started_at"), 0.0))
    state["nap_until"] = max(0.0, _num(raw.get("nap_until"), 0.0))
    job = raw.get("job")
    state["job"] = job if isinstance(job, dict) and job.get("id") in D.JOBS else None
    events = raw.get("last_event_at")
    state["last_event_at"] = (
        {str(k): max(0.0, _num(v, 0.0)) for k, v in events.items()}
        if isinstance(events, dict) else {}
    )
    owned = raw.get("owned")
    state["owned"] = [str(item) for item in owned] if isinstance(owned, list) else []
    # 经验：手改坏值（负数 / 字符串 / NaN）一律回到 0，绝不抛错。
    state["xp"] = max(0.0, _num(raw.get("xp"), 0.0))
    announced = raw.get("announced_skills")
    state["announced_skills"] = (
        [str(item) for item in announced if str(item) in D.SKILLS]
        if isinstance(announced, list) else []
    )
    auto = raw.get("last_auto_at")
    state["last_auto_at"] = (
        {str(k): max(0.0, _num(v, 0.0)) for k, v in auto.items()}
        if isinstance(auto, dict) else {}
    )
    state["autonomy"] = bool(raw.get("autonomy", True))
    return state


def is_sick(state: dict[str, Any]) -> bool:
    return _num(state.get("health"), 0.0) <= 0.0


def apply_delta(state: dict[str, Any], effects: dict[str, float]) -> None:
    """按增量改属性（就地、夹紧）；``coins`` 允许超过 100。"""
    for key, delta in effects.items():
        if key == "coins":
            state["coins"] = max(0.0, _num(state.get("coins"), 0.0) + delta)
        elif key in D.STATUS_KEYS:
            state[key] = clamp(_num(state.get(key), 0.0) + delta)


# ---------------------------------------------------------------- 经验与等级
#: 等级上限 = 阈值表长度（表尾就是满级）
MAX_LEVEL: int = len(D.LEVEL_THRESHOLDS)


def level_for(xp: Any) -> int:
    """累计经验 -> 等级（1..MAX_LEVEL）。坏值当 0 经验。"""
    value = max(0.0, _num(xp, 0.0))
    level = 1
    for index, threshold in enumerate(D.LEVEL_THRESHOLDS):
        if value >= float(threshold):
            level = index + 1
        else:
            break
    return level


def level_progress(xp: Any) -> dict[str, float | int]:
    """``{"level", "into", "need", "next_at", "xp"}``：本级已有 / 本级总共需要。

    满级时 ``need == 0``（面板据此显示"已满级"，不做除零）。
    """
    value = max(0.0, _num(xp, 0.0))
    level = level_for(value)
    if level >= MAX_LEVEL:
        base = float(D.LEVEL_THRESHOLDS[MAX_LEVEL - 1])
        return {
            "level": MAX_LEVEL,
            "into": value - base,
            "need": 0.0,
            "next_at": base,
            "xp": value,
        }
    base = float(D.LEVEL_THRESHOLDS[level - 1])
    next_at = float(D.LEVEL_THRESHOLDS[level])
    return {
        "level": level,
        "into": value - base,
        "need": next_at - base,
        "next_at": next_at,
        "xp": value,
    }


def grant_xp(state: dict[str, Any], amount: Any) -> dict[str, Any]:
    """加经验，返回 ``{"xp", "gained", "level_before", "level_after", "leveled_up"}``。

    经验不设上限（等级封顶，经验继续累加）：满级后再干活不该"扣经验"，
    也不该因为夹紧而让面板的经验条来回跳。
    """
    gained = max(0.0, _num(amount, 0.0))
    before_xp = _num(state.get("xp"), 0.0)
    before_level = level_for(before_xp)
    after_xp = before_xp + gained
    state["xp"] = after_xp
    after_level = level_for(after_xp)
    return {
        "xp": after_xp,
        "gained": gained,
        "level_before": before_level,
        "level_after": after_level,
        "leveled_up": after_level > before_level,
    }


# ---------------------------------------------------------------- 技能
def unlocked_skills(level: Any) -> list[str]:
    """该等级已解锁的技能 id（按解锁等级排序，结果稳定）。"""
    value = 0.0 if level is None else _num(level, 0.0)
    items = sorted(D.SKILLS.items(), key=lambda pair: (pair[1]["level"], pair[0]))
    return [skill_id for skill_id, spec in items if value >= float(spec["level"])]


def has_skill(state: dict[str, Any], skill_id: str) -> bool:
    return skill_id in unlocked_skills(level_for(state.get("xp")))


def take_new_skills(state: dict[str, Any]) -> list[str]:
    """返回"刚解锁、还没播报过"的技能 id，并就地盖戳（保证只播报一次）。

    技能解锁状态由等级派生，所以这里存的不是"解锁了什么"，而是"说过了什么"。
    """
    fresh = [sid for sid in unlocked_skills(level_for(state.get("xp")))
             if sid not in (state.get("announced_skills") or [])]
    if not fresh:
        return []
    announced = state.get("announced_skills")
    if not isinstance(announced, list):
        announced = []
    state["announced_skills"] = [*announced, *fresh]
    return fresh


def level_up_line(level: int) -> str:
    return D.LEVEL_UP_LINE.format(level=int(level))


def skill_unlock_line(skill_id: str) -> str:
    return D.SKILL_UNLOCK_LINES.get(skill_id, "")


# ---------------------------------------------------------------- 衰减与睡觉


def apply_tick(state: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    """推进一次心跳，返回 ``{"hours", "slept", "woke", "napped", "nap_gain"}``。

    - 首次调用（``last_tick_at`` 为 0）只记时间，不衰减：不能让"第一次装"就掉一半血。
    - 单次最多结算 ``MAX_TICK_HOURS``：关机一周回来不该瞬间病倒。
    - 精力见底自动睡、睡到 ``WAKE_THRESHOLD`` 自动醒（滞回，不在阈值上抖）。
    - **主动小睡**（``nap_until > 0``）到点先结算：一次性给精力、落下睡眠，
      期间不再按小时回血（否则"半小时 +10 再 +40"两套收益叠着算）。
    """
    moment = time.time() if now is None else float(now)
    last = _num(state.get("last_tick_at"), 0.0)
    state["last_tick_at"] = moment
    empty = {"hours": 0.0, "slept": False, "woke": False, "napped": False, "nap_gain": 0.0}
    if last <= 0:
        return empty

    hours = min(max(0.0, (moment - last) / 3600.0), D.MAX_TICK_HOURS)
    if hours <= 0:
        return empty

    if not bool(state.get("enabled", True)):
        return {**empty, "hours": hours}

    slept = woke = napped = False
    nap_gain = 0.0
    nap_until = _num(state.get("nap_until"), 0.0)
    nap_end = 0.0

    # ① 主动小睡到点：先结算（``_settle_nap`` 会自己把 sleeping 落下）
    if nap_until > 0.0 and moment >= nap_until:
        nap_gain = _settle_nap(state, moment)
        woke = napped = True
        nap_end = nap_until
        nap_until = 0.0

    # ② 自动入睡 / 醒来（滞回）。主动小睡期间不参与这套判据：
    #    它的醒来时刻由 ``nap_until`` 决定，不该被"精力已经够了"提前叫醒。
    energy = _num(state.get("energy"), 0.0)
    if not bool(state.get("sleeping")):
        if energy <= D.SLEEP_THRESHOLD:
            state["sleeping"] = True
            slept = True
    elif nap_until <= 0.0 and energy >= D.WAKE_THRESHOLD:
        state["sleeping"] = False
        woke = True

    # 数据表里 DECAY_PER_HOUR 是"每小时往下掉多少"的正数，这里统一转成增量；
    # SLEEP_PER_HOUR 已经是增量（energy 为正=恢复）。
    if napped:
        # 这一拍**跨了睡与醒两段**（关机回来时可能整段都在睡）：分开算。
        # 把睡着的时长按清醒速率扣一遍，就等于"睡醒时先回满再扣半小时"，
        # 数字与观感都对不上。
        sleep_hours = min(hours, max(0.0, (min(moment, nap_end) - last) / 3600.0))
        awake_hours = max(0.0, hours - sleep_hours)
        deltas: dict[str, float] = {
            key: per_hour * sleep_hours for key, per_hour in D.SLEEP_PER_HOUR.items()
        }
        deltas.pop("energy", None)   # 精力由小睡结算一次性给
        for key, rate in D.DECAY_PER_HOUR.items():
            deltas[key] = deltas.get(key, 0.0) - rate * awake_hours
    elif bool(state.get("sleeping")):
        deltas = dict(D.SLEEP_PER_HOUR)
        if nap_until > 0.0:
            # 小睡期间的精力由醒来那一次性结算给，这里不叠加
            deltas.pop("energy", None)
    else:
        deltas = {key: -rate for key, rate in D.DECAY_PER_HOUR.items()}
    for key, delta_per_hour in deltas.items():
        state[key] = clamp(_num(state.get(key), 0.0) + delta_per_hour * hours)

    starving = 0
    if _num(state.get("hunger"), 0.0) <= 0:
        starving += 1
    if _num(state.get("thirst"), 0.0) <= 0:
        starving += 1
    if starving:
        state["health"] = clamp(
            _num(state.get("health"), 0.0) - D.STARVING_HEALTH_PER_HOUR * starving * hours
        )
    return {
        "hours": hours,
        "slept": slept,
        "woke": woke,
        "napped": napped,
        "nap_gain": nap_gain,
    }


# ---------------------------------------------------------------- 睡觉（生活动作）


def is_napping(state: dict[str, Any]) -> bool:
    """是不是在「主动小睡」（有到点时间的睡，区别于精力见底的自动睡）。"""
    return bool(state.get("sleeping")) and _num(state.get("nap_until"), 0.0) > 0.0


def nap_remaining(state: dict[str, Any], now: float | None = None) -> float:
    """小睡还要睡多少秒（没在睡 = 0）。面板/HUD 显示用。"""
    if not is_napping(state):
        return 0.0
    moment = time.time() if now is None else float(now)
    return max(0.0, _num(state.get("nap_until"), 0.0) - moment)


def _settle_nap(state: dict[str, Any], moment: float) -> float:
    """结算一次小睡（到点或被叫醒），返回**实际**恢复的精力。

    提前叫醒按实际睡的比例给：睡 1 分钟拿满 40 精力等于白送。
    """
    started = _num(state.get("nap_started_at"), 0.0)
    until = _num(state.get("nap_until"), 0.0)
    planned = (until - started) if (until > started) else D.NAP_MINUTES * 60.0
    planned = max(60.0, planned)
    elapsed = planned if started <= 0 else max(0.0, min(moment - started, planned))
    gain = round(D.NAP_ENERGY * (elapsed / planned), 1)
    state["sleeping"] = False
    state["nap_started_at"] = 0.0
    state["nap_until"] = 0.0
    if gain > 0:
        apply_delta(state, {"energy": gain})
    return gain


def start_nap(
    state: dict[str, Any],
    now: float | None = None,
    minutes: float | None = None,
) -> dict[str, Any]:
    """「去睡觉」：躺下，睡 ``NAP_MINUTES`` 分钟后自动醒并结算精力。

    拒绝条件与工作/玩耍同源：关闭、病倒（先吃）、在干活（先停下）、已经在睡。
    """
    if not bool(state.get("enabled", True)):
        return {"ok": False, "reason": "养成系统已关闭", "line": ""}
    if is_sick(state):
        return {"ok": False, "reason": D.NAP_SICK_LINE, "line": ""}
    if isinstance(state.get("job"), dict):
        return {"ok": False, "reason": D.NAP_WORKING_LINE, "line": ""}
    if bool(state.get("sleeping")):
        return {"ok": False, "reason": D.NAP_ALREADY_LINE, "line": ""}
    moment = time.time() if now is None else float(now)
    length = D.NAP_MINUTES if minutes is None else max(1.0, _num(minutes, D.NAP_MINUTES))
    state["sleeping"] = True
    state["nap_started_at"] = moment
    state["nap_until"] = moment + length * 60.0
    line = D.NAP_START_LINE.format(
        minutes=int(round(length)), energy=int(round(D.NAP_ENERGY))
    )
    return {"ok": True, "reason": "", "line": line}


def wake_up(state: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    """叫醒她：小睡中被叫醒按已睡时长比例结算；自动睡只落状态（收益已在心跳里给过）。"""
    if not bool(state.get("sleeping")):
        return {"ok": False, "reason": "她没在睡嘟。", "line": "", "energy": 0.0}
    moment = time.time() if now is None else float(now)
    if _num(state.get("nap_until"), 0.0) > 0.0:
        gain = _settle_nap(state, moment)
        return {
            "ok": True,
            "reason": "",
            "line": D.NAP_INTERRUPT_LINE.format(energy=int(round(gain))),
            "energy": gain,
        }
    state["sleeping"] = False
    return {"ok": True, "reason": "", "line": D.WAKE_LINE, "energy": 0.0}


# ---------------------------------------------------------------- 自主事件


def due_needs(state: dict[str, Any], now: float | None = None) -> list[str]:
    """返回**本次该提醒**的需求键（已按冷却过滤并就地盖戳）。

    冷却按需求键独立计：饿了和渴了可以同一次各说一句，但同一句 30 分钟内不重复。
    """
    moment = time.time() if now is None else float(now)
    if is_sick(state) or not bool(state.get("enabled", True)):
        return []
    if bool(state.get("sleeping")):
        return []  # 睡着了就别喊饿，醒来说
    seen = state.get("last_event_at")
    if not isinstance(seen, dict):
        seen = {}
        state["last_event_at"] = seen
    due: list[str] = []
    for key, threshold in D.NEED_THRESHOLDS.items():
        if _num(state.get(key), 100.0) > threshold:
            continue
        last = _num(seen.get(key), 0.0)
        if moment - last < D.EVENT_COOLDOWN_MINUTES * 60.0:
            continue
        seen[key] = moment
        due.append(key)
    return due


def need_line(key: str, rng: random.Random | None = None) -> str:
    lines = D.NEED_LINES.get(key) or ()
    if not lines:
        return ""
    return (rng or random).choice(lines)


# ---------------------------------------------------------------- 工作


def start_job(
    state: dict[str, Any],
    job_id: str,
    now: float | None = None,
) -> dict[str, Any]:
    """开始一份工作。返回 ``{"ok": bool, "reason": str}``。"""
    if job_id not in D.JOBS:
        return {"ok": False, "reason": "没有这份工作"}
    if not bool(state.get("enabled", True)):
        return {"ok": False, "reason": "养成系统已关闭"}
    if is_sick(state):
        return {"ok": False, "reason": D.SICK_LINE}
    if bool(state.get("sleeping")):
        return {"ok": False, "reason": "她睡着了嘟，叫醒她再干活。"}
    if isinstance(state.get("job"), dict):
        return {"ok": False, "reason": "她已经在忙了嘟。"}
    moment = time.time() if now is None else float(now)
    job = D.JOBS[job_id]
    state["job"] = {
        "id": job_id,
        "started_at": moment,
        "ends_at": moment + float(job.get("duration_minutes", 10)) * 60.0,
    }
    return {"ok": True, "reason": ""}


def settle_job(
    state: dict[str, Any],
    now: float | None = None,
) -> dict[str, Any] | None:
    """到点的活儿结算掉，返回 ``{"job_id", "coins", "line"}``；没到点返回 ``None``。"""
    job = state.get("job")
    if not isinstance(job, dict):
        return None
    job_id = str(job.get("id") or "")
    spec = D.JOBS.get(job_id)
    if spec is None:
        state["job"] = None
        return None
    moment = time.time() if now is None else float(now)
    if moment < _num(job.get("ends_at"), 0.0):
        return None
    coins = int(spec.get("coins", 0))
    apply_delta(state, {"coins": coins})
    apply_delta(state, spec.get("effects") or {})
    state["job"] = None
    # 经验与钱一起结算：中断的活不结算（``cancel_job``），所以不存在"白刷经验"。
    xp_result = grant_xp(state, D.JOB_XP.get(job_id, 0))
    lines = D.JOB_DONE_LINES.get(job_id) or ()
    line = (random.choice(lines).format(coins=coins) if lines else f"赚到 {coins} 币嘟。")
    return {
        "job_id": job_id,
        "coins": coins,
        "line": line,
        "xp": int(xp_result["gained"]),
        "level_before": xp_result["level_before"],
        "level_after": xp_result["level_after"],
    }


def cancel_job(state: dict[str, Any]) -> bool:
    """中断工作：**不结算**收益（避免"开了就关"白拿钱）。"""
    if not isinstance(state.get("job"), dict):
        return False
    state["job"] = None
    return True


def job_progress(state: dict[str, Any], now: float | None = None) -> float:
    """0..1 的进度（面板画进度条用）；没在干活返回 0。"""
    job = state.get("job")
    if not isinstance(job, dict):
        return 0.0
    start = _num(job.get("started_at"), 0.0)
    end = _num(job.get("ends_at"), 0.0)
    if end <= start:
        return 0.0
    moment = time.time() if now is None else float(now)
    return clamp((moment - start) / (end - start), 0.0, 1.0)


# ---------------------------------------------------------------- 商店与动作


def buy(
    state: dict[str, Any],
    item_id: str,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """买一件东西。返回 ``{"ok", "reason", "quip", "extra_line"}``。"""
    spec = D.SHOP_ITEMS.get(item_id)
    if spec is None:
        return {"ok": False, "reason": "没有这件商品", "quip": "", "extra_line": ""}
    if not bool(state.get("enabled", True)):
        return {"ok": False, "reason": "养成系统已关闭", "quip": "", "extra_line": ""}
    price = float(spec.get("price", 0))
    if _num(state.get("coins"), 0.0) < price:
        return {
            "ok": False,
            "reason": D.NOT_ENOUGH_COINS_LINE,
            "quip": "",
            "extra_line": "",
        }
    apply_delta(state, {"coins": -price})
    apply_delta(state, spec.get("effects") or {})
    extra = ""
    gamble = spec.get("gamble")
    if isinstance(gamble, dict):
        hit = (rng or random).random() < float(gamble.get("chance", 0.0))
        if hit:
            apply_delta(state, gamble.get("effects") or {})
        extra = D.GAMBLE_HIT_LINE if hit else D.GAMBLE_MISS_LINE
    return {
        "ok": True,
        "reason": "",
        "quip": str(spec.get("quip") or ""),
        "extra_line": extra,
    }


def _cooldown_left(last_at: Any, minutes: float, moment: float) -> float:
    """剩余冷却秒数（<=0 表示可用）。"""
    return _num(last_at, 0.0) + minutes * 60.0 - moment


def feed(state: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    """免费喂食（有冷却）。"""
    moment = time.time() if now is None else float(now)
    if not bool(state.get("enabled", True)):
        return {"ok": False, "reason": "养成系统已关闭", "quip": ""}
    # 睡着了不喂（别吵醒）；但病倒时允许——喂食是把她救回来的唯一手段。
    if bool(state.get("sleeping")) and not is_sick(state):
        return {"ok": False, "reason": "她睡着了嘟，别吵醒她。", "quip": ""}
    left = _cooldown_left(state.get("last_feed_at"), D.FEED_COOLDOWN_MINUTES, moment)
    if left > 0:
        return {
            "ok": False,
            "reason": f"{D.FEED_COOLDOWN_LINE}（还要等 {int(left // 60) + 1} 分钟）",
            "quip": "",
        }
    state["last_feed_at"] = moment
    apply_delta(state, D.FEED_EFFECTS)
    return {"ok": True, "reason": "", "quip": D.FEED_LINE}


def drink(state: dict[str, Any], now: float | None = None) -> dict[str, Any]:
    """免费喝水（有冷却）。"""
    moment = time.time() if now is None else float(now)
    if not bool(state.get("enabled", True)):
        return {"ok": False, "reason": "养成系统已关闭", "quip": ""}
    if bool(state.get("sleeping")) and not is_sick(state):
        return {"ok": False, "reason": "她睡着了嘟，待会儿再喝。", "quip": ""}
    left = _cooldown_left(state.get("last_drink_at"), D.DRINK_COOLDOWN_MINUTES, moment)
    if left > 0:
        return {
            "ok": False,
            "reason": f"{D.DRINK_COOLDOWN_LINE}（还要等 {int(left // 60) + 1} 分钟）",
            "quip": "",
        }
    state["last_drink_at"] = moment
    apply_delta(state, D.DRINK_EFFECTS)
    return {"ok": True, "reason": "", "quip": D.DRINK_LINE}


def play(state: dict[str, Any], act_id: str) -> dict[str, Any]:
    """玩耍：心情/健康涨，精力掉。病倒/睡觉/在干活时拒绝。"""
    spec = D.PLAY_ACTS.get(act_id)
    if spec is None:
        return {"ok": False, "reason": "没有这种玩法", "quip": ""}
    if not bool(state.get("enabled", True)):
        return {"ok": False, "reason": "养成系统已关闭", "quip": ""}
    if is_sick(state):
        return {"ok": False, "reason": D.SICK_LINE, "quip": ""}
    if bool(state.get("sleeping")):
        return {"ok": False, "reason": "她睡着了嘟。", "quip": ""}
    if isinstance(state.get("job"), dict):
        return {"ok": False, "reason": "她正在工作嘟，先停下再玩。", "quip": ""}
    apply_delta(state, spec.get("effects") or {})
    # 玩耍也给经验，但比工作少一截（表在 pet_life_data.PLAY_XP）
    xp_result = grant_xp(state, D.PLAY_XP.get(act_id, 0))
    return {
        "ok": True,
        "reason": "",
        "quip": str(spec.get("quip") or ""),
        "xp": int(xp_result["gained"]),
        "level_before": xp_result["level_before"],
        "level_after": xp_result["level_after"],
    }


# ---------------------------------------------------------------- 自主技能
#
# 技能本身不存"已解锁"标记：解锁状态完全由等级派生（``unlocked_skills``）。
# 这里只关心"这一拍她要不要自己动一下"，且**一拍最多动一次**——
# 同一拍又买东西又打工会让数值与气泡同时乱跳，玩家看不懂发生了什么。


def _auto_cooldown_ok(state: dict[str, Any], kind: str, minutes: float, moment: float) -> bool:
    stamps = state.get("last_auto_at")
    last = _num(stamps.get(kind), 0.0) if isinstance(stamps, dict) else 0.0
    return moment - last >= minutes * 60.0


def _stamp_auto(state: dict[str, Any], kind: str, moment: float) -> None:
    stamps = state.get("last_auto_at")
    if not isinstance(stamps, dict):
        stamps = {}
        state["last_auto_at"] = stamps
    stamps[kind] = float(moment)


def auto_job_choice(state: dict[str, Any]) -> str | None:
    """按当前精力挑一份**做得动**的最高收入工作；一份都做不动返回 ``None``。"""
    energy = _num(state.get("energy"), 0.0)
    best_id: str | None = None
    best_coins = -1
    for job_id, spec in D.JOBS.items():
        cost = -_num((spec.get("effects") or {}).get("energy"), 0.0)  # 表里是负数（消耗）
        if cost > 0 and energy - cost < D.AUTO_WORK_ENERGY_RESERVE:
            continue
        coins = int(spec.get("coins", 0))
        if coins > best_coins:
            best_id, best_coins = job_id, coins
    return best_id


def auto_buy_choice(state: dict[str, Any]) -> str | None:
    """按"先救命、再解渴、后解饿"的顺序挑一件**买得起的对症商品**。"""
    coins = _num(state.get("coins"), 0.0)
    for key, threshold in D.AUTO_BUY_THRESHOLDS.items():
        if _num(state.get(key), 100.0) >= threshold:
            continue
        candidates: list[tuple[float, str]] = []
        for item_id, spec in D.SHOP_ITEMS.items():
            price = _num(spec.get("price"), 0.0)
            gain = _num((spec.get("effects") or {}).get(key), 0.0)
            if price <= coins and gain > 0:
                candidates.append((price, item_id))
        if candidates:
            candidates.sort()
            return candidates[0][1]
    return None


def auto_action(
    state: dict[str, Any],
    now: float | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any] | None:
    """自主技能决策：返回 ``{"kind", "id", "line"}``（并**就地执行**），否则 ``None``。

    优先级：先"自己买东西"（属性见底是急事），再"自己打工"（缺钱才动）。
    所有前置条件（开关、睡、病、在忙、冷却、钱、精力）都在这里判完，
    服务层只管把 ``line`` 发成气泡——规则留在纯函数里才钉得住。
    """
    if not bool(state.get("enabled", True)) or not bool(state.get("autonomy", True)):
        return None
    if bool(state.get("sleeping")) or isinstance(state.get("job"), dict):
        return None
    moment = time.time() if now is None else float(now)
    skills = unlocked_skills(level_for(state.get("xp")))

    if "self_shop" in skills and _auto_cooldown_ok(
        state, "shop", D.AUTO_BUY_COOLDOWN_MINUTES, moment
    ):
        item_id = auto_buy_choice(state)
        if item_id:
            result = buy(state, item_id, rng=rng)
            if bool(result.get("ok")):
                _stamp_auto(state, "shop", moment)
                name = str((D.SHOP_ITEMS.get(item_id) or {}).get("name") or "")
                line = D.AUTO_BUY_LINE.format(item=name).strip()
                quip = str(result.get("quip") or "")
                return {
                    "kind": "buy",
                    "id": item_id,
                    "line": " ".join(part for part in (line, quip) if part),
                }

    if (
        "self_work" in skills
        and not is_sick(state)
        and _num(state.get("coins"), 0.0) < D.AUTO_WORK_COINS
        and _num(state.get("energy"), 0.0) >= D.AUTO_WORK_MIN_ENERGY
        and _auto_cooldown_ok(state, "work", D.AUTO_WORK_COOLDOWN_MINUTES, moment)
    ):
        job_id = auto_job_choice(state)
        if job_id:
            result = start_job(state, job_id, now=moment)
            if bool(result.get("ok")):
                _stamp_auto(state, "work", moment)
                return {"kind": "work", "id": job_id, "line": D.AUTO_WORK_LINE}
    return None


# ---------------------------------------------------------------- 动画挑选


def pick_clip(acts: Any, kind: str) -> str | None:
    """在素材库的 ``acts`` 里按关键词池挑一个动画名；挑不到返回 ``None``。

    只做子串匹配，不改素材、不猜名字——素材改名了这里自然失效（静默不播），
    比播错一个动作安全。
    """
    pool = D.CLIP_POOLS.get(kind) or ()
    if not pool or not acts:
        return None
    try:
        names = [str(name) for name in acts]
    except TypeError:
        return None
    for keyword in pool:
        for name in names:
            if keyword in name:
                return name
    return None


# ---------------------------------------------------------------- 文案


def status_level(key: str, value: float) -> str:
    """属性 -> 一句人话（注入 prompt 与 HUD 提示共用同一口径）。"""
    level = _num(value, 0.0)
    if key == "hunger":
        return "饿坏了" if level < 20 else "有点饿" if level < 40 else "不饿" if level < 70 else "吃饱了"
    if key == "thirst":
        return "渴得不行" if level < 20 else "有点渴" if level < 40 else "不渴" if level < 70 else "喝足了"
    if key == "energy":
        return "困得睁不开眼" if level <= 15 else "有点困" if level < 40 else "精神还行" if level < 70 else "很精神"
    if key == "mood":
        return "很低落" if level < 20 else "有点闷" if level < 40 else "还不错" if level < 70 else "心情很好"
    if key == "health":
        return "病倒了" if level <= 0 else "很虚弱" if level < 30 else "还行" if level < 70 else "很健康"
    return f"{level:.0f}"


def _growth_text(state: dict[str, Any]) -> str:
    """等级与技能的一句话（注入段用；面板另有一套自己的画法）。

    为什么放进注入：等级决定了她"会不会自己动"，模型知道这件事，
    才不会在她说"我去打工了"的时候当成胡话。
    """
    progress = level_progress(state.get("xp"))
    level = int(progress["level"])
    need = float(progress["need"])
    if need > 0:
        level_text = f"Lv.{level}（本级 {int(round(float(progress['into'])))}/{int(round(need))} 经验）"
    else:
        level_text = f"Lv.{level}（已满级）"
    skills = unlocked_skills(level)
    skill_text = "、".join(str(D.SKILLS[sid]["name"]) for sid in skills) if skills else "还没有"
    return f"\n【等级与技能】{level_text}；已掌握的自主技能：{skill_text}。"


def prompt_text(state: dict[str, Any]) -> str:
    """给 AI 的状态注入段。空状态（未启用）返回空串——调用方据此跳过注入。"""
    if not bool(state.get("enabled", True)):
        return ""
    parts = [
        f"{D.STATUS_LABELS[key]} {int(round(_num(state.get(key), 0.0)))}/100"
        f"（{status_level(key, _num(state.get(key), 0.0))}）"
        for key in D.STATUS_KEYS
    ]
    head = "【嘟嘟当前状态】" + "、".join(parts) + f"、嘟嘟币 {int(_num(state.get('coins'), 0.0))}。"
    head += _growth_text(state)

    rules: list[str] = [
        # 这条永远在：她必须对自己当下的状态**说实话**。少了它，模型会照人设
        # 硬撑"我不困"（实机就是这么答的），注入的数值等于白给。
        "被问到困不困、累不累、饿不饿、渴不渴、心情怎么样时，"
        "必须照上面的档位如实回答（精力 25 就是「有点困」），"
        "不许说反话，也不许用「我很好」盖过去",
    ]
    energy = _num(state.get("energy"), 100.0)
    if energy <= 15:
        rules.append("她现在困得不行：回话要短、句子软、多撒娇、会想睡觉")
    elif energy < 40:
        rules.append("她有点困：回话比平时短一点、语气软一点")
    elif energy >= 70:
        rules.append("她精力很好：可以活泼一点、话多一点")
    if _num(state.get("hunger"), 100.0) < 20:
        rules.append("她饿坏了：会惦记吃的、容易分心")
    if _num(state.get("thirst"), 100.0) < 20:
        rules.append("她很渴：会想喝水")
    if _num(state.get("mood"), 100.0) < 20:
        rules.append("她心情低落：安静、黏人、不太主动开玩笑")
    if is_sick(state):
        rules.append("她病倒了：非常虚弱，几乎只想休息，需要被照顾")
    if isinstance(state.get("job"), dict):
        rules.append("她正在干活：偶尔抱怨累，但不会停下")
    if is_napping(state):
        rules.append("她正在小睡（定了时间的觉）：说话含糊、声音轻，会想接着睡")
    elif bool(state.get("sleeping")):
        rules.append("她正在睡觉：说话要含糊、像刚被叫醒")

    tail = ""
    if rules:
        tail = "\n【表达要求】" + "；".join(rules) + "。不要复述这些数字，也不要解释这份状态。"
    return head + tail


def hud_rows(state: dict[str, Any]) -> list[tuple[str, str, float]]:
    """HUD 用的行：``[(属性键, 中文名, 0..100)]``，顺序即显示顺序。"""
    return [
        (key, D.STATUS_LABELS[key], clamp(_num(state.get(key), 0.0)))
        for key in D.STATUS_KEYS
    ]


def flags(state: dict[str, Any]) -> dict[str, bool]:
    """状态标记（服务层与面板共用，避免各处自己判）。"""
    return {
        "enabled": bool(state.get("enabled", True)),
        "sleeping": bool(state.get("sleeping")),
        "napping": is_napping(state),
        "sick": is_sick(state),
        "working": isinstance(state.get("job"), dict),
    }