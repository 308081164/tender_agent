"""图片槽绑定建议与 manifest 块更新。"""
from __future__ import annotations

from typing import Any


def suggest_image_slot_bindings(
    manifest: dict[str, Any],
    index: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """根据邻近标题/alt 为 image_slot 建议资质绑定。"""
    headings = [
        p.get("text") or ""
        for p in (index or {}).get("paragraphs") or []
        if p.get("is_heading")
    ]
    images = (index or {}).get("images") or []
    suggestions = []
    for i, block in enumerate(manifest.get("blocks") or []):
        if block.get("type") != "image_slot":
            continue
        anchor = block.get("anchor") or {}
        loc = anchor.get("location") or ""
        img_idx = int(loc.split(":")[1]) if loc.startswith("img:") and ":" in loc else i
        alt = ""
        if img_idx < len(images):
            alt = images[img_idx].get("alt") or ""
        # 取最近标题作为章节提示
        section_hint = headings[-1] if headings else ""
        qual_name = alt or block.get("bind", {}).get("qual_name") or ""
        qual_category = ""
        if "资质" in section_hint or "证明" in section_hint:
            qual_category = "企业资质包"
        elif "人员" in section_hint or "简历" in section_hint:
            qual_category = "人员资质包"
        elif "业绩" in section_hint:
            qual_category = "业绩证明"
        suggestions.append({
            "block_id": block.get("id"),
            "location": loc,
            "suggested_bind": {
                "qual_name": qual_name,
                "qual_category": qual_category,
                "section_hint": section_hint,
                "alt": alt,
            },
        })
    return suggestions


def update_manifest_block_bind(
    manifest: dict[str, Any],
    block_id: str,
    bind: dict[str, Any],
) -> dict[str, Any]:
    out = dict(manifest)
    blocks = []
    for b in manifest.get("blocks") or []:
        if b.get("id") == block_id and b.get("type") == "image_slot":
            nb = dict(b)
            nb["bind"] = {**(b.get("bind") or {}), **bind}
            blocks.append(nb)
        else:
            blocks.append(b)
    out["blocks"] = blocks
    return out
