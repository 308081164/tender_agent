"""向导字段默认值与企业档案预填逻辑。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import CompanyProfile, FieldDef

# 字段 key → 企业档案列名（兼容未设置 is_company_default 的旧数据）
FIELD_COMPANY_MAP: dict[str, str] = {
    "bidder_name": "full_name",
    "address": "office_address",
    "phone": "phone",
    "fax": "fax",
    "email": "email",
    "website": "website",
    "postcode": "postcode",
    "legal_name": "legal_name",
    "legal_gender": "legal_gender",
    "legal_age": "legal_age",
    "legal_title": "legal_title",
    "legal_id_no": "legal_id_no",
    "company_founded": "founded_date",
    "registered_capital": "registered_capital",
    "bank_name": "bank_name",
    "bank_account": "bank_account",
    "recent_revenue": "recent_revenue",
    "related_companies": "related_companies",
}

# 地址类字段：办公地址优先，注册地址兜底
ADDRESS_FIELD_KEYS = frozenset({"address"})


def resolve_company_field(fd: FieldDef) -> str:
    """解析字段对应的企业档案列名。"""
    cf = getattr(fd, "company_field", "") or ""
    if getattr(fd, "is_company_default", False) and cf:
        return cf
    return FIELD_COMPANY_MAP.get(fd.key, "")


def company_field_value(company: CompanyProfile | None, company_field: str, field_key: str = "") -> str:
    """读取企业档案字段值，地址类支持注册地址兜底。"""
    if not company or not company_field:
        return ""
    val = getattr(company, company_field, "") or ""
    if val:
        return str(val)
    if field_key in ADDRESS_FIELD_KEYS and company_field == "office_address":
        fallback = getattr(company, "register_address", "") or ""
        if fallback:
            return str(fallback)
    if field_key == "bidder_name" and company_field == "full_name":
        short = getattr(company, "short_name", "") or ""
        if short:
            return str(short)
    return ""


def field_effective_default(fd: FieldDef, company: CompanyProfile | None) -> str:
    """字段当前有效默认值：优先企业档案，其次静态 default_value。"""
    cf = resolve_company_field(fd)
    if company and cf:
        val = company_field_value(company, cf, fd.key)
        if val:
            return val
    return fd.default_value or ""


def _should_apply_company_default(current: str | None, company_val: str, static_default: str) -> bool:
    """是否应以企业档案覆盖当前值。"""
    if not company_val:
        return False
    if not current:
        return True
    cur = str(current)
    if static_default and cur == str(static_default) and cur != str(company_val):
        return True
    return False


def fill_field_defaults(db: Session, fields: dict | None) -> dict:
    """用企业档案 / 字段默认值补齐空缺，并修正旧的静态种子默认值。"""
    result = dict(fields or {})
    company = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    for fd in db.query(FieldDef).order_by(FieldDef.sort_order).all():
        cf = resolve_company_field(fd)
        static_default = fd.default_value or ""
        if cf and company:
            company_val = company_field_value(company, cf, fd.key)
            if _should_apply_company_default(result.get(fd.key), company_val, static_default):
                result[fd.key] = company_val
                continue
        if result.get(fd.key):
            continue
        val = field_effective_default(fd, company)
        if val:
            result[fd.key] = val
    return result


def backfill_field_company_mappings(db: Session) -> int:
    """为已有 field_defs 补齐企业档案映射标记（幂等）。"""
    updated = 0
    for fd in db.query(FieldDef).all():
        cf = FIELD_COMPANY_MAP.get(fd.key)
        if not cf:
            continue
        needs_update = False
        if not getattr(fd, "is_company_default", False):
            fd.is_company_default = True
            needs_update = True
        if (getattr(fd, "company_field", "") or "") != cf:
            fd.company_field = cf
            needs_update = True
        if needs_update:
            updated += 1
    if updated:
        db.commit()
    return updated
