from datetime import datetime
from pathlib import Path
from urllib.parse import quote
import asyncio
import json
import uuid
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.database import get_db
from app.models import (
    Template, Qualification, TenderProject, ProjectSnapshot, ProjectExport,
    ChecklistItem, FAQItem, FieldDef, ChatSession, ChatMessage,
)
from app.services import storage, word, checklist as checklist_svc, ai as ai_svc
from app.services import settings_svc, chat_assistant, document_agent
from app.services import pdf_convert
from app.services.field_defaults import field_effective_default as _field_effective_default
from app.services.field_defaults import fill_field_defaults as _fill_field_defaults

router = APIRouter()

STEP_NAMES = {
    1: "选择起点",
    2: "信息录入",
    3: "Agent创作",
    4: "AI审查",
    5: "AI审查",
    6: "导出Word",
}


def _workspace_phase_name(step: int, status: str | None = None) -> str:
    if status == "exported":
        return "导出Word"
    if step >= 6:
        return "导出Word"
    if step >= 4:
        return "AI审查"
    if step >= 3:
        return "Agent创作"
    return STEP_NAMES.get(step, f"步骤{step}")


def _workspace_progress(step: int, status: str | None = None) -> float:
    if status == "exported":
        return 1.0
    if step >= 6:
        return 0.92
    if step >= 5:
        return 0.75
    if step >= 4:
        return 0.58
    if step >= 3:
        return 0.42
    return min(max(step, 1), 2) / 2 * 0.35


class ProjectCreate(BaseModel):
    title: str = "未命名标书"
    source_type: str = "template"
    template_id: int | None = None
    workspace_dir: str | None = None


class ProjectWorkspaceUpdate(BaseModel):
    workspace_dir: str


class SettingsUpdate(BaseModel):
    deepseek_api_key: str | None = None
    deepseek_base_url: str | None = None
    deepseek_model: str | None = None
    qwen_api_key: str | None = None
    qwen_base_url: str | None = None
    qwen_model: str | None = None
    qwen_vl_model: str | None = None
    kimi_api_key: str | None = None
    kimi_base_url: str | None = None
    kimi_model: str | None = None
    kimi_k3_model: str | None = None
    preferred_provider: str | None = None
    web_search_provider: str | None = None
    web_search_api_key: str | None = None
    clear_deepseek_api_key: bool = False
    clear_qwen_api_key: bool = False
    clear_kimi_api_key: bool = False
    clear_web_search_api_key: bool = False


class TestProviderRequest(BaseModel):
    provider: str  # deepseek | qwen | kimi



class FieldsUpdate(BaseModel):
    fields: dict
    confirm: bool = False


class GenerateRequest(BaseModel):
    chapters: list[str] | None = None


class InsertQualRequest(BaseModel):
    qualification_ids: list[int]


class ChatRequest(BaseModel):
    question: str
    session_id: int | None = None


class ChatSessionCreate(BaseModel):
    title: str = "新对话"


class ChatSessionUpdate(BaseModel):
    title: str


class ChatMessageCreate(BaseModel):
    content: str
    context: dict | None = None


class RollbackRequest(BaseModel):
    snapshot_id: int


class SaveProgressRequest(BaseModel):
    """保存当前步骤进度（可不进入下一步）"""
    title: str | None = None
    template_id: int | None = None
    source_type: str | None = None
    fields: dict | None = None
    chapters: dict | None = None
    inserted_quals: list[int] | None = None
    checklist_result: dict | None = None
    current_step: int | None = None
    advance: bool = False  # True 时进入下一步
    create_snapshot: bool = True


def project_summary(p: TenderProject) -> dict:
    fields = p.fields or {}
    chapters = p.chapters or {}
    step = p.current_step or 1
    step_name = _workspace_phase_name(step, p.status) if step >= 3 else STEP_NAMES.get(step, f"步骤{step}")
    project_name = fields.get("project_name") or p.title or "未命名标书"
    tenderer = fields.get("tenderer") or ""
    bid_amount = fields.get("bid_amount") or ""
    manager = fields.get("project_manager") or ""
    project_type = fields.get("project_type") or ""
    chapter_count = len(chapters)
    qual_count = len(p.inserted_quals or [])
    parts = []
    if project_type:
        parts.append(project_type)
    if tenderer:
        parts.append(f"招标人 {tenderer}")
    if bid_amount:
        parts.append(f"报价 {bid_amount}")
    if manager:
        parts.append(f"项目经理 {manager}")
    if chapter_count:
        parts.append(f"已生成 {chapter_count} 个章节")
    if qual_count:
        parts.append(f"资质 {qual_count} 项")
    brief = " · ".join(parts) if parts else "尚未填写关键信息，可继续完善。"
    status_label = {
        "draft": "起草中",
        "exported": "已导出",
    }.get(p.status, p.status or "起草中")
    return {
        "project_name": project_name,
        "tender_no": fields.get("tender_no") or "",
        "tenderer": tenderer,
        "bid_amount": bid_amount,
        "project_manager": manager,
        "project_type": project_type,
        "duration": fields.get("duration") or "",
        "step_name": step_name,
        "status_label": status_label,
        "brief": brief,
        "chapter_count": chapter_count,
        "qual_count": qual_count,
        "progress": _workspace_progress(step, p.status),
    }


def project_to_dict(p: TenderProject) -> dict:
    return {
        "id": p.id,
        "title": p.title,
        "source_type": p.source_type,
        "template_id": p.template_id,
        "current_step": p.current_step,
        "fields": p.fields or {},
        "chapters": p.chapters or {},
        "inserted_quals": p.inserted_quals or [],
        "checklist_result": p.checklist_result or {},
        "status": p.status,
        "workspace_dir": getattr(p, "workspace_dir", None) or "",
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "summary": project_summary(p),
    }


def save_snapshot(db: Session, project: TenderProject, step: int):
    snap = ProjectSnapshot(
        project_id=project.id,
        step=step,
        step_name=STEP_NAMES.get(step, str(step)),
        payload={
            "fields": project.fields,
            "chapters": project.chapters,
            "inserted_quals": project.inserted_quals,
            "checklist_result": project.checklist_result,
            "current_step": project.current_step,
            "template_id": project.template_id,
            "source_type": project.source_type,
            "title": project.title,
        },
    )
    db.add(snap)
    db.commit()
    return snap


def export_to_dict(e: ProjectExport) -> dict:
    return {
        "id": e.id,
        "project_id": e.project_id,
        "object_key": e.object_key,
        "filename": e.filename,
        "created_at": e.created_at.isoformat() if e.created_at else None,
    }


def sync_exports_from_minio(db: Session, project_id: int) -> list[ProjectExport]:
    """将 MinIO exports/ 下尚未入库的 DOCX 文件补录为 ProjectExport（忽略缓存的 PDF）。"""
    existing = {
        e.object_key
        for e in db.query(ProjectExport).filter(ProjectExport.project_id == project_id).all()
    }
    prefix = f"exports/project_{project_id}_"
    for obj in storage.list_objects(prefix):
        key = obj["object_key"]
        if key in existing:
            continue
        if not key.lower().endswith(".docx"):
            continue
        name = key.rsplit("/", 1)[-1]
        row = ProjectExport(
            project_id=project_id,
            object_key=key,
            filename=name,
        )
        db.add(row)
        existing.add(key)
    db.commit()
    return (
        db.query(ProjectExport)
        .filter(ProjectExport.project_id == project_id)
        .order_by(ProjectExport.id.desc())
        .all()
    )


def get_export_or_404(db: Session, project_id: int, export_id: int) -> ProjectExport:
    e = (
        db.query(ProjectExport)
        .filter(ProjectExport.id == export_id, ProjectExport.project_id == project_id)
        .first()
    )
    if not e:
        raise HTTPException(404, "导出记录不存在")
    return e


def ensure_export_pdf(e: ProjectExport) -> tuple[bytes, str, bool]:
    """
    Return (pdf_bytes, pdf_object_key, from_cache).
    Converts DOCX→PDF with LibreOffice and caches to MinIO when missing.
    """
    pdf_key = pdf_convert.pdf_object_key(e.object_key)
    if storage.object_exists(pdf_key):
        return storage.download_bytes(pdf_key), pdf_key, True

    try:
        doc_bytes = storage.download_bytes(e.object_key)
    except Exception as err:
        raise HTTPException(404, f"导出文件不存在：{err}") from err

    try:
        pdf_bytes = pdf_convert.convert_docx_to_pdf(doc_bytes)
    except RuntimeError as err:
        raise HTTPException(503, str(err)) from err

    storage.upload_bytes(pdf_key, pdf_bytes, "application/pdf")
    return pdf_bytes, pdf_key, False


@router.get("/health")
def health():
    return {"status": "ok", "app": "tender-agent"}


@router.get("/system/check")
def system_environment_check(db: Session = Depends(get_db)):
    """运行环境自检（设置页 / 部署验收）。"""
    from app.services.system_check import run_system_check
    return run_system_check(db)


@router.get("/system/logs/recent")
def system_recent_logs(max_lines: int = 400):
    """只读 tail 应用日志（桌面 data 目录 / 开发 data 目录）。"""
    from app.services.recent_logs import get_recent_logs

    return get_recent_logs(max_lines=max_lines)


@router.get("/settings")
def get_settings_api(db: Session = Depends(get_db)):
    row = settings_svc.get_or_create_setting(db)
    return settings_svc.to_public_dict(row)


@router.put("/settings")
def update_settings_api(body: SettingsUpdate, db: Session = Depends(get_db)):
    row = settings_svc.update_settings(db, body.model_dump(exclude_unset=True))
    return settings_svc.to_public_dict(row)


@router.post("/settings/test")
async def test_settings_api(body: TestProviderRequest, db: Session = Depends(get_db)):
    if body.provider not in ("deepseek", "qwen", "qwen_vl", "kimi", "kimi_k3"):
        raise HTTPException(400, "provider 仅支持 deepseek、qwen、qwen_vl、kimi")
    return await ai_svc.test_provider(body.provider, db=db)


@router.get("/meta/steps")
def get_steps():
    return [{"step": k, "name": v} for k, v in STEP_NAMES.items()]


@router.get("/templates")
def list_templates(include_disabled: bool = False, db: Session = Depends(get_db)):
    q = db.query(Template)
    if not include_disabled:
        q = q.filter(Template.enabled.is_(True))
    # 招标文件不作为导出起点
    q = q.filter(Template.kind != "tender_doc")
    from app.services.project_workflow import resolve_template_mode

    items = q.order_by(Template.id.desc()).all()
    result = []
    for t in items:
        ph_list = (t.placeholders or {}).get("list") or []
        mode_info = resolve_template_mode(t)
        result.append({
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "placeholders": t.placeholders,
            "is_history": bool((t.placeholders or {}).get("is_history")) or t.kind == "history",
            "template_code": getattr(t, "template_code", "common") or "common",
            "kind": getattr(t, "kind", "template") or "template",
            "enabled": getattr(t, "enabled", True),
            "placeholder_count": len(ph_list),
            "workflow_mode": mode_info.get("mode") or "compose",
            "workflow_label": mode_info.get("label") or "",
        })
    return result


@router.get("/fields")
def list_fields(template_code: str | None = None, db: Session = Depends(get_db)):
    from app.models import CompanyProfile

    company = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    q = db.query(FieldDef)
    if template_code:
        q = q.filter(FieldDef.template_code.in_([template_code, "common"]))
    items = q.order_by(FieldDef.sort_order, FieldDef.id).all()
    return [
        {
            "id": f.id,
            "name": f.name,
            "key": f.key,
            "field_type": f.field_type,
            "required": f.required,
            "default_value": f.default_value,
            "effective_default": _field_effective_default(f, company),
            "options": [o for o in (f.options or "").replace("；", ";").split(";") if o] if f.options else [],
            "module": f.module,
            "validation": f.validation,
            "template_code": getattr(f, "template_code", "common") or "common",
            "is_company_default": getattr(f, "is_company_default", False),
            "company_field": getattr(f, "company_field", "") or "",
            "desensitized": getattr(f, "desensitized", False),
        }
        for f in items
    ]


@router.get("/qualifications")
def list_qualifications(category: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Qualification)
    if category:
        q = q.filter(Qualification.category == category)
    items = q.order_by(Qualification.sort_order, Qualification.category, Qualification.id).all()
    today = datetime.utcnow().date()
    result = []
    for x in items:
        expired = False
        expiring = False
        if x.valid_to and not x.is_long_term:
            expired = x.valid_to < today
            expiring = (not expired) and (x.valid_to - today).days <= 90
        result.append({
            "id": x.id,
            "category": x.category,
            "name": x.name,
            "issuer": x.issuer,
            "file_type": x.file_type,
            "file_name": getattr(x, "file_name", "") or "",
            "keywords": x.keywords,
            "section_hint": getattr(x, "section_hint", "") or "",
            "valid_from": x.valid_from.isoformat() if x.valid_from else None,
            "valid_to": x.valid_to.isoformat() if x.valid_to else None,
            "is_long_term": x.is_long_term,
            "ocr_text": x.ocr_text,
            "expired": expired,
            "expiring": expiring,
        })
    return result


@router.get("/qualifications/categories")
def qual_categories(db: Session = Depends(get_db)):
    from app.services.qual_extract import QUAL_CATEGORIES

    rows = db.query(Qualification.category).distinct().all()
    extra = [r[0] for r in rows if r[0]]
    seen: set[str] = set()
    out: list[str] = []
    for c in [*QUAL_CATEGORIES, *extra]:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


@router.get("/checklist")
def list_checklist(template_code: str | None = None, db: Session = Depends(get_db)):
    q = db.query(ChecklistItem)
    if template_code:
        q = q.filter(ChecklistItem.template_code.in_([template_code, "common"]))
    items = q.order_by(ChecklistItem.sort_order, ChecklistItem.section, ChecklistItem.id).all()
    return [
        {
            "id": i.id,
            "section": i.section,
            "name": i.name,
            "required": i.required,
            "chapter": i.chapter,
            "remark": i.remark,
            "template_code": getattr(i, "template_code", "common") or "common",
        }
        for i in items
    ]


@router.get("/company")
def get_company_public(db: Session = Depends(get_db)):
    from app.routers.admin import company_to_dict
    from app.models import CompanyProfile
    c = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    return company_to_dict(c)


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    items = db.query(TenderProject).order_by(TenderProject.id.desc()).all()
    return [project_to_dict(p) for p in items]


@router.post("/projects")
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    if body.template_id:
        tpl = db.query(Template).filter(Template.id == body.template_id).first()
        if not tpl:
            raise HTTPException(404, "模板不存在")
    workspace_dir = ""
    if body.workspace_dir and str(body.workspace_dir).strip():
        from app.services.agent_workspace import validate_workspace_dir

        try:
            workspace_dir = validate_workspace_dir(str(body.workspace_dir).strip())
        except Exception as err:
            raise HTTPException(400, str(err)) from err
    project = TenderProject(
        title=body.title,
        source_type=body.source_type,
        template_id=body.template_id,
        current_step=1,
        fields={},
        chapters={},
        inserted_quals=[],
        workspace_dir=workspace_dir,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    save_snapshot(db, project, 1)
    return project_to_dict(project)


@router.patch("/projects/{project_id}/workspace-dir")
def patch_project_workspace_dir(
    project_id: int, body: ProjectWorkspaceUpdate, db: Session = Depends(get_db),
):
    from app.services.agent_workspace import validate_workspace_dir
    from app.services.project_sessions import find_bound_session

    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    try:
        p.workspace_dir = validate_workspace_dir(body.workspace_dir.strip())
    except Exception as err:
        raise HTTPException(400, str(err)) from err
    p.updated_at = datetime.utcnow()
    bound = find_bound_session(db, project_id)
    if bound:
        ws = dict(bound.workspace or {})
        ws["workspace_dir"] = p.workspace_dir
        ws["project_id"] = project_id
        bound.workspace = ws
        bound.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(p)
    return project_to_dict(p)


@router.get("/projects/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db)):
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    data = project_to_dict(p)
    if (p.current_step or 1) >= 2:
        data["fields"] = _fill_field_defaults(db, p.fields)
    return data


@router.get("/projects/{project_id}/context")
def get_project_context(project_id: int, db: Session = Depends(get_db)):
    from app.services.project_context import build_project_context

    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    try:
        return build_project_context(db, project_id)
    except ValueError as err:
        raise HTTPException(404, str(err)) from err


@router.post("/projects/{project_id}/sessions")
def get_or_create_project_chat_session(project_id: int, db: Session = Depends(get_db)):
    from app.services.project_sessions import get_or_create_project_session

    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    s = get_or_create_project_session(db, p)
    return {"session": session_to_dict(s), "project_id": project_id}


class WorkspaceOpenIn(BaseModel):
    guided_intake: bool | None = None


@router.post("/projects/{project_id}/workspace/open")
async def open_project_workspace(
    project_id: int,
    body: WorkspaceOpenIn | None = None,
    db: Session = Depends(get_db),
):
    """进入创作工作台：绑定会话并注入主动开场 assistant 消息（幂等）。"""
    from app.services.project_sessions import get_or_create_project_session
    from app.services import project_workspace_agent

    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    s = get_or_create_project_session(db, p)
    guided = body.guided_intake if body and body.guided_intake is not None else None
    msg = await project_workspace_agent.ensure_workspace_opening_message(
        db, s, p, guided=guided,
    )
    if msg:
        db.refresh(s)
    return {
        "session": session_to_dict(s),
        "project_id": project_id,
        "assistant_message": message_to_dict(msg) if msg else None,
        "created": bool(msg),
    }


class WorkspaceFollowupIn(BaseModel):
    guided_intake: bool = True


@router.post("/projects/{project_id}/workspace/followup")
async def project_workspace_followup(
    project_id: int,
    body: WorkspaceFollowupIn,
    db: Session = Depends(get_db),
):
    """字段保存后主动追问下一缺项（引导补全开启时）。"""
    from app.services.project_sessions import find_bound_session
    from app.services import project_workspace_agent

    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if not body.guided_intake:
        return {"assistant_message": None, "created": False}
    s = find_bound_session(db, project_id)
    if not s:
        raise HTTPException(404, "请先打开创作工作台以创建项目会话")
    msg = await project_workspace_agent.append_workspace_followup_message(
        db, s, p, guided=True,
    )
    return {
        "assistant_message": message_to_dict(msg) if msg else None,
        "created": bool(msg),
    }


@router.get("/projects/{project_id}/draft-preview/status")
async def draft_preview_status(project_id: int, db: Session = Depends(get_db)):
    from app.services.project_draft import get_draft_preview_status

    try:
        return await get_draft_preview_status(db, project_id)
    except ValueError as err:
        raise HTTPException(404, str(err)) from err


@router.post("/projects/{project_id}/render")
async def render_project_draft(project_id: int, db: Session = Depends(get_db)):
    from app.services.project_draft import render_project_draft_docx

    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    try:
        _doc, draft_key, meta = await render_project_draft_docx(db, p)
    except ValueError as err:
        raise HTTPException(400, str(err)) from err
    db.refresh(p)
    return {
        "draft_object_key": draft_key,
        "render_meta": meta,
        "project": project_to_dict(p),
    }


@router.get("/projects/{project_id}/draft-preview.pdf")
async def draft_preview_pdf(project_id: int, force: bool = False, db: Session = Depends(get_db)):
    from app.services.project_draft import get_draft_preview_pdf

    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    from app.services import pdf_convert

    import logging

    log = logging.getLogger(__name__)
    try:
        pdf_bytes = await get_draft_preview_pdf(db, project_id, force_render=force)
    except ValueError as err:
        raise HTTPException(400, str(err)) from err
    except Exception as err:
        log.exception("draft-preview.pdf failed project_id=%s", project_id)
        raise HTTPException(500, str(err) or "预览生成失败") from err
    title = (p.fields or {}).get("project_name") or p.title or "draft"
    pdf_name = f"{title}.pdf"
    engine = pdf_convert.get_pdf_engine() or "unknown"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=\"preview.pdf\"; filename*=UTF-8''{quote(pdf_name)}",
            "Cache-Control": "private, max-age=60",
            "X-PDF-Engine": engine,
        },
    )


@router.post("/projects/{project_id}/draft-preview/async")
async def start_draft_preview_async(
    project_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    from app.services import project_draft

    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    job_id = project_draft.start_async_preview_job(project_id)

    async def _run():
        from app.database import SessionLocal

        session = SessionLocal()
        try:
            project_draft.set_preview_job(job_id, status="running")
            await project_draft.get_draft_preview_pdf(session, project_id, force_render=True)
            project_draft.set_preview_job(job_id, status="done", pdf_ready=True)
        except Exception as err:
            project_draft.set_preview_job(job_id, status="failed", error=str(err))
        finally:
            session.close()

    background_tasks.add_task(_run)
    return {"job_id": job_id, "status": "pending"}


@router.get("/projects/{project_id}/draft-preview/jobs/{job_id}")
def get_draft_preview_job(project_id: int, job_id: str):
    from app.services import project_draft

    job = project_draft.get_preview_job(job_id)
    if not job or job.get("project_id") != project_id:
        raise HTTPException(404, "预览任务不存在")
    return {
        **job,
        "preview_url": f"/api/projects/{project_id}/draft-preview.pdf" if job.get("pdf_ready") else None,
    }


class SensitiveConfirmIn(BaseModel):
    field_keys: list[str]


class WritingRequirementsIn(BaseModel):
    requirements: str = ""


class GuidedIntakeIn(BaseModel):
    answered: dict[str, str] = {}


class ApplyAttachmentPatchIn(BaseModel):
    attachment_id: str
    keys: list[str] | None = None
    confirm_sensitive: bool = False


class ComposeProjectIn(BaseModel):
    requirements: str = ""
    reference_snippets: list[str] = []


@router.patch("/projects/{project_id}/fields/confirm-sensitive")
def confirm_sensitive_fields(
    project_id: int,
    body: SensitiveConfirmIn,
    db: Session = Depends(get_db),
):
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    fields = dict(p.fields or {})
    confirmed = dict(fields.get("_sensitive_confirmed") or {})
    stamp = datetime.utcnow().isoformat()
    for key in body.field_keys or []:
        if key:
            confirmed[key] = stamp
    fields["_sensitive_confirmed"] = confirmed
    p.fields = fields
    flag_modified(p, "fields")
    p.updated_at = datetime.utcnow()
    db.commit()
    return {"confirmed": confirmed, "project": project_to_dict(p)}


@router.post("/projects/{project_id}/attachments")
async def upload_project_attachment(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    from app.services.project_attachments import ingest_attachment

    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    data = await file.read()
    if not data:
        raise HTTPException(400, "文件为空")
    name = file.filename or "upload.bin"
    return await ingest_attachment(db, p, name, data, file.content_type or "")


@router.post("/projects/{project_id}/tender-file")
async def upload_project_tender_file(
    project_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """把招标 PDF/Word 解析进项目上下文，供写作中对照。"""
    from app.services.agent_capabilities import (
        parse_tender_docx,
        parse_tender_text,
        store_tender_record,
        tender_has_items,
    )

    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    data = await file.read()
    if not data:
        raise HTTPException(400, "文件为空")
    name = file.filename or "tender.docx"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ("pdf", "doc", "docx", "txt"):
        raise HTTPException(400, "请上传招标 PDF 或 Word")
    parsed = None
    if ext in ("txt", "md"):
        parsed = parse_tender_text(data.decode("utf-8", errors="ignore"))
    elif ext == "docx":
        try:
            parsed = parse_tender_docx(data)
        except Exception:
            parsed = None
        if not tender_has_items(parsed):
            text = ""
            try:
                preview = word.extract_preview(data, max_paragraphs=400)
                text = "\n".join(
                    item.get("text") or ""
                    for item in (preview.get("paragraphs") or [])
                    if isinstance(item, dict)
                )
            except Exception:
                text = ""
            if isinstance(text, str) and text.strip():
                parsed = parse_tender_text(text)
        if parsed is None:
            parsed = parse_tender_text("")
    else:
        text = ""
        if ext == "pdf":
            try:
                from io import BytesIO

                from pypdf import PdfReader

                reader = PdfReader(BytesIO(data))
                text = "\n".join((page.extract_text() or "") for page in reader.pages)
            except Exception:
                text = ""
        if not str(text or "").strip():
            try:
                from io import BytesIO

                import aspose.words as aw

                doc = aw.Document(BytesIO(data))
                raw = doc.to_string(aw.SaveFormat.TEXT)
                text = raw if isinstance(raw, str) else ""
            except Exception:
                text = ""
        parsed = parse_tender_text(text if isinstance(text, str) else "")
    key = f"projects/{p.id}/tender/{name}"
    try:
        storage.upload_bytes(key, data, file.content_type or "application/octet-stream")
    except Exception:
        key = ""
    record = store_tender_record(p, parsed, name=name, object_key=key)
    p.updated_at = datetime.utcnow()
    db.commit()
    return {"tender": record}


@router.get("/projects/{project_id}/memos")
def list_project_memos(project_id: int, db: Session = Depends(get_db)):
    from app.services.agent_capabilities import project_memos

    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    return {"memos": project_memos(p.fields)}


@router.delete("/projects/{project_id}/memos/{memo_id}")
def delete_project_memo(project_id: int, memo_id: str, db: Session = Depends(get_db)):
    from app.services.agent_capabilities import delete_memo, project_memos

    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if not delete_memo(p, memo_id):
        raise HTTPException(404, "备忘不存在")
    p.updated_at = datetime.utcnow()
    db.commit()
    return {"memos": project_memos(p.fields)}


@router.post("/projects/{project_id}/review-issues/{issue_id}/fix")
async def fix_project_review_issue(project_id: int, issue_id: str, db: Session = Depends(get_db)):
    from app.services.agent_capabilities import fix_review_issue, open_bound_docx
    from app.services.project_sessions import find_bound_session

    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    result = await fix_review_issue(
        p, issue_id, docx_bytes=open_bound_docx(db, p), db=db,
    )
    blob = result.pop("docx_bytes", None)
    if isinstance(blob, (bytes, bytearray)):
        try:
            key = f"projects/{p.id}/review/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.docx"
            storage.upload_bytes(
                key, bytes(blob),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            fields = dict(p.fields or {})
            fields["_draft_object_key"] = key
            p.fields = fields
            flag_modified(p, "fields")
            bound = find_bound_session(db, p.id)
            if bound is not None:
                ws = dict(bound.workspace or {})
                ws["draft_object_key"] = key
                ws["version"] = int(ws.get("version") or 0) + 1
                bound.workspace = ws
            result["draft_object_key"] = key
        except Exception:
            result["draft_saved"] = False
    if not result.get("ok") and result.get("error") == "没有这一条审查问题":
        raise HTTPException(404, result["error"])
    p.updated_at = datetime.utcnow()
    db.commit()
    return result


@router.post("/projects/{project_id}/attachments/apply")
def apply_attachment_field_patch(
    project_id: int,
    body: ApplyAttachmentPatchIn,
    db: Session = Depends(get_db),
):
    from app.services.field_verify import is_verify_field

    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    fields = dict(p.fields or {})
    attachments = fields.get("_attachments") or []
    att = next((a for a in attachments if a.get("id") == body.attachment_id), None)
    if not att:
        raise HTTPException(404, "附件不存在")
    applied = []
    for item in att.get("suggested_field_patch") or []:
        key = item.get("key")
        if body.keys and key not in body.keys:
            continue
        fd = db.query(FieldDef).filter(FieldDef.key == key).first()
        if fd and is_verify_field(fd) and not body.confirm_sensitive:
            continue
        if item.get("sensitive") and not body.confirm_sensitive:
            continue
        fields[key] = item.get("value")
        applied.append(key)
    p.fields = _fill_field_defaults(db, fields)
    flag_modified(p, "fields")
    p.updated_at = datetime.utcnow()
    db.commit()
    return {"applied_keys": applied, "project": project_to_dict(p)}


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    for e in list(p.exports or []):
        try:
            storage.delete_object(e.object_key)
            pdf_key = pdf_convert.pdf_object_key(e.object_key)
            if storage.object_exists(pdf_key):
                storage.delete_object(pdf_key)
        except Exception:
            pass
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.post("/projects/{project_id}/save")
def save_progress(project_id: int, body: SaveProgressRequest, db: Session = Depends(get_db)):
    """每步保存：持久化当前内容并创建快照，可选进入下一步。"""
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")

    if body.title is not None:
        p.title = body.title.strip() or p.title
    if body.template_id is not None:
        tpl = db.query(Template).filter(Template.id == body.template_id).first()
        if not tpl:
            raise HTTPException(404, "模板不存在")
        p.template_id = body.template_id
        if body.source_type:
            p.source_type = body.source_type
        else:
            p.source_type = "history" if (tpl.placeholders or {}).get("is_history") else "template"
        if not body.title:
            p.title = tpl.name
    if body.fields is not None:
        p.fields = _fill_field_defaults(db, body.fields)
        flag_modified(p, "fields")
        if p.fields.get("project_name"):
            p.title = str(p.fields["project_name"])
    if body.chapters is not None:
        p.chapters = body.chapters
        flag_modified(p, "chapters")
    if body.inserted_quals is not None:
        p.inserted_quals = body.inserted_quals
        flag_modified(p, "inserted_quals")
    if body.checklist_result is not None:
        p.checklist_result = body.checklist_result
        flag_modified(p, "checklist_result")

    step_for_snap = body.current_step or p.current_step or 1
    # 保存本步不回退总进度；仅在 advance 或前进到更高步骤时更新 current_step
    if body.advance:
        base = body.current_step or p.current_step or 1
        p.current_step = min(6, max(p.current_step or 1, base) + 1)
    elif body.current_step is not None and body.current_step > (p.current_step or 1):
        p.current_step = min(6, body.current_step)

    if (p.current_step or 1) >= 3:
        from app.services.field_verify import auto_confirm_wizard_verify_fields

        auto_confirm_wizard_verify_fields(db, p)
        flag_modified(p, "fields")

    if (p.current_step or 1) >= 2:
        filled = _fill_field_defaults(db, p.fields or {})
        if filled != (p.fields or {}):
            p.fields = filled
            flag_modified(p, "fields")

    p.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(p)

    if body.create_snapshot:
        save_snapshot(db, p, step_for_snap)
    return project_to_dict(p)


@router.post("/projects/{project_id}/step1")
def confirm_step1(project_id: int, body: ProjectCreate, db: Session = Depends(get_db)):
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if not body.template_id:
        raise HTTPException(400, "请选择模板或历史标书")
    tpl = db.query(Template).filter(Template.id == body.template_id).first()
    if not tpl:
        raise HTTPException(404, "模板不存在")
    if getattr(tpl, "kind", "") == "tender_doc" or not getattr(tpl, "enabled", True):
        raise HTTPException(400, "该文件不可作为标书起点")
    p.template_id = body.template_id
    p.source_type = (
        "history"
        if (tpl.placeholders or {}).get("is_history") or getattr(tpl, "kind", "") == "history"
        else "template"
    )
    p.title = body.title or tpl.name
    p.fields = _fill_field_defaults(db, p.fields)
    flag_modified(p, "fields")
    p.current_step = max(p.current_step, 2)
    p.updated_at = datetime.utcnow()
    db.commit()
    save_snapshot(db, p, 1)
    return project_to_dict(p)


@router.put("/projects/{project_id}/fields")
def update_fields(project_id: int, body: FieldsUpdate, db: Session = Depends(get_db)):
    from app.services.field_verify import is_verify_field

    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    from app.services.field_verify import mark_fields_for_reverify

    incoming = dict(body.fields or {})
    old = dict(p.fields or {})
    confirmed = dict(old.get("_sensitive_confirmed") or {})
    blocked: list[str] = []
    reverify_keys: list[str] = []
    for fd in db.query(FieldDef).all():
        if fd.key not in incoming or incoming.get(fd.key) == old.get(fd.key):
            continue
        if is_verify_field(fd):
            reverify_keys.append(fd.key)
            if fd.key not in confirmed and not body.confirm:
                blocked.append(fd.key)
                incoming[fd.key] = old.get(fd.key)
    merged = _fill_field_defaults(db, incoming)
    if reverify_keys:
        merged = mark_fields_for_reverify(merged, reverify_keys)
    p.fields = merged
    flag_modified(p, "fields")
    if p.fields.get("project_name"):
        p.title = str(p.fields["project_name"])
    if body.confirm:
        p.current_step = max(p.current_step, 3)
    p.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(p)
    save_snapshot(db, p, 2 if body.confirm else max(p.current_step, 2))
    out = project_to_dict(p)
    if blocked:
        out["blocked_sensitive"] = blocked
    return out


def _company_context(db: Session) -> str:
    from app.models import CompanyProfile
    c = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    if not c:
        return ""
    return "\n".join([
        f"企业：{c.full_name}",
        f"简介：{(c.intro or '')[:800]}",
        f"资质概述：{(c.qual_overview or '')[:500]}",
        f"典型项目：{(c.typical_projects or '')[:600]}",
        f"文风：{(c.ai_style_notes or '')[:400]}",
    ])


def _template_reference_context(db: Session, project: TenderProject) -> str:
    """空白模板类文档：将模板正文作为 AI 生成参考（含编写规则、格式说明等）。"""
    if not project.template_id:
        return ""
    tpl = db.query(Template).filter(Template.id == project.template_id).first()
    if not tpl or not tpl.object_key:
        return ""
    ph = tpl.placeholders or {}
    use_full = (
        getattr(tpl, "kind", "") == "skeleton"
        or bool(ph.get("ai_reference_full_doc"))
    )
    if not use_full:
        return ""
    try:
        data = storage.download_bytes(tpl.object_key)
        preview = word.extract_preview(data, max_paragraphs=250)
        lines = [p.get("text", "") for p in (preview.get("paragraphs") or []) if p.get("text")]
        body = "\n".join(lines).strip()
        if not body:
            return ""
        return f"模板参考文档（{tpl.name}）：\n{body[:4500]}"
    except Exception as e:
        print(f"[generate] template reference warn: {e}")
        return ""


@router.post("/projects/{project_id}/generate")
async def generate_content(project_id: int, body: GenerateRequest, db: Session = Depends(get_db)):
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    keys = body.chapters or [
        "技术规格书条款点对点应答",
        "生产供应计划方案",
        "运输方案",
        "售后服务方案",
        "应急预案和配套措施",
        "质量保证措施",
        "施工组织设计",
        "人员配置说明",
    ]
    ctx = _company_context(db)
    tpl_ref = _template_reference_context(db, p)
    chapters = dict(p.chapters or {})
    for key in keys:
        chapters[key] = await ai_svc.generate_chapter(
            key, p.fields or {}, db=db, company_context=ctx, template_reference=tpl_ref,
        )
    p.chapters = chapters
    flag_modified(p, "chapters")
    p.current_step = max(p.current_step, 3)
    p.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(p)
    save_snapshot(db, p, 3)
    return project_to_dict(p)


@router.post("/projects/{project_id}/generate/{chapter_key}")
async def regenerate_chapter(project_id: int, chapter_key: str, db: Session = Depends(get_db)):
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    chapters = dict(p.chapters or {})
    chapters[chapter_key] = await ai_svc.generate_chapter(
        chapter_key,
        p.fields or {},
        db=db,
        company_context=_company_context(db),
        template_reference=_template_reference_context(db, p),
    )
    p.chapters = chapters
    flag_modified(p, "chapters")
    p.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(p)
    save_snapshot(db, p, 3)
    return project_to_dict(p)


@router.post("/projects/{project_id}/confirm-ai")
def confirm_ai(project_id: int, db: Session = Depends(get_db)):
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if not p.chapters:
        raise HTTPException(400, "请先生成 AI 内容")
    p.current_step = max(p.current_step, 4)
    p.updated_at = datetime.utcnow()
    db.commit()
    save_snapshot(db, p, 3)
    return project_to_dict(p)


@router.post("/projects/{project_id}/insert-quals")
def insert_quals(project_id: int, body: InsertQualRequest, db: Session = Depends(get_db)):
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    p.inserted_quals = body.qualification_ids
    flag_modified(p, "inserted_quals")
    p.current_step = max(p.current_step, 5)
    p.updated_at = datetime.utcnow()
    db.commit()
    save_snapshot(db, p, 4)
    db.refresh(p)
    return project_to_dict(p)


@router.post("/projects/{project_id}/validate")
def validate_project(project_id: int, db: Session = Depends(get_db)):
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    tpl_code = "common"
    tpl_kind = "template"
    if p.template_id:
        tpl = db.query(Template).filter(Template.id == p.template_id).first()
        if tpl:
            tpl_code = getattr(tpl, "template_code", "common") or "common"
            tpl_kind = getattr(tpl, "kind", "template") or "template"
    q = db.query(ChecklistItem)
    if tpl_kind == "skeleton" or tpl_code == "common":
        q = q.filter(ChecklistItem.template_code == "common")
    else:
        q = q.filter(ChecklistItem.template_code.in_([tpl_code, "common"]))
    items = q.all()
    checklist = [
        {"id": i.id, "section": i.section, "name": i.name, "required": i.required, "remark": i.remark}
        for i in items
    ]
    quals = db.query(Qualification).all()
    qual_dicts = [
        {
            "id": q.id, "name": q.name, "category": q.category, "keywords": q.keywords,
            "is_long_term": q.is_long_term, "valid_to": q.valid_to,
        }
        for q in quals
    ]
    headings: list[str] = []
    if p.template_id:
        tpl = db.query(Template).filter(Template.id == p.template_id).first()
        if tpl:
            try:
                tpl_bytes = storage.download_bytes(tpl.object_key)
                structure = word.extract_structure(tpl_bytes)
                headings = [h["text"] for h in structure.get("headings", [])]
                headings.extend(
                    para.get("text", "") for para in structure.get("paragraphs", [])[:80]
                )
            except Exception as e:
                print(f"template parse warn: {e}")
    result = checklist_svc.run_checklist(
        checklist, p.chapters or {}, p.fields or {}, qual_dicts, p.inserted_quals or [], headings
    )
    # 骨架模板仅用关键字段/过期资质决定能否导出，避免空清单误杀
    if tpl_kind == "skeleton":
        critical_reds = [
            i for i in result.get("items", [])
            if i.get("level") == "red" and (
                str(i.get("id", "")).startswith("field-")
                or str(i.get("id", "")).startswith("qual-")
            )
        ]
        result["can_export"] = len(critical_reds) == 0
        if result["can_export"] and result.get("status") == "red":
            result["status"] = "yellow"
    p.checklist_result = result
    flag_modified(p, "checklist_result")
    p.current_step = max(p.current_step, 5)
    p.updated_at = datetime.utcnow()
    db.commit()
    save_snapshot(db, p, 5)
    return result


@router.post("/projects/{project_id}/doc-review")
async def doc_review_project(project_id: int, db: Session = Depends(get_db)):
    """文档引擎 v2：LLM+规则全篇审阅（导出前预检）。"""
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if not p.template_id:
        raise HTTPException(400, "未选择模板")
    tpl = db.query(Template).filter(Template.id == p.template_id).first()
    tpl_bytes = storage.download_bytes(tpl.object_key)
    export_fields = _fill_field_defaults(db, p.fields)
    from app.services.doc_engine.engine import render_project_document, review_project_document

    snap = getattr(tpl, "source_snapshot", None) or {}
    writing_req = str(export_fields.get("_writing_requirements") or "")
    doc_bytes, _ = await render_project_document(
        tpl_bytes,
        tpl.placeholders,
        export_fields,
        p.chapters,
        source_snapshot=snap if getattr(tpl, "kind", "") == "history" else None,
        highlight=False,
        requirements=writing_req,
        company_context=_company_context(db),
        db=db,
        mode="replace" if getattr(tpl, "kind", "") == "history" else None,
    )
    required = ["project_name", "tender_no", "tenderer", "project_manager"]
    review = await review_project_document(
        doc_bytes, tpl.placeholders, export_fields, snap, required, db=db
    )
    from app.services.agent_capabilities import stamp_review_issues

    review = stamp_review_issues(review)
    merged = dict(p.checklist_result or {})
    merged["doc_review"] = review
    merged["can_export"] = review.get("can_export", False) and merged.get("can_export", True)
    p.checklist_result = merged
    flag_modified(p, "checklist_result")
    p.updated_at = datetime.utcnow()
    db.commit()
    return review


@router.get("/projects/{project_id}/workflow-plan")
def get_project_workflow_plan(project_id: int, db: Session = Depends(get_db)):
    """根据所选模板返回工作流模式：占位符替换或 AI 创作。"""
    from app.services.project_workflow import get_workflow_plan

    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    plan = get_workflow_plan(db, p.template_id)
    plan["project_id"] = p.id
    plan["current_step"] = p.current_step
    return plan


@router.post("/projects/{project_id}/guided-intake")
async def project_guided_intake(
    project_id: int,
    body: GuidedIntakeIn,
    db: Session = Depends(get_db),
):
    """AI 审视模板并生成引导式信息收集问题。"""
    from app.services.project_workflow import guided_intake_questions

    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if not p.template_id:
        raise HTTPException(400, "请先选择模板")
    fields = _fill_field_defaults(db, p.fields)
    return await guided_intake_questions(
        db, p.template_id, fields, answered=body.answered or {}
    )


@router.post("/projects/{project_id}/compose")
async def compose_project(
    project_id: int,
    body: ComposeProjectIn,
    db: Session = Depends(get_db),
):
    """创作模式：根据编写要求分块生成章节并写入项目。"""
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if not p.template_id:
        raise HTTPException(400, "未选择模板")
    tpl = db.query(Template).filter(Template.id == p.template_id).first()
    tpl_bytes = storage.download_bytes(tpl.object_key)
    fields = _fill_field_defaults(db, p.fields)
    if body.requirements:
        fields["_writing_requirements"] = body.requirements
        p.fields = fields
        flag_modified(p, "fields")

    from app.services.doc_engine.composition import build_composition_plan, generate_block_contents
    from app.services.doc_engine.manifest import get_manifest
    from app.services.doc_engine.parser import parse_template_manifest

    manifest = get_manifest(tpl.placeholders) or parse_template_manifest(tpl_bytes)
    req = body.requirements or ""
    if body.reference_snippets:
        ref_block = "\n---\n".join(s for s in body.reference_snippets if s and str(s).strip())
        req = f"{req}\n\n参照段落：\n{ref_block}".strip()
    plan = await build_composition_plan(
        manifest, fields, req, _company_context(db), db=db
    )
    contents, table_rows = await generate_block_contents(
        plan, fields, req, _company_context(db), db=db
    )
    if table_rows:
        fields = dict(fields)
        for bind, rows in table_rows.items():
            fields[bind] = rows
        p.fields = fields
        flag_modified(p, "fields")
    chapters = dict(p.chapters or {})
    for k, v in contents.items():
        if k and v and not k.startswith("field.") and not k.startswith("ai."):
            chapters[k] = {"content": v, "source": "ai", "engine": "doc_engine_v2"}
    p.chapters = chapters
    flag_modified(p, "chapters")
    p.current_step = max(p.current_step, 3)
    p.updated_at = datetime.utcnow()
    db.commit()
    save_snapshot(db, p, 3)
    return {
        "plan": plan,
        "generated_keys": list(contents.keys()),
        "table_binds": list(table_rows.keys()) if table_rows else [],
        "project": project_to_dict(p),
    }


@router.get("/projects/{project_id}/table-slots")
def list_project_table_slots(project_id: int, db: Session = Depends(get_db)):
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if not p.template_id:
        return {"slots": [], "rows": {}}
    tpl = db.query(Template).filter(Template.id == p.template_id).first()
    from app.services.doc_engine.table_compose import get_table_slot_rows, table_slots_from_template

    tpl_bytes = storage.download_bytes(tpl.object_key)
    slots = table_slots_from_template(tpl.placeholders, tpl_bytes)
    fields = _fill_field_defaults(db, p.fields)
    rows = {s["bind"]: get_table_slot_rows(fields, s["bind"]) for s in slots if s.get("bind")}
    return {"slots": slots, "rows": rows}


class TableRowsUpdate(BaseModel):
    bind: str
    rows: list[dict]


class GenerateTablesIn(BaseModel):
    requirements: str = ""


@router.put("/projects/{project_id}/table-slots")
def update_project_table_slots(
    project_id: int, body: TableRowsUpdate, db: Session = Depends(get_db),
):
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    fields = dict(_fill_field_defaults(db, p.fields))
    fields[body.bind] = body.rows
    p.fields = fields
    flag_modified(p, "fields")
    p.updated_at = datetime.utcnow()
    db.commit()
    return {"bind": body.bind, "row_count": len(body.rows), "project": project_to_dict(p)}


@router.post("/projects/{project_id}/generate-tables")
async def generate_project_tables(
    project_id: int, body: GenerateTablesIn, db: Session = Depends(get_db),
):
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if not p.template_id:
        raise HTTPException(400, "未选择模板")
    tpl = db.query(Template).filter(Template.id == p.template_id).first()
    tpl_bytes = storage.download_bytes(tpl.object_key)
    fields = _fill_field_defaults(db, p.fields)
    req = body.requirements or str(fields.get("_writing_requirements") or "")
    from app.services.doc_engine.manifest import get_manifest
    from app.services.doc_engine.parser import parse_template_manifest
    from app.services.doc_engine.table_compose import generate_all_table_rows, table_slots_from_template

    manifest = get_manifest(tpl.placeholders) or parse_template_manifest(tpl_bytes)
    table_rows = await generate_all_table_rows(
        manifest, fields, req, _company_context(db), db=db,
    )
    for bind, rows in table_rows.items():
        fields[bind] = rows
    p.fields = fields
    flag_modified(p, "fields")
    p.updated_at = datetime.utcnow()
    db.commit()
    return {
        "table_binds": list(table_rows.keys()),
        "rows": table_rows,
        "slots": table_slots_from_template(tpl.placeholders, tpl_bytes),
        "project": project_to_dict(p),
    }


@router.get("/projects/{project_id}/export")
async def export_project(project_id: int, db: Session = Depends(get_db)):
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    if not p.template_id:
        raise HTTPException(400, "未选择模板")
    # 若未校验则先校验
    if not p.checklist_result:
        validate_project(project_id, db)
        db.refresh(p)
    if p.checklist_result and not p.checklist_result.get("can_export", True):
        raise HTTPException(400, detail={"message": "条目校验未通过，无法导出", "result": p.checklist_result})

    from app.services.field_verify import unconfirmed_sensitive_keys

    pending_sensitive = unconfirmed_sensitive_keys(p.fields, db, project=p)
    if pending_sensitive:
        raise HTTPException(
            400,
            detail={
                "message": "存在未人工确认的敏感字段，无法导出",
                "needs_confirm": pending_sensitive,
            },
        )

    tpl = db.query(Template).filter(Template.id == p.template_id).first()
    if getattr(tpl, "kind", "") == "tender_doc":
        raise HTTPException(400, "招标文件仅供参考，不能作为导出起点")
    tpl_bytes = storage.download_bytes(tpl.object_key)
    chapters = dict(p.chapters or {})
    quals = []
    if p.inserted_quals:
        quals = db.query(Qualification).filter(Qualification.id.in_(p.inserted_quals)).all()
        chapters["资质材料清单"] = {
            "content": "\n".join(f"- {q.category} / {q.name}（{q.issuer}）" for q in quals),
            "source": "system",
        }
    snap = getattr(tpl, "source_snapshot", None) or {}
    export_fields = _fill_field_defaults(db, p.fields)
    if export_fields != (p.fields or {}):
        p.fields = export_fields
        flag_modified(p, "fields")
        db.commit()
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
        (p.chapters or {}).get("_writing_requirements") or ""
    )
    from app.services.doc_engine.engine import render_project_document, review_project_document

    doc_bytes, _render_meta = await render_project_document(
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

    fields = export_fields
    required = ["project_name", "tender_no", "tenderer", "project_manager"]
    if not (fields.get("bid_amount_upper") or fields.get("bid_amount")):
        required.append("bid_amount_upper")

    validation = await review_project_document(
        doc_bytes,
        tpl.placeholders,
        fields,
        snap if getattr(tpl, "kind", "") == "history" else None,
        required,
        db=db,
    )
    if not validation.get("can_export", validation.get("status") != "red"):
        raise HTTPException(400, detail={"message": "文档审阅未通过，无法导出", "validation": validation})

    filename = f"{(p.fields or {}).get('project_name') or p.title or 'bid'}.docx"
    stamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    out_key = f"exports/project_{p.id}_{stamp}.docx"
    storage.upload_bytes(
        out_key, doc_bytes,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    export_row = ProjectExport(
        project_id=p.id,
        object_key=out_key,
        filename=filename,
    )
    db.add(export_row)
    p.status = "exported"
    p.current_step = 6
    p.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(export_row)
    export_fields = dict(p.fields or {})
    audit = list(export_fields.get("_export_audit_log") or [])
    audit.append({
        "export_id": export_row.id,
        "at": datetime.utcnow().isoformat(),
        "sensitive_confirmed": dict(export_fields.get("_sensitive_confirmed") or {}),
    })
    export_fields["_export_audit_log"] = audit[-20:]
    p.fields = export_fields
    flag_modified(p, "fields")
    db.commit()
    save_snapshot(db, p, 6)

    try:
        from app.services.agent_workspace import mirror_bytes_to_project_workspace

        rel = f"产出/{filename}"
        mirror_bytes_to_project_workspace(p, rel, doc_bytes)
    except Exception:
        pass

    ascii_name = "tender.docx"
    return Response(
        content=doc_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}",
            "X-Export-Validation": validation["status"],
            "X-Export-Id": str(export_row.id),
        },
    )


@router.get("/projects/{project_id}/exports")
def list_exports(project_id: int, db: Session = Depends(get_db)):
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    try:
        items = sync_exports_from_minio(db, project_id)
    except Exception as e:
        print(f"sync exports warn: {e}")
        items = (
            db.query(ProjectExport)
            .filter(ProjectExport.project_id == project_id)
            .order_by(ProjectExport.id.desc())
            .all()
        )
    return [export_to_dict(e) for e in items]


@router.get("/projects/{project_id}/exports/{export_id}/download")
def download_export(project_id: int, export_id: int, inline: bool = False, db: Session = Depends(get_db)):
    e = get_export_or_404(db, project_id, export_id)
    try:
        doc_bytes = storage.download_bytes(e.object_key)
    except Exception as err:
        raise HTTPException(404, f"导出文件不存在：{err}") from err
    filename = e.filename or "tender.docx"
    disposition = "inline" if inline else "attachment"
    return Response(
        content=doc_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"{disposition}; filename=\"tender.docx\"; filename*=UTF-8''{quote(filename)}",
        },
    )


@router.get("/projects/{project_id}/exports/{export_id}/preview")
def preview_export(project_id: int, export_id: int, db: Session = Depends(get_db)):
    """高保真预览：触发/复用 DOCX→PDF 转换，返回 PDF 预览地址元数据。"""
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    e = get_export_or_404(db, project_id, export_id)
    _pdf_bytes, pdf_key, from_cache = ensure_export_pdf(e)
    title = (p.fields or {}).get("project_name") or p.title or e.filename
    return {
        "export_id": e.id,
        "project_id": project_id,
        "filename": e.filename,
        "title": title,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "format": "pdf",
        "preview_url": f"/api/projects/{project_id}/exports/{export_id}/preview.pdf",
        "pdf_object_key": pdf_key,
        "cached": from_cache,
        "pages": None,
    }


@router.get("/projects/{project_id}/exports/{export_id}/preview.pdf")
def preview_export_pdf(project_id: int, export_id: int, db: Session = Depends(get_db)):
    """返回按页分页的 PDF（LibreOffice 从 DOCX 转换，结果缓存到 MinIO）。"""
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    e = get_export_or_404(db, project_id, export_id)
    pdf_bytes, _pdf_key, _from_cache = ensure_export_pdf(e)
    pdf_name = (e.filename or "tender.docx").rsplit(".", 1)[0] + ".pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=\"preview.pdf\"; filename*=UTF-8''{quote(pdf_name)}",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/projects/{project_id}/snapshots")
def list_snapshots(project_id: int, db: Session = Depends(get_db)):
    items = (
        db.query(ProjectSnapshot)
        .filter(ProjectSnapshot.project_id == project_id)
        .order_by(ProjectSnapshot.id.desc())
        .all()
    )
    return [
        {
            "id": s.id,
            "step": s.step,
            "step_name": s.step_name,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in items
    ]


@router.post("/projects/{project_id}/rollback")
def rollback(project_id: int, body: RollbackRequest, db: Session = Depends(get_db)):
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    snap = (
        db.query(ProjectSnapshot)
        .filter(ProjectSnapshot.id == body.snapshot_id, ProjectSnapshot.project_id == project_id)
        .first()
    )
    if not snap:
        raise HTTPException(404, "快照不存在")
    payload = snap.payload or {}
    p.fields = payload.get("fields") or {}
    p.chapters = payload.get("chapters") or {}
    p.inserted_quals = payload.get("inserted_quals") or []
    p.checklist_result = payload.get("checklist_result") or {}
    p.current_step = payload.get("current_step") or snap.step
    p.template_id = payload.get("template_id") or p.template_id
    p.source_type = payload.get("source_type") or p.source_type
    p.title = payload.get("title") or p.title
    p.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(p)
    return project_to_dict(p)


def session_to_dict(s: ChatSession, include_messages: bool = False) -> dict:
    data = {
        "id": s.id,
        "title": s.title,
        "workspace": getattr(s, "workspace", None) or {},
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        "message_count": len(s.messages or []),
    }
    if include_messages:
        data["messages"] = [message_to_dict(m) for m in (s.messages or [])]
    return data


def message_to_dict(m: ChatMessage) -> dict:
    meta = getattr(m, "metadata_json", None) or {}
    return {
        "id": m.id,
        "session_id": m.session_id,
        "role": m.role,
        "content": m.content,
        "source": m.source or "",
        "matched_question": m.matched_question or "",
        "metadata": meta if isinstance(meta, dict) else {},
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def get_session_or_404(db: Session, session_id: int) -> ChatSession:
    s = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    if not s:
        raise HTTPException(404, "会话不存在")
    return s


@router.get("/chat/sessions")
def list_chat_sessions(db: Session = Depends(get_db)):
    items = db.query(ChatSession).order_by(ChatSession.updated_at.desc()).all()
    return [session_to_dict(s) for s in items]


@router.get("/chat/features")
def chat_features():
    from app.services import onlyoffice as oo_svc

    return {
        "feature_cards": chat_assistant.get_feature_cards(),
        "suggested_prompts": chat_assistant.get_suggested_prompts(),
        "onlyoffice": oo_svc.status_payload(),
    }


@router.post("/chat/sessions")
def create_chat_session(body: ChatSessionCreate, db: Session = Depends(get_db)):
    s = ChatSession(title=(body.title or "新对话").strip() or "新对话")
    db.add(s)
    db.commit()
    db.refresh(s)
    return session_to_dict(s, include_messages=True)


@router.get("/chat/sessions/{session_id}")
def get_chat_session(session_id: int, db: Session = Depends(get_db)):
    s = get_session_or_404(db, session_id)
    return session_to_dict(s, include_messages=True)


@router.delete("/chat/sessions/{session_id}")
def delete_chat_session(session_id: int, db: Session = Depends(get_db)):
    s = get_session_or_404(db, session_id)
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.patch("/chat/sessions/{session_id}")
def update_chat_session(session_id: int, body: ChatSessionUpdate, db: Session = Depends(get_db)):
    s = get_session_or_404(db, session_id)
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(400, "标题不能为空")
    s.title = title[:200]
    s.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(s)
    return session_to_dict(s)


@router.get("/chat/sessions/{session_id}/messages")
def list_chat_messages(session_id: int, db: Session = Depends(get_db)):
    s = get_session_or_404(db, session_id)
    return [message_to_dict(m) for m in (s.messages or [])]


@router.get("/chat/sessions/{session_id}/mentions")
def list_chat_mentions(session_id: int, q: str = "", db: Session = Depends(get_db)):
    from app.services.agent_capabilities import mention_candidates

    s = get_session_or_404(db, session_id)
    return {"items": mention_candidates(db, s, q)}


async def _finalize_chat_message_turn(
    session_id: int,
    s: ChatSession,
    user_msg: ChatMessage,
    content: str,
    body: "ChatMessageCreate",
    result: dict,
    db: Session,
) -> dict:
    meta = dict(result.get("metadata") or {})
    ws = dict(getattr(s, "workspace", None) or {})

    # 工作区：按模板生成标书
    if meta.get("needs_workspace_generate"):
        doc_key = ws.get("draft_object_key") or ws.get("template_object_key")
        if doc_key:
            from app.models import CompanyProfile
            company = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
            ctx = ""
            if company:
                ctx = f"{company.full_name}\n{company.intro}\n{company.qual_overview}"
            doc_bytes = storage.download_bytes(doc_key)
            requirements = meta.get("requirements") or content
            new_bytes, gen_meta = await document_agent.generate_document_from_template(
                doc_bytes, requirements, db=db, company_context=ctx,
            )
            new_key = f"chat/{session_id}/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_generated.docx"
            storage.upload_bytes(new_key, new_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            ws["draft_object_key"] = new_key
            ws["version"] = int(ws.get("version") or 0) + 1
            ws["last_action"] = "generate"
            ws["generation_meta"] = gen_meta
            s.workspace = ws
            result["answer"] = (
                (result.get("answer") or "")
                + f"\n\n✅ 已生成新标书（版本 v{ws['version']}），请在左侧预览查看。"
                f" 共填充 {len(gen_meta.get('generated_keys') or [])} 个字段/章节。"
            )
            meta["workspace_updated"] = True

    # 工作区：全文批量替换
    if meta.get("needs_workspace_bulk_replace"):
        doc_key = ws.get("draft_object_key") or ws.get("template_object_key")
        old_t = meta.get("old_text") or ""
        new_t = meta.get("new_text") or ""
        if doc_key and old_t:
            doc_bytes = storage.download_bytes(doc_key)
            new_bytes = word.apply_literal_replacements(doc_bytes, [(old_t, new_t)])
            new_key = f"chat/{session_id}/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_replaced.docx"
            storage.upload_bytes(new_key, new_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            ws["draft_object_key"] = new_key
            ws["version"] = int(ws.get("version") or 0) + 1
            ws["last_action"] = "bulk_replace"
            s.workspace = ws
            result["answer"] = (
                f"✅ 已完成全文替换（版本 v{ws['version']}）：\n"
                f"「{old_t}」→「{new_t}」\n\n请在左侧预览确认效果。"
            )
            meta["workspace_updated"] = True

    # 工作区：插入表格（必须有明确锚点，不用段落 0 兜底）
    if meta.get("needs_workspace_insert_table"):
        from app.services.agent_capabilities import ANCHOR_MISSING

        doc_key = ws.get("draft_object_key") or ws.get("template_object_key")
        raw_idx = meta.get("paragraph_index")
        if raw_idx is None:
            raw_idx = (body.context or {}).get("paragraph_index")
        if doc_key and raw_idx is not None and str(raw_idx) != "":
            doc_bytes = storage.download_bytes(doc_key)
            pidx = int(raw_idx)
            rows = int(meta.get("rows") or 3)
            cols = int(meta.get("cols") or 3)
            new_bytes, ins_meta = document_agent.insert_table_in_document(
                doc_bytes, paragraph_index=pidx, rows=rows, cols=cols,
            )
            new_key = f"chat/{session_id}/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_table.docx"
            storage.upload_bytes(new_key, new_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            ws["draft_object_key"] = new_key
            ws["version"] = int(ws.get("version") or 0) + 1
            ws["last_action"] = "insert_table"
            s.workspace = ws
            result["answer"] = f"✅ 已插入 {rows}×{cols} 表格（版本 v{ws['version']}），请在左侧预览确认。"
            meta["workspace_updated"] = True
            meta["insert_meta"] = ins_meta
        else:
            result["answer"] = ANCHOR_MISSING
            meta["anchor_missing"] = True

    # 工作区：插入图片（必须有明确锚点，不用段落 0 兜底）
    if meta.get("needs_workspace_insert_image"):
        from app.services.agent_capabilities import ANCHOR_MISSING as _ANCHOR_MISSING

        doc_key = ws.get("draft_object_key") or ws.get("template_object_key")
        att_key = meta.get("attachment_object_key") or (body.context or {}).get("attachment_object_key")
        raw_idx = meta.get("paragraph_index")
        if raw_idx is None:
            raw_idx = (body.context or {}).get("paragraph_index")
        if doc_key and att_key and raw_idx is not None and str(raw_idx) != "":
            doc_bytes = storage.download_bytes(doc_key)
            img_bytes = storage.download_bytes(att_key)
            pidx = int(raw_idx)
            new_bytes, ins_meta = document_agent.insert_image_in_document(
                doc_bytes, img_bytes, paragraph_index=pidx,
            )
            new_key = f"chat/{session_id}/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_image.docx"
            storage.upload_bytes(new_key, new_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            ws["draft_object_key"] = new_key
            ws["version"] = int(ws.get("version") or 0) + 1
            ws["last_action"] = "insert_image"
            s.workspace = ws
            result["answer"] = f"✅ 图片已插入文档（版本 v{ws['version']}）。"
            meta["workspace_updated"] = True
            meta["insert_meta"] = ins_meta
        elif not att_key:
            result["answer"] = "请先通过 📎 上传图片，再选中插入位置。"
        else:
            result["answer"] = _ANCHOR_MISSING
            meta["anchor_missing"] = True

    # 工作区：局部修改
    if meta.get("needs_workspace_edit"):
        doc_key = ws.get("draft_object_key") or ws.get("template_object_key")
        if doc_key:
            from app.models import CompanyProfile
            company = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
            ctx = company.intro if company else ""
            doc_bytes = storage.download_bytes(doc_key)
            ctx_sel = body.context or {}
            refs = ctx_sel.get("reference_snippets") or []
            if isinstance(refs, str):
                refs = [refs]
            new_bytes, revised, edit_meta = await document_agent.edit_document_fragment(
                doc_bytes,
                meta.get("instruction") or content,
                selected_text=meta.get("selected_text") or ctx_sel.get("selected_text") or "",
                paragraph_index=meta.get("paragraph_index") if meta.get("paragraph_index") is not None else ctx_sel.get("paragraph_index"),
                db=db,
                company_context=ctx,
                reference_snippets=refs,
            )
            new_key = f"chat/{session_id}/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_edited.docx"
            storage.upload_bytes(new_key, new_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            ws["draft_object_key"] = new_key
            ws["version"] = int(ws.get("version") or 0) + 1
            ws["last_action"] = "edit"
            s.workspace = ws
            result["answer"] = (
                f"✅ 已应用修订（版本 v{ws['version']}）。\n\n"
                f"修订后片段预览：\n{revised[:500]}{'…' if len(revised) > 500 else ''}"
            )
            meta["workspace_updated"] = True
            meta["revised_preview"] = revised[:1000]

    pid = ws.get("project_id")
    if pid:
        try:
            from app.services.project_context import build_project_context
            from app.services import agent_tools, project_workspace_agent

            ctx_pack = build_project_context(db, int(pid))
            meta["project_context"] = ctx_pack
            tpl = ctx_pack.get("template") or {}
            cl = ctx_pack.get("field_checklist") or {}
            missing_n = len(cl.get("missing_required") or [])
            verify_n = len([
                v for v in (cl.get("needs_verify") or []) if not v.get("confirmed")
            ])
            if tpl.get("name") and not meta.get("project_context_hint"):
                hint = f"当前模板：{tpl.get('name')}（{tpl.get('mode')}）"
                if missing_n or verify_n:
                    hint += f"；待填 {missing_n} 项，待核实 {verify_n} 项"
                result["answer"] = ((result.get("answer") or "").strip() + f"\n\n_{hint}_").strip()
            guided = ws.get("guided_intake", True)
            ctx_body = body.context or {}
            if ctx_body.get("guided_intake") is False:
                guided = False
            if guided and not meta.get("cards"):
                guided_meta = await project_workspace_agent.build_guided_intake_metadata(
                    db, int(pid), guided=True,
                )
                for card in guided_meta.get("cards") or []:
                    meta.setdefault("cards", []).append(card)
                follow = guided_meta.get("guided_followup_text")
                if follow and not meta.get("cards"):
                    result["answer"] = ((result.get("answer") or "") + f"\n\n{follow}").strip()
            if guided and not meta.get("cards"):
                tail = await project_workspace_agent.build_workspace_followup(db, int(pid), guided=True)
                if tail and tail not in (result.get("answer") or ""):
                    result["answer"] = ((result.get("answer") or "").strip() + f"\n\n{tail}").strip()
        except Exception as err:
            import logging

            logging.getLogger(__name__).warning("project chat context enrich failed: %s", err)

    bot_msg = ChatMessage(
        session_id=s.id,
        role="assistant",
        content=result.get("answer") or "",
        source=result.get("source") or "",
        matched_question=result.get("matched_question") or "",
        metadata_json=meta,
    )
    db.add(bot_msg)

    if s.title in ("新对话", "") or len(s.messages or []) <= 1:
        s.title = content[:40] + ("…" if len(content) > 40 else "")
    s.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user_msg)
    db.refresh(bot_msg)
    db.refresh(s)
    return {
        "session": session_to_dict(s),
        "user_message": message_to_dict(user_msg),
        "assistant_message": message_to_dict(bot_msg),
        "answer": result.get("answer"),
        "source": result.get("source"),
        "matched_question": result.get("matched_question"),
        "mode": result.get("mode"),
        "metadata": meta,
    }


_EXT_TYPE_LABELS = {
    "pdf": "PDF",
    "doc": "DOC",
    "docx": "DOCX",
    "txt": "TXT",
    "png": "PNG",
    "jpg": "JPG",
    "jpeg": "JPG",
    "webp": "WEBP",
    "gif": "GIF",
    "zip": "ZIP",
    "tif": "TIFF",
    "tiff": "TIFF",
    "bmp": "BMP",
}


def _file_type_label(name: str) -> str:
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
    if not ext:
        return "文件"
    return _EXT_TYPE_LABELS.get(ext, ext.upper()[:6])


def sanitize_attachment_chips(raw) -> list[dict]:
    """只保留展示用的名称/类型，不把本地路径写进消息 metadata。"""
    if not isinstance(raw, list):
        return []
    chips: list[dict] = []
    for item in raw[:24]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        kind = "folder" if str(item.get("kind") or "") == "folder" else "file"
        type_label = str(item.get("type") or "").strip()[:32] or (
            "文件夹" if kind == "folder" else _file_type_label(name)
        )
        chips.append({"name": name[:180], "kind": kind, "type": type_label})
    return chips


def prepare_chat_turn(body: ChatMessageCreate) -> tuple[str, dict, list[dict], list[dict]]:
    from app.services.agent_capabilities import normalize_mentions

    ctx = dict(body.context or {})
    chips = sanitize_attachment_chips(ctx.pop("attachments", None))
    mentions = normalize_mentions(ctx.get("mentions"))
    if mentions:
        ctx["mentions"] = mentions
    else:
        ctx.pop("mentions", None)
    content = (body.content or "").strip()
    return content, ctx, chips, mentions


def _user_message_with_chips(
    session_id: int,
    content: str,
    chips: list[dict],
    mentions: list[dict] | None = None,
) -> ChatMessage:
    meta: dict = {}
    if chips:
        meta["attachments"] = chips
    if mentions:
        meta["mentions"] = mentions
    kwargs = {"metadata_json": meta} if meta else {}
    return ChatMessage(session_id=session_id, role="user", content=content, **kwargs)


def _attachment_only_payload(db: Session, s: ChatSession, user_msg: ChatMessage) -> dict:
    s.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user_msg)
    db.refresh(s)
    return {
        "session": session_to_dict(s),
        "user_message": message_to_dict(user_msg),
        "assistant_message": None,
        "answer": "",
        "source": "",
        "matched_question": "",
        "mode": "attachments",
        "metadata": {},
    }


@router.post("/chat/sessions/{session_id}/messages")
async def post_chat_message(session_id: int, body: ChatMessageCreate, db: Session = Depends(get_db)):
    s = get_session_or_404(db, session_id)
    content, ctx, chips, mentions = prepare_chat_turn(body)
    if not content and not chips and not mentions:
        raise HTTPException(400, "消息不能为空")
    body.context = ctx or None

    user_msg = _user_message_with_chips(s.id, content, chips, mentions)
    if not content:
        db.add(user_msg)
        return _attachment_only_payload(db, s, user_msg)
    db.add(user_msg)
    db.flush()

    history = [
        {"role": m.role, "content": m.content}
        for m in (s.messages or [])
        if m.id != user_msg.id
    ]
    faqs = db.query(FAQItem).all()
    items = [
        {"question": f.question, "answer": f.answer, "category": f.category, "source": f.source}
        for f in faqs
    ]
    result = await chat_assistant.process_chat_message(
        content,
        db,
        history=history,
        faq_items=items,
        workspace=getattr(s, "workspace", None) or {},
        context=ctx,
        session=s,
    )
    return await _finalize_chat_message_turn(session_id, s, user_msg, content, body, result, db)


@router.post("/chat/sessions/{session_id}/messages/stream")
async def post_chat_message_stream(session_id: int, body: ChatMessageCreate, db: Session = Depends(get_db)):
    s = get_session_or_404(db, session_id)
    content, ctx, chips, mentions = prepare_chat_turn(body)
    if not content and not chips and not mentions:
        raise HTTPException(400, "消息不能为空")
    body.context = ctx or None

    user_msg = _user_message_with_chips(s.id, content, chips, mentions)
    db.add(user_msg)
    if not content:
        payload = _attachment_only_payload(db, s, user_msg)

        async def attachment_only_stream():
            yield f"data: {json.dumps({'type': 'done', 'payload': payload}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            attachment_only_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    db.commit()
    user_msg_id = user_msg.id
    db_bind = db.get_bind()

    async def event_stream():
        stream_db = Session(bind=db_bind)
        try:
            s_live = stream_db.query(ChatSession).filter(ChatSession.id == session_id).first()
            user_live = stream_db.query(ChatMessage).filter(ChatMessage.id == user_msg_id).first()
            if not s_live or not user_live:
                return
            history = [
                {"role": m.role, "content": m.content}
                for m in (s_live.messages or [])
                if m.id != user_live.id
            ]
            faqs = stream_db.query(FAQItem).all()
            items = [
                {"question": f.question, "answer": f.answer, "category": f.category, "source": f.source}
                for f in faqs
            ]
            ws = getattr(s_live, "workspace", None) or {}

            from app.services.agent_capabilities import interrupted_answer

            pieces: list[str] = []
            tool_events: list[dict] = []
            queue: asyncio.Queue = asyncio.Queue()

            async def on_token(text: str):
                await queue.put(("token", text))

            async def on_tool(item: dict):
                await queue.put(("tool", item))

            async def runner():
                try:
                    result = await chat_assistant.process_chat_message(
                        content,
                        stream_db,
                        history=history,
                        faq_items=items,
                        workspace=ws,
                        context=ctx,
                        session=s_live,
                        stream=True,
                        on_token=on_token,
                        on_tool=on_tool,
                    )
                    await queue.put(("result", result))
                except Exception as exc:
                    await queue.put(("exc", exc))

            task = asyncio.create_task(runner())
            result = None
            failed = None
            try:
                while True:
                    kind, payload = await queue.get()
                    if kind == "token":
                        pieces.append(payload)
                        yield f"data: {json.dumps({'type': 'token', 'text': payload}, ensure_ascii=False)}\n\n"
                    elif kind == "tool":
                        tool_events.append(payload)
                        yield f"data: {json.dumps({'type': 'tool', 'tool': payload.get('tool'), 'ok': payload.get('ok', True)}, ensure_ascii=False)}\n\n"
                    elif kind == "exc":
                        failed = payload
                        break
                    elif kind == "result":
                        result = payload
                        break
                if failed is not None:
                    reason = str(failed) or failed.__class__.__name__
                    result = {
                        "answer": interrupted_answer("".join(pieces), reason),
                        "mode": "error",
                        "metadata": {"stream_error": reason, "intent": "stream_error"},
                    }
                    yield f"data: {json.dumps({'type': 'error', 'message': reason}, ensure_ascii=False)}\n\n"
                else:
                    result = result or {}
                    streamed = bool(pieces) or bool((result.get("metadata") or {}).get("tokens_streamed"))
                    for item in (result.get("metadata") or {}).get("tool_trace") or []:
                        if any(ev.get("tool") == item.get("tool") for ev in tool_events):
                            continue
                        yield f"data: {json.dumps({'type': 'tool', 'tool': item.get('tool'), 'ok': item.get('ok', True)}, ensure_ascii=False)}\n\n"
                    stream_msgs = result.pop("stream_messages", None)
                    if stream_msgs and not streamed:
                        try:
                            async for tok in ai_svc.chat_completion_stream(stream_msgs, db=stream_db):
                                pieces.append(tok)
                                yield f"data: {json.dumps({'type': 'token', 'text': tok}, ensure_ascii=False)}\n\n"
                            result["answer"] = "".join(pieces)
                        except Exception as exc:
                            reason = str(exc) or exc.__class__.__name__
                            result["answer"] = interrupted_answer("".join(pieces), reason)
                            result["mode"] = "error"
                            meta = dict(result.get("metadata") or {})
                            meta["stream_error"] = reason
                            result["metadata"] = meta
                            yield f"data: {json.dumps({'type': 'error', 'message': reason}, ensure_ascii=False)}\n\n"
                    elif not streamed:
                        ans = result.get("answer") or ""
                        if ans:
                            pieces.append(ans)
                            yield f"data: {json.dumps({'type': 'token', 'text': ans}, ensure_ascii=False)}\n\n"
            finally:
                if not task.done():
                    task.cancel()

            payload = await _finalize_chat_message_turn(
                session_id, s_live, user_live, content, body, result, stream_db,
            )
            yield f"data: {json.dumps({'type': 'done', 'payload': payload}, ensure_ascii=False)}\n\n"
        finally:
            stream_db.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class ChatActionRequest(BaseModel):
    message_id: int | None = None
    card_id: str = ""
    action: str
    payload: dict = {}


class ImportFolderBody(BaseModel):
    folder_path: str
    label: str = "选择资质文件夹"


class WorkspaceFileBody(BaseModel):
    path: str
    content: str = ""
    encoding: str = "utf-8"


class WorkspaceTreeBody(BaseModel):
    path: str = ""


class ChatSessionWorkspacePatch(BaseModel):
    workspace_dir: str | None = None
    project_id: int | None = None


def _persist_assistant_turn(
    db: Session,
    s: ChatSession,
    user_content: str,
    result: dict,
    user_metadata: dict | None = None,
):
    meta = dict(result.get("metadata") or {})
    user_msg = ChatMessage(
        session_id=s.id,
        role="user",
        content=user_content,
        metadata_json=user_metadata or {},
    )
    db.add(user_msg)
    db.flush()
    bot_msg = ChatMessage(
        session_id=s.id,
        role="assistant",
        content=result.get("answer") or "",
        source=result.get("source") or "",
        matched_question=result.get("matched_question") or "",
        metadata_json=meta,
    )
    db.add(bot_msg)
    s.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user_msg)
    db.refresh(bot_msg)
    db.refresh(s)
    return user_msg, bot_msg


def _resolve_card_state(message: ChatMessage | None, card_id: str, action: str, label: str) -> None:
    """将卡片状态固化为 confirmed/cancelled，防止重复操作。"""
    if not message or not card_id:
        return
    meta = dict(getattr(message, "metadata_json", None) or {})
    cards = meta.get("cards") or []
    changed = False
    for card in cards:
        if card.get("id") == card_id and card.get("state") == "active":
            card["state"] = "cancelled" if action == "cancel_flow" else "confirmed"
            card["result_label"] = label
            changed = True
    if changed:
        meta["cards"] = cards
        message.metadata_json = meta
        flag_modified(message, "metadata_json")


@router.post("/chat/sessions/{session_id}/actions")
async def post_chat_action(session_id: int, body: ChatActionRequest, db: Session = Depends(get_db)):
    """卡片动作回调：驱动多轮流程状态机，返回用户操作消息与新的助手消息。"""
    from app.services import agent_flows

    s = get_session_or_404(db, session_id)
    acted_message = None
    if body.message_id:
        acted_message = (
            db.query(ChatMessage)
            .filter(ChatMessage.id == body.message_id, ChatMessage.session_id == s.id)
            .first()
        )

    user_label, result, _ws_updated = await agent_flows.handle_action(
        db, s, body.action, body.payload or {}
    )
    meta = dict(result.get("metadata") or {})

    if acted_message is not None:
        _resolve_card_state(acted_message, body.card_id, body.action, user_label)

    user_msg = None
    if user_label:
        user_msg = ChatMessage(session_id=s.id, role="user", content=user_label)
        db.add(user_msg)
        db.flush()

    bot_msg = ChatMessage(
        session_id=s.id,
        role="assistant",
        content=result.get("answer") or "",
        source=result.get("source") or "",
        matched_question=result.get("matched_question") or "",
        metadata_json=meta,
    )
    db.add(bot_msg)
    s.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(bot_msg)
    db.refresh(s)
    if user_msg is not None:
        db.refresh(user_msg)

    return {
        "session": session_to_dict(s),
        "user_message": message_to_dict(user_msg) if user_msg is not None else None,
        "assistant_message": message_to_dict(bot_msg),
        "acted_message": message_to_dict(acted_message) if acted_message is not None else None,
        "metadata": meta,
    }


@router.patch("/chat/sessions/{session_id}/workspace")
def patch_chat_session_workspace(
    session_id: int,
    body: ChatSessionWorkspacePatch,
    db: Session = Depends(get_db),
):
    from app.services.agent_workspace import validate_workspace_dir

    s = get_session_or_404(db, session_id)
    ws = dict(getattr(s, "workspace", None) or {})
    if body.workspace_dir is not None:
        raw = (body.workspace_dir or "").strip()
        if raw:
            ws["workspace_dir"] = validate_workspace_dir(raw)
        else:
            ws.pop("workspace_dir", None)
    if body.project_id is not None:
        pid = int(body.project_id or 0)
        if pid <= 0:
            ws.pop("project_id", None)
        else:
            p = db.query(TenderProject).filter(TenderProject.id == pid).first()
            if not p:
                raise HTTPException(404, "项目不存在")
            ws["project_id"] = pid
            if getattr(p, "workspace_dir", None):
                ws["workspace_dir"] = p.workspace_dir
            if p.template_id:
                ws["template_id"] = p.template_id
    s.workspace = ws
    s.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(s)
    return session_to_dict(s)


@router.get("/chat/sessions/{session_id}/workspace")
def get_chat_workspace(session_id: int, db: Session = Depends(get_db)):
    s = get_session_or_404(db, session_id)
    ws = getattr(s, "workspace", None) or {}
    doc_key = ws.get("draft_object_key") or ws.get("template_object_key")
    paragraphs = []
    if doc_key:
        data = storage.download_bytes(doc_key)
        preview = word.extract_preview(data, max_paragraphs=800)
        paragraphs = preview.get("paragraphs") or []
    return {
        "workspace": ws,
        "paragraphs": paragraphs,
        "pdf_preview_url": f"/api/chat/sessions/{session_id}/workspace/preview.pdf" if doc_key else None,
        "download_url": f"/api/chat/sessions/{session_id}/workspace/download" if doc_key else None,
    }


@router.get("/chat/sessions/{session_id}/workspace/preview.pdf")
def chat_workspace_preview_pdf(session_id: int, db: Session = Depends(get_db)):
    s = get_session_or_404(db, session_id)
    ws = getattr(s, "workspace", None) or {}
    doc_key = ws.get("draft_object_key") or ws.get("template_object_key")
    if not doc_key:
        raise HTTPException(404, "工作区暂无文档")
    data = storage.download_bytes(doc_key)
    pdf_bytes = word.convert_docx_to_pdf(data)
    fname = ws.get("filename") or "workspace.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{quote(fname.replace(".docx", ".pdf"))}"'},
    )


@router.get("/chat/sessions/{session_id}/workspace/download")
def chat_workspace_download(session_id: int, db: Session = Depends(get_db)):
    s = get_session_or_404(db, session_id)
    ws = getattr(s, "workspace", None) or {}
    doc_key = ws.get("draft_object_key") or ws.get("template_object_key")
    if not doc_key:
        raise HTTPException(404, "工作区暂无文档")
    data = storage.download_bytes(doc_key)
    fname = ws.get("filename") or "document.docx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{quote(fname)}"'},
    )


@router.post("/chat/sessions/{session_id}/workspace/paragraph")
async def update_workspace_paragraph(
    session_id: int,
    body: dict,
    db: Session = Depends(get_db),
):
    """用户手动编辑某段落。"""
    s = get_session_or_404(db, session_id)
    ws = dict(getattr(s, "workspace", None) or {})
    doc_key = ws.get("draft_object_key") or ws.get("template_object_key")
    if not doc_key:
        raise HTTPException(400, "请先上传模板文档")
    paragraph_index = int(body.get("paragraph_index", -1))
    new_text = str(body.get("text") or "")
    data = storage.download_bytes(doc_key)
    new_bytes = word.replace_paragraph_text(data, paragraph_index, new_text)
    new_key = f"chat/{session_id}/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_manual.docx"
    storage.upload_bytes(new_key, new_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    ws["draft_object_key"] = new_key
    ws["version"] = int(ws.get("version") or 0) + 1
    ws["last_action"] = "manual_edit"
    s.workspace = ws
    s.updated_at = datetime.utcnow()
    db.commit()
    preview = word.extract_preview(new_bytes, max_paragraphs=800)
    return {"workspace": ws, "paragraphs": preview.get("paragraphs") or []}


@router.post("/chat/sessions/{session_id}/upload")
async def upload_chat_file(
    session_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """上传文件到对话上下文（如标书 DOCX），并返回引导信息。"""
    s = get_session_or_404(db, session_id)
    data = await file.read()
    if not data:
        raise HTTPException(400, "文件为空")
    fname = file.filename or "upload.bin"
    key = f"chat/{session_id}/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{fname}"
    content_type = file.content_type or "application/octet-stream"
    storage.upload_bytes(key, data, content_type)

    is_docx = fname.lower().endswith(".docx")
    if is_docx:
        placeholders = word.extract_placeholders(data)
        preview = word.extract_preview(data, max_paragraphs=30)
        para_count = len(preview.get("paragraphs") or [])
        ws = dict(getattr(s, "workspace", None) or {})
        ws["template_object_key"] = key
        ws["draft_object_key"] = key
        ws["filename"] = fname
        ws["version"] = 1
        ws["last_action"] = "upload"
        ws["awaiting_file_intent"] = True
        ws["upload_meta"] = {
            "placeholder_count": len(placeholders),
            "paragraph_count": para_count,
            "size_kb": len(data) // 1024,
        }
        s.workspace = ws
        answer = (
            f"已收到并阅读文档「{fname}」（{len(data) // 1024} KB，约 {para_count} 段）。\n\n"
            f"检测到 {len(placeholders)} 个占位符。\n\n"
            "**在您明确下达指令前，我不会自动修改文档。** 请告诉我您希望进行哪种操作：\n"
            "1. 工程化为可复用模板\n"
            "2. 结合企业信息按此格式编写招标标书\n"
            "3. 在文档中批量替换指定文字\n"
            "4. 仅作为工作区文档预览/编辑\n\n"
            "也可直接用自然语言描述您的需求。"
        )
        actions = [
            {"type": "link", "label": "下载当前文档", "url": f"/api/chat/sessions/{session_id}/workspace/download"},
        ]
        uid = uuid.uuid4().hex[:8]
        cards = [
            {
                "id": f"upload-tpl-{uid}",
                "type": "confirm",
                "title": "生成标书模板",
                "state": "active",
                "payload": {
                    "message": "识别项目名称、招标人等字段并替换为占位符，生成可复用模板。",
                    "confirm_label": "创建模板",
                    "cancel_label": "暂不",
                    "confirm_action": "start_template_create",
                    "cancel_action": "dismiss_card",
                },
            },
            {
                "id": f"upload-gen-{uid}",
                "type": "confirm",
                "title": "按此格式编写标书",
                "state": "active",
                "payload": {
                    "message": "将结合系统内企业信息，按当前文档版式生成招标标书（需补充编写要求）。",
                    "confirm_label": "开始编写",
                    "cancel_label": "暂不",
                    "confirm_action": "dismiss_card",
                    "cancel_action": "dismiss_card",
                },
            },
        ]
    else:
        answer = f"已收到文件「{fname}」。当前支持 DOCX 标书文件的模板化分析，其他格式可作为参考资料。"
        actions = [{"type": "link", "label": "前往数据管理", "url": "/admin"}]
        cards = []

    user_msg = ChatMessage(
        session_id=s.id,
        role="user",
        content=f"[上传文件] {fname}",
        metadata_json={
            "attachment": {"filename": fname, "object_key": key, "size": len(data)},
            "attachments": [{"name": fname, "kind": "file", "type": _file_type_label(fname)}],
        },
    )
    db.add(user_msg)
    bot_msg = ChatMessage(
        session_id=s.id,
        role="assistant",
        content=answer,
        metadata_json={"intent": "file_upload", "actions": actions, "attachment_key": key, "cards": cards},
    )
    db.add(bot_msg)
    s.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(user_msg)
    db.refresh(bot_msg)
    db.refresh(s)
    return {
        "session": session_to_dict(s),
        "user_message": message_to_dict(user_msg),
        "assistant_message": message_to_dict(bot_msg),
        "filename": fname,
        "object_key": key,
        "workspace": getattr(s, "workspace", None) or {},
    }


@router.post("/chat/sessions/{session_id}/import-folder")
async def post_chat_import_folder(
    session_id: int, body: ImportFolderBody, db: Session = Depends(get_db),
):
    from app.services import agent_flows

    s = get_session_or_404(db, session_id)
    folder = (body.folder_path or "").strip()
    if not folder:
        raise HTTPException(400, "folder_path 不能为空")
    result = await agent_flows.start_qual_folder_import(db, s, folder)
    label = (body.label or "选择资质文件夹").strip()
    folder_name = Path(folder).name or label
    user_msg, bot_msg = _persist_assistant_turn(
        db,
        s,
        f"[{label}] {folder}",
        result,
        user_metadata={
            "attachments": [{"name": folder_name[:180], "kind": "folder", "type": "文件夹"}],
        },
    )
    return {
        "session": session_to_dict(s),
        "user_message": message_to_dict(user_msg),
        "assistant_message": message_to_dict(bot_msg),
        "metadata": dict(result.get("metadata") or {}),
    }


@router.post("/chat/sessions/{session_id}/upload-batch")
async def upload_chat_files_batch(
    session_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    """批量上传附件；多份资质类文件时走文件夹导入确认流程。"""
    import zipfile
    from io import BytesIO

    from app.services import agent_flows
    from app.services.agent_qual_folder import SCAN_EXTENSIONS
    from app.services.agent_workspace import chat_staging_dir

    s = get_session_or_404(db, session_id)
    if not files:
        raise HTTPException(400, "请至少选择一个文件")

    batch_id = datetime.utcnow().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:6]
    staging = chat_staging_dir(session_id, batch_id)

    saved_names: list[str] = []
    for upload in files:
        data = await upload.read()
        if not data:
            continue
        fname = upload.filename or "upload.bin"
        if fname.lower().endswith(".zip") and len(files) == 1:
            with zipfile.ZipFile(BytesIO(data)) as zf:
                for info in zf.infolist():
                    if info.is_dir() or info.filename.startswith("__MACOSX"):
                        continue
                    base = Path(info.filename).name
                    if not base or base.startswith("."):
                        continue
                    ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
                    if ext and ext not in SCAN_EXTENSIONS and ext != "zip":
                        continue
                    target = staging / base
                    target.write_bytes(zf.read(info))
                    saved_names.append(base)
        else:
            safe = Path(fname).name
            (staging / safe).write_bytes(data)
            saved_names.append(safe)

    if not saved_names:
        raise HTTPException(400, "未保存任何有效文件")

    docx_only = len(saved_names) == 1 and saved_names[0].lower().endswith(".docx")
    if docx_only:
        data = (staging / saved_names[0]).read_bytes()
        fname = saved_names[0]

        class _BytesUpload:
            def __init__(self, name: str, payload: bytes):
                self.filename = name
                self._payload = payload

            async def read(self):
                return self._payload

        return await upload_chat_file(session_id, _BytesUpload(fname, data), db)

    qual_count = sum(
        1 for n in saved_names
        if (("." in n and n.rsplit(".", 1)[-1].lower() in SCAN_EXTENSIONS) or n.lower().endswith(".docx"))
    )
    names_label = "、".join(saved_names[:8]) + ("…" if len(saved_names) > 8 else "")
    user_label = f"[上传 {len(saved_names)} 个文件] {names_label}"

    if qual_count >= 1:
        result = await agent_flows.start_qual_folder_import(db, s, str(staging))
        answer_prefix = f"已接收 **{len(saved_names)}** 个文件并暂存。\n\n"
        result["answer"] = answer_prefix + (result.get("answer") or "")
    else:
        result = {
            "answer": (
                f"已接收 **{len(saved_names)}** 个文件：{names_label}\n\n"
                "当前批次未识别为资质包材料；如需导入资质库，请使用「整个文件夹」或上传 pdf/docx/图片等资质文件。"
            ),
            "metadata": {"intent": "file_upload_batch", "staging_dir": str(staging), "files": saved_names},
        }

    user_msg, bot_msg = _persist_assistant_turn(
        db,
        s,
        user_label,
        result,
        user_metadata={
            "attachments": [
                {"name": name[:180], "kind": "file", "type": _file_type_label(name)}
                for name in saved_names[:24]
            ],
        },
    )
    return {
        "session": session_to_dict(s),
        "user_message": message_to_dict(user_msg),
        "assistant_message": message_to_dict(bot_msg),
        "metadata": dict(result.get("metadata") or {}),
        "workspace": getattr(s, "workspace", None) or {},
    }


@router.post("/chat/sessions/{session_id}/workspace/tree")
def list_session_workspace_tree(
    session_id: int, body: WorkspaceTreeBody, db: Session = Depends(get_db),
):
    from app.services import agent_tools
    from app.services.agent_qual_folder import PathNotAllowedError

    s = get_session_or_404(db, session_id)
    try:
        return agent_tools.list_workspace_dir(db, s, body.path or "")
    except PathNotAllowedError as err:
        raise HTTPException(400, str(err)) from err
    except NotADirectoryError as err:
        raise HTTPException(400, str(err)) from err
    except FileNotFoundError as err:
        raise HTTPException(404, str(err)) from err


@router.post("/chat/sessions/{session_id}/workspace/files/read")
def read_session_workspace_file(
    session_id: int, body: WorkspaceFileBody, db: Session = Depends(get_db),
):
    from app.services import agent_tools
    from app.services.agent_qual_folder import PathNotAllowedError

    s = get_session_or_404(db, session_id)
    try:
        data = agent_tools.read_workspace_file(db, s, body.path)
    except PathNotAllowedError as err:
        raise HTTPException(400, str(err)) from err
    except FileNotFoundError as err:
        raise HTTPException(404, str(err)) from err
    return data


@router.post("/chat/sessions/{session_id}/workspace/files/write")
def write_session_workspace_file(
    session_id: int, body: WorkspaceFileBody, db: Session = Depends(get_db),
):
    from app.services import agent_tools
    from app.services.agent_qual_folder import PathNotAllowedError

    s = get_session_or_404(db, session_id)
    if not (body.path or "").strip():
        raise HTTPException(400, "path 不能为空")
    try:
        data = agent_tools.write_workspace_file(
            db, s, body.path.strip(), body.content or "", encoding=body.encoding or "utf-8",
        )
    except PathNotAllowedError as err:
        raise HTTPException(400, str(err)) from err
    return data


@router.post("/chatbot/ask")
async def chatbot_ask(body: ChatRequest, db: Session = Depends(get_db)):
    faqs = db.query(FAQItem).all()
    items = [
        {"question": f.question, "answer": f.answer, "category": f.category, "source": f.source}
        for f in faqs
    ]
    history = []
    session = None
    if body.session_id:
        session = get_session_or_404(db, body.session_id)
        history = [{"role": m.role, "content": m.content} for m in (session.messages or [])]
        user_msg = ChatMessage(session_id=session.id, role="user", content=body.question.strip())
        db.add(user_msg)
        db.flush()

    result = await ai_svc.answer_faq(body.question, items, db=db, history=history)

    if session:
        bot_msg = ChatMessage(
            session_id=session.id,
            role="assistant",
            content=result.get("answer") or "",
            source=result.get("source") or "",
            matched_question=result.get("matched_question") or "",
        )
        db.add(bot_msg)
        if session.title in ("新对话", ""):
            q = body.question.strip()
            session.title = q[:40] + ("…" if len(q) > 40 else "")
        session.updated_at = datetime.utcnow()
        db.commit()
        result["session_id"] = session.id

    return result


@router.get("/chatbot/faqs")
def list_faqs(db: Session = Depends(get_db)):
    items = db.query(FAQItem).order_by(FAQItem.id).all()
    return [
        {"id": f.id, "category": f.category, "question": f.question, "answer": f.answer, "source": f.source}
        for f in items
    ]


@router.post("/templates/upload")
async def upload_template(file: UploadFile = File(...), db: Session = Depends(get_db)):
    data = await file.read()
    name = file.filename or "uploaded.docx"
    key = f"templates/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{name}"
    storage.upload_bytes(
        key, data,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    placeholders = word.extract_placeholders(data)
    structure = word.extract_structure(data)
    tpl = Template(
        name=name.rsplit(".", 1)[0],
        description="用户上传模板",
        object_key=key,
        placeholders={"list": placeholders, "structure": structure},
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return {"id": tpl.id, "name": tpl.name, "placeholders": placeholders}
