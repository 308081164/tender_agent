"""基于 LLM + 规则从完整标书识别可模板化字段，并工程化为 {{key}} 占位符。"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.services import ai, word

# 规则兜底：常见标书字段的正则线索
RULE_HINTS: list[tuple[str, list[str]]] = [
    ("tender_no", [r"[A-Z]{2,8}[\w\-（）()]{4,40}"]),
    ("project_name", [r"[\u4e00-\u9fffA-Za-z0-9（）()\-·]{8,120}(?:工程|项目|采购|标段|包件)"]),
    ("bid_amount", [r"\d+(?:\.\d+)?(?:万|亿)?元"]),
    ("duration", [r"\d+\s*(?:个)?月", r"\d+\s*天"]),
    ("phone", [r"0\d{2,3}-\d{7,8}"]),
    ("postcode", [r"\b\d{6}\b"]),
    ("legal_name", [r"[\u4e00-\u9fff]{2,4}(?=\s*(?:男|女|\d{2}岁))"]),
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
        })
    return catalog


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
                if len(original) < 2 or original in seen_text:
                    continue
                seen_text.add(original)
                found.append({
                    "key": key,
                    "field_name": name,
                    "original_text": original,
                    "confidence": 0.55,
                    "reason": "规则匹配",
                    "source": "rule",
                })
    return found


def _merge_candidates(items: list[dict]) -> list[dict]:
    """按原文去重，保留置信度更高的一项。"""
    best: dict[str, dict] = {}
    for item in items:
        text = (item.get("original_text") or "").strip()
        key = (item.get("key") or "").strip()
        if not text or not key:
            continue
        sig = f"{key}::{text}"
        prev = best.get(sig)
        if not prev or float(item.get("confidence") or 0) > float(prev.get("confidence") or 0):
            best[sig] = item
    merged = list(best.values())
    merged.sort(key=lambda x: (-float(x.get("confidence") or 0), -len(x.get("original_text") or "")))
    return merged[:40]


async def detect_placeholder_candidates(
    docx_bytes: bytes,
    field_defs: list[dict],
    db: Session | None = None,
) -> dict[str, Any]:
    preview = word.extract_preview(docx_bytes, max_paragraphs=200)
    paragraphs = preview.get("paragraphs") or []
    text = "\n".join(p["text"] for p in paragraphs if p.get("text"))
    catalog = _field_catalog(field_defs)
    existing = word.extract_placeholders(docx_bytes)

    llm_items = await ai.detect_placeholder_candidates(text, catalog, db=db)
    rule_items = _rule_candidates(text, catalog)
    candidates = _merge_candidates([*llm_items, *rule_items])

    # 过滤已在文档中的占位符对应原文
    filtered = []
    for c in candidates:
        ot = c.get("original_text") or ""
        if "{{" in ot or "}}" in ot:
            continue
        if any(ot in f"{{{{{k}}}}}" for k in existing):
            continue
        filtered.append(c)

    return {
        "candidates": filtered,
        "existing_placeholders": existing,
        "paragraph_count": len(paragraphs),
        "document_excerpt": text[:4000],
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
        pairs.append((original, f"{{{{{key}}}}}"))
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
        if not key or not original:
            continue
        out.append({
            "key": key,
            "field_name": str(item.get("field_name") or item.get("name") or key),
            "original_text": original,
            "confidence": float(item.get("confidence") or 0.7),
            "reason": str(item.get("reason") or "AI 识别"),
            "source": "ai",
        })
    return out
