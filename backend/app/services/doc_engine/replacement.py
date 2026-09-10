"""替换模式：位置感知替换 + 图片适配。"""
from __future__ import annotations

from typing import Any

from app.services import word
from app.services.doc_engine.indexer import (
    replace_at_location,
    replace_image_at_location,
    replace_text_in_paragraph_index,
)
from app.services.doc_engine.ocr_match import rank_quals_for_slot
from app.services.doc_engine.sdt import normalize_tag, write_sdt_image, write_sdt_text


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
        img_bytes = bind.get("data") or b""
        if not img_bytes:
            continue
        sdt_tag = bind.get("sdt_tag") or ""
        if sdt_tag:
            data = write_sdt_image(data, sdt_tag, img_bytes, width_pt=bind.get("width_pt") or 420)
            continue
        loc = bind.get("location") or (bind.get("anchor") or {}).get("location")
        if loc:
            data = replace_image_at_location(
                data, loc, img_bytes, width_pt=bind.get("width_pt")
            )
    return data


def build_image_bindings_from_quals(
    manifest: dict[str, Any],
    qual_files: list[dict[str, Any]],
    snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """根据 manifest 图片槽与资质文件生成绑定（含 OCR/文本匹配）。"""
    bindings: list[dict[str, Any]] = []
    blocks = [b for b in (manifest.get("blocks") or []) if b.get("type") == "image_slot"]
    snap_images = (snapshot or {}).get("images") or []
    used_qual_ids: set[str] = set()

    for i, block in enumerate(blocks):
        anchor = block.get("anchor") or {}
        loc = anchor.get("location") or (
            snap_images[i].get("location") if i < len(snap_images) else ""
        )
        sdt_tag = anchor.get("tag") if anchor.get("kind") == "sdt" else normalize_tag(block.get("id") or "")
        bind = block.get("bind") or {}
        context = str(bind.get("qual_name") or snap_images[i].get("alt") if i < len(snap_images) else "")
        available = [q for q in qual_files if (q.get("name") or q.get("category")) not in used_qual_ids]
        ranked = rank_quals_for_slot(available or qual_files, bind, context=context)
        qual = ranked[0] if ranked else None
        if qual:
            used_qual_ids.add(qual.get("name") or qual.get("category") or str(i))
        ftype = str(qual.get("file_type", "")).lower().lstrip(".") if qual else ""
        if qual and qual.get("data") and ftype in ("jpg", "jpeg", "png", "bmp", "gif", ""):
            bindings.append({
                "location": loc,
                "sdt_tag": sdt_tag,
                "data": qual.get("data"),
                "qual_name": qual.get("name"),
                "width_pt": bind.get("width_pt") or 420,
            })
    return bindings
