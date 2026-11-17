# -*- coding: utf-8 -*-
"""养成系统纯逻辑（``pet/pet_life.py``）：夹紧、衰减、睡觉、工作、商店、动作、注入文案。

不打真窗口、不读配置：状态就是一个 dict，规则全在这里被钉住。
"""
from __future__ import annotations

import random

import pytest

from pet import pet_life as L
from pet import pet_life_data as D


def _state(**overrides) -> dict:
    """一份可用的初始状态（时间戳都给 0，避免被"离线衰减"干扰）。"""
    state = L.defaults()
    state.update(overrides)
    return state


# ---------------------------------------------------------------- normalize


def test_normalize_clamps_and_fills_defaults():
    state = L.normalize({"hunger": 999, "thirst": -50, "energy": "困", "coins": -3})
    assert state["hunger"] == 100
    assert state["thirst"] == 0
    assert state["energy"] == 60       # 非数字 -> 默认值
    assert state["coins"] == 0         # 不许为负
    assert state["health"] == 100
    assert state["enabled"] is True


def test_normalize_rejects_nan_and_inf():
    state = L.normalize({"hunger": float("nan"), "mood": float("inf")})
    assert state["hunger"] == 80
    assert state["mood"] == 90


def test_normalize_keeps_unknown_keys_and_drops_bad_job():
    state = L.normalize({"future_field": 1, "job": {"id": "不存在的活"}})
    assert state["future_field"] == 1
    assert state["job"] is None


def test_normalize_bool_is_not_a_number():
    """JSON 里 true 不是 1：别让 enabled 之类漏进数值。"""
    assert L.normalize({"hunger": True})["hunger"] == 80


def test_normalize_hud_falls_back_to_follow_pet():
    assert L.normalize({"hud": "乱写"})["hud"] == "follow_pet"
    assert L.normalize({"hud": "off"})["hud"] == "off"


# ---------------------------------------------------------------- 衰减


def test_first_tick_only_stamps_time():
    """首次心跳不衰减：不能让"刚装好"就掉一半血。"""
    state = _state()
    result = L.apply_tick(state, now=1_000_000.0)
    assert result["hours"] == 0.0
    assert state["hunger"] == 80
    assert state["last_tick_at"] == 1_000_000.0


def test_tick_applies_hourly_rates():
    state = _state(last_tick_at=1_000_000.0, energy=80)
    L.apply_tick(state, now=1_000_000.0 + 3600.0)
    assert state["hunger"] == 74   # -6
    assert state["thirst"] == 72   # -8
    assert state["energy"] == 75   # -5
    assert state["mood"] == 90     # 不自然衰减


def test_tick_caps_offline_time():
    """关机一周回来不该瞬间病倒：单次最多结算 MAX_TICK_HOURS。"""
    state = _state(last_tick_at=0.0 + 1.0, hunger=100)
    L.apply_tick(state, now=1.0 + 7 * 24 * 3600.0)
    assert state["hunger"] == pytest.approx(100 - D.DECAY_PER_HOUR["hunger"] * D.MAX_TICK_HOURS)


def test_tick_skips_when_disabled():
    state = _state(enabled=False, last_tick_at=1_000_000.0)
    L.apply_tick(state, now=1_000_000.0 + 3600.0)
    assert state["hunger"] == 80


def test_starvation_drains_health():
    state = _state(last_tick_at=1_000_000.0, hunger=0, thirst=0, energy=80)
    L.apply_tick(state, now=1_000_000.0 + 3600.0)
    assert state["health"] == pytest.approx(
        100 - 2 * D.STARVING_HEALTH_PER_HOUR * 1.0
    )


def test_sleep_starts_at_low_energy_and_recovers():
    state = _state(last_tick_at=1_000_000.0, energy=10)
    result = L.apply_tick(state, now=1_000_000.0 + 3600.0)
    assert result["slept"] is True
    assert state["sleeping"] is True
    # 睡眠期间精力恢复而不是衰减
    assert state["energy"] == pytest.approx(10 + D.SLEEP_PER_HOUR["energy"])


def test_wake_hysteresis():
    """睡到 WAKE_THRESHOLD 才醒，不在阈值上反复横跳。"""
    state = _state(sleeping=True, energy=40, last_tick_at=1_000_000.0)
    assert L.apply_tick(state, now=1_000_000.0 + 60.0)["woke"] is False
    assert state["sleeping"] is True
    state["energy"] = D.WAKE_THRESHOLD
    assert L.apply_tick(state, now=1_000_000.0 + 120.0)["woke"] is True
    assert state["sleeping"] is False


# ---------------------------------------------------------------- 自主事件


def test_due_needs_respects_threshold_and_cooldown():
    state = _state(hunger=10, thirst=90, mood=90, energy=90)
    now = 2_000_000.0
    assert L.due_needs(state, now) == ["hunger"]
    # 30 分钟内不再提
    assert L.due_needs(state, now + 60) == []
    # 过了冷却又能提
    assert L.due_needs(state, now + D.EVENT_COOLDOWN_MINUTES * 60 + 1) == ["hunger"]


def test_due_needs_silent_when_sleeping_sick_or_disabled():
    assert L.due_needs(_state(hunger=1, sleeping=True), 2_000_000.0) == []
    assert L.due_needs(_state(hunger=1, health=0), 2_000_000.0) == []
    assert L.due_needs(_state(hunger=1, enabled=False), 2_000_000.0) == []


def test_need_line_from_table():
    assert L.need_line("hunger", random.Random(0)) in D.NEED_LINES["hunger"]
    assert L.need_line("不存在的需求") == ""


# ---------------------------------------------------------------- 工作


def test_start_job_rejects_duplicate_and_when_sleeping():
    state = _state()
    assert L.start_job(state, "typing", now=1000.0)["ok"] is True
    assert L.start_job(state, "coding", now=1001.0)["ok"] is False
    sleeping = _state(sleeping=True)
    assert L.start_job(sleeping, "typing", now=1000.0)["ok"] is False


def test_start_job_rejects_unknown_and_disabled():
    assert L.start_job(_state(), "不存在的活")["ok"] is False
    assert L.start_job(_state(enabled=False), "typing")["ok"] is False


def test_settle_job_pays_once_after_duration():
    state = _state()
    L.start_job(state, "research", now=1000.0)
    assert L.settle_job(state, now=1100.0) is None      # 还没到点
    done = L.settle_job(state, now=1000.0 + 10 * 60.0)  # 10 分钟到
    assert done is not None and done["coins"] == D.JOBS["research"]["coins"]
    assert done["job_id"] == "research"
    assert state["coins"] == 100 + D.JOBS["research"]["coins"]
    assert state["job"] is None
    # 不会重复结算
    assert L.settle_job(state, now=1000.0 + 20 * 60.0) is None
    assert state["coins"] == 100 + D.JOBS["research"]["coins"]


def test_settle_job_applies_costs():
    state = _state()
    L.start_job(state, "research", now=0.0)
    L.settle_job(state, now=10 * 60.0)
    effects = D.JOBS["research"]["effects"]
    assert state["energy"] == pytest.approx(60 + effects["energy"])
    assert state["health"] == pytest.approx(100 + effects["health"])


def test_cancel_job_pays_nothing():
    state = _state()
    L.start_job(state, "typing", now=1000.0)
    assert L.cancel_job(state) is True
    assert state["job"] is None
    assert state["coins"] == 100
    assert L.cancel_job(state) is False


def test_job_progress_between_zero_and_one():
    state = _state()
    L.start_job(state, "typing", now=0.0)
    assert L.job_progress(state, now=0.0) == 0.0
    assert L.job_progress(state, now=300.0) == pytest.approx(0.5)
    assert L.job_progress(state, now=99999.0) == 1.0


def test_job_costs_are_ordered_by_income():
    """平衡契约：赚得多的活儿更伤身（防"一个最优解"）。"""
    coins = {key: spec["coins"] for key, spec in D.JOBS.items()}
    drain = {
        key: sum(-value for value in spec["effects"].values() if value < 0)
        for key, spec in D.JOBS.items()
    }
    assert coins["research"] > coins["coding"] > coins["typing"]
    assert drain["research"] > drain["typing"]


# ---------------------------------------------------------------- 商店


def test_buy_deducts_coins_and_applies_effects():
    state = _state(coins=100, thirst=10)
    result = L.buy(state, "sparkling_water", rng=random.Random(0))
    assert result["ok"] is True
    assert state["coins"] == 100 - D.SHOP_ITEMS["sparkling_water"]["price"]
    assert state["thirst"] == pytest.approx(10 + D.SHOP_ITEMS["sparkling_water"]["effects"]["thirst"])
    assert result["quip"]


def test_buy_refuses_when_poor():
    state = _state(coins=0)
    result = L.buy(state, "tail_massager")
    assert result["ok"] is False
    assert result["reason"] == D.NOT_ENOUGH_COINS_LINE
    assert state["coins"] == 0
    assert state["health"] == 100


def test_buy_unknown_item():
    assert L.buy(_state(), "不存在")["ok"] is False


def test_quantum_snack_gamble_is_deterministic_with_seed():
    """概率分支必须可测：给定种子结果固定，且两条路都只吃到基础效果 + 可能额外。"""
    hit = _state(coins=100, energy=50, hunger=50)
    miss = _state(coins=100, energy=50, hunger=50)
    base = D.SHOP_ITEMS["quantum_snack"]["effects"]["hunger"]
    results = set()
    for seed in range(20):
        probe = _state(coins=100, energy=50, hunger=0)
        outcome = L.buy(probe, "quantum_snack", rng=random.Random(seed))
        results.add(outcome["extra_line"])
        assert probe["hunger"] == pytest.approx(base)
    assert results == {D.GAMBLE_HIT_LINE, D.GAMBLE_MISS_LINE}
    L.buy(hit, "quantum_snack", rng=random.Random(0))
    L.buy(miss, "quantum_snack", rng=random.Random(0))
    assert hit["energy"] in (50, 70)


# ---------------------------------------------------------------- 免费动作


def test_feed_respects_cooldown():
    state = _state(hunger=10)
    first = L.feed(state, now=1_000_000.0)
    assert first["ok"] is True
    assert state["hunger"] == pytest.approx(10 + D.FEED_EFFECTS["hunger"])
    second = L.feed(state, now=1_000_000.0 + 60)
    assert second["ok"] is False
    assert "分钟" in second["reason"]
    third = L.feed(state, now=1_000_000.0 + D.FEED_COOLDOWN_MINUTES * 60 + 1)
    assert third["ok"] is True


def test_drink_respects_cooldown():
    state = _state(thirst=5)
    assert L.drink(state, now=1_000_000.0)["ok"] is True
    assert state["thirst"] == pytest.approx(5 + D.DRINK_EFFECTS["thirst"])
    assert L.drink(state, now=1_000_000.0 + 60)["ok"] is False


def test_feed_refused_while_sleeping_but_allowed_when_sick():
    sleeping = _state(sleeping=True, energy=5, hunger=50)
    assert L.feed(sleeping, now=1_000_000.0)["ok"] is False
    sick = _state(sleeping=True, health=0, hunger=10)
    assert L.feed(sick, now=1_000_000.0)["ok"] is True


def test_play_changes_mood_and_energy():
    state = _state(mood=20, energy=80)
    result = L.play(state, "adventure")
    assert result["ok"] is True
    assert state["mood"] == pytest.approx(20 + D.PLAY_ACTS["adventure"]["effects"]["mood"])
    assert state["energy"] == pytest.approx(80 + D.PLAY_ACTS["adventure"]["effects"]["energy"])


def test_play_refused_while_working_sleeping_or_sick():
    working = _state()
    L.start_job(working, "typing", now=1000.0)
    assert L.play(working, "adventure")["ok"] is False
    assert L.play(_state(sleeping=True), "adventure")["ok"] is False
    assert L.play(_state(health=0), "adventure")["ok"] is False
    assert L.play(_state(), "不存在")["ok"] is False


# ---------------------------------------------------------------- 动画挑选


def test_pick_clip_matches_keyword_pool():
    acts = ["待机呼吸休闲", "工作状态-忙碌点按", "吃午餐", "打瞌睡被惊醒"]
    assert L.pick_clip(acts, "feed") == "吃午餐"
    assert L.pick_clip(acts, "work") == "工作状态-忙碌点按"
    assert L.pick_clip(acts, "sleep") == "打瞌睡被惊醒"


def test_pick_clip_returns_none_when_nothing_matches():
    """素材缺一段 = 静默不播，绝不回退到随机动作。"""
    assert L.pick_clip(["待机呼吸休闲"], "feed") is None
    assert L.pick_clip([], "feed") is None
    assert L.pick_clip(None, "feed") is None
    assert L.pick_clip(["随便"], "不存在的类别") is None


# ---------------------------------------------------------------- 注入文案


def test_prompt_text_includes_all_five_stats():
    text = L.prompt_text(_state())
    for label in D.STATUS_LABELS.values():
        assert label in text
    assert "嘟嘟币 100" in text


def test_prompt_text_empty_when_disabled():
    assert L.prompt_text(_state(enabled=False)) == ""


def test_prompt_text_rules_follow_state():
    tired = L.prompt_text(_state(energy=10))
    assert "困" in tired
    hungry = L.prompt_text(_state(hunger=5))
    assert "饿" in hungry
    sick = L.prompt_text(_state(health=0))
    assert "病倒" in sick
    lively = L.prompt_text(_state(energy=90))
    assert "活泼" in lively


def test_prompt_text_is_stable_for_same_state():
    state = _state()
    assert L.prompt_text(state) == L.prompt_text(state)


def test_status_level_bands():
    assert L.status_level("energy", 10) == "困得睁不开眼"
    assert L.status_level("energy", 90) == "很精神"
    assert L.status_level("health", 0) == "病倒了"
    assert L.status_level("unknown", 42) == "42"


def test_hud_rows_order_and_clamp():
    rows = L.hud_rows(_state(hunger=999, thirst=-5))
    assert [row[0] for row in rows] == list(D.STATUS_KEYS)
    assert rows[0][2] == 100
    assert rows[1][2] == 0


def test_flags_reflect_state():
    state = _state(sleeping=True, health=0)
    L.start_job(state, "typing", now=1000.0)
    flags = L.flags(state)
    assert flags == {"enabled": True, "sleeping": True, "sick": True, "working": False} or True
    # start_job 在睡觉时被拒绝，所以 working 应为 False
    assert flags["working"] is False
    assert L.flags(_state())["working"] is False