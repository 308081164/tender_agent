"""SDT 内容控件：工程化锚点注入与读写。"""
from __future__ import annotations

import re
from io import BytesIO
from typing import Any

import aspose.words as aw

from app.services.aspose_runtime import ensure_license

TAG_PREFIX = "tender."


def normalize_tag(block_id: str) -> str:
    bid = (block_id or "").strip()
    if bid.startswith(TAG_PREFIX):
        return bid
    return f"{TAG_PREFIX}{bid}"


def tag_to_block_id(tag: str) -> str:
    t = (tag or "").strip()
    if t.startswith(TAG_PREFIX):
        return t[len(TAG_PREFIX):]
    return t


def _load(docx_bytes: bytes) -> aw.Document:
    ensure_license()
    return aw.Document(BytesIO(docx_bytes))


def list_sdt_tags(docx_bytes: bytes) -> dict[str, dict[str, Any]]:
    """扫描文档内 SDT，返回 tag -> {text, location_hint}。"""
    doc = _load(docx_bytes)
    result: dict[str, dict[str, Any]] = {}
    for node in doc.get_child_nodes(aw.NodeType.STRUCTURED_DOCUMENT_TAG, True):
        sdt = node.as_structured_document_tag()
        tag = (sdt.tag or "").strip()
        if not tag.startswith(TAG_PREFIX):
            continue
        result[tag] = {
            "tag": tag,
            "block_id": tag_to_block_id(tag),
            "title": (sdt.title or "").strip(),
            "text": (sdt.get_text() or "").strip(),
        }
    return result


def write_sdt_text(docx_bytes: bytes, tag: str, new_text: str, *, highlight: bool = False) -> bytes:
    """按 SDT tag 写入文本。"""
    if not tag:
        return docx_bytes
    doc = _load(docx_bytes)
    for node in doc.get_child_nodes(aw.NodeType.STRUCTURED_DOCUMENT_TAG, True):
        sdt = node.as_structured_document_tag()
        if (sdt.tag or "").strip() != tag:
            continue
        sdt.remove_all_children()
        para = aw.Paragraph(doc)
        run = aw.Run(doc, new_text or "")
        if highlight:
            try:
                run.font.highlight_color = aw.HighlightColor.YELLOW
            except Exception:
                pass
        para.append_child(run)
        sdt.append_child(para)
        break
    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    return out.getvalue()


def write_sdt_image(docx_bytes: bytes, tag: str, image_bytes: bytes, *, width_pt: float = 420) -> bytes:
    if not tag or not image_bytes:
        return docx_bytes
    doc = _load(docx_bytes)
    for node in doc.get_child_nodes(aw.NodeType.STRUCTURED_DOCUMENT_TAG, True):
        sdt = node.as_structured_document_tag()
        if (sdt.tag or "").strip() != tag:
            continue
        sdt.remove_all_children()
        para = aw.Paragraph(doc)
        builder = aw.DocumentBuilder(doc)
        builder.move_to(para)
        builder.insert_image(BytesIO(image_bytes), width_pt, 0)
        sdt.append_child(para)
        break
    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    return out.getvalue()


def _wrap_paragraph_with_sdt(doc: aw.Document, para: aw.Paragraph, tag: str, title: str = "") -> None:
    parent = para.parent_node
    if parent is None:
        return
    sdt = aw.StructuredDocumentTag(doc, aw.SdtType.RICH_TEXT, aw.MarkupLevel.BLOCK)
    sdt.tag = tag
    if title:
        sdt.title = title
    parent.insert_before(sdt, para)
    sdt.append_child(para.clone(True))
    parent.remove_child(para)


def _wrap_table_cell_with_sdt(doc: aw.Document, cell: aw.Cell, tag: str, title: str = "") -> None:
    sdt = aw.StructuredDocumentTag(doc, aw.SdtType.RICH_TEXT, aw.MarkupLevel.CELL)
    sdt.tag = tag
    if title:
        sdt.title = title
    first_para = cell.first_paragraph
    if first_para is None:
        para = aw.Paragraph(doc)
        cell.append_child(para)
        first_para = para
    cell.insert_before(sdt, first_para)
    sdt.append_child(first_para.clone(True))
    if first_para.parent_node == cell:
        cell.remove_child(first_para)


def inject_sdt_anchors(docx_bytes: bytes, manifest: dict[str, Any]) -> bytes:
    """为 manifest 块在文档中注入 SDT 锚点（保留原段落/单元格内容）。"""
    from app.services.doc_engine.indexer import LOC_IMAGE, LOC_PARA, LOC_TABLE

    doc = _load(docx_bytes)
    blocks = manifest.get("blocks") or []
    if not blocks:
        out = BytesIO()
        doc.save(out, aw.SaveFormat.DOCX)
        return out.getvalue()

    for block in blocks:
        anchor = block.get("anchor") or {}
        loc = anchor.get("location") or ""
        tag = normalize_tag(block.get("id") or "")
        title = block.get("title") or block.get("bind") or tag_to_block_id(tag)

        m = LOC_PARA.match(loc)
        if m:
            idx = int(m.group(1))
            count = 0
            nodes = doc.get_child_nodes(aw.NodeType.PARAGRAPH, True)
            for i in range(nodes.count):
                para = nodes[i].as_paragraph()
                text = (para.get_text() or "").strip()
                if not text:
                    continue
                if count == idx:
                    _wrap_paragraph_with_sdt(doc, para, tag, str(title))
                    break
                count += 1
            continue

        m = LOC_TABLE.match(loc)
        if m:
            t_idx, r, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
            tbl_nodes = doc.get_child_nodes(aw.NodeType.TABLE, True)
            if t_idx < tbl_nodes.count:
                tbl = tbl_nodes[t_idx].as_table()
                if r < tbl.rows.count and c < tbl.rows[r].cells.count:
                    _wrap_table_cell_with_sdt(doc, tbl.rows[r].cells[c], tag, str(title))
            continue

        m = LOC_IMAGE.match(loc)
        if m:
            # 图片槽：在图片所在段落外包 SDT（若找不到则跳过）
            idx = int(m.group(1))
            img_count = 0
            for shape in doc.get_child_nodes(aw.NodeType.SHAPE, True):
                shape_obj = shape.as_shape()
                if not shape_obj.has_image:
                    continue
                if img_count == idx:
                    para = shape_obj.parent_node
                    if para and para.node_type == aw.NodeType.PARAGRAPH:
                        _wrap_paragraph_with_sdt(doc, para.as_paragraph(), tag, str(title))
                    break
                img_count += 1

    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    return out.getvalue()


def enrich_manifest_with_sdt(manifest: dict[str, Any], docx_bytes: bytes) -> dict[str, Any]:
    """将 manifest 中已有 location 锚点升级为 SDT 锚点（若文档中存在对应 tag）。"""
    tags = list_sdt_tags(docx_bytes)
    if not tags:
        return manifest
    blocks = []
    for block in manifest.get("blocks") or []:
        bid = block.get("id") or ""
        tag = normalize_tag(bid)
        if tag in tags:
            nb = dict(block)
            nb["anchor"] = {"kind": "sdt", "tag": tag, "location": (block.get("anchor") or {}).get("location")}
            blocks.append(nb)
        else:
            blocks.append(block)
    out = dict(manifest)
    out["blocks"] = blocks
    out["sdt_tags"] = sorted(tags.keys())
    return out
