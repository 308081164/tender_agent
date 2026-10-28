"""块级文档装配器。"""
from __future__ import annotations

from typing import Any

from app.services import word
from app.services.doc_engine.indexer import insert_text_after_heading, replace_at_location
from app.services.doc_engine.replacement import apply_image_replacements
from app.services.doc_engine.sdt import normalize_tag, write_sdt_text
from app.services.doc_engine.bundles import expand_repeat_block, insert_qual_bundle
from app.services.doc_engine.compose_policy import (
    filter_chapters_for_render,
    should_apply_ai_section_content,
)
from app.services.doc_engine.tables import fill_table_slot, resolve_table_rows


def _fill_parenthesis_form_tokens(
    docx_bytes: bytes,
    fields: dict[str, Any],
    *,
    highlight: bool = False,
) -> bytes:
    """铁路等空白模板竞标函括号占位 → 第二步字段值。"""
    lower = str(fields.get("bid_amount_lower") or fields.get("bid_amount") or "").strip()
    upper = str(
        fields.get("bid_amount_upper") or fields.get("bid_amount") or ""
    ).strip()
    pairs: list[tuple[str, str]] = []
    token_map = (
        ("（谈判编号）", "tender_no"),
        ("(谈判编号)", "tender_no"),
        ("（包件号）", "package_no"),
        ("(包件号)", "package_no"),
        ("（物资类别/名称）", "material_type"),
        ("(物资类别/名称)", "material_type"),
    )
    for token, key in token_map:
        val = str(fields.get(key) or "").strip()
        if val:
            pairs.append((token, val))
    if lower and upper:
        pairs.extend([
            ("人民币（小写）元整（大写元整）", f"人民币{lower}元整（{upper}）"),
            ("人民币(小写)元整(大写元整)", f"人民币{lower}元整（{upper}）"),
            ("（大写元整）", upper),
            ("(大写元整)", upper),
        ])
    elif lower:
        pairs.append(("（小写）", lower))
    if not pairs:
        return docx_bytes
    return word.apply_literal_replacements(docx_bytes, pairs, highlight=highlight)


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
    from app.services.creation_draft import apply_railway_blank_cover_lines

    data = apply_railway_blank_cover_lines(data, fields)

    # AI 章节与块内容写入（结构化函件/表单章节不写入整段叙事，避免重复）
    ch = dict(filter_chapters_for_render(chapters or {}, docx_bytes))
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

    # 按 manifest 块写入（先 field/table，再 ai_section）
    blocks = manifest.get("blocks") or []
    contents = block_contents or {}
    used_locations: set[str] = set()

    def _apply_table(block: dict) -> None:
        nonlocal data
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

    for block in blocks:
        if block.get("type") != "field_slot":
            continue
        anchor = block.get("anchor") or {}
        loc = anchor.get("location")
        sdt_tag = anchor.get("tag") if anchor.get("kind") == "sdt" else ""
        if not sdt_tag:
            sdt_tag = normalize_tag(block.get("id") or "") if anchor.get("kind") == "sdt" else ""
        key = block.get("bind") or ""
        val = fields.get(key) or contents.get(key) or ""
        if not val:
            continue
        if sdt_tag:
            data = write_sdt_text(data, sdt_tag, str(val), highlight=highlight)
        elif loc:
            data = replace_at_location(data, loc, str(val), highlight=highlight)

    for block in blocks:
        if block.get("type") == "table_slot":
            _apply_table(block)

    for block in blocks:
        if block.get("type") != "ai_section":
            continue
        if not should_apply_ai_section_content(block, data, manifest=manifest):
            continue
        anchor = block.get("anchor") or {}
        loc = anchor.get("location")
        sdt_tag = anchor.get("tag") if anchor.get("kind") == "sdt" else ""
        if not sdt_tag:
            sdt_tag = normalize_tag(block.get("id") or "") if anchor.get("kind") == "sdt" else ""
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
        elif title:
            data = insert_text_after_heading(data, title, text, highlight=highlight)
        elif loc and loc not in used_locations:
            data = replace_at_location(data, loc, text, highlight=highlight)
            used_locations.add(loc)

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

    data = _fill_parenthesis_form_tokens(data, fields, highlight=highlight)

    return data
