"""按章节插入资质材料。"""
from __future__ import annotations

from io import BytesIO
from typing import Any

import aspose.words as aw

from app.services.aspose_runtime import ensure_license
from app.services.doc_engine.ocr_match import score_qual_match
from app.services.word import _insert_image_bytes


def _load(docx_bytes: bytes) -> aw.Document:
    ensure_license()
    return aw.Document(BytesIO(docx_bytes))


def _normalize_hint(s: str) -> str:
    return (s or "").strip().lower().replace(" ", "")


def match_heading_for_qual(qual: dict[str, Any], headings: list[dict[str, Any]]) -> int | None:
    """返回最匹配的标题索引（用于在该标题后插入资质）。"""
    hint = _normalize_hint(qual.get("section_hint") or "")
    name = _normalize_hint(qual.get("name") or "")
    category = _normalize_hint(qual.get("category") or "")
    ocr = _normalize_hint(qual.get("ocr_text") or "")

    best_idx = None
    best_score = 0.0
    for i, h in enumerate(headings):
        title = _normalize_hint(h.get("text") or "")
        if not title:
            continue
        score = 0.0
        if hint and (hint in title or title in hint):
            score = 0.9
        elif name and name in title:
            score = 0.7
        elif category and category in title:
            score = 0.55
        elif ocr and any(tok in title for tok in [hint, name, category] if tok):
            score = 0.4
        else:
            score = score_qual_match(qual, context=h.get("text") or "")
        if score > best_score:
            best_score = score
            best_idx = i
    return best_idx if best_score >= 0.35 else None


def insert_qualifications_by_section(
    docx_bytes: bytes,
    qual_files: list[dict[str, Any]],
    headings: list[dict[str, Any]] | None = None,
) -> bytes:
    """将资质插入到匹配章节标题之后；未匹配的留在文末。"""
    if not qual_files:
        return docx_bytes

    from app.services.doc_engine.indexer import build_document_index

    index = build_document_index(docx_bytes) if headings is None else None
    hlist = headings or [
        {"text": p.get("text"), "location": p.get("location"), "level": p.get("heading_level", 1)}
        for p in (index or {}).get("paragraphs") or []
        if p.get("is_heading")
    ]

    doc = _load(docx_bytes)
    builder = aw.DocumentBuilder(doc)
    unmatched: list[dict[str, Any]] = []

    # 按章节分组
    groups: dict[int, list[dict]] = {}
    for q in qual_files:
        idx = match_heading_for_qual(q, hlist)
        if idx is None:
            unmatched.append(q)
        else:
            groups.setdefault(idx, []).append(q)

    # 从后往前插入，避免位置偏移
    for heading_idx in sorted(groups.keys(), reverse=True):
        heading = hlist[heading_idx]
        loc = heading.get("location") or ""
        if not loc.startswith("p:"):
            unmatched.extend(groups[heading_idx])
            continue
        para_idx = int(loc.split(":")[1])
        nodes = doc.get_child_nodes(aw.NodeType.PARAGRAPH, True)
        target_para = None
        count = 0
        for i in range(nodes.count):
            para = nodes[i].as_paragraph()
            text = (para.get_text() or "").strip()
            if not text:
                continue
            if count == para_idx:
                target_para = para
                break
            count += 1
        if target_para is None:
            unmatched.extend(groups[heading_idx])
            continue
        builder.move_to(target_para)
        builder.insert_paragraph()
        for q in groups[heading_idx]:
            _insert_qual_block(builder, q)

    if unmatched:
        builder.move_to_document_end()
        builder.insert_break(aw.BreakType.PAGE_BREAK)
        builder.paragraph_format.style_identifier = aw.StyleIdentifier.HEADING1
        builder.writeln("附件：资质与证明材料")
        builder.paragraph_format.style_identifier = aw.StyleIdentifier.NORMAL
        for q in unmatched:
            _insert_qual_block(builder, q)

    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    return out.getvalue()


def _insert_qual_block(builder: aw.DocumentBuilder, q: dict[str, Any]) -> None:
    name = q.get("name") or "材料"
    category = q.get("category") or ""
    hint = q.get("section_hint") or ""
    ftype = (q.get("file_type") or "").lower().lstrip(".")
    data = q.get("data") or b""

    builder.paragraph_format.style_identifier = aw.StyleIdentifier.HEADING2
    builder.writeln(f"{category} / {name}" + (f"（{hint}）" if hint else ""))
    builder.paragraph_format.style_identifier = aw.StyleIdentifier.NORMAL
    if not data:
        builder.writeln("（文件缺失）")
        return
    try:
        if ftype in ("jpg", "jpeg", "png", "bmp", "gif", ""):
            _insert_image_bytes(builder, data)
            builder.writeln("")
        elif ftype == "docx":
            src = aw.Document(BytesIO(data))
            builder.insert_document(src, aw.ImportFormatMode.KEEP_SOURCE_FORMATTING)
            builder.writeln("")
        else:
            builder.writeln(f"[附件：{name}]")
    except Exception as exc:
        builder.writeln(f"[嵌入失败：{name} — {exc}]")
