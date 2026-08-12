"""OnlyOffice Document Server 回调与文件代理。"""

from __future__ import annotations

import logging
from datetime import datetime
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.config import get_settings
from app.database import get_db
from app.models import ChatSession
from app.services import onlyoffice as oo_svc
from app.services import storage

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_session_or_404(db: Session, session_id: int) -> ChatSession:
    s = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not s:
        raise HTTPException(404, "会话不存在")
    return s


@router.get("/onlyoffice/status")
def onlyoffice_status():
    return oo_svc.status_payload()


@router.get("/chat/sessions/{session_id}/onlyoffice/config")
def get_onlyoffice_editor_config(session_id: int, db: Session = Depends(get_db)):
    if not oo_svc.is_enabled():
        raise HTTPException(503, "OnlyOffice 未启用，请配置 ONLYOFFICE_ENABLED 并启动 Document Server")
    s = _get_session_or_404(db, session_id)
    ws = getattr(s, "workspace", None) or {}
    doc_key = ws.get("draft_object_key") or ws.get("template_object_key")
    if not doc_key:
        raise HTTPException(404, "工作区暂无文档")
    settings = get_settings()
    config = oo_svc.build_editor_config(
        session_id=session_id,
        filename=ws.get("filename") or "document.docx",
        object_key=doc_key,
        version=int(ws.get("version") or 1),
    )
    return {
        "config": config,
        "document_server_url": settings.onlyoffice_document_server_url,
        **oo_svc.status_payload(),
    }


@router.get("/onlyoffice/files/{file_token}")
def onlyoffice_download_file(file_token: str):
    if not oo_svc.is_enabled():
        raise HTTPException(503, "OnlyOffice 未启用")
    try:
        payload = oo_svc.verify_token(file_token)
    except Exception as exc:
        raise HTTPException(401, "文件令牌无效或已过期") from exc

    object_key = payload.get("key")
    if not object_key:
        raise HTTPException(400, "令牌缺少文件信息")
    if not storage.object_exists(object_key):
        raise HTTPException(404, "文件不存在")

    data = storage.download_bytes(object_key)
    filename = object_key.rsplit("/", 1)[-1]
    return Response(
        content=data,
        media_type=oo_svc.DOCX_CONTENT_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{quote(filename)}"'},
    )


@router.post("/onlyoffice/callback/{session_id}")
async def onlyoffice_callback(session_id: int, request: Request, db: Session = Depends(get_db)):
    """Document Server 保存回调。必须返回 {"error": 0}。"""
    if not oo_svc.is_enabled():
        return {"error": 1}

    try:
        body = await request.json()
    except Exception:
        return {"error": 1}

    status = body.get("status")
    logger.info("OnlyOffice callback session=%s status=%s", session_id, status)

    if status in (1, 4):
        return {"error": 0}

    if status not in (2, 6):
        return {"error": 0}

    download_url = body.get("url")
    if not download_url:
        logger.warning("OnlyOffice callback missing url for session %s", session_id)
        return {"error": 1}

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(download_url)
            resp.raise_for_status()
            data = resp.content
    except Exception as exc:
        logger.exception("OnlyOffice download failed: %s", exc)
        return {"error": 1}

    s = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not s:
        return {"error": 1}

    ws = dict(getattr(s, "workspace", None) or {})
    fname = ws.get("filename") or "document.docx"
    if not fname.lower().endswith(".docx"):
        fname = f"{fname.rsplit('.', 1)[0]}.docx" if "." in fname else f"{fname}.docx"

    new_key = f"chat/{session_id}/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_onlyoffice.docx"
    storage.upload_bytes(new_key, data, oo_svc.DOCX_CONTENT_TYPE)
    ws["draft_object_key"] = new_key
    ws["version"] = int(ws.get("version") or 0) + 1
    ws["last_action"] = "onlyoffice_save"
    s.workspace = ws
    flag_modified(s, "workspace")
    s.updated_at = datetime.utcnow()
    db.commit()
    logger.info("OnlyOffice saved session=%s key=%s", session_id, new_key)
    return {"error": 0}
