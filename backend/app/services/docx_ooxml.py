"""不依赖 Aspose 的 docx 读写。工具环用它真正改段落、插表、插图。"""
from __future__ import annotations

import os
import sys
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import xml.etree.ElementTree as ET

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC = "http://schemas.openxmlformats.org/drawingml/2006/picture"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"w": W, "r": R, "wp": WP, "a": A, "pic": PIC}

ET.register_namespace("w", W)
ET.register_namespace("r", R)


def aspose_available() -> bool:
    if os.environ.get("TENDER_DISABLE_ASPOSE") == "1":
        return False
    mod = sys.modules.get("aspose.words")
    if mod is None:
        try:
            import aspose.words as mod
        except Exception:
            return False
    if type(mod).__name__ == "MagicMock":
        return False
    document = getattr(mod, "Document", None)
    if not (callable(document) and type(document).__name__ != "MagicMock"):
        return False
    from app.services.aspose_runtime import aspose_runtime_usable
    return aspose_runtime_usable()


def build_docx(paragraphs: list[str]) -> bytes:
    body = "".join(_paragraph_xml(text) for text in paragraphs) or _paragraph_xml("")
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>{body}'
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Types xmlns="{CT}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{PR}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{PR}"></Relationships>'
    )
    return _pack({
        "[Content_Types].xml": content_types.encode(),
        "_rels/.rels": rels.encode(),
        "word/document.xml": document.encode(),
        "word/_rels/document.xml.rels": doc_rels.encode(),
    })


def paragraphs(docx_bytes: bytes) -> list[str]:
    root = _document_root(docx_bytes)
    return [_paragraph_text(node) for node in _body_paragraphs(root)]


def plain_text(docx_bytes: bytes) -> str:
    return "\n".join(paragraphs(docx_bytes))


def document_text(docx_bytes: bytes) -> str:
    """正文和表格单元格都按段输出，招标解析不能只看顶层段落。"""
    root = _document_root(docx_bytes)
    lines = []
    for node in _body(root).iter(f"{{{W}}}p"):
        text = _paragraph_text(node).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def document_blocks(docx_bytes: bytes) -> list[dict]:
    """按文档顺序交出正文段落和表格。表格单元格单独成行，不并进顶层段落。"""
    root = _document_root(docx_bytes)
    blocks: list[dict] = []
    paragraph_index = 0
    table_index = 0
    for child in list(_body(root)):
        if child.tag == f"{{{W}}}p":
            blocks.append({
                "kind": "paragraph",
                "index": paragraph_index,
                "text": _paragraph_text(child).strip(),
                "source": f"paragraph:{paragraph_index}",
            })
            paragraph_index += 1
        elif child.tag == f"{{{W}}}tbl":
            rows: list[list[str]] = []
            for tr in child.findall(f"{{{W}}}tr"):
                cells: list[str] = []
                for tc in tr.findall(f"{{{W}}}tc"):
                    parts = [
                        _paragraph_text(p).strip()
                        for p in tc.findall(f"{{{W}}}p")
                    ]
                    cells.append("".join(part for part in parts if part))
                rows.append(cells)
            blocks.append({
                "kind": "table",
                "index": table_index,
                "rows": rows,
                "source": f"table:{table_index}",
            })
            table_index += 1
    return blocks


def _all_paragraphs(root: ET.Element) -> list[ET.Element]:
    """正文段落和表格单元格里的段落。"""
    return list(_body(root).iter(f"{{{W}}}p"))


def replace_text(docx_bytes: bytes, old: str, new: str, *, paragraph_index: int | None = None) -> bytes:
    """替换选中文字或指定段落。找不到原文时抛错，不改到文首。

    未指定段落时同时查找表格单元格，避免只改到 w:body 的直接段落。
    """
    if not old and paragraph_index is None:
        raise ValueError("请提供选中文本或段落索引")
    root = _document_root(docx_bytes)
    nodes = _body_paragraphs(root)
    replaced = False
    if paragraph_index is not None:
        if paragraph_index < 0 or paragraph_index >= len(nodes):
            raise ValueError(f"段落索引越界: {paragraph_index}")
        targets = [nodes[paragraph_index]]
    else:
        targets = _all_paragraphs(root)
    for node in targets:
        current = _paragraph_text(node)
        if old and old in current:
            _set_paragraph_text(node, current.replace(old, new, 1))
            replaced = True
            break
        if not old and paragraph_index is not None:
            _set_paragraph_text(node, new)
            replaced = True
            break
    if not replaced:
        raise ValueError("文档里找不到要替换的原文")
    return _save_document(docx_bytes, root)


def insert_table(
    docx_bytes: bytes,
    paragraph_index: int,
    rows: int = 3,
    cols: int = 3,
    cells: list[list[str]] | None = None,
) -> bytes:
    root = _document_root(docx_bytes)
    nodes = _body_paragraphs(root)
    if paragraph_index < 0 or paragraph_index >= len(nodes):
        raise ValueError(f"段落索引越界: {paragraph_index}")
    table = ET.fromstring(_table_xml(rows, cols, cells))
    anchor = nodes[paragraph_index]
    parent = _parent_map(root)[anchor]
    index = list(parent).index(anchor)
    parent.insert(index + 1, table)
    return _save_document(docx_bytes, root)


def insert_image(docx_bytes: bytes, paragraph_index: int, image_bytes: bytes) -> bytes:
    if not image_bytes:
        raise ValueError("图片数据为空")
    root = _document_root(docx_bytes)
    nodes = _body_paragraphs(root)
    if paragraph_index < 0 or paragraph_index >= len(nodes):
        raise ValueError(f"段落索引越界: {paragraph_index}")
    rel_id = _add_image_part(docx_bytes, image_bytes)
    drawing = ET.fromstring(_image_paragraph_xml(rel_id))
    anchor = nodes[paragraph_index]
    parent = _parent_map(root)[anchor]
    index = list(parent).index(anchor)
    parent.insert(index + 1, drawing)
    packed = _save_document(docx_bytes, root)
    # _save_document rewrites document.xml from the tree; image parts were staged on the bytes
    # used before the rewrite. Merge the image parts into the saved package.
    return _merge_new_parts(docx_bytes, packed, rel_id, image_bytes)


def _paragraph_xml(text: str, style: str | None = None) -> str:
    safe = (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    ppr = ""
    if style:
        safe_style = (
            style.replace("&", "")
            .replace("<", "")
            .replace(">", "")
            .replace('"', "")
        )
        ppr = f'<w:pPr><w:pStyle w:val="{safe_style}"/></w:pPr>'
    return f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{safe}</w:t></w:r></w:p>'


def build_styled_docx(items: list[tuple[str, str | None]]) -> bytes:
    """段落列表，每项是 (正文, 样式名)。样式名可为空。"""
    body = "".join(_paragraph_xml(text, style) for text, style in items) or _paragraph_xml("")
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>{body}'
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Types xmlns="{CT}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{PR}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{PR}"></Relationships>'
    )
    return _pack({
        "[Content_Types].xml": content_types.encode(),
        "_rels/.rels": rels.encode(),
        "word/document.xml": document.encode(),
        "word/_rels/document.xml.rels": doc_rels.encode(),
    })


def _paragraph_style(node: ET.Element) -> str:
    ppr = node.find(f"{{{W}}}pPr")
    if ppr is None:
        return ""
    pstyle = ppr.find(f"{{{W}}}pStyle")
    if pstyle is None:
        return ""
    return pstyle.get(f"{{{W}}}val") or ""


def _record_for(node: ET.Element, *, in_table: bool) -> dict:
    return {
        "text": _paragraph_text(node).strip(),
        "style": _paragraph_style(node),
        "in_table": in_table,
    }


def paragraph_records(docx_bytes: bytes) -> list[dict]:
    """按阅读顺序交出正文段落和表格单元格。空段保留，用来识别空白章节。"""
    root = _document_root(docx_bytes)
    records: list[dict] = []
    for child in list(_body(root)):
        if child.tag == f"{{{W}}}p":
            records.append(_record_for(child, in_table=False))
        elif child.tag == f"{{{W}}}tbl":
            for para in child.iter(f"{{{W}}}p"):
                records.append(_record_for(para, in_table=True))
    return records


def build_table_docx(rows: list[list[str]]) -> bytes:
    """只有一张表的 docx，用来覆盖单元格里的旧事实。"""
    width = max((len(row) for row in rows), default=1)
    table = _table_xml(len(rows) or 1, width, rows)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>{table}'
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Types xmlns="{CT}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{PR}">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{PR}"></Relationships>'
    )
    return _pack({
        "[Content_Types].xml": content_types.encode(),
        "_rels/.rels": rels.encode(),
        "word/document.xml": document.encode(),
        "word/_rels/document.xml.rels": doc_rels.encode(),
    })


def write_section_starters(docx_bytes: bytes, starters: dict[str, str]) -> bytes:
    """标题下一段为空或短于 30 字时，写入该章节的起稿。"""
    if not starters:
        return docx_bytes
    from app.services.word import is_heading_style_name, paragraph_is_toc_like

    root = _document_root(docx_bytes)
    paras = _body_paragraphs(root)
    changed = False
    for index, node in enumerate(paras):
        style = _paragraph_style(node)
        text = _paragraph_text(node).strip()
        if paragraph_is_toc_like(style, text):
            continue
        heading = is_heading_style_name(style)
        starter = starters.get(text) or ""
        if not heading or not starter:
            continue
        nxt = paras[index + 1] if index + 1 < len(paras) else None
        if nxt is None:
            parent = _parent_map(root)[node]
            inserted = ET.fromstring(_paragraph_xml(starter))
            parent.insert(list(parent).index(node) + 1, inserted)
            changed = True
            continue
        nxt_text = _paragraph_text(nxt).strip()
        if len(nxt_text) > 30:
            continue
        _set_paragraph_text(nxt, starter)
        changed = True
    if not changed:
        return docx_bytes
    return _save_document(docx_bytes, root)


def write_section_bodies(
    docx_bytes: bytes,
    bodies: dict[str, str],
    *,
    replace_if_shorter_than: int = 120,
) -> bytes:
    """按章节标题写入正文；标题下一段过短或为空时替换为完整内容。"""
    if not bodies:
        return docx_bytes
    root = _document_root(docx_bytes)
    paras = _body_paragraphs(root)
    changed = False
    for index, node in enumerate(paras):
        style = _paragraph_style(node)
        text = _paragraph_text(node).strip()
        heading = style.lower().startswith("heading") or "标题" in style
        if not heading or not text:
            continue
        body = bodies.get(text) or ""
        if not body:
            for key, val in bodies.items():
                if key in text or text in key:
                    body = val
                    break
        if not body:
            continue
        nxt = paras[index + 1] if index + 1 < len(paras) else None
        if nxt is None:
            parent = _parent_map(root)[node]
            inserted = ET.fromstring(_paragraph_xml(body))
            parent.insert(list(parent).index(node) + 1, inserted)
            changed = True
            continue
        nxt_text = _paragraph_text(nxt).strip()
        if len(nxt_text) >= replace_if_shorter_than:
            continue
        _set_paragraph_text(nxt, body)
        changed = True
    if not changed:
        return docx_bytes
    return _save_document(docx_bytes, root)


def _table_xml(rows: int, cols: int, cells: list[list[str]] | None = None) -> str:
    row_count = max(1, len(cells) if cells else rows)
    col_count = max(1, max((len(row) for row in cells), default=cols) if cells else cols)
    row_xml = []
    for r in range(row_count):
        row_cells = []
        for c in range(col_count):
            if cells and r < len(cells) and c < len(cells[r]):
                label = cells[r][c]
            else:
                label = f"列{c + 1}" if r == 0 else ""
            safe = (label or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            row_cells.append(f"<w:tc><w:p><w:r><w:t>{safe}</w:t></w:r></w:p></w:tc>")
        row_xml.append("<w:tr>" + "".join(row_cells) + "</w:tr>")
    return f'<w:tbl xmlns:w="{W}">' + "".join(row_xml) + "</w:tbl>"


def _image_paragraph_xml(rel_id: str) -> str:
    return (
        f'<w:p xmlns:w="{W}" xmlns:r="{R}" xmlns:wp="{WP}" xmlns:a="{A}" xmlns:pic="{PIC}">'
        "<w:r><w:drawing><wp:inline>"
        '<wp:extent cx="952500" cy="952500"/>'
        '<wp:docPr id="1" name="Picture"/>'
        f'<a:graphic><a:graphicData uri="{PIC}">'
        "<pic:pic><pic:nvPicPr><pic:cNvPr id=\"0\" name=\"image\"/><pic:cNvPicPr/></pic:nvPicPr>"
        f'<pic:blipFill><a:blip r:embed="{rel_id}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        "<pic:spPr><a:xfrm><a:off x=\"0\" y=\"0\"/><a:ext cx=\"952500\" cy=\"952500\"/></a:xfrm>"
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        "</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
    )


def _document_root(docx_bytes: bytes) -> ET.Element:
    with ZipFile(BytesIO(docx_bytes)) as archive:
        xml = archive.read("word/document.xml")
    return ET.fromstring(xml)


def _body(root: ET.Element) -> ET.Element:
    body = root.find(f"{{{W}}}body")
    if body is None:
        raise ValueError("docx 没有正文")
    return body


def _body_paragraphs(root: ET.Element) -> list[ET.Element]:
    return [node for node in list(_body(root)) if node.tag == f"{{{W}}}p"]


def _paragraph_text(node: ET.Element) -> str:
    return "".join((item.text or "") for item in node.iter(f"{{{W}}}t"))


def _set_paragraph_text(node: ET.Element, text: str) -> None:
    for child in list(node):
        node.remove(child)
    run = ET.SubElement(node, f"{{{W}}}r")
    text_node = ET.SubElement(run, f"{{{W}}}t")
    text_node.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text_node.text = text


def _parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in list(parent)}


def _save_document(original: bytes, root: ET.Element) -> bytes:
    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    with ZipFile(BytesIO(original)) as archive:
        names = {name: archive.read(name) for name in archive.namelist()}
    names["word/document.xml"] = xml
    return _pack(names)


def _pack(parts: dict[str, bytes]) -> bytes:
    out = BytesIO()
    with ZipFile(out, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return out.getvalue()


def _add_image_part(docx_bytes: bytes, image_bytes: bytes) -> str:
    """占位：真正写入发生在 _merge_new_parts。返回关系 id。"""
    return "rIdImage1"


def _merge_new_parts(original: bytes, rewritten: bytes, rel_id: str, image_bytes: bytes) -> bytes:
    with ZipFile(BytesIO(rewritten)) as archive:
        names = {name: archive.read(name) for name in archive.namelist()}
    names["word/media/image1.png"] = image_bytes
    names["[Content_Types].xml"] = _ensure_png_content_type(names.get("[Content_Types].xml", b""))
    names["word/_rels/document.xml.rels"] = _ensure_image_rel(
        names.get("word/_rels/document.xml.rels", b""), rel_id,
    )
    return _pack(names)


def _ensure_png_content_type(xml: bytes) -> bytes:
    text = xml.decode("utf-8") if xml else (
        f'<?xml version="1.0" encoding="UTF-8"?><Types xmlns="{CT}"></Types>'
    )
    if 'Extension="png"' not in text:
        text = text.replace(
            "</Types>",
            '<Default Extension="png" ContentType="image/png"/></Types>',
        )
    return text.encode()


def _ensure_image_rel(xml: bytes, rel_id: str) -> bytes:
    text = xml.decode("utf-8") if xml else (
        f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{PR}"></Relationships>'
    )
    if rel_id not in text:
        text = text.replace(
            "</Relationships>",
            f'<Relationship Id="{rel_id}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
            'Target="media/image1.png"/></Relationships>',
        )
    return text.encode()
