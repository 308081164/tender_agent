"""资质 OCR/文本匹配：为图片槽与章节选择最佳资质。"""
from __future__ import annotations

import re
from typing import Any

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]{2,}")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) >= 2}


def score_qual_match(
    qual: dict[str, Any],
    *,
    qual_name: str = "",
    qual_category: str = "",
    section_hint: str = "",
    context: str = "",
) -> float:
    """根据名称/分类/章节提示/OCR 文本计算匹配分（0~1）。"""
    score = 0.0
    qname = (qual.get("name") or "").lower()
    qcat = (qual.get("category") or "").lower()
    qhint = (qual.get("section_hint") or "").lower()
    qocr = (qual.get("ocr_text") or "").lower()

    want_name = (qual_name or "").lower()
    want_cat = (qual_category or "").lower()
    want_hint = (section_hint or "").lower()
    ctx = (context or "").lower()

    if want_name and want_name in qname:
        score += 0.45
    elif want_name and qname and want_name in qocr:
        score += 0.35

    if want_cat and (want_cat in qcat or want_cat in qocr):
        score += 0.25

    if want_hint and (want_hint in qhint or want_hint in qocr):
        score += 0.2

    if ctx:
        ctx_tokens = _tokens(ctx)
        qual_tokens = _tokens(" ".join([qname, qcat, qhint, qocr]))
        if ctx_tokens and qual_tokens:
            overlap = len(ctx_tokens & qual_tokens) / max(len(ctx_tokens), 1)
            score += min(0.35, overlap * 0.35)

    return min(score, 1.0)


def rank_quals_for_slot(
    quals: list[dict[str, Any]],
    bind: dict[str, Any] | None = None,
    *,
    context: str = "",
) -> list[dict[str, Any]]:
    bind = bind or {}
    scored = []
    for q in quals:
        s = score_qual_match(
            q,
            qual_name=str(bind.get("qual_name") or ""),
            qual_category=str(bind.get("qual_category") or ""),
            section_hint=str(bind.get("section_hint") or ""),
            context=context or str(bind.get("alt") or ""),
        )
        scored.append((s, q))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [q for s, q in scored if s > 0] or [q for _, q in scored]
