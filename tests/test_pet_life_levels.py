# -*- coding: utf-8 -*-
"""v4.7.0 成长线：经验 / 等级 / 技能解锁 / 自主行为 / 状态注入。

分层照旧：纯逻辑（``pet_life``）用 dict 直接钉死；服务（``PetLifeService``）
用 ``tmp_path`` 里的一份真 ``Config`` 跑，不起 QTimer；注入通道连源码一起钉
——"某个聊天面忘了注入"正是 v4.6.0 那个真 bug 的形状。
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from pet import pet_life as L
from pet import pet_life_data as D
from pet.chat.pet_status import pet_status_text
from pet.config import Config
from pet.pet_life_service import CONFIG_KEY, PetLifeService, prompt_text_from_config


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


def _finished_job(job_id: str = "typing", seconds_ago: float = 5.0) -> dict:
    """一份"已经到点"的工作（不真的等 10 分钟）。"""
    now = time.time()
    return {"id": job_id, "started_at": now - 700.0, "ends_at": now - seconds_ago}


# ---------------------------------------------------------------- 等级
def test_level_for_boundaries():
    assert L.level_for(0) == 1
    assert L.level_for(39.9) == 1
    assert L.level_for(40) == 2
    assert L.level_for(99.9) == 2
    assert L.level_for(100) == 3
    assert L.level_for(D.LEVEL_THRESHOLDS[-1]) == L.MAX_LEVEL
    assert L.level_for(10**9) == L.MAX_LEVEL      # 经验不封顶，等级封顶
    assert L.level_for(-50) == 1
    assert L.level_for("坏了") == 1


def test_level_progress_reports_into_and_need():
    progress = L.level_progress(150)
    assert progress["level"] == 3
    assert progress["into"] == pytest.approx(50.0)
    assert progress["need"] == pytest.approx(80.0)
    assert progress["next_at"] == pytest.approx(180.0)


def test_level_progress_at_max_level_has_zero_need():
    progress = L.level_progress(D.LEVEL_THRESHOLDS[-1] + 10)
    assert progress["level"] == L.MAX_LEVEL
    assert progress["need"] == 0          # 面板据此显示"已满级"，不除零


def test_grant_xp_can_cross_two_levels():
    state = _state(xp=38)
    result = L.grant_xp(state, 70)
    assert (result["level_before"], result["level_after"]) == (1, 3)
    assert state["xp"] == pytest.approx(108.0)


# ---------------------------------------------------------------- 经验来源
def test_job_settlement_grants_xp():
    state = _state()
    L.start_job(state, "research", now=1000.0)
    done = L.settle_job(state, now=1000.0 + 601)
    assert done["xp"] == D.JOB_XP["research"]
    assert state["xp"] == D.JOB_XP["research"]


def test_cancelled_job_grants_no_xp():
    state = _state()
    L.start_job(state, "research", now=1000.0)
    assert L.cancel_job(state) is True
    assert L.settle_job(state, now=1000.0 + 601) is None
    assert state["xp"] == 0


def test_play_grants_less_xp_than_work():
    state = _state()
    result = L.play(state, "adventure")
    assert result["ok"] is True
    assert state["xp"] == D.PLAY_XP["adventure"]
    assert state["xp"] < min(D.JOB_XP.values())


def test_job_xp_records_level_transition():
    state = _state(xp=float(D.LEVEL_THRESHOLDS[1]) - 1)   # 差 1 点升级
    L.start_job(state, "typing", now=1000.0)
    done = L.settle_job(state, now=1000.0 + 601)
    assert (done["level_before"], done["level_after"]) == (1, 2)


# ---------------------------------------------------------------- 技能
def test_skills_unlock_by_level():
    assert L.unlocked_skills(1) == []
    assert L.unlocked_skills(2) == []
    assert L.unlocked_skills(3) == ["self_work"]
    assert L.unlocked_skills(4) == ["self_work"]
    assert L.unlocked_skills(5) == ["self_work", "self_shop"]
    assert L.unlocked_skills(L.MAX_LEVEL) == ["self_work", "self_shop"]


def test_take_new_skills_announces_only_once():
    state = _state(xp=100.0)          # Lv3
    assert L.take_new_skills(state) == ["self_work"]
    assert L.take_new_skills(state) == []
    state["xp"] = 280.0               # 升到 Lv5，只补报新那一个
    assert L.take_new_skills(state) == ["self_shop"]


def test_normalize_filters_unknown_skills_and_clamps_xp():
    state = L.normalize({
        "xp": -5,
        "announced_skills": ["self_work", "乱写", 7],
        "last_auto_at": {"work": 12},
        "autonomy": 0,
    })
    assert state["xp"] == 0
    assert state["announced_skills"] == ["self_work"]
    assert state["last_auto_at"] == {"work": 12.0}
    assert state["autonomy"] is False


# ---------------------------------------------------------------- 自主行为
def test_auto_work_triggers_when_broke():
    state = _state(xp=float(D.LEVEL_THRESHOLDS[2]), coins=5, energy=60)
    action = L.auto_action(state, now=10_000.0)
    assert action is not None and action["kind"] == "work"
    assert isinstance(state["job"], dict)
    assert state["job"]["id"] == action["id"]
    assert state["last_auto_at"]["work"] == pytest.approx(10_000.0)


def test_auto_work_respects_cooldown():
    state = _state(xp=100.0, coins=0, energy=60)
    assert L.auto_action(state, now=10_000.0) is not None
    state["job"] = None                      # 手工清掉，看冷却
    assert L.auto_action(state, now=10_000.0 + 60.0) is None
    assert L.auto_action(state, now=10_000.0 + 601.0) is not None


def test_auto_work_needs_energy():
    state = _state(xp=100.0, coins=0, energy=20)
    assert L.auto_action(state, now=10_000.0) is None
    assert state["job"] is None


def test_auto_actions_respect_switches():
    for override in ({"sleeping": True}, {"autonomy": False}, {"enabled": False}):
        state = _state(xp=280.0, coins=0, thirst=5, **override)
        assert L.auto_action(state, now=10_000.0) is None
        assert state["job"] is None


def test_auto_actions_skip_while_working():
    state = _state(xp=280.0, coins=0, thirst=5)
    L.start_job(state, "typing", now=9_000.0)
    assert L.auto_action(state, now=9_001.0) is None


def test_auto_buy_fixes_low_thirst():
    state = _state(xp=float(D.LEVEL_THRESHOLDS[4]), coins=100, thirst=10)
    action = L.auto_action(state, now=10_000.0)
    assert action is not None and action["kind"] == "buy"
    assert state["thirst"] > 10
    assert state["coins"] < 100
    assert state["last_auto_at"]["shop"] == pytest.approx(10_000.0)


def test_auto_buy_skips_when_poor_and_falls_back_to_work():
    """买不起就不买（不动钱包不动属性），并把这一拍让给"自己打工"。"""
    state = _state(xp=280.0, coins=5, thirst=5, energy=60)
    action = L.auto_action(state, now=10_000.0)
    assert action is not None and action["kind"] == "work"
    assert state["coins"] == 5
    assert state["thirst"] == 5


def test_auto_buy_needs_the_skill():
    """Lv3 只学会打工：一样渴也一样有钱，但不会自己买。"""
    state = _state(xp=float(D.LEVEL_THRESHOLDS[2]), coins=100, thirst=5, energy=10)
    assert L.auto_action(state, now=10_000.0) is None
    assert state["thirst"] == 5


def test_auto_buy_prefers_saving_health_first():
    state = _state(xp=280.0, coins=100, hunger=5, thirst=5, health=10)
    action = L.auto_action(state, now=10_000.0)
    assert action is not None and action["kind"] == "buy"
    assert state["health"] > 10


# ---------------------------------------------------------------- 注入文案
def test_prompt_text_carries_level_and_skills():
    text = L.prompt_text(_state(xp=100.0))
    assert "Lv.3" in text
    assert "自己打工" in text
    assert "等级与技能" in text


def test_prompt_text_demands_honest_state_answers():
    text = L.prompt_text(_state(energy=25))
    assert "如实回答" in text
    assert "有点困" in text


def test_prompt_text_empty_when_disabled():
    assert L.prompt_text(_state(xp=100.0, enabled=False)) == ""


# ---------------------------------------------------------------- 服务层
def test_service_syncs_memory_on_every_tick(tmp_path):
    """不写盘也要同步内存：聊天侧读的就是这份（"精力 26 说不困"的第二个来源）。"""
    service = _service(tmp_path)
    before = float(service._config.get(CONFIG_KEY)["hunger"])
    service.state["last_tick_at"] = time.time() - 3600.0
    service.tick()
    live = service._config.get(CONFIG_KEY)
    assert live["hunger"] == pytest.approx(service.state["hunger"])
    assert live["hunger"] < before


def test_service_persists_xp_and_announcements(tmp_path):
    service = _service(tmp_path)
    service.state["xp"] = 95.0
    service.state["last_tick_at"] = time.time()
    service.state["job"] = _finished_job("typing")
    service.tick()
    assert service.state["xp"] > 95.0
    assert "self_work" in service.state["announced_skills"]
    again = PetLifeService(Config(tmp_path))
    assert again.state["xp"] == pytest.approx(service.state["xp"])
    assert "self_work" in again.state["announced_skills"]


def test_service_emits_level_up_once(tmp_path):
    service = _service(tmp_path)
    levels = _collect(service.level_up)
    service.state["xp"] = float(D.LEVEL_THRESHOLDS[2]) - 1.0   # 差 1 点升 Lv3
    service.state["last_tick_at"] = time.time()
    service.state["job"] = _finished_job("typing")
    service.tick()
    assert levels == [(3,)]


def test_service_auto_work_emits_story_and_starts_job(tmp_path):
    service = _service(tmp_path)
    stories = _collect(service.story)
    service.state.update({"xp": float(D.LEVEL_THRESHOLDS[2]), "coins": 5.0, "energy": 60.0})
    service.state["last_tick_at"] = time.time()
    service.tick()
    assert isinstance(service.state["job"], dict)
    assert any("打工" in args[0] for args in stories)


def test_service_autonomy_toggle_stops_self_actions(tmp_path):
    service = _service(tmp_path)
    service.set_autonomy(False)
    assert service.autonomy() is False
    service.state.update({"xp": float(D.LEVEL_THRESHOLDS[2]), "coins": 5.0, "energy": 60.0})
    service.state["last_tick_at"] = time.time()
    service.tick()
    assert service.state["job"] is None


# ---------------------------------------------------------------- 注入通道
def test_status_injection_shared_entry(tmp_path):
    config = Config(tmp_path)
    state = L.defaults()
    state["energy"] = 25.0
    config.set(CONFIG_KEY, state)
    text = pet_status_text(config)
    assert "有点困" in text
    assert text == prompt_text_from_config(config)


def test_status_injection_is_empty_without_config():
    assert pet_status_text(None) == ""


def test_status_injection_survives_broken_config():
    class _Broken:
        def get(self, key, default=None):
            raise RuntimeError("读配置炸了")

    assert pet_status_text(_Broken()) == ""


def test_all_chat_surfaces_pass_pet_status():
    """三处聊天面都必须传状态段：只在新版窗注入正是 v4.6.0 那个 bug。"""
    root = Path(__file__).resolve().parents[1] / "pet"
    for relative in ("chat/widgets.py", "chat/legacy_widgets.py", "quick_chat.py"):
        text = (root / relative).read_text(encoding="utf-8")
        start = text.index("build_messages(")
        assert "pet_status_text=" in text[start:start + 1500], relative


def test_empty_status_keeps_prompt_byte_identical():
    """空串 = 不注入：这是"没有养成系统时提示词不变"的那条契约。"""
    from pet.chat.models import ChatSettings
    from pet.chat.prompt import PromptBuilder

    builder = PromptBuilder()
    settings = ChatSettings()
    settings.pet_status_text = ""
    baseline = builder.build_messages(settings, "dudu", [], "在吗")
    settings.pet_status_text = ""
    again = builder.build_messages(settings, "dudu", [], "在吗")
    assert baseline == again
    assert "【嘟嘟当前状态】" not in baseline[0]["content"]
