"""基础数据管理 CRUD"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import and_, case, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    CompanyProfile,
    FieldDef,
    Template,
    Qualification,
    ChecklistItem,
    FAQItem,
)
from app.services import storage, word, pdf_convert, template_detect
from app.seed.import_customer_pack import run_import

router = APIRouter(prefix="/admin", tags=["admin"])


def _paginate(query, page: int | None, page_size: int, serialize):
    if page is None:
        return [serialize(x) for x in query.all()]
    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [serialize(x) for x in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _qual_status(q: Qualification) -> tuple[bool, bool]:
    today = datetime.utcnow().date()
    if q.is_long_term or not q.valid_to:
        return False, False
    expired = q.valid_to < today
    expiring = (not expired) and (q.valid_to - today).days <= 90
    return expired, expiring


def _qual_status_rank_expr(today: date | None = None):
    """0=过期, 1=临期, 2=有有效期且正常, 3=长期/无有效期"""
    today = today or datetime.utcnow().date()
    threshold = today + timedelta(days=90)
    has_date = and_(Qualification.is_long_term.is_(False), Qualification.valid_to.isnot(None))
    return case(
        (and_(has_date, Qualification.valid_to < today), 0),
        (and_(has_date, Qualification.valid_to >= today, Qualification.valid_to <= threshold), 1),
        (has_date, 2),
        else_=3,
    )


def _apply_qual_status_filter(query, status: str, today: date | None = None):
    if not status:
        return query
    today = today or datetime.utcnow().date()
    threshold = today + timedelta(days=90)
    has_date = and_(Qualification.is_long_term.is_(False), Qualification.valid_to.isnot(None))
    if status == "expired":
        return query.filter(and_(has_date, Qualification.valid_to < today))
    if status == "expiring":
        return query.filter(and_(has_date, Qualification.valid_to >= today, Qualification.valid_to <= threshold))
    if status == "normal":
        return query.filter(or_(
            Qualification.is_long_term.is_(True),
            Qualification.valid_to.is_(None),
            and_(has_date, Qualification.valid_to > threshold),
        ))
    return query


def _order_qualifications(query, sort_by: str, sort_dir: str, today: date | None = None):
    today = today or datetime.utcnow().date()
    direction = (sort_dir or "asc").lower()
    desc = direction == "desc"

    if sort_by == "valid_to":
        col = Qualification.valid_to
        order = col.desc().nulls_last() if desc else col.asc().nulls_last()
        return query.order_by(order, Qualification.sort_order, Qualification.id)

    if sort_by == "status":
        rank = _qual_status_rank_expr(today)
        order = rank.desc() if desc else rank.asc()
        valid_order = Qualification.valid_to.asc().nulls_last()
        return query.order_by(order, valid_order, Qualification.sort_order, Qualification.id)

    return query.order_by(Qualification.sort_order, Qualification.id)


def _delete_minio_key(object_key: str | None) -> None:
    if object_key:
        try:
            storage.delete_object(object_key)
        except Exception:
            pass
    if object_key:
        pdf_key = pdf_convert.pdf_object_key(object_key)
        if pdf_key != object_key:
            try:
                storage.delete_object(pdf_key)
            except Exception:
                pass


def _get_template_or_404(db: Session, template_id: int) -> Template:
    t = db.query(Template).filter(Template.id == template_id).first()
    if not t:
        raise HTTPException(404, "模板不存在")
    return t


def _ensure_template_pdf(t: Template) -> tuple[bytes, str, bool]:
    if not t.object_key:
        raise HTTPException(404, "模板文件不存在")
    pdf_key = pdf_convert.pdf_object_key(t.object_key)
    if storage.object_exists(pdf_key):
        return storage.download_bytes(pdf_key), pdf_key, True
    try:
        doc_bytes = storage.download_bytes(t.object_key)
    except Exception as err:
        raise HTTPException(404, f"模板文件不存在：{err}") from err
    try:
        pdf_bytes = pdf_convert.convert_docx_to_pdf(doc_bytes)
    except RuntimeError as err:
        raise HTTPException(503, str(err)) from err
    storage.upload_bytes(pdf_key, pdf_bytes, "application/pdf")
    return pdf_bytes, pdf_key, False


def company_to_dict(c: CompanyProfile | None) -> dict:
    if not c:
        return {}
    return {
        "id": c.id,
        "full_name": c.full_name,
        "short_name": c.short_name,
        "credit_code": c.credit_code,
        "register_address": c.register_address,
        "office_address": c.office_address,
        "legal_name": c.legal_name,
        "legal_gender": c.legal_gender,
        "legal_age": c.legal_age,
        "legal_title": c.legal_title,
        "legal_id_no": c.legal_id_no,
        "registered_capital": c.registered_capital,
        "founded_date": c.founded_date,
        "phone": c.phone,
        "fax": c.fax,
        "email": c.email,
        "website": c.website,
        "postcode": c.postcode,
        "bank_name": c.bank_name,
        "bank_account": c.bank_account,
        "recent_revenue": c.recent_revenue,
        "related_companies": c.related_companies,
        "intro": c.intro,
        "business_scope": c.business_scope,
        "qual_overview": c.qual_overview,
        "typical_projects": c.typical_projects,
        "ai_style_notes": c.ai_style_notes,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


class CompanyIn(BaseModel):
    full_name: str = ""
    short_name: str = ""
    credit_code: str = ""
    register_address: str = ""
    office_address: str = ""
    legal_name: str = ""
    legal_gender: str = ""
    legal_age: str = ""
    legal_title: str = ""
    legal_id_no: str = ""
    registered_capital: str = ""
    founded_date: str = ""
    phone: str = ""
    fax: str = ""
    email: str = ""
    website: str = ""
    postcode: str = ""
    bank_name: str = ""
    bank_account: str = ""
    recent_revenue: str = ""
    related_companies: str = "无"
    intro: str = ""
    business_scope: str = ""
    qual_overview: str = ""
    typical_projects: str = ""
    ai_style_notes: str = ""


@router.get("/company")
def get_company(db: Session = Depends(get_db)):
    c = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    if not c:
        c = CompanyProfile(id=1)
        db.add(c)
        db.commit()
        db.refresh(c)
    return company_to_dict(c)


@router.put("/company")
def update_company(body: CompanyIn, db: Session = Depends(get_db)):
    c = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    if not c:
        c = CompanyProfile(id=1)
        db.add(c)
    # 仅更新请求中显式给出的字段，避免部分 PUT 清空其它档案项
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    c.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(c)
    return company_to_dict(c)


class FieldIn(BaseModel):
    name: str
    key: str
    field_type: str = "文本"
    required: bool = True
    default_value: str = ""
    options: str = ""
    module: str = ""
    validation: str = ""
    template_code: str = "common"
    sort_order: int = 0
    is_company_default: bool = False
    company_field: str = ""
    desensitized: bool = False


def field_dict(f: FieldDef) -> dict:
    return {
        "id": f.id,
        "name": f.name,
        "key": f.key,
        "field_type": f.field_type,
        "required": f.required,
        "default_value": f.default_value,
        "options": f.options,
        "module": f.module,
        "validation": f.validation,
        "template_code": getattr(f, "template_code", "common") or "common",
        "sort_order": getattr(f, "sort_order", 0) or 0,
        "is_company_default": getattr(f, "is_company_default", False),
        "company_field": getattr(f, "company_field", "") or "",
        "desensitized": getattr(f, "desensitized", False),
    }


@router.get("/fields")
def admin_list_fields(
    q: str = "",
    template_code: str = "",
    page: int | None = None,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    query = db.query(FieldDef)
    if template_code:
        query = query.filter(FieldDef.template_code.in_([template_code, "common"]))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(FieldDef.name.ilike(like), FieldDef.key.ilike(like)))
    query = query.order_by(FieldDef.sort_order, FieldDef.id)
    return _paginate(query, page, page_size, field_dict)


@router.get("/fields/{field_id}")
def get_field(field_id: int, db: Session = Depends(get_db)):
    f = db.query(FieldDef).filter(FieldDef.id == field_id).first()
    if not f:
        raise HTTPException(404, "字段不存在")
    return field_dict(f)


@router.post("/fields")
def create_field(body: FieldIn, db: Session = Depends(get_db)):
    if db.query(FieldDef).filter(FieldDef.key == body.key).first():
        raise HTTPException(400, "字段 key 已存在")
    f = FieldDef(**body.model_dump())
    db.add(f)
    db.commit()
    db.refresh(f)
    return field_dict(f)


@router.put("/fields/{field_id}")
def update_field(field_id: int, body: FieldIn, db: Session = Depends(get_db)):
    f = db.query(FieldDef).filter(FieldDef.id == field_id).first()
    if not f:
        raise HTTPException(404, "字段不存在")
    other = db.query(FieldDef).filter(FieldDef.key == body.key, FieldDef.id != field_id).first()
    if other:
        raise HTTPException(400, "字段 key 已存在")
    for k, v in body.model_dump().items():
        setattr(f, k, v)
    db.commit()
    db.refresh(f)
    return field_dict(f)


@router.delete("/fields/{field_id}")
def delete_field(field_id: int, db: Session = Depends(get_db)):
    f = db.query(FieldDef).filter(FieldDef.id == field_id).first()
    if not f:
        raise HTTPException(404, "字段不存在")
    db.delete(f)
    db.commit()
    return {"ok": True}


def tpl_dict(t: Template) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "description": t.description,
        "object_key": t.object_key,
        "placeholders": t.placeholders or {},
        "template_code": getattr(t, "template_code", "common") or "common",
        "kind": getattr(t, "kind", "template") or "template",
        "enabled": getattr(t, "enabled", True),
        "source_snapshot": getattr(t, "source_snapshot", {}) or {},
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


class TemplateMetaIn(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    template_code: Optional[str] = None
    kind: Optional[str] = None
    enabled: Optional[bool] = None
    source_snapshot: Optional[dict] = None


@router.get("/templates")
def admin_list_templates(
    q: str = "",
    kind: str = "",
    template_code: str = "",
    enabled: str = "",
    page: int | None = None,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    query = db.query(Template)
    if kind:
        query = query.filter(Template.kind == kind)
    if template_code:
        query = query.filter(Template.template_code == template_code)
    if enabled == "true":
        query = query.filter(Template.enabled.is_(True))
    elif enabled == "false":
        query = query.filter(Template.enabled.is_(False))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Template.name.ilike(like), Template.description.ilike(like)))
    query = query.order_by(Template.kind, Template.id.desc())
    return _paginate(query, page, page_size, tpl_dict)


@router.get("/templates/{template_id}")
def get_template(template_id: int, db: Session = Depends(get_db)):
    t = db.query(Template).filter(Template.id == template_id).first()
    if not t:
        raise HTTPException(404, "模板不存在")
    return tpl_dict(t)


@router.get("/templates/{template_id}/download")
def download_template(template_id: int, db: Session = Depends(get_db)):
    t = _get_template_or_404(db, template_id)
    if not t.object_key:
        raise HTTPException(404, "模板文件不存在")
    data = storage.download_bytes(t.object_key)
    fname = (t.name or "template").replace('"', "") + ".docx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"},
    )


@router.get("/templates/{template_id}/preview")
def preview_template(template_id: int, db: Session = Depends(get_db)):
    """返回模板结构化正文预览 + PDF 预览地址。"""
    t = _get_template_or_404(db, template_id)
    if not t.object_key:
        raise HTTPException(404, "模板文件不存在")
    try:
        doc_bytes = storage.download_bytes(t.object_key)
    except Exception as err:
        raise HTTPException(404, f"模板文件不存在：{err}") from err
    structured = word.extract_preview(doc_bytes, max_paragraphs=800)
    placeholders = (t.placeholders or {}).get("list") or []
    return {
        "template_id": t.id,
        "name": t.name,
        "kind": getattr(t, "kind", "template") or "template",
        "template_code": getattr(t, "template_code", "common") or "common",
        "format": "structured",
        "pdf_preview_url": f"/api/admin/templates/{template_id}/preview.pdf",
        "pdf_available": pdf_convert.pdf_conversion_available(),
        "pdf_engine": pdf_convert.get_pdf_engine(),
        "headings": structured.get("headings") or [],
        "paragraphs": structured.get("paragraphs") or [],
        "truncated": bool(structured.get("truncated")),
        "placeholder_count": len(placeholders),
        "placeholders": placeholders[:60],
    }


@router.get("/templates/{template_id}/preview.pdf")
def preview_template_pdf(template_id: int, db: Session = Depends(get_db)):
    """高保真 PDF 分页预览（Aspose / LibreOffice，结果缓存 MinIO）。"""
    t = _get_template_or_404(db, template_id)
    pdf_bytes, _pdf_key, _cached = _ensure_template_pdf(t)
    pdf_name = (t.name or "template").replace('"', "") + ".pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename=\"preview.pdf\"; filename*=UTF-8''{quote(pdf_name)}",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.put("/templates/{template_id}")
def update_template(template_id: int, body: TemplateMetaIn, db: Session = Depends(get_db)):
    t = db.query(Template).filter(Template.id == template_id).first()
    if not t:
        raise HTTPException(404, "模板不存在")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(t, k, v)
    db.commit()
    db.refresh(t)
    return tpl_dict(t)


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, db: Session = Depends(get_db)):
    t = db.query(Template).filter(Template.id == template_id).first()
    if not t:
        raise HTTPException(404, "模板不存在")
    _delete_minio_key(t.object_key)
    db.delete(t)
    db.commit()
    return {"ok": True}


@router.post("/templates/upload")
async def admin_upload_template(
    file: UploadFile = File(...),
    name: str = "",
    template_code: str = "common",
    kind: str = "template",
    db: Session = Depends(get_db),
):
    data = await file.read()
    fname = file.filename or "uploaded.docx"
    key = f"templates/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{fname}"
    storage.upload_bytes(
        key, data, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    ph = word.extract_placeholders(data)
    t = Template(
        name=name or fname,
        description="管理端上传",
        object_key=key,
        placeholders={"list": ph},
        template_code=template_code,
        kind=kind,
        enabled=True,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return tpl_dict(t)


class PlaceholderMappingIn(BaseModel):
    key: str
    original_text: str
    approved: bool = True
    action: str = "replace"  # replace | keep
    field_name: str = ""


class ApplyPlaceholdersIn(BaseModel):
    mappings: list[PlaceholderMappingIn]
    kind: str | None = None
    set_enabled: bool = True


class PreviewMappingsIn(BaseModel):
    mappings: list[PlaceholderMappingIn]


@router.post("/templates/{template_id}/preview-mappings")
def preview_template_mappings(
    template_id: int,
    body: PreviewMappingsIn,
    db: Session = Depends(get_db),
):
    """预览映射效果（不写入文档），用于工程化编辑工作台。"""
    t = _get_template_or_404(db, template_id)
    if not t.object_key:
        raise HTTPException(400, "模板文件不存在")
    data = storage.download_bytes(t.object_key)
    preview = word.extract_preview(data, max_paragraphs=800)
    mappings = [m.model_dump() for m in body.mappings]
    paragraphs = word.simulate_mapping_preview(preview.get("paragraphs") or [], mappings)
    approved = [m for m in mappings if m.get("approved", True) and m.get("action", "replace") != "keep"]
    return {
        "paragraphs": paragraphs,
        "approved_count": len(approved),
        "placeholder_keys": sorted({m.get("key") for m in approved if m.get("key")}),
    }


@router.post("/templates/{template_id}/detect-placeholders")
async def detect_template_placeholders(template_id: int, db: Session = Depends(get_db)):
    """使用 LLM + 规则从完整标书中识别可模板化的字段原文。"""
    t = _get_template_or_404(db, template_id)
    if not t.object_key:
        raise HTTPException(400, "模板文件不存在")
    data = storage.download_bytes(t.object_key)
    field_defs = [
        {
            "key": f.key,
            "name": f.name,
            "field_type": f.field_type,
            "module": f.module,
        }
        for f in db.query(FieldDef).order_by(FieldDef.sort_order.asc()).all()
    ]
    result = await template_detect.detect_placeholder_candidates(data, field_defs, db=db)
    result["template_id"] = t.id
    result["template_name"] = t.name
    return result


@router.post("/templates/{template_id}/apply-placeholders")
async def apply_template_placeholders(
    template_id: int,
    body: ApplyPlaceholdersIn,
    db: Session = Depends(get_db),
):
    """将确认的映射应用到 DOCX，替换为 {{key}} 并更新模板元数据。"""
    t = _get_template_or_404(db, template_id)
    if not t.object_key:
        raise HTTPException(400, "模板文件不存在")
    data = storage.download_bytes(t.object_key)
    mappings = [m.model_dump() for m in body.mappings]
    new_bytes, snapshot, placeholders = template_detect.apply_placeholder_mappings(data, mappings)
    new_key = f"templates/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_engineered_{t.name}.docx"
    storage.upload_bytes(
        new_key,
        new_bytes,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    old_key = t.object_key
    t.object_key = new_key
    t.placeholders = {"list": placeholders, "detected": True}
    t.source_snapshot = {**(t.source_snapshot or {}), **snapshot}
    if body.kind:
        t.kind = body.kind
    if body.set_enabled:
        t.enabled = True
    db.commit()
    db.refresh(t)
    if old_key and old_key != new_key:
        try:
            storage.delete_object(old_key)
        except Exception:
            pass
    return {
        "template": tpl_dict(t),
        "applied_count": len(snapshot),
        "placeholders": placeholders,
        "source_snapshot": snapshot,
    }


def qual_dict(q: Qualification) -> dict:
    expired, expiring = _qual_status(q)
    return {
        "id": q.id,
        "category": q.category,
        "name": q.name,
        "issuer": q.issuer,
        "file_type": q.file_type,
        "file_name": getattr(q, "file_name", "") or "",
        "object_key": q.object_key,
        "keywords": q.keywords,
        "section_hint": getattr(q, "section_hint", "") or "",
        "sort_order": getattr(q, "sort_order", 0) or 0,
        "valid_from": q.valid_from.isoformat() if q.valid_from else None,
        "valid_to": q.valid_to.isoformat() if q.valid_to else None,
        "is_long_term": q.is_long_term,
        "ocr_text": q.ocr_text,
        "expired": expired,
        "expiring": expiring,
    }


class QualIn(BaseModel):
    category: str
    name: str
    issuer: str = ""
    file_type: str = "docx"
    file_name: str = ""
    keywords: str = ""
    section_hint: str = ""
    sort_order: int = 0
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    is_long_term: bool = False
    ocr_text: str = ""


@router.get("/qualifications")
def admin_list_quals(
    q: str = "",
    category: str = "",
    status: str = "",
    sort_by: str = "",
    sort_dir: str = "asc",
    page: int | None = None,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    query = db.query(Qualification)
    if category:
        query = query.filter(Qualification.category == category)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            Qualification.name.ilike(like),
            Qualification.issuer.ilike(like),
            Qualification.keywords.ilike(like),
        ))
    query = _apply_qual_status_filter(query, status.strip().lower())
    allowed_sort = {"", "valid_to", "status"}
    sort_key = sort_by.strip().lower()
    if sort_key not in allowed_sort:
        sort_key = ""
    query = _order_qualifications(query, sort_key, sort_dir)
    return _paginate(query, page, page_size, qual_dict)


@router.get("/qualifications/{qual_id}")
def get_qual(qual_id: int, db: Session = Depends(get_db)):
    q = db.query(Qualification).filter(Qualification.id == qual_id).first()
    if not q:
        raise HTTPException(404, "资质不存在")
    return qual_dict(q)


@router.get("/qualifications/{qual_id}/file")
def download_qual_file(qual_id: int, inline: bool = False, db: Session = Depends(get_db)):
    q = db.query(Qualification).filter(Qualification.id == qual_id).first()
    if not q:
        raise HTTPException(404, "资质不存在")
    if not q.object_key:
        raise HTTPException(404, "资质文件不存在")
    data = storage.download_bytes(q.object_key)
    fname = q.file_name or q.name or "qualification"
    ftype = (q.file_type or "bin").lower().lstrip(".")
    media = {
        "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
        "pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(ftype, "application/octet-stream")
    disp = "inline" if inline else "attachment"
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f"{disp}; filename*=UTF-8''{quote(fname)}"},
    )


@router.post("/qualifications")
def create_qual(body: QualIn, db: Session = Depends(get_db)):
    q = Qualification(
        category=body.category,
        name=body.name,
        issuer=body.issuer,
        file_type=body.file_type,
        file_name=body.file_name or "",
        object_key="",
        keywords=body.keywords,
        section_hint=body.section_hint,
        sort_order=body.sort_order,
        valid_from=date.fromisoformat(body.valid_from) if body.valid_from else None,
        valid_to=date.fromisoformat(body.valid_to) if body.valid_to else None,
        is_long_term=body.is_long_term,
        ocr_text=body.ocr_text,
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    return qual_dict(q)


@router.put("/qualifications/{qual_id}")
def update_qual(qual_id: int, body: QualIn, db: Session = Depends(get_db)):
    q = db.query(Qualification).filter(Qualification.id == qual_id).first()
    if not q:
        raise HTTPException(404, "资质不存在")
    q.category = body.category
    q.name = body.name
    q.issuer = body.issuer
    q.file_type = body.file_type
    q.file_name = body.file_name or q.file_name
    q.keywords = body.keywords
    q.section_hint = body.section_hint
    q.sort_order = body.sort_order
    q.valid_from = date.fromisoformat(body.valid_from) if body.valid_from else None
    q.valid_to = date.fromisoformat(body.valid_to) if body.valid_to else None
    q.is_long_term = body.is_long_term
    q.ocr_text = body.ocr_text
    db.commit()
    db.refresh(q)
    return qual_dict(q)


@router.post("/qualifications/{qual_id}/file")
async def replace_qual_file(qual_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    q = db.query(Qualification).filter(Qualification.id == qual_id).first()
    if not q:
        raise HTTPException(404, "资质不存在")
    _delete_minio_key(q.object_key)
    data = await file.read()
    fname = file.filename or q.file_name or "file.bin"
    key = f"qualifications/{q.category}/{fname}"
    storage.upload_bytes(key, data, file.content_type or "application/octet-stream")
    q.object_key = key
    q.file_name = fname
    q.file_type = (fname.rsplit(".", 1)[-1] if "." in fname else q.file_type)
    db.commit()
    db.refresh(q)
    return qual_dict(q)


@router.delete("/qualifications/{qual_id}")
def delete_qual(qual_id: int, db: Session = Depends(get_db)):
    q = db.query(Qualification).filter(Qualification.id == qual_id).first()
    if not q:
        raise HTTPException(404, "资质不存在")
    _delete_minio_key(q.object_key)
    db.delete(q)
    db.commit()
    return {"ok": True}


class ChecklistIn(BaseModel):
    section: str
    name: str
    required: str = "必含"
    chapter: str = ""
    remark: str = ""
    template_code: str = "common"
    sort_order: int = 0


def check_dict(c: ChecklistItem) -> dict:
    return {
        "id": c.id,
        "section": c.section,
        "name": c.name,
        "required": c.required,
        "chapter": c.chapter,
        "remark": c.remark,
        "template_code": getattr(c, "template_code", "common") or "common",
        "sort_order": getattr(c, "sort_order", 0) or 0,
    }


@router.get("/checklist")
def admin_list_checklist(
    template_code: str = "",
    q: str = "",
    page: int | None = None,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    query = db.query(ChecklistItem)
    if template_code:
        query = query.filter(ChecklistItem.template_code.in_([template_code, "common"]))
    if q:
        like = f"%{q}%"
        query = query.filter(or_(ChecklistItem.name.ilike(like), ChecklistItem.section.ilike(like)))
    query = query.order_by(ChecklistItem.template_code, ChecklistItem.sort_order, ChecklistItem.id)
    return _paginate(query, page, page_size, check_dict)


@router.get("/checklist/{item_id}")
def get_checklist_item(item_id: int, db: Session = Depends(get_db)):
    c = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if not c:
        raise HTTPException(404, "清单条目不存在")
    return check_dict(c)


@router.post("/checklist")
def create_checklist(body: ChecklistIn, db: Session = Depends(get_db)):
    c = ChecklistItem(**body.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return check_dict(c)


@router.put("/checklist/{item_id}")
def update_checklist(item_id: int, body: ChecklistIn, db: Session = Depends(get_db)):
    c = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if not c:
        raise HTTPException(404)
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return check_dict(c)


@router.delete("/checklist/{item_id}")
def delete_checklist(item_id: int, db: Session = Depends(get_db)):
    c = db.query(ChecklistItem).filter(ChecklistItem.id == item_id).first()
    if not c:
        raise HTTPException(404)
    db.delete(c)
    db.commit()
    return {"ok": True}


class FAQIn(BaseModel):
    category: str = ""
    question: str
    answer: str
    source: str = ""
    template_code: str = "common"


def faq_dict(f: FAQItem) -> dict:
    return {
        "id": f.id,
        "category": f.category,
        "question": f.question,
        "answer": f.answer,
        "source": f.source,
        "template_code": getattr(f, "template_code", "common") or "common",
    }


@router.get("/faqs")
def admin_list_faqs(
    q: str = "",
    category: str = "",
    page: int | None = None,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    query = db.query(FAQItem)
    if category:
        query = query.filter(FAQItem.category == category)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(FAQItem.question.ilike(like), FAQItem.answer.ilike(like)))
    query = query.order_by(FAQItem.id)
    return _paginate(query, page, page_size, faq_dict)


@router.get("/faqs/{faq_id}")
def get_faq(faq_id: int, db: Session = Depends(get_db)):
    f = db.query(FAQItem).filter(FAQItem.id == faq_id).first()
    if not f:
        raise HTTPException(404, "FAQ 不存在")
    return faq_dict(f)


@router.post("/faqs")
def create_faq(body: FAQIn, db: Session = Depends(get_db)):
    f = FAQItem(**body.model_dump())
    db.add(f)
    db.commit()
    db.refresh(f)
    return faq_dict(f)


@router.put("/faqs/{faq_id}")
def update_faq(faq_id: int, body: FAQIn, db: Session = Depends(get_db)):
    f = db.query(FAQItem).filter(FAQItem.id == faq_id).first()
    if not f:
        raise HTTPException(404)
    for k, v in body.model_dump().items():
        setattr(f, k, v)
    db.commit()
    db.refresh(f)
    return faq_dict(f)


@router.delete("/faqs/{faq_id}")
def delete_faq(faq_id: int, db: Session = Depends(get_db)):
    f = db.query(FAQItem).filter(FAQItem.id == faq_id).first()
    if not f:
        raise HTTPException(404)
    db.delete(f)
    db.commit()
    return {"ok": True}


class ImportIn(BaseModel):
    force: bool = False


@router.post("/import")
def admin_import(body: ImportIn):
    try:
        return run_import(force=body.force)
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/export-snapshot")
def export_snapshot(db: Session = Depends(get_db)):
    return {
        "company": company_to_dict(db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()),
        "fields": [field_dict(f) for f in db.query(FieldDef).all()],
        "templates": [tpl_dict(t) for t in db.query(Template).all()],
        "qualifications": [qual_dict(q) for q in db.query(Qualification).all()],
        "checklist": [check_dict(c) for c in db.query(ChecklistItem).all()],
        "faqs": [faq_dict(f) for f in db.query(FAQItem).all()],
        "exported_at": datetime.utcnow().isoformat(),
    }
