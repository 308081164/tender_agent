"""模板解析器：从 DOCX 生成 Template Manifest v2。"""
from __future__ import annotations

import re
from typing import Any

from app.services.doc_engine.indexer import build_document_index
from app.services.doc_engine.manifest import empty_manifest, infer_mode
from app.services.doc_engine.sdt import list_sdt_tags, normalize_tag
from app.services.doc_engine.tables import infer_table_slots
from app.services.word import AI_MARKER_RE, PLACEHOLDER_RE


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", s.strip())
    return s[:48] or "block"


def parse_template_manifest(
    docx_bytes: bytes,
    *,
    is_history: bool = False,
    field_defs: list[dict] | None = None,
) -> dict[str, Any]:
    """解析文档结构，生成 manifest blocks。"""
    index = build_document_index(docx_bytes)
    blocks: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    # 1) 已有 {{key}} 占位符
    for para in index["paragraphs"]:
        loc = para.get("location") or ""
        text = para.get("text") or ""
        for key in para.get("placeholders") or PLACEHOLDER_RE.findall(text):
            if key in seen_keys:
                continue
            seen_keys.add(key)
            blocks.append({
                "id": f"field.{key}",
                "type": "field_slot",
                "bind": key,
                "anchor": {"kind": "location", "location": loc},
                "required": True,
                "sample": text[:200],
            })

    # 2) AI 章节标记
    for para in index["paragraphs"]:
        loc = para.get("location") or ""
        text = para.get("text") or ""
        for marker in para.get("ai_markers") or AI_MARKER_RE.findall(text):
            bid = f"ai.{_slug(marker)}"
            if bid in seen_keys:
                continue
            seen_keys.add(bid)
            blocks.append({
                "id": bid,
                "type": "ai_section",
                "title": marker,
                "anchor": {"kind": "location", "location": loc},
                "required": True,
                "sample": text[:200],
            })

    # 3) 图片槽
    for img in index.get("images") or []:
        loc = img.get("location") or ""
        bid = f"image.{img.get('index', 0)}"
        blocks.append({
            "id": bid,
            "type": "image_slot",
            "bind": {"qual_category": "", "qual_name": img.get("alt") or ""},
            "anchor": {"kind": "location", "location": loc},
            "insert_policy": "replace_in_place",
            "required": False,
        })

    # 4) 空白/结构模板：标题下空段或极短段 → ai_section 候选
    if not is_history and len([b for b in blocks if b["type"] == "ai_section"]) < 2:
        paras = index["paragraphs"]
        for i, para in enumerate(paras):
            if not para.get("is_heading"):
                continue
            title = (para.get("text") or "").strip()
            if not title or len(title) > 80:
                continue
            # 看下一段是否为空或占位
            next_para = paras[i + 1] if i + 1 < len(paras) else None
            if not next_para:
                continue
            ntext = (next_para.get("text") or "").strip()
            if len(ntext) > 30 and "【AI_GENERATED" not in ntext:
                continue
            bid = f"ai.{_slug(title)}"
            if bid in seen_keys:
                continue
            seen_keys.add(bid)
            blocks.append({
                "id": bid,
                "type": "ai_section",
                "title": title,
                "anchor": {"kind": "location", "location": next_para.get("location")},
                "required": False,
                "inferred": True,
            })

    # 5) 表格槽
    seen_table_ids: set[str] = set()
    for tbl_block in infer_table_slots(index):
        bid = tbl_block.get("id") or ""
        if bid and bid not in seen_table_ids:
            seen_table_ids.add(bid)
            blocks.append(tbl_block)

    # 6) SDT 锚点优先（若文档已注入内容控件）
    sdt_tags = list_sdt_tags(docx_bytes)
    if sdt_tags:
        for block in blocks:
            tag = normalize_tag(block.get("id") or "")
            if tag in sdt_tags:
                block["anchor"] = {
                    "kind": "sdt",
                    "tag": tag,
                    "location": (block.get("anchor") or {}).get("location"),
                }

    mode = infer_mode(
        blocks,
        len(index.get("placeholder_keys") or []),
        is_history,
    )
    manifest = empty_manifest(mode)
    manifest["blocks"] = blocks
    if sdt_tags:
        manifest["sdt_tags"] = sorted(sdt_tags.keys())
    manifest["index_stats"] = {
        "paragraphs": len(index.get("paragraphs") or []),
        "tables": len(index.get("tables") or []),
        "images": len(index.get("images") or []),
        "placeholder_keys": index.get("placeholder_keys") or [],
        "ai_markers": index.get("ai_markers") or [],
    }
    return manifest


def enrich_snapshot_with_locations(
    docx_bytes: bytes,
    field_values: dict[str, str],
) -> dict[str, Any]:
    """为替换模式构建带位置信息的快照。"""
    index = build_document_index(docx_bytes)
    snapshot: dict[str, Any] = {"fields": {}, "images": []}
    for key, value in (field_values or {}).items():
        if not value:
            continue
        val = str(value).strip()
        locations = []
        for para in index["paragraphs"]:
            if val in (para.get("text") or ""):
                locations.append({
                    "location": para.get("location"),
                    "context": (para.get("text") or "")[:300],
                })
        snapshot["fields"][key] = {"value": val, "locations": locations}
    for img in index.get("images") or []:
        snapshot["images"].append({
            "location": img.get("location"),
            "alt": img.get("alt") or "",
        })
    return snapshot
