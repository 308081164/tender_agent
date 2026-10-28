"""端到端验收：必须配置真实 LLM，禁止仅靠本地 expanded 兜底通过。"""
from __future__ import annotations

import os


def llm_api_configured() -> bool:
    return bool(
        (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
        or (os.environ.get("KIMI_API_KEY") or "").strip()
    )


def require_llm_api_keys() -> None:
    if not llm_api_configured():
        raise RuntimeError(
            "验收需要配置 DEEPSEEK_API_KEY 和/或 KIMI_API_KEY（写入 gitignore 的 .env），"
            "不可仅用 acceptance 脚本本地 expanded 兜底通过。"
        )
