"""系统设置：持久化 AI API Key，优先数据库，回退环境变量"""
from __future__ import annotations
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import SystemSetting

env = get_settings()


def _mask(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * max(len(key) - 8, 4)}{key[-4:]}"


def get_or_create_setting(db: Session) -> SystemSetting:
    row = db.query(SystemSetting).filter(SystemSetting.id == 1).first()
    if row:
        return row
    row = SystemSetting(
        id=1,
        deepseek_api_key=env.deepseek_api_key or "",
        deepseek_base_url=env.deepseek_base_url or "https://api.deepseek.com",
        deepseek_model="deepseek-chat",
        qwen_api_key=env.qwen_api_key or "",
        qwen_base_url=env.qwen_base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
        qwen_model="qwen-plus",
        preferred_provider="auto",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def resolve_ai_config(db: Session | None = None) -> dict:
    """返回实际用于调用的 AI 配置（含完整 Key）"""
    cfg = {
        "deepseek_api_key": env.deepseek_api_key or "",
        "deepseek_base_url": env.deepseek_base_url or "https://api.deepseek.com",
        "deepseek_model": "deepseek-chat",
        "qwen_api_key": env.qwen_api_key or "",
        "qwen_base_url": env.qwen_base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen_model": "qwen-plus",
        "preferred_provider": "auto",
    }
    if db is None:
        return cfg
    row = get_or_create_setting(db)
    if row.deepseek_api_key:
        cfg["deepseek_api_key"] = row.deepseek_api_key
    if row.deepseek_base_url:
        cfg["deepseek_base_url"] = row.deepseek_base_url
    if row.deepseek_model:
        cfg["deepseek_model"] = row.deepseek_model
    if row.qwen_api_key:
        cfg["qwen_api_key"] = row.qwen_api_key
    if row.qwen_base_url:
        cfg["qwen_base_url"] = row.qwen_base_url
    if row.qwen_model:
        cfg["qwen_model"] = row.qwen_model
    if row.preferred_provider:
        cfg["preferred_provider"] = row.preferred_provider
    return cfg


def to_public_dict(row: SystemSetting, env_fallback: bool = True) -> dict:
    ds_key = row.deepseek_api_key or ((env.deepseek_api_key or "") if env_fallback else "")
    qw_key = row.qwen_api_key or ((env.qwen_api_key or "") if env_fallback else "")
    return {
        "deepseek_api_key_set": bool(ds_key),
        "deepseek_api_key_masked": _mask(ds_key),
        "deepseek_base_url": row.deepseek_base_url or env.deepseek_base_url,
        "deepseek_model": row.deepseek_model or "deepseek-chat",
        "qwen_api_key_set": bool(qw_key),
        "qwen_api_key_masked": _mask(qw_key),
        "qwen_base_url": row.qwen_base_url or env.qwen_base_url,
        "qwen_model": row.qwen_model or "qwen-plus",
        "preferred_provider": row.preferred_provider or "auto",
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def update_settings(db: Session, payload: dict) -> SystemSetting:
    row = get_or_create_setting(db)

    # API Key：空字符串表示不修改；显式 clear_*=True 表示清空
    if payload.get("clear_deepseek_api_key"):
        row.deepseek_api_key = ""
    elif payload.get("deepseek_api_key"):
        row.deepseek_api_key = str(payload["deepseek_api_key"]).strip()

    if payload.get("clear_qwen_api_key"):
        row.qwen_api_key = ""
    elif payload.get("qwen_api_key"):
        row.qwen_api_key = str(payload["qwen_api_key"]).strip()

    if "deepseek_base_url" in payload and payload["deepseek_base_url"] is not None:
        row.deepseek_base_url = str(payload["deepseek_base_url"]).strip() or row.deepseek_base_url
    if "deepseek_model" in payload and payload["deepseek_model"] is not None:
        row.deepseek_model = str(payload["deepseek_model"]).strip() or row.deepseek_model
    if "qwen_base_url" in payload and payload["qwen_base_url"] is not None:
        row.qwen_base_url = str(payload["qwen_base_url"]).strip() or row.qwen_base_url
    if "qwen_model" in payload and payload["qwen_model"] is not None:
        row.qwen_model = str(payload["qwen_model"]).strip() or row.qwen_model
    if "preferred_provider" in payload and payload["preferred_provider"] is not None:
        provider = str(payload["preferred_provider"]).strip()
        if provider in ("auto", "deepseek", "qwen"):
            row.preferred_provider = provider

    db.commit()
    db.refresh(row)
    return row
