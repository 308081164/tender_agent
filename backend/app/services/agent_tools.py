"""Agent 中台工具层：对话可调用的系统能力执行器。

每个工具接收 db 与必要参数，执行真实的数据变更，返回结构化结果。
流程编排（多轮状态机）见 agent_flows.py。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import FieldDef, Template, TenderProject
from app.services import storage, template_detect, word

TEMPLATE_KINDS = ("template", "skeleton")


def template_card_dict(t: Template) -> dict[str, Any]:
    ph = (t.placeholders or {}).get("list") or []
    return {
        "id": t.id,
        "name": t.name,
        "kind": t.kind,
        "placeholder_count": len(ph),
        "enabled": bool(t.enabled),
        "created_at": t.created_at.isoformat() if t.created_at else "",
    }


def list_selectable_templates(db: Session, limit: int = 12) -> list[dict[str, Any]]:
    items = (
        db.query(Template)
        .filter(Template.enabled.is_(True), Template.kind.in_(TEMPLATE_KINDS))
        .order_by(Template.id.desc())
        .limit(limit)
        .all()
    )
    return [template_card_dict(t) for t in items]


def create_template_from_workspace(
    db: Session, workspace: dict[str, Any], name: str = ""
) -> Template:
    """从会话工作区的 DOCX 创建模板草稿（未启用，待映射确认后启用）。"""
    ws = workspace or {}
    doc_key = ws.get("template_object_key") or ws.get("draft_object_key")
    if not doc_key:
        raise ValueError("请先在左侧工作区上传一份完整的标书 DOCX")
    data = storage.download_bytes(doc_key)
    fname = (ws.get("filename") or "对话上传标书").rsplit(".", 1)[0]
    t = Template(
        name=(name or fname)[:180] or "对话创建模板",
        description="由 AI 助手从对话文档创建",
        object_key=doc_key,
        placeholders={"list": word.extract_placeholders(data)},
        template_code="common",
        kind="template",
        enabled=False,
    )
    db.add(t)
    db.flush()
    return t


async def detect_template_placeholders(
    db: Session, template_id: int
) -> dict[str, Any]:
    t = db.query(Template).filter(Template.id == template_id).first()
    if not t:
        raise ValueError("模板不存在或已被删除")
    data = storage.download_bytes(t.object_key)
    field_defs = [
        {"key": f.key, "name": f.name, "field_type": f.field_type, "module": f.module}
        for f in db.query(FieldDef).order_by(FieldDef.sort_order.asc()).all()
    ]
    result = await template_detect.detect_placeholder_candidates(data, field_defs, db=db)
    result["template_id"] = t.id
    result["template_name"] = t.name
    return result


def apply_template_placeholder_mappings(
    db: Session, template_id: int, mappings: list[dict[str, Any]]
) -> dict[str, Any]:
    """应用确认的映射并启用模板，返回模板信息与占位符清单。"""
    t = db.query(Template).filter(Template.id == template_id).first()
    if not t:
        raise ValueError("模板不存在或已被删除")
    data = storage.download_bytes(t.object_key)
    new_bytes, snapshot, placeholders = template_detect.apply_placeholder_mappings(
        data, mappings
    )
    new_key = (
        f"templates/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_engineered_{t.name}.docx"
    )
    storage.upload_bytes(
        new_key,
        new_bytes,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    old_key = t.object_key
    t.object_key = new_key
    ph_meta = {"list": placeholders, "detected": True}
    try:
        from app.services.doc_engine.engine import (
            attach_manifest_to_template,
            engineer_template_with_sdt,
        )
        from app.services.doc_engine.parser import parse_template_manifest
        manifest = parse_template_manifest(new_bytes)
        new_bytes, manifest = engineer_template_with_sdt(new_bytes, manifest)
        storage.upload_bytes(
            new_key,
            new_bytes,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        ph_meta = attach_manifest_to_template(ph_meta, manifest)
    except Exception:
        pass
    t.placeholders = ph_meta
    t.source_snapshot = {**(t.source_snapshot or {}), **snapshot}
    t.enabled = True
    db.flush()
    if old_key and old_key != new_key and not str(old_key).startswith("chat/"):
        try:
            storage.delete_object(old_key)
        except Exception:
            pass
    return {
        "template": template_card_dict(t),
        "object_key": new_key,
        "applied_count": len(snapshot),
        "placeholders": placeholders,
    }


def discard_template_draft(db: Session, template_id: int) -> None:
    t = db.query(Template).filter(Template.id == template_id).first()
    if t and not t.enabled:
        db.delete(t)
        db.flush()


def create_project_with_template(
    db: Session,
    template_id: int,
    title: str,
    fields: dict[str, Any],
) -> TenderProject:
    t = db.query(Template).filter(Template.id == template_id).first()
    if not t:
        raise ValueError("所选模板不存在")
    project = TenderProject(
        title=(title or fields.get("project_name") or t.name or "新标书项目")[:180],
        source_type="template",
        template_id=t.id,
        current_step=3,
        fields=fields,
        status="draft",
        updated_at=datetime.utcnow(),
    )
    db.add(project)
    db.flush()
    return project


def _parse_options(raw: Any) -> list[str]:
    """FieldDef.options 在数据库中是分号分隔字符串，统一解析为列表。"""
    if isinstance(raw, list):
        return [str(o) for o in raw if str(o).strip()]
    if isinstance(raw, str):
        return [o.strip() for o in raw.replace("；", ";").split(";") if o.strip()]
    return []


def required_fields_for_template(db: Session, template_id: int | None = None) -> list[dict[str, Any]]:
    """对话内收集的关键字段：必填优先，补充常用项（含 verify / effective_default）。"""
    from app.services.project_context import field_defs_enriched_for_template

    enriched = field_defs_enriched_for_template(db, template_id)
    picked: list[dict[str, Any]] = []
    for f in enriched:
        if f.get("required") or f.get("key") in ("project_name", "tender_no", "tenderer", "duration"):
            picked.append({
                "key": f["key"],
                "name": f["name"],
                "field_type": f.get("field_type") or "文本",
                "default": f.get("effective_default") or f.get("default") or "",
                "options": f.get("options") or [],
                "required": bool(f.get("required")) or f["key"] == "project_name",
                "verify": bool(f.get("verify")),
                "desensitized": bool(f.get("desensitized")),
            })
    seen = {f["key"] for f in picked}
    for key in ("project_name", "tender_no", "tenderer", "duration"):
        if key in seen:
            continue
        picked.append({
            "key": key,
            "name": {"project_name": "项目名称", "tender_no": "招标编号",
                     "tenderer": "招标人", "duration": "工期/服务期"}.get(key, key),
            "field_type": "文本",
            "default": "",
            "options": [],
            "required": key == "project_name",
            "verify": key == "duration",
        })
    return picked[:8]


def get_project_context(db: Session, project_id: int) -> dict[str, Any]:
    from app.services.project_context import build_project_context

    return build_project_context(db, project_id)


def get_missing_critical_fields(db: Session, project_id: int) -> dict[str, Any]:
    ctx = get_project_context(db, project_id)
    cl = ctx.get("field_checklist") or {}
    return {
        "missing_required": cl.get("missing_required") or [],
        "needs_verify": cl.get("needs_verify") or [],
        "empty_chapters": (ctx.get("chapters") or {}).get("empty_keys") or [],
    }


def scan_qual_folder(folder: str) -> dict[str, Any]:
    from app.services.agent_qual_folder import scan_qual_folder as _scan

    return _scan(folder)


def read_document_file(path: str) -> dict[str, Any]:
    from app.services.agent_qual_folder import read_document_file as _read

    doc = _read(path)
    # 工具层不向外返回原始 bytes
    return {k: v for k, v in doc.items() if k != "data"}


def apply_company_field_patch(
    db: Session, patch: dict[str, Any], *, force_sensitive: bool = False
) -> dict[str, Any]:
    from app.services.agent_qual_folder import apply_company_field_patch as _apply

    return _apply(db, patch, force_sensitive=force_sensitive)


def apply_qual_record(
    db: Session, file_info: dict[str, Any], analyzed: dict[str, Any], data: bytes
) -> dict[str, Any]:
    from app.services.agent_qual_folder import apply_qual_record as _apply

    return _apply(db, file_info, analyzed, data)


def get_onboarding_gaps(db: Session) -> dict[str, Any]:
    from app.services.agent_qual_folder import get_onboarding_gaps as _gaps

    return _gaps(db)


async def import_qual_folder(db: Session, folder: str, *, dry_run: bool = False) -> dict[str, Any]:
    from app.services.agent_qual_folder import import_qual_folder_pipeline
    from app.services.ai import MultimodalRequiredError

    try:
        return await import_qual_folder_pipeline(db, folder, dry_run=dry_run)
    except MultimodalRequiredError as err:
        return err.payload()


async def list_missing_intake_questions(db: Session, project_id: int) -> dict[str, Any]:
    from app.models import TenderProject
    from app.services.project_workflow import guided_intake_questions

    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p or not p.template_id:
        return {"questions": [], "field_cards": []}
    critical = get_missing_critical_fields(db, project_id)
    missing = critical.get("missing_required") or []
    if missing:
        fields = required_fields_for_template(db, p.template_id)
        by_key = {f["key"]: f for f in fields}
        card_fields = [by_key[m["key"]] for m in missing[:3] if m["key"] in by_key]
        if not card_fields:
            card_fields = [
                {"key": m["key"], "name": m.get("name", m["key"]), "required": True, "default": ""}
                for m in missing[:3]
            ]
        return {"questions": [], "field_cards": card_fields}
    answered = (p.fields or {}).get("_guided_answers") or {}
    intake = await guided_intake_questions(db, p.template_id, p.fields or {}, answered=answered)
    return {"questions": intake.get("questions") or [], "field_cards": []}
