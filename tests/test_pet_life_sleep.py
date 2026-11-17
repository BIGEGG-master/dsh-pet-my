# -*- coding: utf-8 -*-
"""睡觉作为「生活动作」（v4.7.1）：去睡觉 → 到点醒来恢复精力 / 叫醒按比例结算。

分层照旧：纯逻辑直接对 dict 断言；服务用 tmp_path 里的真 Config 跑，不起 QTimer。
"""
from __future__ import annotations

import time

import pytest

from pet import pet_life as L
from pet import pet_life_data as D
from pet.config import Config
from pet.pet_life_service import CONFIG_KEY, PetLifeService


def _state(**overrides) -> dict:
    state = L.defaults()
    state.update(overrides)
    return state


def _service(tmp_path) -> PetLifeService:
    return PetLifeService(Config(tmp_path))


def _collect(signal) -> list:
    hits: list = []
    signal.connect(lambda *args: hits.append(args))
    return hits


# ---------------------------------------------------------------- 纯逻辑
def test_start_nap_sets_sleeping_and_deadline():
    state = _state()
    result = L.start_nap(state, now=1000.0)
    assert result["ok"] is True
    assert state["sleeping"] is True
    assert state["nap_started_at"] == pytest.approx(1000.0)
    assert state["nap_until"] == pytest.approx(1000.0 + D.NAP_MINUTES * 60.0)
    assert L.is_napping(state) is True


def test_start_nap_rejects_bad_states():
    assert L.start_nap(_state(enabled=False))["ok"] is False
    assert L.start_nap(_state(health=0))["ok"] is False
    assert L.start_nap(_state(sleeping=True))["ok"] is False
    working = _state()
    L.start_job(working, "typing", now=100.0)
    assert L.start_nap(working)["ok"] is False


def test_nap_settles_energy_at_deadline():
    state = _state(energy=20.0, last_tick_at=1000.0)
    L.start_nap(state, now=1000.0)
    until = state["nap_until"]

    result = L.apply_tick(state, now=until + 1.0)

    assert result["napped"] is True
    assert result["woke"] is True
    assert result["nap_gain"] == pytest.approx(D.NAP_ENERGY)
    assert state["sleeping"] is False
    assert state["nap_until"] == 0.0
    # 20 + 40 = 60；睡眠段不再按清醒速率扣（只扣醒来那一小段，误差 < 0.1）
    assert state["energy"] == pytest.approx(60.0, abs=0.1)


def test_nap_does_not_recover_hourly_while_running():
    state = _state(energy=20.0, last_tick_at=1000.0)
    L.start_nap(state, now=1000.0)

    L.apply_tick(state, now=1000.0 + 600.0)   # 10 分钟，还没到点

    assert state["sleeping"] is True
    assert state["energy"] == pytest.approx(20.0)      # 精力只在醒来结算
    assert state["hunger"] < 80                        # 但饥饿照睡速下降


def test_wake_up_early_prorates_energy():
    state = _state(energy=10.0)
    L.start_nap(state, now=1000.0)
    half = 1000.0 + D.NAP_MINUTES * 30.0               # 睡一半

    result = L.wake_up(state, now=half)

    assert result["ok"] is True
    assert result["energy"] == pytest.approx(D.NAP_ENERGY / 2, rel=0.02)
    assert state["sleeping"] is False
    assert state["energy"] == pytest.approx(10.0 + D.NAP_ENERGY / 2, rel=0.02)


def test_wake_up_without_sleep_is_refused():
    assert L.wake_up(_state())["ok"] is False


def test_wake_up_on_auto_sleep_keeps_legacy_gain():
    """精力见底的自动睡：收益已在心跳里给过，叫醒不再补发。"""
    state = _state(sleeping=True, energy=20.0, nap_until=0.0)
    result = L.wake_up(state, now=2000.0)
    assert result["ok"] is True
    assert result["energy"] == 0.0
    assert state["sleeping"] is False


def test_nap_remaining_counts_down():
    state = _state()
    L.start_nap(state, now=1000.0)
    assert L.nap_remaining(state, now=1000.0) == pytest.approx(D.NAP_MINUTES * 60.0)
    assert L.nap_remaining(state, now=1000.0 + 300.0) == pytest.approx(D.NAP_MINUTES * 60.0 - 300.0)
    assert L.nap_remaining(_state()) == 0.0


def test_flags_report_napping():
    state = _state()
    L.start_nap(state, now=1000.0)
    assert L.flags(state)["napping"] is True
    assert L.flags(_state(sleeping=True))["napping"] is False


def test_normalize_clamps_nap_keys():
    state = L.normalize({"nap_started_at": "坏了", "nap_until": -5})
    assert state["nap_started_at"] == 0.0
    assert state["nap_until"] == 0.0


def test_prompt_text_mentions_nap():
    state = _state()
    L.start_nap(state, now=time.time())
    assert "小睡" in L.prompt_text(state)


# ---------------------------------------------------------------- 服务层
def test_service_start_nap_emits_sleep_changed(tmp_path):
    service = _service(tmp_path)
    changes = _collect(service.sleep_changed)
    assert service.start_nap() is True
    assert service.state["sleeping"] is True
    assert changes == [(True,)]
    assert service.napping() is True


def test_service_nap_deadline_wakes_and_reports_gain(tmp_path):
    service = _service(tmp_path)
    service.state["energy"] = 20.0
    assert service.start_nap() is True
    service.state["nap_until"] = time.time() - 1.0     # 到点
    service.state["nap_started_at"] = service.state["nap_until"] - D.NAP_MINUTES * 60.0
    changes = _collect(service.sleep_changed)
    stories = _collect(service.story)
    service.state["last_tick_at"] = time.time()

    service.tick()

    assert service.state["sleeping"] is False
    assert changes == [(False,)]
    assert any("精神" in args[0] for args in stories)


def test_service_wake_up_is_persisted(tmp_path):
    service = _service(tmp_path)
    service.start_nap()
    assert service.wake_up() is True
    again = PetLifeService(Config(tmp_path))
    assert again.state["sleeping"] is False
    assert again.state["nap_until"] == 0.0


def test_service_nap_state_survives_restart(tmp_path):
    service = _service(tmp_path)
    service.start_nap()
    until = service.state["nap_until"]
    again = PetLifeService(Config(tmp_path))
    assert again.state["nap_until"] == pytest.approx(until)


def test_config_roundtrip_keeps_nap_keys(tmp_path):
    config = Config(tmp_path)
    state = L.defaults()
    L.start_nap(state, now=1000.0)
    config.set(CONFIG_KEY, state)
    stored = config.get(CONFIG_KEY)
    assert stored["nap_until"] == pytest.approx(state["nap_until"])


# ---------------------------------------------------------------- 入睡/醒来过渡（v4.7.4）
def test_transition_keyword_pools_exist():
    assert D.CLIP_POOLS["sleep_in"][0] == "入睡过渡"
    assert D.CLIP_POOLS["sleep_out"][0] == "醒来过渡"


def test_transition_clips_are_pickable_from_sleep_pool():
    """过渡段放在 videos/sleep/，只属于 sleeps 池——点名播放要挑得到。"""
    pool = ["入睡过渡", "醒来过渡", "睡觉-主"]
    assert L.pick_clip(pool, "sleep_in") == "入睡过渡"
    assert L.pick_clip(pool, "sleep_out") == "醒来过渡"


def test_pose_still_wins_for_hold_slot():
    """常驻姿态不能被过渡段顶掉（过渡段是一次性的，循环播它很怪）。"""
    pool = ["入睡过渡", "醒来过渡", "睡觉-主"]
    assert L.pick_clip(pool, "sleep") == "睡觉-主"


def test_transition_pool_falls_back_to_none_without_clips():
    assert L.pick_clip(["随便"], "sleep_in") is None
    assert L.pick_clip([], "sleep_out") is None
