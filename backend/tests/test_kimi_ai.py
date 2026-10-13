"""Kimi K3 / 多模态路由与门禁测试（mock，无需真实 Key）。"""
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


BASE_CFG = {
    "deepseek_api_key": "sk-ds",
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_model": "deepseek-v4-pro",
    "qwen_api_key": "",
    "qwen_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "qwen_model": "qwen-plus",
    "qwen_vl_model": "qwen-vl-plus",
    "kimi_api_key": "",
    "kimi_base_url": "https://api.moonshot.cn/v1",
    "kimi_model": "moonshot-v1-8k",
    "kimi_k3_model": "kimi-k3",
    "preferred_provider": "auto",
}

KIMI_CFG = {**BASE_CFG, "deepseek_api_key": "", "kimi_api_key": "sk-kimi", "preferred_provider": "kimi"}


def test_pick_model_text_prefers_deepseek():
    order = ai_svc.pick_model("text", BASE_CFG)
    assert order[0] == "deepseek"


def test_pick_model_text_no_deepseek_falls_qwen_kimi():
    cfg = {**BASE_CFG, "deepseek_api_key": "", "qwen_api_key": "sk-q", "kimi_api_key": "sk-k"}
    order = ai_svc.pick_model("text", cfg)
    assert order == ["qwen", "kimi"]


def test_pick_model_qual_folder_classify_skips_deepseek():
    order = ai_svc.pick_model("qual_folder_classify", BASE_CFG)
    assert "deepseek" not in order
    assert order == []


def test_pick_model_vision_qwen_before_kimi():
    cfg = {**BASE_CFG, "qwen_api_key": "sk-q", "kimi_api_key": "sk-k"}
    order = ai_svc.pick_model("vision", cfg)
    assert order == ["qwen_vl", "kimi_k3"]


def test_multimodal_ready_gate():
    assert not settings_svc.multimodal_ready(BASE_CFG)
    assert settings_svc.multimodal_ready({**BASE_CFG, "qwen_api_key": "sk-q"})
    assert settings_svc.multimodal_ready({**BASE_CFG, "kimi_api_key": "sk-k"})


def test_require_multimodal_raises():
    with pytest.raises(ai_svc.MultimodalRequiredError):
        ai_svc.require_multimodal(None)
    with patch.object(settings_svc, "resolve_ai_config", return_value={**BASE_CFG, "qwen_api_key": "x"}):
        ai_svc.require_multimodal(None)


@pytest.mark.asyncio
async def test_chat_completion_text_uses_deepseek():
    with patch.object(settings_svc, "resolve_ai_config", return_value=BASE_CFG):
        with patch.object(ai_svc, "_openai_compat", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "ds"
            text = await ai_svc.chat_completion([{"role": "user", "content": "hi"}], db=None, task_kind="text")
            assert text == "ds"
            assert mock_call.await_args[0][2] == "deepseek-v4-pro"


@pytest.mark.asyncio
async def test_chat_completion_kimi_only():
    with patch.object(settings_svc, "resolve_ai_config", return_value=KIMI_CFG):
        with patch.object(ai_svc, "_openai_compat", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "hello kimi"
            text = await ai_svc.chat_completion([{"role": "user", "content": "hi"}], db=None, task_kind="text")
            assert text == "hello kimi"
            assert mock_call.await_args[0][2] == "moonshot-v1-8k"


@pytest.mark.asyncio
async def test_chat_completion_vision_no_multimodal_raises():
    with patch.object(settings_svc, "resolve_ai_config", return_value=BASE_CFG):
        with pytest.raises(ai_svc.MultimodalRequiredError):
            await ai_svc.chat_completion_vision(
                [{"role": "user", "content": "看图片"}],
                image_data_urls=["data:image/png;base64,abc"],
                db=None,
            )


@pytest.mark.asyncio
async def test_chat_completion_vision_uses_qwen_vl():
    cfg = {**BASE_CFG, "qwen_api_key": "sk-q"}
    with patch.object(settings_svc, "resolve_ai_config", return_value=cfg):
        with patch.object(ai_svc, "_openai_compat", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "vl ok"
            text = await ai_svc.chat_completion_vision(
                [{"role": "user", "content": "描述"}],
                image_data_urls=["data:image/png;base64,abc"],
                db=None,
            )
            assert text == "vl ok"
            assert mock_call.await_args[0][2] == "qwen-vl-plus"


@pytest.mark.asyncio
async def test_import_qual_folder_gate_payload():
    with patch.object(settings_svc, "resolve_ai_config", return_value={
        "qwen_api_key": "",
        "qwen_vl_model": "qwen-vl-plus",
        "kimi_api_key": "",
        "kimi_k3_model": "kimi-k3",
    }):
        from app.services.agent_qual_folder import import_qual_folder_pipeline
        with pytest.raises(ai_svc.MultimodalRequiredError) as exc:
            await import_qual_folder_pipeline(None, "/tmp/x")
        assert exc.value.payload().get("settings_url") == "/settings"


@pytest.mark.asyncio
async def test_test_provider_kimi_ok():
    with patch.object(settings_svc, "resolve_ai_config", return_value=KIMI_CFG):
        with patch.object(ai_svc, "_openai_compat", new_callable=AsyncMock) as mock_call:
            mock_call.return_value = "ok"
            res = await ai_svc.test_provider("kimi_k3", db=None)
            assert res["ok"] is True
