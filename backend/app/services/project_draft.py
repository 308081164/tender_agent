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


def _pdf_cache_key_for_draft(draft_key: str) -> str:
    base = draft_key.rsplit("/", 1)[-1]
    if base.lower().endswith(".docx"):
        base = base[:-5]
    return f"projects/preview_cache/{base}.pdf"


async def get_draft_preview_status(db: Session, project_id: int) -> dict[str, Any]:
    project = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not project:
        raise ValueError("项目不存在")
    engine = pdf_convert.get_pdf_engine()
    fields = project.fields or {}
    draft_key = fields.get("_draft_object_key")
    pdf_key = fields.get("_draft_pdf_key")
    pdf_ready = bool(
        pdf_key
        and fields.get("_draft_pdf_for") == draft_key
        and storage.object_exists(pdf_key)
    )
    hint = ""
    if not project.template_id:
        hint = "请先完成向导并选择模板"
    elif not engine:
        hint = "未检测到 PDF 转换引擎（Aspose 授权或 LibreOffice）。桌面版请确认 aspose 目录；服务器可安装 libreoffice-writer 或设置 PDF_CONVERTER=libreoffice"
    elif not draft_key:
        hint = "尚未渲染草稿，保存字段后将自动生成"
    return {
        "project_id": project_id,
        "template_id": project.template_id,
        "pdf_engine": engine,
        "pdf_ready": pdf_ready,
        "draft_object_key": draft_key,
        "preview_pdf_key": pdf_key if pdf_ready else None,
        "hint": hint,
        "async_supported": True,
    }


async def get_draft_preview_pdf(db: Session, project_id: int, *, force_render: bool = False) -> bytes:
    project = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not project:
        raise ValueError("项目不存在")
    if not project.template_id:
        raise ValueError("未选择模板，请先在向导中选择模板后再预览")
    fields = dict(project.fields or {})
    draft_key = fields.get("_draft_object_key")
    pdf_key = fields.get("_draft_pdf_key")
    if (
        not force_render
        and draft_key
        and pdf_key
        and fields.get("_draft_pdf_for") == draft_key
        and storage.object_exists(pdf_key)
    ):
        return storage.download_bytes(pdf_key)

    if force_render or not draft_key or not storage.object_exists(draft_key):
        doc_bytes, draft_key, _ = await render_project_draft_docx(db, project)
        db.refresh(project)
        fields = dict(project.fields or {})
    else:
        doc_bytes = storage.download_bytes(draft_key)

    if not pdf_convert.pdf_conversion_available():
        raise ValueError(
            "PDF 预览不可用：未找到 Aspose 授权或 LibreOffice。"
            "桌面安装包请确认安装目录下 aspose/Aspose.License.txt 存在；"
            "也可在环境变量中设置 SOFFICE_PATH 或 PDF_CONVERTER=libreoffice。"
        )

    pdf_bytes = draft_pdf_bytes(docx_bytes)
    cache_key = _pdf_cache_key_for_draft(draft_key)
    storage.upload_bytes(cache_key, pdf_bytes, "application/pdf")
    fields["_draft_pdf_key"] = cache_key
    fields["_draft_pdf_for"] = draft_key
    project.fields = fields
    flag_modified(project, "fields")
    db.commit()
    return pdf_bytes


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
