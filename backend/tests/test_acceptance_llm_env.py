"""验收脚本环境：必须配置 LLM API Key。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.acceptance_llm import llm_api_configured, require_llm_api_keys


def test_require_llm_api_keys_fails_without_env(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    assert not llm_api_configured()
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        require_llm_api_keys()


def test_require_llm_api_keys_passes_with_deepseek(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.delenv("KIMI_API_KEY", raising=False)
    require_llm_api_keys()
