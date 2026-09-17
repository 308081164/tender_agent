"""基于 LLM + 规则从完整标书识别可模板化字段，并工程化为 {{key}} 占位符。"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.services import ai, word
from app.services.mapping_resources import build_mapping_resource_catalog

# 规则兜底：仅在语义明确时使用，避免 tender_no 泛化匹配
RULE_HINTS: list[tuple[str, list[str]]] = [
    (
        "project_name",
        [r"[\u4e00-\u9fffA-Za-z0-9（）()\-·]{10,120}(?:工程|项目|采购|标段|包件)"],
    ),
    ("bid_amount", [r"人民币[\u4e00-\u9fff]{2,30}整", r"\d+(?:\.\d+)?(?:万|亿)?元"]),
    ("bid_date", [r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日"]),
    ("duration", [r"\d+\s*日历天", r"\d+\s*工作日", r"\d+\s*(?:个)?月(?!\s*\d)"]),
    ("phone", [r"0\d{2,3}-\d{7,8}"]),
    ("postcode", [r"(?<!\d)\d{6}(?!\d)"]),
]

JUNK_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"PAGE\s*\\",
        r"\\\*",
        r"\\[a-z]+\s",
        r"HYPERLINK",
        r"TOC\s",
        r"PAGEREF",
        r"SEQ\s",
        r"^\s*\d+\s*$",
        r"^\s*[\{\}\\]+\s*$",
    ]
]


def _field_catalog(field_defs: list[dict]) -> list[dict]:
    catalog = []
    for f in field_defs:
        key = (f.get("key") or "").strip()
        if not key:
            continue
        catalog.append({
            "key": key,
            "name": f.get("name") or key,
            "type": f.get("field_type") or "文本",
            "module": f.get("module") or "",
            "required": bool(f.get("required")),
            "options": (f.get("options") or "")[:120],
            "company_field": f.get("company_field") or "",
        })
    return catalog


def _is_junk_text(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < 2:
        return True
    if "{{" in t or "}}" in t:
        return True
    if "\\" in t and ("PAGE" in t.upper() or "TOC" in t.upper()):
        return True
    return any(p.search(t) for p in JUNK_PATTERNS)


def _rule_candidates(text: str, catalog: list[dict]) -> list[dict]:
    keys = {c["key"] for c in catalog}
    found: list[dict] = []
    seen_text: set[str] = set()
    for key, patterns in RULE_HINTS:
        if key not in keys:
            continue
        name = next((c["name"] for c in catalog if c["key"] == key), key)
        for pat in patterns:
            for m in re.finditer(pat, text):
                original = m.group(0).strip()
                if _is_junk_text(original) or original in seen_text:
                    continue
                seen_text.add(original)
                found.append({
                    "key": key,
                    "field_name": name,
                    "original_text": original,
                    "confidence": 0.6,
                    "reason": "规则匹配",
                    "source": "rule",
                    "bind_type": "field",
                })
    return found


def _merge_candidates(items: list[dict]) -> list[dict]:
    """按原文去重，保留置信度更高的一项。"""
    best: dict[str, dict] = {}
    for item in items:
        text = (item.get("original_text") or "").strip()
        if _is_junk_text(text):
            continue
        sig = text
        prev = best.get(sig)
        if not prev or float(item.get("confidence") or 0) > float(prev.get("confidence") or 0):
            best[sig] = item
    merged = list(best.values())
    merged.sort(key=lambda x: (-float(x.get("confidence") or 0), -len(x.get("original_text") or "")))
    return merged[:50]


def _annotate_match_status(candidates: list[dict], field_keys: set[str]) -> list[dict]:
    out = []
    for c in candidates:
        item = dict(c)
        key = (item.get("key") or "").strip()
        conf = float(item.get("confidence") or 0)
        bind = item.get("bind_type") or "field"
        if bind == "qual" or key.startswith("qual_"):
            item["match_status"] = "matched"
            item["bind_type"] = "qual"
        elif bind == "runtime" or key.startswith("runtime_"):
            item["match_status"] = "runtime"
            item["bind_type"] = "runtime"
        elif key in field_keys:
            item["match_status"] = "matched" if conf >= 0.55 else "low_confidence"
            item["bind_type"] = "field"
        else:
            item["match_status"] = "unresolved"
            item["needs_field_creation"] = True
            item.setdefault("suggested_field", {
                "key": key or "custom_field",
                "name": item.get("field_name") or key or "自定义字段",
                "field_type": item.get("value_type") or "文本",
                "module": item.get("module") or "临场填写",
            })
        out.append(item)
    return out


async def detect_placeholder_candidates(
    docx_bytes: bytes,
    field_defs: list[dict],
    db: Session | None = None,
) -> dict[str, Any]:
    preview = word.extract_preview(docx_bytes, max_paragraphs=400)
    paragraphs = preview.get("paragraphs") or []
    text = "\n".join(p["text"] for p in paragraphs if p.get("text"))
    catalog = _field_catalog(field_defs)
    existing = word.extract_placeholders(docx_bytes)

    resource_catalog = build_mapping_resource_catalog(db) if db is not None else {"field_keys": set()}
    field_keys = set(resource_catalog.get("field_keys") or [])

    llm_items = await ai.detect_placeholder_candidates(text, catalog, db=db)
    rule_items = _rule_candidates(text, catalog)
    merged = _merge_candidates([*llm_items, *rule_items])

    # 过滤已在文档中的占位符对应原文
    filtered = []
    for c in merged:
        ot = c.get("original_text") or ""
        if _is_junk_text(ot):
            continue
        if any(ot in f"{{{{{k}}}}}" for k in existing):
            continue
        filtered.append(c)

    # AI 二次决策：结合系统资源目录为每处原文选择最合适的字段/材料
    if db is not None and filtered:
        resolved = await ai.resolve_placeholder_mappings(
            filtered,
            resource_catalog,
            document_text=text[:12000],
            db=db,
        )
        if resolved:
            filtered = resolved

    annotated = _annotate_match_status(filtered, field_keys)
    stats = {
        "total": len(annotated),
        "matched": sum(1 for x in annotated if x.get("match_status") == "matched"),
        "low_confidence": sum(1 for x in annotated if x.get("match_status") == "low_confidence"),
        "unresolved": sum(1 for x in annotated if x.get("match_status") == "unresolved"),
        "runtime": sum(1 for x in annotated if x.get("match_status") == "runtime"),
    }

    return {
        "candidates": annotated,
        "existing_placeholders": existing,
        "paragraph_count": len(paragraphs),
        "document_excerpt": text[:4000],
        "format_info": preview.get("format_info") or {},
        "resource_catalog": {
            "fields": resource_catalog.get("fields") or [],
            "qualifications": resource_catalog.get("qualifications") or [],
            "runtime": resource_catalog.get("runtime") or [],
        },
        "mapping_stats": stats,
    }


def apply_placeholder_mappings(
    docx_bytes: bytes,
    mappings: list[dict],
    *,
    highlight: bool = False,
) -> tuple[bytes, dict[str, str], list[str]]:
    """应用用户确认的映射，返回新文档、source_snapshot、占位符列表。"""
    approved = [
        m for m in (mappings or [])
        if m.get("approved", True)
        and m.get("action", "replace") != "keep"
        and (m.get("original_text") or "").strip()
        and (m.get("key") or "").strip()
    ]
    pairs: list[tuple[str, str]] = []
    snapshot: dict[str, str] = {}
    for m in sorted(approved, key=lambda x: len(x.get("original_text") or ""), reverse=True):
        key = str(m["key"]).strip()
        original = str(m["original_text"]).strip()
        if not original or original in snapshot.values():
            continue
        placeholder = f"{{{{{key}}}}}"
        if m.get("bind_type") == "qual":
            placeholder = f"【QUAL_SLOT:{m.get('qualification_id') or key}】"
        pairs.append((original, placeholder))
        snapshot[key] = original

    new_bytes = word.apply_literal_replacements(docx_bytes, pairs, highlight=highlight)
    placeholders = word.extract_placeholders(new_bytes)
    return new_bytes, snapshot, placeholders


def parse_llm_candidate_json(raw: str) -> list[dict]:
    if not raw:
        return []
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        original = str(item.get("original_text") or item.get("text") or "").strip()
        if not key or not original or _is_junk_text(original):
            continue
        out.append({
            "key": key,
            "field_name": str(item.get("field_name") or item.get("name") or key),
            "original_text": original,
            "confidence": float(item.get("confidence") or 0.7),
            "reason": str(item.get("reason") or "AI 识别"),
            "source": "ai",
            "bind_type": str(item.get("bind_type") or "field"),
            "value_type": str(item.get("value_type") or ""),
        })
    return out


def parse_resolve_json(raw: str) -> list[dict]:
    if not raw:
        return []
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        original = str(item.get("original_text") or item.get("text") or "").strip()
        if not key or not original or _is_junk_text(original):
            continue
        bind_type = str(item.get("bind_type") or "field").strip()
        qual_id = item.get("qualification_id")
        if bind_type == "qual" and not qual_id and key.startswith("qual_"):
            try:
                qual_id = int(key.split("_", 1)[1])
            except (ValueError, IndexError):
                qual_id = None
        parsed = {
            "key": key,
            "field_name": str(item.get("field_name") or item.get("name") or key),
            "original_text": original,
            "confidence": float(item.get("confidence") or 0.75),
            "reason": str(item.get("reason") or "AI 映射决策"),
            "source": "ai",
            "bind_type": bind_type,
            "value_type": str(item.get("value_type") or ""),
        }
        if qual_id is not None:
            parsed["qualification_id"] = int(qual_id)
        suggested = item.get("suggested_field")
        if isinstance(suggested, dict) and suggested.get("key"):
            parsed["suggested_field"] = {
                "key": str(suggested.get("key") or "").strip(),
                "name": str(suggested.get("name") or suggested.get("key") or "").strip(),
                "field_type": str(suggested.get("field_type") or "文本"),
                "module": str(suggested.get("module") or "临场填写"),
            }
            parsed["needs_field_creation"] = True
        out.append(parsed)
    return out
