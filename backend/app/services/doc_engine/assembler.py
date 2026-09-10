"""块级文档装配器。"""
from __future__ import annotations

from typing import Any

from app.services import word
from app.services.doc_engine.indexer import replace_at_location, replace_image_at_location
from app.services.doc_engine.replacement import apply_image_replacements


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

    # 按 manifest 块写入（位置锚点）
    blocks = manifest.get("blocks") or []
    contents = block_contents or {}
    for block in blocks:
        btype = block.get("type")
        anchor = block.get("anchor") or {}
        loc = anchor.get("location")
        if not loc:
            continue
        if btype == "field_slot":
            key = block.get("bind") or ""
            val = fields.get(key) or contents.get(key) or ""
            if val and loc:
                data = replace_at_location(data, loc, str(val), highlight=highlight)
        elif btype == "ai_section":
            title = block.get("title") or ""
            val = (
                contents.get(block.get("id") or "")
                or contents.get(title)
                or (ch.get(title) or {}).get("content")
                or ""
            )
            if val:
                marker = f"【AI_GENERATED:{title}】"
                data = replace_at_location(data, loc, val if marker not in val else val, highlight=highlight)

    if image_bindings:
        data = apply_image_replacements(data, image_bindings)

    return data
