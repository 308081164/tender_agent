"""基础数据迁移包：一键导出/导入（含 MinIO 附件）。"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    CompanyProfile,
    FieldDef,
    Template,
    Qualification,
    ChecklistItem,
    FAQItem,
)
from app.services import storage


def _company_dict(c: CompanyProfile | None) -> dict:
    if not c:
        return {}
    return {
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
    }


def _field_dict(f: FieldDef) -> dict:
    return {
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


def _tpl_dict(t: Template) -> dict:
    return {
        "name": t.name,
        "description": t.description,
        "object_key": t.object_key,
        "placeholders": t.placeholders or {},
        "template_code": getattr(t, "template_code", "common") or "common",
        "kind": getattr(t, "kind", "template") or "template",
        "enabled": getattr(t, "enabled", True),
        "source_snapshot": getattr(t, "source_snapshot", {}) or {},
    }


def _qual_dict(q: Qualification) -> dict:
    return {
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
    }


def _check_dict(c: ChecklistItem) -> dict:
    return {
        "section": c.section,
        "name": c.name,
        "required": c.required,
        "chapter": c.chapter,
        "remark": c.remark,
        "template_code": getattr(c, "template_code", "common") or "common",
        "sort_order": getattr(c, "sort_order", 0) or 0,
    }


def _faq_dict(f: FAQItem) -> dict:
    return {
        "category": f.category,
        "question": f.question,
        "answer": f.answer,
        "source": f.source,
        "template_code": getattr(f, "template_code", "common") or "common",
    }

SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"
FILES_PREFIX = "files/"


def _collect_object_keys(manifest: dict) -> set[str]:
    keys: set[str] = set()
    for tpl in manifest.get("templates") or []:
        key = tpl.get("object_key")
        if key:
            keys.add(key)
    for qual in manifest.get("qualifications") or []:
        key = qual.get("object_key")
        if key:
            keys.add(key)
    return keys


def build_manifest(db: Session) -> dict:
    company = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.utcnow().isoformat(),
        "company": _company_dict(company),
        "fields": [_field_dict(f) for f in db.query(FieldDef).order_by(FieldDef.sort_order, FieldDef.id).all()],
        "templates": [_tpl_dict(t) for t in db.query(Template).all()],
        "qualifications": [_qual_dict(q) for q in db.query(Qualification).all()],
        "checklist": [_check_dict(c) for c in db.query(ChecklistItem).all()],
        "faqs": [_faq_dict(f) for f in db.query(FAQItem).all()],
    }


def export_pack(db: Session) -> bytes:
    manifest = build_manifest(db)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        for key in sorted(_collect_object_keys(manifest)):
            try:
                data = storage.download_bytes(key)
            except Exception:
                continue
            zf.writestr(f"{FILES_PREFIX}{key}", data)
    return buf.getvalue()


def _parse_date(val: str | None) -> date | None:
    if not val:
        return None
    try:
        return date.fromisoformat(str(val)[:10])
    except Exception:
        return None


def _clear_base_data_keep_projects(db: Session):
    """迁移导入：清空基础数据，保留标书项目。"""
    db.query(Qualification).delete()
    db.query(ChecklistItem).delete()
    db.query(FAQItem).delete()
    db.query(FieldDef).delete()
    db.query(Template).delete()
    db.query(CompanyProfile).delete()
    db.commit()


def import_pack(db: Session, data: bytes, *, force: bool = True) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        if MANIFEST_NAME not in zf.namelist():
            raise ValueError("迁移包缺少 manifest.json")
        manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
        version = manifest.get("schema_version", 0)
        if version > SCHEMA_VERSION:
            raise ValueError(f"迁移包版本 {version} 高于当前支持版本 {SCHEMA_VERSION}")

        has_data = db.query(FieldDef).count() > 0 or db.query(Template).count() > 0
        if has_data and not force:
            return {"skipped": True, "reason": "已有基础数据"}

        _clear_base_data_keep_projects(db)

        company = manifest.get("company") or {}
        if company:
            db.add(CompanyProfile(id=1, **{k: v for k, v in company.items() if k != "id"}))

        for f in manifest.get("fields") or []:
            row = dict(f)
            row.pop("id", None)
            db.add(FieldDef(**row))

        for t in manifest.get("templates") or []:
            row = dict(t)
            row.pop("id", None)
            db.add(Template(**row))

        for q in manifest.get("qualifications") or []:
            row = dict(q)
            row.pop("id", None)
            row["valid_from"] = _parse_date(row.get("valid_from"))
            row["valid_to"] = _parse_date(row.get("valid_to"))
            db.add(Qualification(**row))

        for c in manifest.get("checklist") or []:
            row = dict(c)
            row.pop("id", None)
            db.add(ChecklistItem(**row))

        for f in manifest.get("faqs") or []:
            row = dict(f)
            row.pop("id", None)
            db.add(FAQItem(**row))

        db.commit()

        uploaded = 0
        missing = 0
        for name in zf.namelist():
            if not name.startswith(FILES_PREFIX):
                continue
            key = name[len(FILES_PREFIX):]
            if not key:
                continue
            blob = zf.read(name)
            try:
                storage.upload_bytes(key, blob)
                uploaded += 1
            except Exception:
                missing += 1

        return {
            "ok": True,
            "counts": {
                "fields": len(manifest.get("fields") or []),
                "templates": len(manifest.get("templates") or []),
                "qualifications": len(manifest.get("qualifications") or []),
                "checklist": len(manifest.get("checklist") or []),
                "faqs": len(manifest.get("faqs") or []),
                "files_uploaded": uploaded,
                "files_missing": missing,
            },
        }
