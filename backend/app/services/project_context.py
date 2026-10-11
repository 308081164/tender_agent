"""项目创作上下文：模板、workflow、字段清单、章节摘要（Agent 与 UI 共用）。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import FieldDef, Template, TenderProject
from app.services.field_defaults import field_effective_default, fill_field_defaults
from app.services.field_verify import is_verify_field, verify_reason
from app.services.project_workflow import get_workflow_plan
from app.models import CompanyProfile


def _field_defs_for_project(db: Session, template_code: str) -> list[FieldDef]:
    q = db.query(FieldDef)
    if template_code:
        q = q.filter(FieldDef.template_code.in_([template_code, "common"]))
    return q.order_by(FieldDef.sort_order, FieldDef.id).all()


def _chapter_summary(chapters: dict | None, manifest_blocks: list | None) -> dict[str, Any]:
    chapters = chapters or {}
    content_keys = [
        k for k, v in chapters.items()
        if k and not str(k).startswith("_") and isinstance(v, dict) and (v.get("content") or "").strip()
    ]
    ai_keys = []
    for b in manifest_blocks or []:
        if b.get("type") in ("ai_section", "table_slot"):
            bid = b.get("id") or b.get("bind") or b.get("title")
            if bid:
                ai_keys.append(str(bid))
    empty_keys = [k for k in ai_keys if k not in content_keys]
    total = max(len(ai_keys), len(content_keys), 1)
    return {
        "done": len(content_keys),
        "total": total,
        "empty_keys": empty_keys[:20],
    }


def build_field_checklist(
    db: Session,
    project: TenderProject,
    fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tpl = db.query(Template).filter(Template.id == project.template_id).first() if project.template_id else None
    template_code = (getattr(tpl, "template_code", None) or "common") if tpl else "common"
    company = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    merged = fill_field_defaults(db, fields if fields is not None else (project.fields or {}))
    confirmed = (project.fields or {}).get("_sensitive_confirmed") or {}

    filled: list[dict] = []
    missing_required: list[dict] = []
    needs_verify: list[dict] = []

    for fd in _field_defs_for_project(db, template_code):
        val = merged.get(fd.key)
        has_val = val is not None and str(val).strip() != ""
        entry_base = {
            "key": fd.key,
            "name": fd.name,
            "module": fd.module or "",
            "required": bool(fd.required),
        }
        if is_verify_field(fd):
            if not has_val or fd.key not in confirmed:
                needs_verify.append({
                    **entry_base,
                    "value": str(val) if has_val else "",
                    "reason": verify_reason(fd),
                    "confirmed": fd.key in confirmed,
                })
        if fd.required and not has_val:
            missing_required.append(entry_base)
        elif has_val:
            filled.append({
                **entry_base,
                "value": str(val)[:500],
                "verify": is_verify_field(fd),
            })

    return {
        "filled": filled,
        "missing_required": missing_required,
        "needs_verify": needs_verify,
    }


def build_project_context(db: Session, project_id: int) -> dict[str, Any]:
    project = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not project:
        raise ValueError("项目不存在")

    tpl = db.query(Template).filter(Template.id == project.template_id).first() if project.template_id else None
    workflow = get_workflow_plan(db, project.template_id)
    ph_list = (tpl.placeholders or {}).get("list") or [] if tpl else []
    manifest = (tpl.placeholders or {}).get("manifest") or {} if tpl else {}
    blocks = manifest.get("blocks") or []

    checklist = build_field_checklist(db, project)
    chapters = _chapter_summary(project.chapters, blocks)

    mode = workflow.get("mode") or "compose"
    return {
        "project_id": project.id,
        "project_title": project.title,
        "template": {
            "id": tpl.id if tpl else None,
            "name": tpl.name if tpl else "",
            "kind": getattr(tpl, "kind", "") if tpl else "",
            "mode": mode,
            "template_code": getattr(tpl, "template_code", "common") if tpl else "common",
            "placeholder_count": len(ph_list),
            "ai_block_count": len([b for b in blocks if b.get("type") == "ai_section"]),
            "table_slot_count": len([b for b in blocks if b.get("type") == "table_slot"]),
        },
        "workflow": workflow,
        "field_checklist": checklist,
        "chapters": chapters,
        "capabilities": [
            "edit_selection",
            "compose_block",
            "parse_attachment",
            "insert_qual",
            "reference_rewrite",
        ],
        "guided_intake_enabled": bool((project.fields or {}).get("_guided_intake", True)),
    }


def field_defs_enriched_for_template(db: Session, template_id: int | None = None) -> list[dict[str, Any]]:
    """Agent 字段卡：含 effective_default 与 verify 标记。"""
    tpl = db.query(Template).filter(Template.id == template_id).first() if template_id else None
    template_code = (getattr(tpl, "template_code", None) or "common") if tpl else "common"
    company = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    out: list[dict] = []
    for fd in _field_defs_for_project(db, template_code):
        opts = [o.strip() for o in (fd.options or "").replace("；", ";").split(";") if o.strip()] if fd.options else []
        out.append({
            "key": fd.key,
            "name": fd.name,
            "field_type": fd.field_type,
            "default": fd.default_value or "",
            "effective_default": field_effective_default(fd, company),
            "options": opts,
            "required": bool(fd.required),
            "verify": is_verify_field(fd),
            "desensitized": bool(getattr(fd, "desensitized", False)),
        })
    return out
