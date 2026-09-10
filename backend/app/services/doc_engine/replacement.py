"""替换模式：位置感知替换 + 图片适配。"""
from __future__ import annotations

from typing import Any

from app.services import word
from app.services.doc_engine.indexer import (
    replace_at_location,
    replace_image_at_location,
    replace_text_in_paragraph_index,
)


def apply_field_replacements(
    docx_bytes: bytes,
    fields: dict[str, Any],
    snapshot: dict[str, Any] | None,
    *,
    highlight: bool = False,
) -> bytes:
    """优先按快照位置替换，再占位符/智能替换兜底。"""
    data = docx_bytes
    snap = snapshot or {}
    field_snap = snap.get("fields") if isinstance(snap.get("fields"), dict) else snap

    replaced_keys: set[str] = set()

    # 历史标书：旧值→新值（位置优先）
    if isinstance(field_snap, dict):
        for key, new_val in fields.items():
            if key.startswith("ai::"):
                continue
            new_s = str(new_val or "").strip()
            if not new_s:
                continue
            entry = field_snap.get(key)
            if not isinstance(entry, dict):
                continue
            old_val = str(entry.get("value") or "").strip()
            if not old_val or old_val == new_s:
                continue
            for loc_info in entry.get("locations") or []:
                loc = loc_info.get("location") or ""
                if loc.startswith("p:"):
                    idx = int(loc.split(":")[1])
                    data = replace_text_in_paragraph_index(
                        data, idx, old_val, new_s, highlight=highlight
                    )
                    replaced_keys.add(key)
                elif loc.startswith("tbl:"):
                    ctx = loc_info.get("context") or old_val
                    if old_val in ctx:
                        data = replace_at_location(
                            data, loc, ctx.replace(old_val, new_s, 1), highlight=highlight
                        )
                        replaced_keys.add(key)

    chapters = {
        k: v for k, v in (fields or {}).items()
        if k.startswith("ai::")
    }
    plain_fields = {k: v for k, v in (fields or {}).items() if not k.startswith("ai::")}

    # 占位符 + 未位置替换的字段兜底
    legacy_snap = None
    if isinstance(field_snap, dict):
        legacy_snap = {
            k: (v.get("value") if isinstance(v, dict) else v)
            for k, v in field_snap.items()
            if k not in replaced_keys
        }
    elif field_snap:
        legacy_snap = field_snap

    data = word.render_document(
        data,
        plain_fields,
        {k: {"content": v} for k, v in chapters.items()} if chapters else None,
        highlight=highlight,
        source_snapshot=legacy_snap if legacy_snap else None,
    )
    return data


def apply_image_replacements(
    docx_bytes: bytes,
    image_bindings: list[dict[str, Any]],
) -> bytes:
    data = docx_bytes
    for bind in image_bindings or []:
        loc = bind.get("location") or (bind.get("anchor") or {}).get("location")
        img_bytes = bind.get("data") or b""
        if loc and img_bytes:
            data = replace_image_at_location(
                data, loc, img_bytes, width_pt=bind.get("width_pt")
            )
    return data


def build_image_bindings_from_quals(
    manifest: dict[str, Any],
    qual_files: list[dict[str, Any]],
    snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """根据 manifest 图片槽与资质文件生成绑定。"""
    bindings: list[dict[str, Any]] = []
    blocks = [b for b in (manifest.get("blocks") or []) if b.get("type") == "image_slot"]
    snap_images = (snapshot or {}).get("images") or []

    qual_by_name = {(q.get("name") or "").lower(): q for q in qual_files}
    qual_by_cat: dict[str, list] = {}
    for q in qual_files:
        qual_by_cat.setdefault((q.get("category") or "").lower(), []).append(q)

    for i, block in enumerate(blocks):
        anchor = block.get("anchor") or {}
        loc = anchor.get("location") or (
            snap_images[i].get("location") if i < len(snap_images) else ""
        )
        bind = block.get("bind") or {}
        qname = (bind.get("qual_name") or "").lower()
        qcat = (bind.get("qual_category") or "").lower()
        qual = qual_by_name.get(qname) if qname else None
        if not qual and qcat:
            cands = qual_by_cat.get(qcat) or []
            qual = cands[0] if cands else None
        if not qual and qual_files:
            qual = qual_files[min(i, len(qual_files) - 1)]
        ftype = str(qual.get("file_type", "")).lower().lstrip(".") if qual else ""
        if qual and qual.get("data") and ftype in ("jpg", "jpeg", "png", "bmp", "gif", ""):
            bindings.append({
                "location": loc,
                "data": qual.get("data"),
                "width_pt": bind.get("width_pt") or 420,
            })
    return bindings
