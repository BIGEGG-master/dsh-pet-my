# -*- coding: utf-8 -*-
"""养成服务（``pet/pet_life_service.py``）：心跳、落盘、信号、动作包装。

不启 QTimer 的用例直接调 ``tick()``（时间用注入的 ``state`` 控制），
只有"启动即结算"那一条真的 ``start()`` 一次再停掉。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from pet import pet_life as L
from pet import pet_life_data as D
from pet.config import Config
from pet.pet_life_service import CONFIG_KEY, PetLifeService, prompt_text_from_config


def _service(tmp_path) -> PetLifeService:
    return PetLifeService(Config(tmp_path))


def _collect(signal) -> list:
    hits: list = []
    signal.connect(lambda *args: hits.append(args))
    return hits


# ---------------------------------------------------------------- 落盘与读回


def test_state_persists_across_instances(tmp_path):
    service = _service(tmp_path)
    service.feed()
    hunger = service.state["hunger"]
    again = PetLifeService(Config(tmp_path))
    assert again.state["hunger"] == hunger


def test_corrupt_config_falls_back_to_defaults(tmp_path):
    config = Config(tmp_path)
    config.set(CONFIG_KEY, {"hunger": "坏了", "energy": None, "coins": "x"})
    config.save()
    service = PetLifeService(Config(tmp_path))
    assert service.state["hunger"] == 80
    assert service.state["energy"] == 60
    assert service.state["coins"] == 100


# ---------------------------------------------------------------- 心跳


def test_tick_decays_and_emits_changed(tmp_path):
    service = _service(tmp_path)
    changes = _collect(service.changed)
    service.state["last_tick_at"] = time.time() - 3600.0
    service.tick()
    assert service.state["hunger"] == pytest.approx(74.0)
    assert len(changes) == 1


def test_tick_does_nothing_when_disabled(tmp_path):
    service = _service(tmp_path)
    service.set_enabled(False)
    before = service.state["hunger"]
    changes = _collect(service.changed)
    service.state["last_tick_at"] = time.time() - 3600.0
    service.tick()
    assert service.state["hunger"] == before
    assert changes == []


def test_tick_emits_need_and_respects_cooldown(tmp_path):
    service = _service(tmp_path)
    needs = _collect(service.need_raised)
    service.state.update({"hunger": 10, "thirst": 90, "energy": 90, "mood": 90})
    service.state["last_tick_at"] = time.time() - 60.0
    service.tick()
    assert [args[0] for args in needs] == ["hunger"]
    service.tick()  # 冷却内不再提
    assert len(needs) == 1


def test_tick_reports_sleep_transition_once(tmp_path):
    service = _service(tmp_path)
    stories = _collect(service.story)
    service.state.update({"energy": 5, "last_tick_at": time.time() - 60.0})
    service.tick()
    assert D.SLEEP_LINE in [args[0] for args in stories]
    assert service.state["sleeping"] is True
    service.tick()  # 已经在睡：不再复读
    assert [args[0] for args in stories].count(D.SLEEP_LINE) == 1


# ---------------------------------------------------------------- 工作


def test_job_settles_on_tick_and_pays(tmp_path):
    service = _service(tmp_path)
    finished = _collect(service.job_finished)
    assert service.start_job("typing") is True
    assert service.state["job"]["id"] == "typing"
    # 时间快进到结束
    service.state["job"]["ends_at"] = time.time() - 1
    service.state["last_tick_at"] = time.time() - 60.0
    service.tick()
    assert service.state["job"] is None
    assert service.state["coins"] == 100 + D.JOBS["typing"]["coins"]
    assert finished and finished[0][1] == D.JOBS["typing"]["coins"]


def test_start_job_rejects_when_already_working(tmp_path):
    service = _service(tmp_path)
    stories = _collect(service.story)
    assert service.start_job("typing") is True
    assert service.start_job("coding") is False
    assert stories and "已经在忙" in stories[-1][0]


def test_cancel_job_pays_nothing_and_talks(tmp_path):
    service = _service(tmp_path)
    stories = _collect(service.story)
    service.start_job("research")
    assert service.cancel_job() is True
    assert service.state["coins"] == 100
    assert stories[-1][0] == D.JOB_CANCELLED_LINE
    assert service.cancel_job() is False


def test_disabling_interrupts_job_without_payment(tmp_path):
    service = _service(tmp_path)
    service.start_job("research")
    service.set_enabled(False)
    assert service.state["job"] is None
    assert service.state["coins"] == 100


def test_current_job_and_progress(tmp_path):
    service = _service(tmp_path)
    assert service.current_job() is None
    service.start_job("coding")
    job = service.current_job()
    assert job is not None and job["id"] == "coding"
    assert 0.0 <= service.job_progress() <= 1.0


# ---------------------------------------------------------------- 动作与信号


def test_feed_speaks_and_raises_changed(tmp_path):
    service = _service(tmp_path)
    stories = _collect(service.story)
    changes = _collect(service.changed)
    assert service.feed() is True
    assert stories and stories[-1][0] == D.FEED_LINE
    assert len(changes) == 1


def test_feed_cooldown_reports_reason(tmp_path):
    service = _service(tmp_path)
    service.feed()
    stories = _collect(service.story)
    assert service.feed() is False
    assert "分钟" in stories[-1][0]


def test_play_and_drink_paths(tmp_path):
    service = _service(tmp_path)
    assert service.play("training") is True
    assert service.drink() is True


def test_buy_poor_reports_reason(tmp_path):
    service = _service(tmp_path)
    service.state["coins"] = 0
    stories = _collect(service.story)
    assert service.buy("tail_massager") is False
    assert stories[-1][0] == D.NOT_ENOUGH_COINS_LINE
    assert service.state["health"] == 100


def test_buy_success_speaks_quip(tmp_path):
    service = _service(tmp_path)
    stories = _collect(service.story)
    assert service.buy("sparkling_water") is True
    assert stories[-1][0].startswith("咕嘟")
    assert service.state["coins"] == 90


# ---------------------------------------------------------------- 展示位与注入


def test_hud_mode_roundtrip(tmp_path):
    service = _service(tmp_path)
    assert service.hud_mode() == "follow_pet"
    service.set_hud_mode("off")
    assert PetLifeService(Config(tmp_path)).hud_mode() == "off"
    service.set_hud_mode("乱写")
    assert service.hud_mode() == "follow_pet"


def test_reset_restores_defaults(tmp_path):
    service = _service(tmp_path)
    service.feed()
    service.reset()
    assert service.state["hunger"] == 80
    assert service.state["coins"] == 100


def test_prompt_text_follows_state(tmp_path):
    service = _service(tmp_path)
    assert "精力" in service.prompt_text()
    service.set_enabled(False)
    assert service.prompt_text() == ""


def test_prompt_text_from_config_is_read_only(tmp_path):
    config = Config(tmp_path)
    before = dict(config.get(CONFIG_KEY) or {})
    assert prompt_text_from_config(config) != ""
    # 只读入口不得改动配置（默认值本来就已落进 data，比较的是"没被改写"）
    assert dict(config.get(CONFIG_KEY) or {}) == before


def test_prompt_text_from_config_survives_broken_data(tmp_path):
    config = Config(tmp_path)
    config.set(CONFIG_KEY, "不是字典")
    assert isinstance(prompt_text_from_config(config), str)


# ---------------------------------------------------------------- 启动即结算


def test_start_settles_offline_job_without_spamming(tmp_path):
    """开机那一拍：离线期间完成的工作要结算，但不该立刻弹"我饿了"。"""
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    config = Config(tmp_path)
    seed = L.defaults()
    seed.update({"hunger": 5, "energy": 90, "last_tick_at": time.time() - 7200.0})
    seed["job"] = {"id": "typing", "started_at": time.time() - 3600.0,
                   "ends_at": time.time() - 60.0}
    config.set(CONFIG_KEY, seed)
    config.save()

    service = PetLifeService(Config(tmp_path))
    needs = _collect(service.need_raised)
    finished = _collect(service.job_finished)
    service.start()
    try:
        assert finished, "离线期间做完的活必须结算"
        assert needs == [], "开机不该立刻刷自主需求"
        assert service.state["job"] is None
    finally:
        service.stop()
def test_first_persist_keeps_every_key(tmp_path):
    """首次落盘必须写全 16 个键。

    回归：``_merge_config_changes`` 对 dict 做叶合并，盘上还没有 pet_life 时
    只写入"变化过的叶"，``mood`` / ``coins`` / ``hud`` 等未变化的键会丢
    （实测盘上只剩 energy / hunger / thirst / last_tick_at）。pet_life 因此
    改为整值提交（``pet/config.py::_WHOLE_VALUE_KEYS``）。
    """
    config = Config(tmp_path)
    service = PetLifeService(config)
    service.feed()  # 用户动作 → force 落盘
    raw = json.loads(Path(config.path).read_text(encoding="utf-8"))
    stored = raw[CONFIG_KEY]
    expected = {
        "schema", "enabled", "hunger", "thirst", "mood", "energy", "health",
        "coins", "sleeping", "hud", "job", "last_tick_at", "last_feed_at",
        "last_drink_at", "last_event_at", "owned",
    }
    assert expected <= set(stored), f"落盘缺键：{sorted(expected - set(stored))}"
    reloaded = PetLifeService(Config(tmp_path))
    assert reloaded.state["mood"] == stored["mood"]
