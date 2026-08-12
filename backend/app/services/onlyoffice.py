"""OnlyOffice Document Server 集成（Community 版技术验证）。"""

from __future__ import annotations

import hashlib
import time
from typing import Any
from urllib.parse import quote

import jwt

from app.config import get_settings

DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def is_enabled() -> bool:
    settings = get_settings()
    return bool(settings.onlyoffice_enabled and settings.onlyoffice_document_server_url)


def document_key(session_id: int, object_key: str, version: int) -> str:
    raw = f"{session_id}:{object_key}:{version}"
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def _jwt_secret() -> str:
    return get_settings().onlyoffice_jwt_secret or ""


def sign_payload(payload: dict[str, Any]) -> str:
    secret = _jwt_secret()
    if not secret:
        return ""
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_token(token: str) -> dict[str, Any]:
    secret = _jwt_secret()
    if not secret:
        raise ValueError("OnlyOffice JWT 未配置")
    return jwt.decode(token, secret, algorithms=["HS256"])


def create_file_token(session_id: int, object_key: str, *, ttl_seconds: int = 3600) -> str:
    payload = {
        "sid": session_id,
        "key": object_key,
        "exp": int(time.time()) + ttl_seconds,
    }
    token = sign_payload(payload)
    if not token:
        raise ValueError("无法生成文件访问令牌，请配置 ONLYOFFICE_JWT_SECRET")
    return token


def file_download_url(file_token: str) -> str:
    settings = get_settings()
    base = settings.onlyoffice_internal_url.rstrip("/")
    return f"{base}/api/onlyoffice/files/{quote(file_token, safe='')}"


def callback_url(session_id: int) -> str:
    settings = get_settings()
    base = settings.onlyoffice_internal_url.rstrip("/")
    return f"{base}/api/onlyoffice/callback/{session_id}"


def build_editor_config(
    *,
    session_id: int,
    filename: str,
    object_key: str,
    version: int,
    user_id: str = "tender-user",
    user_name: str = "标书用户",
) -> dict[str, Any]:
    settings = get_settings()
    if not is_enabled():
        raise ValueError("OnlyOffice 未启用")

    ext = "docx"
    lower = (filename or "").lower()
    if lower.endswith(".doc"):
        ext = "doc"
    elif lower.endswith(".docx"):
        ext = "docx"

    file_token = create_file_token(session_id, object_key)
    config: dict[str, Any] = {
        "document": {
            "fileType": ext,
            "key": document_key(session_id, object_key, version),
            "title": filename or "document.docx",
            "url": file_download_url(file_token),
        },
        "documentType": "word",
        "editorConfig": {
            "callbackUrl": callback_url(session_id),
            "lang": "zh-CN",
            "mode": "edit",
            "user": {"id": user_id, "name": user_name},
            "customization": {
                "forcesave": True,
                "compactHeader": True,
            },
        },
        "height": "100%",
        "width": "100%",
        "type": "desktop",
    }

    secret = _jwt_secret()
    if secret:
        return {"token": sign_payload(config)}
    return config


def status_payload() -> dict[str, Any]:
    settings = get_settings()
    enabled = is_enabled()
    return {
        "enabled": enabled,
        "document_server_url": settings.onlyoffice_document_server_url if enabled else "",
        "jwt_enabled": bool(settings.onlyoffice_jwt_secret),
    }
