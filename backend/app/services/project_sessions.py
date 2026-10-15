"""项目 ↔ ChatSession 绑定。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import ChatSession, TenderProject


def agent_chat_path(project_id: int | str) -> str:
    """项目后续编写、审查、导出所在的 Agent 对话。"""
    return f"/chat?project={int(project_id)}"


def find_bound_session(db: Session, project_id: int) -> ChatSession | None:
    for s in db.query(ChatSession).order_by(ChatSession.updated_at.desc()).all():
        ws = getattr(s, "workspace", None) or {}
        if ws.get("project_id") == project_id:
            return s
    return None


def _docx_filename(name: str) -> str:
    text = (name or "模板").strip() or "模板"
    if text.lower().endswith(".docx"):
        return text
    return f"{text}.docx"


def attach_template_document(db: Session, session: ChatSession, project: TenderProject) -> bool:
    """工作区打开已选模板。没有草稿时直接引用模板 docx，避免空的「请上传」。"""
    from app.models import Template
    from app.services import storage

    ws = dict(session.workspace or {})
    ws["project_id"] = project.id
    if getattr(project, "workspace_dir", None):
        ws["workspace_dir"] = project.workspace_dir
    if project.template_id:
        ws["template_id"] = project.template_id
    draft_key = str((project.fields or {}).get("_draft_object_key") or "")
    if draft_key:
        try:
            if storage.download_bytes(draft_key):
                ws["draft_object_key"] = draft_key
        except Exception:
            draft_key = ""
    if not ws.get("draft_object_key") and not ws.get("template_object_key") and project.template_id:
        tpl = db.query(Template).filter(Template.id == project.template_id).first()
        if tpl and tpl.object_key:
            try:
                blob = storage.download_bytes(tpl.object_key)
            except Exception:
                blob = b""
            if blob:
                ws["template_object_key"] = tpl.object_key
                ws["filename"] = _docx_filename(tpl.name)
                ws["version"] = max(int(ws.get("version") or 0), 1)
    elif project.template_id and not ws.get("filename"):
        tpl = db.query(Template).filter(Template.id == project.template_id).first()
        if tpl:
            ws["filename"] = _docx_filename(tpl.name)
    session.workspace = ws
    return bool(ws.get("draft_object_key") or ws.get("template_object_key"))


def get_or_create_project_session(db: Session, project: TenderProject) -> ChatSession:
    existing = find_bound_session(db, project.id)
    if existing:
        attach_template_document(db, existing, project)
        existing.updated_at = datetime.utcnow()
        title = (project.fields or {}).get("project_name") or project.title
        if title and existing.title in ("新对话", ""):
            existing.title = str(title)[:40]
        db.commit()
        db.refresh(existing)
        return existing

    ws: dict[str, Any] = {
        "project_id": project.id,
        "template_id": project.template_id,
        "guided_intake": bool((project.fields or {}).get("_guided_intake", True)),
    }
    if getattr(project, "workspace_dir", None):
        ws["workspace_dir"] = project.workspace_dir
    title = (project.fields or {}).get("project_name") or project.title or "标书项目"
    s = ChatSession(title=str(title)[:40], workspace=ws)
    db.add(s)
    db.flush()
    attach_template_document(db, s, project)
    db.commit()
    db.refresh(s)
    return s
