"""不依赖 Aspose 的 docx 读写。工具环用它真正改段落、插表、插图。"""
from __future__ import annotations

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
    mod = sys.modules.get("aspose.words")
    if mod is None:
        try:
            import aspose.words as mod
        except Exception:
            return False
    if type(mod).__name__ == "MagicMock":
        return False
    document = getattr(mod, "Document", None)
    return callable(document) and type(document).__name__ != "MagicMock"


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


def replace_text(docx_bytes: bytes, old: str, new: str, *, paragraph_index: int | None = None) -> bytes:
    """替换选中文字或指定段落。找不到原文时抛错，不改到文首。"""
    if not old and paragraph_index is None:
        raise ValueError("请提供选中文本或段落索引")
    root = _document_root(docx_bytes)
    nodes = _body_paragraphs(root)
    replaced = False
    targets = nodes
    if paragraph_index is not None:
        if paragraph_index < 0 or paragraph_index >= len(nodes):
            raise ValueError(f"段落索引越界: {paragraph_index}")
        targets = [nodes[paragraph_index]]
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


def _paragraph_xml(text: str) -> str:
    safe = (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    return f'<w:p><w:r><w:t xml:space="preserve">{safe}</w:t></w:r></w:p>'


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
