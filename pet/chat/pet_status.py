# -*- coding: utf-8 -*-
"""聊天侧取「养成状态注入段」的**唯一入口**。

为什么要有这个薄封装：v4.6.0 把注入写在了新版聊天窗 ``chat/widgets.py`` 里，
而经典窗 ``chat/legacy_widgets.py`` 与气泡快速对话 ``quick_chat.py`` 各写各的
``build_messages`` 调用，结果 ``chat_ui_style=classic`` 的用户**一次都没被注入过**
——实机上"精力 25 却说不困"就是这么来的。三处共用一份取法，才不会再有
"某个界面上状态是死的"这种只在特定 UI 下复现的问题。

读的是 config **内存**里的 ``pet_life``：养成服务每一拍都会把内存同步好
（见 ``PetLifeService._persist`` → ``_sync_memory``），所以这里拿到的是当前值，
而不是上一次落盘时的旧值。
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def pet_status_text(config) -> str:
    """按 config 里的养成状态生成注入段；任何异常一律返回空串。

    空串 = 调用方跳过注入 → 提示词与"根本没有养成系统"时逐字节一致
    （这条契约有断言钉住，见 ``tests/test_chat_memory.py``）。
    """
    if config is None:
        return ""
    try:
        from ..pet_life_service import prompt_text_from_config

        return prompt_text_from_config(config)
    except Exception:
        log.debug("养成状态读取失败，本轮不注入", exc_info=True)
        return ""
