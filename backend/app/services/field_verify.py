"""敏感/核实字段规则（与前端 fieldDefaults.js 对齐，后端为 checklist 单一来源）。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.models import FieldDef

if TYPE_CHECKING:
    from app.models import TenderProject

SENSITIVE_FIELD_KEYS = frozenset({
    "bid_amount",
    "bid_amount_upper",
    "bid_amount_lower",
    "duration",
    "warranty_period",
    "delivery_period",
    "project_manager",
    "bid_date",
    "sign_date",
})

SENSITIVE_MODULES = frozenset({"报价", "投标报价", "工期与服务"})


def is_verify_field(fd: FieldDef | dict) -> bool:
    if not fd:
        return False
    if isinstance(fd, dict):
        if fd.get("desensitized"):
            return True
        if fd.get("key") in SENSITIVE_FIELD_KEYS:
            return True
        return (fd.get("module") or "") in SENSITIVE_MODULES
    if getattr(fd, "desensitized", False):
        return True
    if fd.key in SENSITIVE_FIELD_KEYS:
        return True
    return (fd.module or "") in SENSITIVE_MODULES


def field_reverify_keys(project_fields: dict | None) -> set[str]:
    raw = (project_fields or {}).get("_field_reverify") or []
    return {str(k) for k in raw if k}


def wizard_step2_trusted(project: "TenderProject | None") -> bool:
    """向导第二步完成后，已填字段默认信任（除非标记需重新核实）。"""
    if not project:
        return False
    return (project.current_step or 1) >= 3


def trust_wizard_filled_verify_field(
    project: "TenderProject | None",
    field_key: str,
    *,
    confirmed: dict | None,
    has_value: bool,
) -> bool:
    """创作工作台：第二步已填写的核实字段视为已确认。"""
    if not has_value:
        return False
    if field_key in (confirmed or {}):
        return True
    if not wizard_step2_trusted(project):
        return False
    return field_key not in field_reverify_keys(project.fields if project else {})


def mark_fields_for_reverify(project_fields: dict, keys: list[str]) -> dict:
    """Agent/用户修改字段后，将对应核实字段标记为待确认。"""
    fields = dict(project_fields or {})
    pending = set(field_reverify_keys(fields))
    for key in keys:
        if key:
            pending.add(str(key))
    if pending:
        fields["_field_reverify"] = sorted(pending)
    confirmed = dict(fields.get("_sensitive_confirmed") or {})
    for key in keys:
        confirmed.pop(str(key), None)
    fields["_sensitive_confirmed"] = confirmed
    return fields


def auto_confirm_wizard_verify_fields(db, project: "TenderProject") -> None:
    """进入创作阶段时，将已填写的核实字段写入确认戳（幂等）。"""
    from datetime import datetime

    from app.models import FieldDef

    fields = dict(project.fields or {})
    confirmed = dict(fields.get("_sensitive_confirmed") or {})
    stamp = datetime.utcnow().isoformat()
    changed = False
    for fd in db.query(FieldDef).all():
        if not is_verify_field(fd):
            continue
        val = fields.get(fd.key)
        if val is None or str(val).strip() == "":
            continue
        if fd.key in field_reverify_keys(fields):
            continue
        if fd.key not in confirmed:
            confirmed[fd.key] = stamp
            changed = True
    if changed:
        fields["_sensitive_confirmed"] = confirmed
        project.fields = fields


def unconfirmed_sensitive_keys(
    project_fields: dict | None,
    db,
    *,
    project: "TenderProject | None" = None,
) -> list[dict]:
    """导出前：已填但未确认的敏感/核实字段。"""
    from app.models import FieldDef

    fields = project_fields or {}
    confirmed = fields.get("_sensitive_confirmed") or {}
    out: list[dict] = []
    for fd in db.query(FieldDef).all():
        if not is_verify_field(fd):
            continue
        val = fields.get(fd.key)
        if val is None or str(val).strip() == "":
            continue
        if trust_wizard_filled_verify_field(
            project, fd.key, confirmed=confirmed, has_value=True,
        ):
            continue
        if fd.key not in confirmed:
            out.append({"key": fd.key, "name": fd.name})
    return out


def verify_reason(fd: FieldDef | dict) -> str:
    if isinstance(fd, dict):
        if fd.get("desensitized"):
            return "desensitized"
        if fd.get("key") in SENSITIVE_FIELD_KEYS:
            return "sensitive_key"
        if (fd.get("module") or "") in SENSITIVE_MODULES:
            return "sensitive_module"
        return ""
    if getattr(fd, "desensitized", False):
        return "desensitized"
    if fd.key in SENSITIVE_FIELD_KEYS:
        return "sensitive_key"
    if (fd.module or "") in SENSITIVE_MODULES:
        return "sensitive_module"
    return ""
