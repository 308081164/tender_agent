from datetime import datetime
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.database import get_db
from app.models import (
    Template, Qualification, TenderProject, ProjectSnapshot, ProjectExport,
    ChecklistItem, FAQItem, FieldDef, ChatSession, ChatMessage,
)
from app.services import storage, word, checklist as checklist_svc, ai as ai_svc
from app.services import settings_svc
from app.services import pdf_convert

router = APIRouter()

STEP_NAMES = {
    1: "选择起点",
    2: "信息录入",
    3: "AI审核",
    4: "插入资质",
    5: "条目校验",
    6: "导出Word",
}


def _fill_field_defaults(db: Session, fields: dict | None) -> dict:
    """用企业档案 / 字段默认值补齐空缺，避免前端局部保存冲掉企业预填。"""
    from app.models import CompanyProfile

    result = dict(fields or {})
    company = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    for fd in db.query(FieldDef).order_by(FieldDef.sort_order).all():
        if result.get(fd.key):
            continue
        val = ""
        cf = getattr(fd, "company_field", "") or ""
        if getattr(fd, "is_company_default", False) and company and cf:
            val = getattr(company, cf, "") or ""
        if not val:
            val = fd.default_value or ""
        if val:
            result[fd.key] = val
    return result


class ProjectCreate(BaseModel):
    title: str = "未命名标书"
    source_type: str = "template"
    template_id: int | None = None


class SettingsUpdate(BaseModel):
    deepseek_api_key: str | None = None
    deepseek_base_url: str | None = None
    deepseek_model: str | None = None
    qwen_api_key: str | None = None
    qwen_base_url: str | None = None
    qwen_model: str | None = None
    preferred_provider: str | None = None
    clear_deepseek_api_key: bool = False
    clear_qwen_api_key: bool = False


class TestProviderRequest(BaseModel):
    provider: str  # deepseek | qwen



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


class ChatMessageCreate(BaseModel):
    content: str


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
    step_name = STEP_NAMES.get(p.current_step, f"步骤{p.current_step}")
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
        "progress": min(max(p.current_step or 1, 1), 6) / 6,
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
    if body.provider not in ("deepseek", "qwen"):
        raise HTTPException(400, "provider 仅支持 deepseek 或 qwen")
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
    items = q.order_by(Template.kind, Template.id).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "placeholders": t.placeholders,
            "is_history": bool((t.placeholders or {}).get("is_history")) or t.kind == "history",
            "template_code": getattr(t, "template_code", "common") or "common",
            "kind": getattr(t, "kind", "template") or "template",
            "enabled": getattr(t, "enabled", True),
        }
        for t in items
    ]


@router.get("/fields")
def list_fields(template_code: str | None = None, db: Session = Depends(get_db)):
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
    rows = db.query(Qualification.category).distinct().all()
    return [r[0] for r in rows]


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
    project = TenderProject(
        title=body.title,
        source_type=body.source_type,
        template_id=body.template_id,
        current_step=1,
        fields={},
        chapters={},
        inserted_quals=[],
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    save_snapshot(db, project, 1)
    return project_to_dict(project)


@router.get("/projects/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db)):
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    return project_to_dict(p)


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
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise HTTPException(404, "项目不存在")
    p.fields = _fill_field_defaults(db, body.fields)
    flag_modified(p, "fields")
    if p.fields.get("project_name"):
        p.title = str(p.fields["project_name"])
    if body.confirm:
        p.current_step = max(p.current_step, 3)
    p.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(p)
    save_snapshot(db, p, 2 if body.confirm else max(p.current_step, 2))
    return project_to_dict(p)


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
    chapters = dict(p.chapters or {})
    for key in keys:
        chapters[key] = await ai_svc.generate_chapter(key, p.fields or {}, db=db, company_context=ctx)
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
        chapter_key, p.fields or {}, db=db, company_context=_company_context(db)
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


@router.get("/projects/{project_id}/export")
def export_project(project_id: int, db: Session = Depends(get_db)):
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
    doc_bytes = word.render_document(
        tpl_bytes,
        export_fields,
        chapters,
        highlight=True,
        source_snapshot=snap if getattr(tpl, "kind", "") == "history" else None,
    )
    # 嵌入资质附件（图片/docx/pdf）
    if quals:
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
                "data": data,
            })
        try:
            doc_bytes = word.embed_qualifications(doc_bytes, qual_files)
        except Exception as e:
            print(f"[export] embed quals warn: {e}")

    fields = export_fields
    required = ["project_name", "tender_no", "tenderer", "project_manager"]
    if fields.get("bid_amount_upper") or fields.get("bid_amount"):
        pass
    else:
        required.append("bid_amount_upper")
    validation = word.validate_export(doc_bytes, required, fields)
    if validation["status"] == "red":
        raise HTTPException(400, detail={"message": "导出格式校验未通过", "validation": validation})

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
    save_snapshot(db, p, 6)

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
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        "message_count": len(s.messages or []),
    }
    if include_messages:
        data["messages"] = [message_to_dict(m) for m in (s.messages or [])]
    return data


def message_to_dict(m: ChatMessage) -> dict:
    return {
        "id": m.id,
        "session_id": m.session_id,
        "role": m.role,
        "content": m.content,
        "source": m.source or "",
        "matched_question": m.matched_question or "",
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


@router.get("/chat/sessions/{session_id}/messages")
def list_chat_messages(session_id: int, db: Session = Depends(get_db)):
    s = get_session_or_404(db, session_id)
    return [message_to_dict(m) for m in (s.messages or [])]


@router.post("/chat/sessions/{session_id}/messages")
async def post_chat_message(session_id: int, body: ChatMessageCreate, db: Session = Depends(get_db)):
    s = get_session_or_404(db, session_id)
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(400, "消息不能为空")

    user_msg = ChatMessage(session_id=s.id, role="user", content=content)
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
    result = await ai_svc.answer_faq(content, items, db=db, history=history)

    bot_msg = ChatMessage(
        session_id=s.id,
        role="assistant",
        content=result.get("answer") or "",
        source=result.get("source") or "",
        matched_question=result.get("matched_question") or "",
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
    }


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
