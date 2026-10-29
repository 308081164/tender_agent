"""Document Map：manifest + 正文结构合并，供 Agent 与 compose 共用。"""
from __future__ import annotations

import re
from typing import Any

from app.services.doc_engine.compose_policy import (
    section_followed_by_form_table,
    section_has_letter_skeleton,
    section_slice_after_heading,
    should_generate_ai_narrative,
    title_is_structured_letter,
    title_prefers_table_fill,
)
from app.services.word import is_heading_style_name, paragraph_is_toc_like

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

REGION_TOC = "toc"
REGION_HEADING = "heading"
REGION_NARRATIVE_EMPTY = "narrative_empty"
REGION_NARRATIVE_FILLED = "narrative_filled"
REGION_FORM_TABLE = "form_table"
REGION_LETTER_SKELETON = "letter_skeleton"
REGION_TABLE_EMPTY = "table_empty"
REGION_TABLE_PARTIAL = "table_partial"
REGION_UNKNOWN = "unknown"

OUTLINE_FIELD = "_document_outline"


def _paragraph_text(node) -> str:
    return "".join((item.text or "") for item in node.iter(f"{{{W}}}t"))


def _paragraph_style(node) -> str:
    ppr = node.find(f"{{{W}}}pPr")
    if ppr is None:
        return ""
    ps = ppr.find(f"{{{W}}}pStyle")
    if ps is None:
        return ""
    return ps.get(f"{{{W}}}val") or ""


def _is_heading_node(node, text: str) -> bool:
    style = _paragraph_style(node)
    return is_heading_style_name(style) or style.lower().startswith("heading") or "标题" in style


def _body_elements(docx_bytes: bytes) -> list[tuple[str, Any]]:
    from app.services.doc_engine.compose_policy import _body_elements as _be

    return _be(docx_bytes)


def _cell_empty(text: str) -> bool:
    t = re.sub(r"\s+", "", (text or "").replace("\x07", ""))
    if not t:
        return True
    if t in ("—", "-", "／", "/"):
        return True
    return False


def _table_summary(docx_bytes: bytes, tbl_node, table_index: int) -> dict[str, Any]:
    rows = tbl_node.findall(f"{{{W}}}tr")
    empty_cells: list[dict[str, Any]] = []
    data_rows = 0
    header_hint = ""
    for r, row in enumerate(rows):
        cells = row.findall(f"{{{W}}}tc")
        row_texts = [_paragraph_text(c).strip() for c in cells]
        if r == 0:
            header_hint = " ".join(row_texts)[:120]
        if r >= 1 and any(row_texts):
            data_rows += 1
        for c, cell in enumerate(cells):
            ct = _paragraph_text(cell).strip()
            if _cell_empty(ct):
                empty_cells.append({
                    "location": f"tbl:{table_index}:r{r}:c{c}",
                    "row": r,
                    "col": c,
                    "text": ct,
                })
    if data_rows == 0 and empty_cells:
        region = REGION_TABLE_EMPTY
    elif empty_cells:
        region = REGION_TABLE_PARTIAL
    else:
        region = REGION_FORM_TABLE if data_rows else REGION_TABLE_EMPTY
    return {
        "table_index": table_index,
        "header": header_hint,
        "data_rows": data_rows,
        "empty_cell_count": len(empty_cells),
        "region_type": region,
        "empty_cells": empty_cells[:80],
    }


def _section_region_type(docx_bytes: bytes, title: str) -> str:
    t = (title or "").strip()
    if not t:
        return REGION_UNKNOWN
    if title_is_structured_letter(t):
        if section_has_letter_skeleton(docx_bytes, t):
            return REGION_LETTER_SKELETON
    if title_prefers_table_fill(t) or section_followed_by_form_table(docx_bytes, t):
        return REGION_FORM_TABLE
    parts = section_slice_after_heading(docx_bytes, t)
    body_texts: list[str] = []
    has_table = False
    for kind, node in parts:
        if kind == "tbl":
            has_table = True
        elif kind == "p":
            txt = _paragraph_text(node).strip()
            if txt:
                body_texts.append(txt)
    body = "\n".join(body_texts)
    compact = re.sub(r"\s+", "", body)
    if has_table and len(compact) < 120:
        return REGION_FORM_TABLE
    if len(compact) < 40:
        return REGION_NARRATIVE_EMPTY
    return REGION_NARRATIVE_FILLED


def build_document_map(
    docx_bytes: bytes,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从当前 DOCX 构建 Outline（OOXML 为主，可选 Aspose 索引 enrichment）。"""
    manifest = manifest or {}
    sections: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    empty_slots: list[dict[str, Any]] = []
    table_counter = 0

    elements = _body_elements(docx_bytes)
    current_heading: dict[str, Any] | None = None

    for kind, node in elements:
        if kind == "p":
            text = _paragraph_text(node).strip()
            style = _paragraph_style(node)
            if not text:
                continue
            if paragraph_is_toc_like(style, text):
                sections.append({
                    "title": text[:80],
                    "level": 0,
                    "region_type": REGION_TOC,
                    "allows_ai_narrative": False,
                })
                continue
            if _is_heading_node(node, text):
                region = _section_region_type(docx_bytes, text)
                allows_ai = should_generate_ai_narrative(text, docx_bytes) and region in (
                    REGION_NARRATIVE_EMPTY,
                    REGION_NARRATIVE_FILLED,
                )
                current_heading = {
                    "title": text,
                    "level": 1,
                    "region_type": region,
                    "allows_ai_narrative": allows_ai,
                    "table_indices": [],
                }
                sections.append(current_heading)
        elif kind == "tbl":
            summary = _table_summary(docx_bytes, node, table_counter)
            tables.append(summary)
            for cell in summary.get("empty_cells") or []:
                empty_slots.append({
                    **cell,
                    "table_index": table_counter,
                    "section_title": (current_heading or {}).get("title") or "",
                    "header": summary.get("header") or "",
                })
            if current_heading is not None:
                current_heading.setdefault("table_indices", []).append(table_counter)
                if summary.get("region_type") in (REGION_TABLE_EMPTY, REGION_TABLE_PARTIAL):
                    current_heading["region_type"] = REGION_FORM_TABLE
                    current_heading["allows_ai_narrative"] = False
            table_counter += 1

    manifest_hints: list[dict[str, Any]] = []
    for block in manifest.get("blocks") or []:
        btype = block.get("type") or ""
        title = str(block.get("title") or block.get("bind") or block.get("id") or "").strip()
        manifest_hints.append({
            "type": btype,
            "id": block.get("id") or "",
            "title": title,
            "table_index": block.get("table_index"),
        })

    doc_index: dict[str, Any] | None = None
    try:
        from app.services.docx_ooxml import aspose_available

        if aspose_available():
            from app.services.doc_engine.indexer import build_document_index

            doc_index = build_document_index(docx_bytes)
    except Exception:
        doc_index = None

    return {
        "version": 1,
        "section_count": len(sections),
        "table_count": len(tables),
        "empty_slot_count": len(empty_slots),
        "sections": sections[:120],
        "tables": [
            {
                "table_index": t["table_index"],
                "header": t.get("header") or "",
                "data_rows": t.get("data_rows") or 0,
                "empty_cell_count": t.get("empty_cell_count") or 0,
                "region_type": t.get("region_type") or REGION_UNKNOWN,
            }
            for t in tables[:40]
        ],
        "empty_slots": empty_slots[:100],
        "manifest_blocks": manifest_hints[:60],
        "has_index": bool(doc_index),
    }


def compact_outline_for_agent(doc_map: dict[str, Any] | None, *, max_sections: int = 25) -> dict[str, Any]:
    if not doc_map:
        return {"sections": [], "empty_slots": [], "tables": []}
    return {
        "section_count": doc_map.get("section_count") or 0,
        "table_count": doc_map.get("table_count") or 0,
        "empty_slot_count": doc_map.get("empty_slot_count") or 0,
        "sections": [
            {
                "title": s.get("title") or "",
                "region_type": s.get("region_type") or REGION_UNKNOWN,
                "allows_ai_narrative": bool(s.get("allows_ai_narrative")),
            }
            for s in (doc_map.get("sections") or [])[:max_sections]
        ],
        "empty_slots": (doc_map.get("empty_slots") or [])[:30],
        "tables": (doc_map.get("tables") or [])[:15],
    }


def region_allows_ai_narrative_write(
    docx_bytes: bytes,
    heading_title: str,
    *,
    manifest: dict[str, Any] | None = None,
    doc_map: dict[str, Any] | None = None,
) -> bool:
    title = (heading_title or "").strip()
    if not title:
        return False
    if not should_generate_ai_narrative(title, docx_bytes):
        return False
    if doc_map:
        for sec in doc_map.get("sections") or []:
            if (sec.get("title") or "").strip() == title:
                return bool(sec.get("allows_ai_narrative"))
    if manifest:
        from app.services.doc_engine.compose_policy import should_apply_ai_section_content

        fake_block = {"type": "ai_section", "title": title}
        return should_apply_ai_section_content(fake_block, docx_bytes, manifest=manifest)
    return _section_region_type(docx_bytes, title) in (
        REGION_NARRATIVE_EMPTY,
        REGION_NARRATIVE_FILLED,
    )


def outline_patch_from_docx(
    docx_bytes: bytes,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    doc_map = build_document_map(docx_bytes, manifest)
    return {OUTLINE_FIELD: doc_map}


def merge_outline_into_fields(
    fields: dict[str, Any] | None,
    docx_bytes: bytes,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(fields or {})
    out.update(outline_patch_from_docx(docx_bytes, manifest))
    return out


def read_section_payload(docx_bytes: bytes, heading_title: str, *, max_chars: int = 6000) -> dict[str, Any]:
    title = (heading_title or "").strip()
    if not title:
        return {"ok": False, "error": "缺少章节标题"}
    parts = section_slice_after_heading(docx_bytes, title)
    if not parts:
        return {"ok": False, "error": f"未找到章节：{title}"}
    paragraphs: list[str] = []
    tables: list[dict[str, Any]] = []
    t_idx = 0
    for kind, node in parts:
        if kind == "p":
            t = _paragraph_text(node).strip()
            if t:
                paragraphs.append(t)
        elif kind == "tbl":
            summary = _table_summary(docx_bytes, node, t_idx)
            tables.append({
                "table_index": summary["table_index"],
                "header": summary.get("header") or "",
                "data_rows": summary.get("data_rows") or 0,
                "empty_cell_count": summary.get("empty_cell_count") or 0,
            })
            t_idx += 1
    body = "\n".join(paragraphs)
    if len(body) > max_chars:
        body = body[: max_chars - 1] + "…"
    return {
        "ok": True,
        "title": title,
        "region_type": _section_region_type(docx_bytes, title),
        "paragraphs": paragraphs[:40],
        "text": body,
        "tables": tables,
    }
