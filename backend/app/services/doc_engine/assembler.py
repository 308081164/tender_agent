"""块级文档装配器。"""
from __future__ import annotations

from typing import Any

from app.services import word
from app.services.doc_engine.indexer import replace_at_location
from app.services.doc_engine.replacement import apply_image_replacements
from app.services.doc_engine.sdt import normalize_tag, write_sdt_text
from app.services.doc_engine.bundles import expand_repeat_block, insert_qual_bundle
from app.services.doc_engine.tables import fill_table_slot, resolve_table_rows


def assemble_document(
    docx_bytes: bytes,
    manifest: dict[str, Any],
    fields: dict[str, Any],
    chapters: dict[str, Any] | None = None,
    *,
    source_snapshot: dict | None = None,
    highlight: bool = False,
    image_bindings: list[dict] | None = None,
    block_contents: dict[str, str] | None = None,
    qual_files: list[dict] | None = None,
    doc_index: dict | None = None,
) -> bytes:
    """按 manifest 块级装配文档。"""
    from app.services.doc_engine.replacement import apply_field_replacements

    data = apply_field_replacements(
        docx_bytes,
        fields,
        source_snapshot,
        highlight=highlight,
    )

    # AI 章节与块内容写入
    ch = dict(chapters or {})
    if block_contents:
        for k, v in block_contents.items():
            if k and v:
                ch[k] = {"content": v, "source": "ai"}

    if ch:
        data = word.render_document(
            data,
            fields,
            ch,
            highlight=highlight,
            source_snapshot=None,
        )

    # 按 manifest 块写入（SDT 或位置锚点）
    blocks = manifest.get("blocks") or []
    contents = block_contents or {}
    for block in blocks:
        btype = block.get("type")
        anchor = block.get("anchor") or {}
        loc = anchor.get("location")
        sdt_tag = anchor.get("tag") if anchor.get("kind") == "sdt" else ""
        if not sdt_tag:
            sdt_tag = normalize_tag(block.get("id") or "") if anchor.get("kind") == "sdt" else ""

        if btype == "table_slot":
            rows = resolve_table_rows(block, fields)
            if rows:
                data = fill_table_slot(
                    data,
                    int(block.get("table_index") or 0),
                    block.get("columns") or [],
                    rows,
                    header_rows=int(block.get("header_rows") or 1),
                    template_row=block.get("template_row"),
                )
            continue

        if btype == "field_slot":
            key = block.get("bind") or ""
            val = fields.get(key) or contents.get(key) or ""
            if not val:
                continue
            if sdt_tag:
                data = write_sdt_text(data, sdt_tag, str(val), highlight=highlight)
            elif loc:
                data = replace_at_location(data, loc, str(val), highlight=highlight)
        elif btype == "ai_section":
            title = block.get("title") or ""
            val = (
                contents.get(block.get("id") or "")
                or contents.get(title)
                or (ch.get(title) or {}).get("content")
                or ""
            )
            if not val:
                continue
            marker = f"【AI_GENERATED:{title}】"
            text = val if marker not in val else val
            if sdt_tag:
                data = write_sdt_text(data, sdt_tag, text, highlight=highlight)
            elif loc:
                data = replace_at_location(data, loc, text, highlight=highlight)

    if image_bindings:
        data = apply_image_replacements(data, image_bindings)

    headings = [
        {"text": p.get("text"), "location": p.get("location"), "level": p.get("heading_level", 1)}
        for p in (doc_index or {}).get("paragraphs") or []
        if p.get("is_heading")
    ]
    for block in blocks:
        if block.get("type") == "qual_bundle" and qual_files:
            data = insert_qual_bundle(data, block, qual_files, headings)
        elif block.get("type") == "repeat_block":
            data = expand_repeat_block(data, block, fields)

    return data
