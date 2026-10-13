"""项目 ↔ ChatSession 绑定。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import ChatSession, TenderProject


def find_bound_session(db: Session, project_id: int) -> ChatSession | None:
    for s in db.query(ChatSession).order_by(ChatSession.updated_at.desc()).all():
        ws = getattr(s, "workspace", None) or {}
        if ws.get("project_id") == project_id:
            return s
    return None


def get_or_create_project_session(db: Session, project: TenderProject) -> ChatSession:
    existing = find_bound_session(db, project.id)
    if existing:
        ws = dict(existing.workspace or {})
        ws["project_id"] = project.id
        if getattr(project, "workspace_dir", None):
            ws["workspace_dir"] = project.workspace_dir
        if project.template_id:
            ws["template_id"] = project.template_id
        draft_key = (project.fields or {}).get("_draft_object_key")
        if draft_key:
            ws["draft_object_key"] = draft_key
        existing.workspace = ws
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
    draft_key = (project.fields or {}).get("_draft_object_key")
    if draft_key:
        ws["draft_object_key"] = draft_key
    title = (project.fields or {}).get("project_name") or project.title or "标书项目"
    s = ChatSession(title=str(title)[:40], workspace=ws)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s
