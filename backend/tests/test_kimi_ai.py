"""Kimi（Moonshot）AI 配置与 chat_completion 路由测试（mock，无需真实 Key）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.services import ai as ai_svc
from app.services import settings_svc


KIMI_CFG = {
    "deepseek_api_key": "",
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_model": "deepseek-v4-pro",
    "qwen_api_key": "",
    "qwen_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "qwen_model": "qwen-plus",
    "kimi_api_key": "sk-test-kimi",
    "kimi_base_url": "https://api.moonshot.cn/v1",
    "kimi_model": "moonshot-v1-8k",
    "preferred_provider": "kimi",
}


@pytest.mark.asyncio
async def test_chat_completion_kimi_only():
    with patch.object(settings_svc, "resolve_ai_config", return_value=KIMI_CFG):
        with patch.object(ai_svc, "_openai_compat", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "hello kimi"
            text = await ai_svc.chat_completion([{"role": "user", "content": "hi"}], db=None)
            assert text == "hello kimi"
            mock_call.assert_awaited_once()
            args = mock_call.await_args[0]
            assert args[0] == "https://api.moonshot.cn/v1"
            assert args[1] == "sk-test-kimi"
            assert args[2] == "moonshot-v1-8k"


@pytest.mark.asyncio
async def test_chat_completion_auto_falls_through_to_kimi():
    cfg = {**KIMI_CFG, "preferred_provider": "auto", "kimi_api_key": "sk-k2"}
    with patch.object(settings_svc, "resolve_ai_config", return_value=cfg):
        with patch.object(ai_svc, "_openai_compat", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "from kimi"
            text = await ai_svc.chat_completion([{"role": "user", "content": "x"}], db=None)
            assert text == "from kimi"
            assert mock_call.await_count == 1


@pytest.mark.asyncio
async def test_test_provider_kimi_no_key():
    cfg = {**KIMI_CFG, "kimi_api_key": ""}
    with patch.object(settings_svc, "resolve_ai_config", return_value=cfg):
        res = await ai_svc.test_provider("kimi", db=None)
        assert res["ok"] is False
        assert "未配置" in res["message"]


@pytest.mark.asyncio
async def test_test_provider_kimi_ok():
    with patch.object(settings_svc, "resolve_ai_config", return_value=KIMI_CFG):
        with patch.object(ai_svc, "_openai_compat", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "ok"
            res = await ai_svc.test_provider("kimi", db=None)
            assert res["ok"] is True
            assert "Kimi" in res["message"]


def test_resolve_ai_config_includes_kimi_defaults():
    cfg = settings_svc.resolve_ai_config(None)
    assert "kimi_api_key" in cfg
    assert cfg["kimi_base_url"] == settings_svc.KIMI_DEFAULT_BASE_URL
    assert cfg["kimi_model"] == settings_svc.KIMI_DEFAULT_MODEL
