"""模板语义清单 v2：块类型、锚点与模式定义。"""
from __future__ import annotations

from typing import Any, Literal

MANIFEST_VERSION = 2

BlockType = Literal[
    "field_slot",
    "ai_section",
    "static_slot",
    "image_slot",
    "table_slot",
    "qual_bundle",
    "repeat_block",
]

DocMode = Literal["create", "replace", "hybrid"]


def empty_manifest(mode: DocMode = "hybrid") -> dict[str, Any]:
    return {
        "version": MANIFEST_VERSION,
        "mode": mode,
        "blocks": [],
        "style_profile": {},
    }


def get_manifest(placeholders: dict | None) -> dict[str, Any] | None:
    ph = placeholders or {}
    m = ph.get("manifest_v2")
    return m if isinstance(m, dict) and m.get("version") == MANIFEST_VERSION else None


def set_manifest(placeholders: dict | None, manifest: dict[str, Any]) -> dict:
    ph = dict(placeholders or {})
    ph["manifest_v2"] = manifest
    return ph


def infer_mode(blocks: list[dict], placeholder_count: int, is_history: bool) -> DocMode:
    if is_history:
        return "replace"
    ai_count = sum(1 for b in blocks if b.get("type") == "ai_section")
    field_count = sum(1 for b in blocks if b.get("type") == "field_slot")
    if ai_count >= 2 and field_count >= 2:
        return "hybrid"
    if ai_count >= 1 and placeholder_count < 3:
        return "create"
    if field_count >= 3 or placeholder_count >= 3:
        return "hybrid"
    return "create"


def block_by_id(manifest: dict[str, Any], block_id: str) -> dict | None:
    for b in manifest.get("blocks") or []:
        if b.get("id") == block_id:
            return b
    return None
