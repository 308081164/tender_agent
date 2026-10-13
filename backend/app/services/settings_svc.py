"""系统设置：持久化 AI API Key，优先数据库，回退环境变量"""
from __future__ import annotations
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import SystemSetting

env = get_settings()

DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-pro"
KIMI_K3_DEFAULT_MODEL = "kimi-k3"
KIMI_DEFAULT_BASE_URL = "https://api.moonshot.cn/v1"
QWEN_VL_DEFAULT_MODEL = "qwen-vl-plus"
# 兼容旧默认
KIMI_DEFAULT_MODEL = KIMI_K3_DEFAULT_MODEL


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
        deepseek_model=DEEPSEEK_DEFAULT_MODEL,
        qwen_api_key=env.qwen_api_key or "",
        qwen_base_url=env.qwen_base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
        qwen_model="qwen-plus",
        qwen_vl_model=getattr(env, "qwen_vl_model", None) or QWEN_VL_DEFAULT_MODEL,
        kimi_api_key=env.kimi_api_key or "",
        kimi_base_url=env.kimi_base_url or KIMI_DEFAULT_BASE_URL,
        kimi_model=env.kimi_model or KIMI_K3_DEFAULT_MODEL,
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
        "deepseek_model": DEEPSEEK_DEFAULT_MODEL,
        "qwen_api_key": env.qwen_api_key or "",
        "qwen_base_url": env.qwen_base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen_model": "qwen-plus",
        "qwen_vl_model": env.qwen_vl_model or QWEN_VL_DEFAULT_MODEL,
        "kimi_api_key": env.kimi_api_key or "",
        "kimi_base_url": env.kimi_base_url or KIMI_DEFAULT_BASE_URL,
        "kimi_model": env.kimi_model or KIMI_K3_DEFAULT_MODEL,
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
    if row.qwen_vl_model:
        cfg["qwen_vl_model"] = row.qwen_vl_model
    if row.kimi_api_key:
        cfg["kimi_api_key"] = row.kimi_api_key
    if row.kimi_base_url:
        cfg["kimi_base_url"] = row.kimi_base_url
    if row.kimi_model:
        cfg["kimi_model"] = row.kimi_model
    if row.preferred_provider:
        cfg["preferred_provider"] = row.preferred_provider
    if not cfg.get("qwen_vl_model"):
        cfg["qwen_vl_model"] = QWEN_VL_DEFAULT_MODEL
    return cfg


def qwen_vl_ready(cfg: dict) -> bool:
    return bool(cfg.get("qwen_api_key"))


def kimi_k3_ready(cfg: dict) -> bool:
    return bool(cfg.get("kimi_api_key"))


def multimodal_ready(cfg: dict) -> bool:
    """资质文件夹扫描 / vision 等多模态能力：千问 VL 或 Kimi K3 至少配置其一。"""
    return qwen_vl_ready(cfg) or kimi_k3_ready(cfg)


def multimodal_warning_message() -> str:
    return (
        "资质文件夹扫描、图片/PDF 多模态理解需要 **通义千问 VL** 或 **Kimi K3** 至少配置一项 API Key。"
        "纯文本生成可单独使用 DeepSeek。"
    )


def to_public_dict(row: SystemSetting, env_fallback: bool = True) -> dict:
    ds_key = row.deepseek_api_key or ((env.deepseek_api_key or "") if env_fallback else "")
    qw_key = row.qwen_api_key or ((env.qwen_api_key or "") if env_fallback else "")
    km_key = row.kimi_api_key or ((env.kimi_api_key or "") if env_fallback else "")
    return {
        "deepseek_api_key_set": bool(ds_key),
        "deepseek_api_key_masked": _mask(ds_key),
        "deepseek_base_url": row.deepseek_base_url or env.deepseek_base_url,
        "deepseek_model": row.deepseek_model or DEEPSEEK_DEFAULT_MODEL,
        "qwen_api_key_set": bool(qw_key),
        "qwen_api_key_masked": _mask(qw_key),
        "qwen_base_url": row.qwen_base_url or env.qwen_base_url,
        "qwen_model": row.qwen_model or "qwen-plus",
        "qwen_vl_model": row.qwen_vl_model or env.qwen_vl_model or QWEN_VL_DEFAULT_MODEL,
        "qwen_vl_ready": bool(qw_key),
        "kimi_api_key_set": bool(km_key),
        "kimi_k3_ready": bool(km_key),
        "kimi_api_key_masked": _mask(km_key),
        "kimi_base_url": row.kimi_base_url or env.kimi_base_url or KIMI_DEFAULT_BASE_URL,
        "kimi_model": row.kimi_model or env.kimi_model or KIMI_K3_DEFAULT_MODEL,
        "preferred_provider": row.preferred_provider or "auto",
        "multimodal_ready": multimodal_ready({
            "qwen_api_key": qw_key,
            "kimi_api_key": km_key,
        }),
        "multimodal_warning": (
            None
            if multimodal_ready({"qwen_api_key": qw_key, "kimi_api_key": km_key})
            else multimodal_warning_message()
        ),
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

    if payload.get("clear_kimi_api_key"):
        row.kimi_api_key = ""
    elif payload.get("kimi_api_key"):
        row.kimi_api_key = str(payload["kimi_api_key"]).strip()

    if "deepseek_base_url" in payload and payload["deepseek_base_url"] is not None:
        row.deepseek_base_url = str(payload["deepseek_base_url"]).strip() or row.deepseek_base_url
    if "deepseek_model" in payload and payload["deepseek_model"] is not None:
        row.deepseek_model = str(payload["deepseek_model"]).strip() or row.deepseek_model
    if "qwen_base_url" in payload and payload["qwen_base_url"] is not None:
        row.qwen_base_url = str(payload["qwen_base_url"]).strip() or row.qwen_base_url
    if "qwen_model" in payload and payload["qwen_model"] is not None:
        row.qwen_model = str(payload["qwen_model"]).strip() or row.qwen_model
    if "qwen_vl_model" in payload and payload["qwen_vl_model"] is not None:
        row.qwen_vl_model = str(payload["qwen_vl_model"]).strip() or row.qwen_vl_model
    if "kimi_base_url" in payload and payload["kimi_base_url"] is not None:
        row.kimi_base_url = str(payload["kimi_base_url"]).strip() or row.kimi_base_url
    if "kimi_model" in payload and payload["kimi_model"] is not None:
        row.kimi_model = str(payload["kimi_model"]).strip() or row.kimi_model
    if "preferred_provider" in payload and payload["preferred_provider"] is not None:
        provider = str(payload["preferred_provider"]).strip()
        if provider in ("auto", "deepseek", "qwen", "kimi"):
            row.preferred_provider = provider

    db.commit()
    db.refresh(row)
    return row
