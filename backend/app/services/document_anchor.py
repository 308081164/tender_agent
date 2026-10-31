"""文档选区锚点：段落、表格单元格 location（tbl:t:r:c）解析与补全。"""
from __future__ import annotations

import re
from typing import Any

LOC_TABLE = re.compile(r"^tbl:(\d+):r(\d+):c(\d+)$")


def anchor_has_table_cell(anchor: dict[str, Any] | None) -> bool:
    if not anchor or not anchor.get("ok"):
        return False
    loc = str(anchor.get("location") or "").strip()
    if loc.startswith("tbl:") and LOC_TABLE.match(loc):
        return True
    ti = anchor.get("table_index")
    row = anchor.get("row")
    col = anchor.get("col")
    if ti is not None and row is not None and col is not None:
        return True
    bid = str(anchor.get("block_id") or "").strip()
    return bool(bid.startswith("tbl:") and LOC_TABLE.match(bid))


def anchor_can_insert_at(anchor: dict[str, Any] | None) -> bool:
    """插图/插表：需要段落索引或明确表格单元格。"""
    if not anchor or not anchor.get("ok"):
        return False
    if anchor_has_table_cell(anchor):
        return True
    idx = anchor.get("paragraph_index")
    return idx is not None and str(idx) != ""


def normalize_table_location(anchor: dict[str, Any]) -> dict[str, Any]:
    out = dict(anchor)
    loc = str(out.get("location") or "").strip()
    bid = str(out.get("block_id") or "").strip()
    if not loc and bid.startswith("tbl:"):
        loc = bid
    if not loc and out.get("table_index") is not None:
        try:
            loc = f"tbl:{int(out['table_index'])}:r{int(out['row'])}:c{int(out['col'])}"
        except (TypeError, ValueError):
            loc = ""
    if loc and LOC_TABLE.match(loc):
        m = LOC_TABLE.match(loc)
        out["location"] = loc
        out["table_index"] = int(m.group(1))
        out["row"] = int(m.group(2))
        out["col"] = int(m.group(3))
        if not bid:
            out["block_id"] = loc
        out["in_table_cell"] = True
    return out


def read_cell_text_at_location(docx_bytes: bytes, location: str) -> str:
    m = LOC_TABLE.match((location or "").strip())
    if not m:
        return ""
    t_idx, r, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        from app.services.doc_engine.indexer import build_document_index

        index = build_document_index(docx_bytes)
    except Exception:
        return ""
    for tbl in index.get("tables") or []:
        if int(tbl.get("index", -1)) != t_idx:
            continue
        rows = tbl.get("rows") or []
        if r >= len(rows):
            return ""
        cells = rows[r]
        if c >= len(cells):
            return ""
        return str((cells[c] or {}).get("text") or "").strip()
    return ""


def lookup_table_cell_in_index(
    docx_bytes: bytes,
    *,
    selected_text: str = "",
    paragraph_index: int | None = None,
) -> dict[str, Any]:
    """用 Aspose 索引把选区落到 tbl:t:r:c（OnlyOffice 段落序号与索引不一致时的兜底）。"""
    try:
        from app.services.doc_engine.indexer import build_document_index

        index = build_document_index(docx_bytes)
    except Exception:
        return {}

    paras = index.get("paragraphs") or []
    if paragraph_index is not None:
        for p in paras:
            if p.get("index") != paragraph_index:
                continue
            loc = str(p.get("location") or "")
            if loc.startswith("tbl:"):
                return {
                    "location": loc,
                    "table_index": p.get("table_index"),
                    "row": p.get("row"),
                    "col": p.get("col"),
                    "in_table_cell": True,
                }

    needle = (selected_text or "").strip()
    if len(needle) < 1:
        return {}

    matches: list[dict[str, Any]] = []
    for tbl in index.get("tables") or []:
        t_idx = int(tbl.get("index", 0))
        for r, row in enumerate(tbl.get("rows") or []):
            for c, cell in enumerate(row):
                cell_text = str((cell or {}).get("text") or "")
                loc = str((cell or {}).get("location") or f"tbl:{t_idx}:r{r}:c{c}")
                if needle == cell_text.strip():
                    matches.append({
                        "location": loc,
                        "table_index": t_idx,
                        "row": r,
                        "col": c,
                        "in_table_cell": True,
                    })
                elif len(needle) >= 2 and needle in cell_text:
                    matches.append({
                        "location": loc,
                        "table_index": t_idx,
                        "row": r,
                        "col": c,
                        "in_table_cell": True,
                        "_partial": True,
                    })

    exact = [m for m in matches if not m.get("_partial")]
    if len(exact) == 1:
        return {k: v for k, v in exact[0].items() if k != "_partial"}
    if len(exact) > 1:
        return {}
    partial = [m for m in matches if m.get("_partial")]
    if len(partial) == 1:
        return {k: v for k, v in partial[0].items() if k != "_partial"}
    return {}


def finalize_document_anchor(anchor: dict[str, Any], docx_bytes: bytes | None = None) -> dict[str, Any]:
    if not anchor.get("ok"):
        return anchor
    out = normalize_table_location(anchor)
    if out.get("in_table_cell"):
        return out
    if docx_bytes:
        extra = lookup_table_cell_in_index(
            docx_bytes,
            selected_text=str(out.get("selected_text") or ""),
            paragraph_index=out.get("paragraph_index"),
        )
        if extra:
            out.update(extra)
            out = normalize_table_location(out)
    return out


def augment_preview_paragraphs(
    docx_bytes: bytes,
    paragraphs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """为 extract_preview 段落附加 tbl:/p: location（与 indexer 对齐）。"""
    try:
        from app.services.doc_engine.indexer import build_document_index

        index = build_document_index(docx_bytes)
        by_idx = {p.get("index"): p for p in (index.get("paragraphs") or [])}
    except Exception:
        return paragraphs
    out: list[dict[str, Any]] = []
    for item in paragraphs:
        aug = dict(item)
        idx = aug.get("index")
        rec = by_idx.get(idx)
        if rec:
            loc = str(rec.get("location") or "")
            if loc:
                aug["location"] = loc
            if rec.get("table_index") is not None:
                aug["table_index"] = rec.get("table_index")
                aug["row"] = rec.get("row")
                aug["col"] = rec.get("col")
        out.append(aug)
    return out


def merge_anchor_context_fields(
    ctx: dict[str, Any],
    args: dict[str, Any] | None,
    nested: dict[str, Any],
) -> dict[str, Any]:
    """从 context / anchor 嵌套对象读取表格坐标字段。"""
    args = args or {}

    def pick(key: str) -> Any:
        if args.get(key) is not None and args.get(key) != "":
            return args.get(key)
        if ctx.get(key) is not None and ctx.get(key) != "":
            return ctx.get(key)
        return nested.get(key)

    loc = str(pick("location") or "").strip()
    table_index = pick("table_index")
    row = pick("row")
    col = pick("col")
    return {
        "location": loc,
        "table_index": table_index,
        "row": row,
        "col": col,
    }
