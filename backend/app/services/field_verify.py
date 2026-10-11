"""敏感/核实字段规则（与前端 fieldDefaults.js 对齐，后端为 checklist 单一来源）。"""
from __future__ import annotations

from app.models import FieldDef

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


def unconfirmed_sensitive_keys(project_fields: dict | None, db) -> list[dict]:
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
