"""文档结构化索引：段落、表格、图片、页眉脚位置锚点。"""
from __future__ import annotations

import re
from io import BytesIO
from typing import Any

import aspose.words as aw

from app.services.aspose_runtime import ensure_license
from app.services.word import AI_MARKER_RE, PLACEHOLDER_RE

LOC_PARA = re.compile(r"^p:(\d+)$")
LOC_TABLE = re.compile(r"^tbl:(\d+):r(\d+):c(\d+)$")
LOC_IMAGE = re.compile(r"^img:(\d+)$")


def _load(docx_bytes: bytes) -> aw.Document:
    ensure_license()
    return aw.Document(BytesIO(docx_bytes))


def _para_style(para: aw.Paragraph) -> str:
    style = para.paragraph_format.style
    return style.name if style else ""


def _heading_level(style_name: str) -> int:
    for ch in style_name:
        if ch.isdigit():
            return int(ch)
    if "标题" in style_name:
        return 1
    return 0


def build_document_index(docx_bytes: bytes) -> dict[str, Any]:
    """构建全文索引，供替换/审阅定位。"""
    doc = _load(docx_bytes)
    paragraphs: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []

    p_idx = 0
    for para in doc.get_child_nodes(aw.NodeType.PARAGRAPH, True):
        p = para.as_paragraph()
        text = (p.get_text() or "").strip()
        if not text:
            continue
        style = _para_style(p)
        loc = f"p:{p_idx}"
        placeholders = PLACEHOLDER_RE.findall(text)
        ai_markers = AI_MARKER_RE.findall(text)
        paragraphs.append({
            "location": loc,
            "index": p_idx,
            "text": text,
            "style": style,
            "is_heading": style.startswith("Heading") or style.startswith("标题"),
            "heading_level": _heading_level(style),
            "placeholders": placeholders,
            "ai_markers": ai_markers,
        })
        p_idx += 1

    t_idx = 0
    for tbl_node in doc.get_child_nodes(aw.NodeType.TABLE, True):
        tbl = tbl_node.as_table()
        rows_data = []
        for r, row in enumerate(tbl.rows):
            cells = []
            for c, cell in enumerate(row.cells):
                cell_text = (cell.get_text() or "").strip()
                loc = f"tbl:{t_idx}:r{r}:c{c}"
                cells.append({
                    "location": loc,
                    "text": cell_text,
                    "placeholders": PLACEHOLDER_RE.findall(cell_text),
                })
                if cell_text:
                    paragraphs.append({
                        "location": loc,
                        "index": p_idx,
                        "text": cell_text,
                        "style": "TableCell",
                        "is_heading": False,
                        "heading_level": 0,
                        "placeholders": PLACEHOLDER_RE.findall(cell_text),
                        "ai_markers": [],
                        "table_index": t_idx,
                        "row": r,
                        "col": c,
                    })
                    p_idx += 1
            rows_data.append(cells)
        tables.append({"index": t_idx, "rows": rows_data})
        t_idx += 1

    img_idx = 0
    for shape in doc.get_child_nodes(aw.NodeType.SHAPE, True):
        shape_obj = shape.as_shape()
        if not shape_obj.has_image:
            continue
        alt = ""
        try:
            alt = shape_obj.title or shape_obj.name or ""
        except Exception:
            pass
        images.append({
            "location": f"img:{img_idx}",
            "index": img_idx,
            "alt": alt,
            "width": float(shape_obj.width),
            "height": float(shape_obj.height),
        })
        img_idx += 1

    full_text = "\n".join(x["text"] for x in paragraphs if x.get("location", "").startswith("p:"))
    return {
        "paragraphs": paragraphs,
        "tables": tables,
        "images": images,
        "full_text": full_text,
        "placeholder_keys": sorted(set(PLACEHOLDER_RE.findall(full_text))),
        "ai_markers": sorted(set(AI_MARKER_RE.findall(full_text))),
    }


def replace_at_location(
    docx_bytes: bytes,
    location: str,
    new_text: str,
    *,
    highlight: bool = False,
) -> bytes:
    doc = _load(docx_bytes)
    options = aw.replacing.FindReplaceOptions()
    if highlight:
        try:
            options.apply_font.highlight_color = aw.HighlightColor.YELLOW
        except Exception:
            pass

    m = LOC_PARA.match(location)
    if m:
        idx = int(m.group(1))
        nodes = doc.get_child_nodes(aw.NodeType.PARAGRAPH, True)
        count = 0
        for i in range(nodes.count):
            para = nodes[i].as_paragraph()
            text = (para.get_text() or "").strip()
            if not text:
                continue
            if count == idx:
                para.remove_all_children()
                run = aw.Run(doc, new_text or "")
                para.append_child(run)
                break
            count += 1
    else:
        m = LOC_TABLE.match(location)
        if m:
            t_idx, r, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
            tbl_nodes = doc.get_child_nodes(aw.NodeType.TABLE, True)
            if t_idx < tbl_nodes.count:
                tbl = tbl_nodes[t_idx].as_table()
                if r < tbl.rows.count and c < tbl.rows[r].cells.count:
                    cell = tbl.rows[r].cells[c]
                    cell.remove_all_children()
                    p = aw.Paragraph(doc)
                    p.append_child(aw.Run(doc, new_text or ""))
                    cell.append_child(p)

    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    return out.getvalue()


def replace_image_at_location(
    docx_bytes: bytes,
    location: str,
    image_bytes: bytes,
    *,
    width_pt: float | None = None,
) -> bytes:
    m = LOC_IMAGE.match(location)
    if not m or not image_bytes:
        return docx_bytes
    idx = int(m.group(1))
    doc = _load(docx_bytes)
    img_count = 0
    for shape in doc.get_child_nodes(aw.NodeType.SHAPE, True):
        shape_obj = shape.as_shape()
        if not shape_obj.has_image:
            continue
        if img_count == idx:
            w = width_pt or float(shape_obj.width)
            shape_obj.image_data.set_image(BytesIO(image_bytes))
            if w:
                shape_obj.width = w
            break
        img_count += 1
    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    return out.getvalue()


def replace_text_in_paragraph_index(
    docx_bytes: bytes,
    para_index: int,
    old_text: str,
    new_text: str,
    *,
    highlight: bool = False,
) -> bytes:
    """在指定段落索引内替换子串（位置感知，不全局替换）。"""
    doc = _load(docx_bytes)
    options = aw.replacing.FindReplaceOptions()
    if highlight:
        try:
            options.apply_font.highlight_color = aw.HighlightColor.YELLOW
        except Exception:
            pass
    nodes = doc.get_child_nodes(aw.NodeType.PARAGRAPH, True)
    count = 0
    for i in range(nodes.count):
        para = nodes[i].as_paragraph()
        text = (para.get_text() or "").strip()
        if not text:
            continue
        if count == para_index:
            # 段落级 find replace scoped by rebuilding if old in text
            full = para.get_text() or ""
            if old_text and old_text in full:
                new_full = full.replace(old_text, new_text, 1)
                para.remove_all_children()
                para.append_child(aw.Run(doc, new_full))
            break
        count += 1
    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    return out.getvalue()
