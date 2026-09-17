"""工程化映射可用的系统资源目录（字段定义、企业档案、资质库、FAQ、临场填写）。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import CompanyProfile, FAQItem, FieldDef, Qualification


def _company_field_entries(company: CompanyProfile | None) -> list[dict]:
    if not company:
        return []
    entries = []
    for col in CompanyProfile.__table__.columns:
        if col.key in ("id",):
            continue
        val = getattr(company, col.key, None)
        if val is None or str(val).strip() == "":
            continue
        entries.append({
            "bind_type": "company",
            "key": col.key,
            "name": col.key,
            "field_type": "文本",
            "module": "企业档案",
            "sample": str(val)[:120],
            "search_text": f"{col.key} 企业档案",
        })
    return entries


def build_mapping_resource_catalog(db: Session, *, limit_each: int = 120) -> dict:
    """构建供 AI 决策与前端搜索选择使用的统一资源目录。"""
    fields = db.query(FieldDef).order_by(FieldDef.sort_order.asc(), FieldDef.id.asc()).all()
    field_items = []
    field_keys: set[str] = set()
    for f in fields:
        key = (f.key or "").strip()
        if not key:
            continue
        field_keys.add(key)
        field_items.append({
            "bind_type": "field",
            "id": f.id,
            "key": key,
            "name": f.name or key,
            "field_type": f.field_type or "文本",
            "module": f.module or "字段定义",
            "required": bool(f.required),
            "options": (f.options or "")[:200],
            "company_field": f.company_field or "",
            "template_code": getattr(f, "template_code", "common") or "common",
            "search_text": f"{f.name} {key} {f.module} {f.field_type}",
        })

    company = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    company_items = _company_field_entries(company)

    quals = db.query(Qualification).order_by(Qualification.category, Qualification.name).limit(limit_each).all()
    qual_items = []
    for q in quals:
        slug = f"qual_{q.id}"
        qual_items.append({
            "bind_type": "qual",
            "id": q.id,
            "key": slug,
            "name": q.name or f"资质{q.id}",
            "field_type": "材料",
            "module": f"资质库/{q.category or '未分类'}",
            "category": q.category or "",
            "keywords": q.keywords or "",
            "section_hint": getattr(q, "section_hint", "") or "",
            "search_text": f"{q.name} {q.category} {q.keywords} {q.issuer or ''}",
        })

    faqs = db.query(FAQItem).order_by(FAQItem.category, FAQItem.id).limit(limit_each).all()
    faq_items = []
    for item in faqs:
        faq_items.append({
            "bind_type": "faq",
            "id": item.id,
            "key": f"faq_{item.id}",
            "name": (item.question or "")[:80],
            "field_type": "FAQ",
            "module": f"FAQ/{item.category or '通用'}",
            "search_text": f"{item.category} {item.question} {item.answer}",
        })

    runtime_items = [
        {
            "bind_type": "runtime",
            "key": "runtime_custom",
            "name": "临场决策填写（通用）",
            "field_type": "文本",
            "module": "临场填写",
            "search_text": "临场 决策 生成时填写 runtime",
        },
    ]

    return {
        "fields": field_items,
        "company": company_items,
        "qualifications": qual_items,
        "faqs": faq_items,
        "runtime": runtime_items,
        "field_keys": sorted(field_keys),
        "all_bindable": field_items + company_items + qual_items + runtime_items,
    }


def search_mapping_resources(catalog: dict, query: str, limit: int = 40) -> list[dict]:
    q = (query or "").strip().lower()
    items = catalog.get("all_bindable") or []
    if not q:
        return items[:limit]
    scored = []
    for item in items:
        text = (item.get("search_text") or item.get("name") or "").lower()
        key = (item.get("key") or "").lower()
        if q in text or q in key:
            score = 2 if q in key else 1
            scored.append((score, item))
    scored.sort(key=lambda x: (-x[0], x[1].get("name", "")))
    return [x[1] for x in scored[:limit]]
