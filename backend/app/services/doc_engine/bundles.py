"""qual_bundle / repeat_block 块处理。"""
from __future__ import annotations

import re
from io import BytesIO
from typing import Any

import aspose.words as aw

from app.services.aspose_runtime import ensure_license
from app.services.doc_engine.qual_insert import _insert_qual_block, match_heading_for_qual
from app.services.doc_engine.tables import parse_rows_data
from app.services.word import PLACEHOLDER_RE


def _load(docx_bytes: bytes) -> aw.Document:
    ensure_license()
    return aw.Document(BytesIO(docx_bytes))


def infer_qual_bundles(index: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = []
    for p in index.get("paragraphs") or []:
        if not p.get("is_heading"):
            continue
        title = (p.get("text") or "").strip()
        if not title:
            continue
        if not any(k in title for k in ("资质", "证明", "信誉", "业绩", "人员")):
            continue
        loc = p.get("location") or ""
        category = "企业资质包"
        if "人员" in title:
            category = "人员资质包"
        elif "业绩" in title:
            category = "业绩证明"
        blocks.append({
            "id": f"qual.{re.sub(r'[^\w\u4e00-\u9fff]+', '_', title)[:32]}",
            "type": "qual_bundle",
            "bind": {"category": category, "section_hint": title},
            "anchor": {"kind": "section", "location": loc, "section_hint": title},
            "required": False,
        })
    return blocks


def infer_repeat_blocks(index: dict[str, Any]) -> list[dict[str, Any]]:
    """识别带递增占位符的重复块，如 staff_1_name, staff_2_name。"""
    blocks = []
    groups: dict[str, list[dict]] = {}
    for p in index.get("paragraphs") or []:
        loc = p.get("location") or ""
        if not loc.startswith("p:"):
            continue
        text = p.get("text") or ""
        keys = PLACEHOLDER_RE.findall(text)
        for key in keys:
            m = re.match(r"^(.+?)_(\d+)_(.+)$", key)
            if not m:
                continue
            prefix = m.group(1)
            groups.setdefault(prefix, []).append({
                "location": loc,
                "text": text,
                "sample_key": key,
                "index": int(m.group(2)),
            })
    for prefix, items in groups.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda x: x["index"])
        blocks.append({
            "id": f"repeat.{prefix}",
            "type": "repeat_block",
            "bind": f"{prefix}_list",
            "template_anchor": {"location": items[0]["location"]},
            "template_text": items[0]["text"],
            "item_pattern": f"{prefix}_{{i}}_",
            "count": len(items),
            "required": False,
        })
    return blocks


def insert_qual_bundle(
    docx_bytes: bytes,
    block: dict[str, Any],
    qual_files: list[dict[str, Any]],
    headings: list[dict[str, Any]],
) -> bytes:
    bind = block.get("bind") or {}
    cat = (bind.get("category") or "").lower()
    hint = bind.get("section_hint") or ""
    matched = []
    for q in qual_files:
        qcat = (q.get("category") or "").lower()
        qhint = (q.get("section_hint") or "").lower()
        if cat and cat in qcat:
            matched.append(q)
        elif hint and (hint in qhint or hint in (q.get("name") or "")):
            matched.append(q)
    if not matched:
        return docx_bytes

    doc = _load(docx_bytes)
    builder = aw.DocumentBuilder(doc)
    idx = match_heading_for_qual({"section_hint": hint, "category": cat}, headings)
    if idx is not None and idx < len(headings):
        loc = headings[idx].get("location") or ""
        if loc.startswith("p:"):
            para_idx = int(loc.split(":")[1])
            nodes = doc.get_child_nodes(aw.NodeType.PARAGRAPH, True)
            count = 0
            target = None
            for i in range(nodes.count):
                para = nodes[i].as_paragraph()
                if not (para.get_text() or "").strip():
                    continue
                if count == para_idx:
                    target = para
                    break
                count += 1
            if target is not None:
                builder.move_to(target)
                builder.insert_paragraph()
                for q in matched:
                    _insert_qual_block(builder, q)
                out = BytesIO()
                doc.save(out, aw.SaveFormat.DOCX)
                return out.getvalue()
    return docx_bytes


def expand_repeat_block(
    docx_bytes: bytes,
    block: dict[str, Any],
    fields: dict[str, Any],
) -> bytes:
    bind = block.get("bind") or ""
    rows = parse_rows_data(fields.get(bind))
    if not rows:
        return docx_bytes
    template_text = block.get("template_text") or ""
    template_loc = (block.get("template_anchor") or {}).get("location") or ""
    if not template_text or not template_loc.startswith("p:"):
        return docx_bytes

    doc = _load(docx_bytes)
    para_idx = int(template_loc.split(":")[1])
    nodes = doc.get_child_nodes(aw.NodeType.PARAGRAPH, True)
    target = None
    count = 0
    for i in range(nodes.count):
        para = nodes[i].as_paragraph()
        if not (para.get_text() or "").strip():
            continue
        if count == para_idx:
            target = para
            break
        count += 1
    if target is None:
        return docx_bytes

    parent = target.parent_node
    insert_after = target
    for row_i, row in enumerate(rows):
        text = template_text
        for key in PLACEHOLDER_RE.findall(template_text):
            val = str(row.get(key) or fields.get(key) or "")
            # staff_1_name -> try row field suffix
            m = re.match(r"^(.+?)_\d+_(.+)$", key)
            if m and not val:
                val = str(row.get(m.group(2)) or row.get(key) or "")
            text = text.replace(f"{{{{{key}}}}}", val)
        para = aw.Paragraph(doc)
        para.append_child(aw.Run(doc, text))
        parent.insert_after(para, insert_after)
        insert_after = para
    if len(rows) > 0:
        parent.remove_child(target)

    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    return out.getvalue()
