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
    t.placeholders = {"list": placeholders, "detected": True}
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


def required_fields_for_template(db: Session) -> list[dict[str, Any]]:
    """对话内收集的关键字段：必填优先，补充常用项。"""
    defs = db.query(FieldDef).order_by(FieldDef.sort_order.asc()).all()
    picked: list[dict[str, Any]] = []
    for f in defs:
        if f.required:
            picked.append({
                "key": f.key,
                "name": f.name,
                "field_type": f.field_type,
                "default": f.default_value or "",
                "options": _parse_options(f.options),
                "required": True,
            })
    for key in ("project_name", "tender_no", "tenderer", "duration"):
        if any(f["key"] == key for f in picked):
            continue
        picked.append({
            "key": key,
            "name": {"project_name": "项目名称", "tender_no": "招标编号",
                     "tenderer": "招标人", "duration": "工期/服务期"}.get(key, key),
            "field_type": "文本",
            "default": "",
            "options": [],
            "required": key == "project_name",
        })
    return picked[:8]
