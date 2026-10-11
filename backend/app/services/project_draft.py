"""项目草稿渲染：DOCX 缓存 + PDF 预览（创作期，非正式导出）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models import Qualification, Template, TenderProject
from app.services import pdf_convert, storage
from app.services.field_defaults import fill_field_defaults


def _company_context(db: Session) -> str:
    from app.models import CompanyProfile

    c = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    if not c:
        return ""
    return "\n".join(p for p in [c.full_name, c.intro, c.qual_overview] if p)


async def render_project_draft_docx(db: Session, project: TenderProject) -> tuple[bytes, str, dict[str, Any]]:
    """渲染当前 fields+chapters 为 DOCX，写入 MinIO，更新 project.fields 缓存键。"""
    if not project.template_id:
        raise ValueError("未选择模板")
    tpl = db.query(Template).filter(Template.id == project.template_id).first()
    if not tpl:
        raise ValueError("模板不存在")
    tpl_bytes = storage.download_bytes(tpl.object_key)
    chapters = dict(project.chapters or {})
    quals = []
    if project.inserted_quals:
        quals = db.query(Qualification).filter(Qualification.id.in_(project.inserted_quals)).all()
        chapters["资质材料清单"] = {
            "content": "\n".join(f"- {q.category} / {q.name}（{q.issuer}）" for q in quals),
            "source": "system",
        }
    export_fields = fill_field_defaults(db, project.fields)
    qual_files = []
    for q in quals:
        data = b""
        if q.object_key:
            try:
                data = storage.download_bytes(q.object_key)
            except Exception:
                data = b""
        qual_files.append({
            "name": q.name,
            "category": q.category,
            "section_hint": getattr(q, "section_hint", "") or "",
            "file_type": q.file_type,
            "ocr_text": getattr(q, "ocr_text", "") or "",
            "data": data,
        })
    writing_req = (export_fields.get("_writing_requirements") or "") or (
        (project.chapters or {}).get("_writing_requirements") or ""
    )
    snap = getattr(tpl, "source_snapshot", None) or {}
    from app.services.doc_engine.engine import render_project_document

    doc_bytes, meta = await render_project_document(
        tpl_bytes,
        tpl.placeholders,
        export_fields,
        chapters,
        source_snapshot=snap if getattr(tpl, "kind", "") == "history" else None,
        qual_files=qual_files,
        highlight=True,
        requirements=str(writing_req),
        company_context=_company_context(db),
        db=db,
        mode="replace" if getattr(tpl, "kind", "") == "history" else None,
    )
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    draft_key = f"projects/{project.id}/draft_{stamp}.docx"
    storage.upload_bytes(
        draft_key,
        doc_bytes,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    fields = dict(project.fields or {})
    prev_key = fields.get("_draft_object_key")
    fields["_draft_object_key"] = draft_key
    fields["_draft_rendered_at"] = datetime.utcnow().isoformat()
    versions = list(fields.get("_draft_versions") or [])
    versions.append({
        "object_key": draft_key,
        "created_at": fields["_draft_rendered_at"],
        "prev_key": prev_key,
    })
    fields["_draft_versions"] = versions[-10:]
    project.fields = fields
    flag_modified(project, "fields")
    project.updated_at = datetime.utcnow()
    db.commit()
    return doc_bytes, draft_key, meta


def draft_pdf_bytes(docx_bytes: bytes) -> bytes:
    try:
        return pdf_convert.convert_docx_to_pdf(docx_bytes)
    except RuntimeError as err:
        raise ValueError(str(err)) from err


async def get_draft_preview_pdf(db: Session, project_id: int, *, force_render: bool = False) -> bytes:
    project = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not project:
        raise ValueError("项目不存在")
    fields = project.fields or {}
    draft_key = fields.get("_draft_object_key")
    if force_render or not draft_key or not storage.object_exists(draft_key):
        doc_bytes, draft_key, _ = await render_project_draft_docx(db, project)
    else:
        doc_bytes = storage.download_bytes(draft_key)
    return draft_pdf_bytes(docx_bytes)


# 内存级异步预览任务（单机桌面；P3.4）
_PREVIEW_JOBS: dict[str, dict[str, Any]] = {}


def start_async_preview_job(project_id: int) -> str:
    import uuid

    job_id = uuid.uuid4().hex[:16]
    _PREVIEW_JOBS[job_id] = {
        "project_id": project_id,
        "status": "pending",
        "error": "",
        "pdf_ready": False,
    }
    return job_id


def get_preview_job(job_id: str) -> dict[str, Any] | None:
    return _PREVIEW_JOBS.get(job_id)


def set_preview_job(job_id: str, **updates: Any) -> None:
    if job_id in _PREVIEW_JOBS:
        _PREVIEW_JOBS[job_id].update(updates)
