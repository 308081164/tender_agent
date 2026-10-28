"""Word 模板解析、占位符替换、智能替换与资质嵌入（Aspose.Words）。"""
from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from io import BytesIO
from pathlib import Path

import aspose.words as aw

from app.services.aspose_runtime import ensure_license, iter_collection

PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")
AI_MARKER_RE = re.compile(r"【AI_GENERATED:([^】]+)】")

# Word 域代码 / 目录域残留（预览时应过滤或更新域后再提取）
FIELD_CODE_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"PAGE\s*\\",
        r"\\\*",
        r"\\[a-z]+\s",
        r"HYPERLINK",
        r"TOC\s",
        r"PAGEREF",
        r"SEQ\s",
        r"MERGEFORMAT",
        r"^\s*\d+\s*$",
        r"^\s*[\{\}\\]+\s*$",
    ]
]


def _load_document(docx_bytes: bytes) -> aw.Document:
    ensure_license()
    return aw.Document(BytesIO(docx_bytes))


def _paragraph_style_name(paragraph: aw.Paragraph) -> str:
    style = paragraph.paragraph_format.style
    return style.name if style else ""


def _heading_level(style_name: str) -> int:
    level = 1
    for ch in style_name:
        if ch.isdigit():
            level = int(ch)
            break
    return level


def _alignment_name(alignment) -> str:
    mapping = {
        aw.ParagraphAlignment.LEFT: "left",
        aw.ParagraphAlignment.CENTER: "center",
        aw.ParagraphAlignment.RIGHT: "right",
        aw.ParagraphAlignment.JUSTIFY: "justify",
        aw.ParagraphAlignment.DISTRIBUTED: "justify",
    }
    try:
        return mapping.get(alignment, "left")
    except Exception:
        return "left"


def _points(value) -> float | None:
    try:
        if value is None:
            return None
        pts = float(value)
        return round(pts, 1) if pts else None
    except Exception:
        return None


def is_field_code_text(text: str) -> bool:
    """判断段落文本是否为 Word 域代码残留（TOC/HYPERLINK/PAGE 等）。"""
    t = (text or "").strip()
    if len(t) < 2:
        return True
    if "\\" in t and any(
        token in t.upper() for token in ("PAGE", "TOC", "HYPERLINK", "PAGEREF", "MERGEFORMAT", "SEQ ")
    ):
        return True
    return any(p.search(t) for p in FIELD_CODE_PATTERNS)


def is_toc_style_name(style_name: str) -> bool:
    """Word 自动目录段落样式（TOC 1 / toc 1 等）。"""
    s = (style_name or "").strip().lower()
    return s.startswith("toc") or s in ("目录", "table of contents")


def is_heading_style_name(style_name: str) -> bool:
    s = (style_name or "").strip()
    if not s:
        return False
    if s.startswith("Heading") or s.startswith("标题"):
        return True
    return bool(re.match(r"^heading\s*\d", s, re.I))


def is_toc_entry_text(text: str) -> bool:
    """目录行：标题 + 制表符 + 页码（域更新后的常见形态）。"""
    t = (text or "").strip()
    if not t:
        return False
    if "\t" in t and re.search(r"\t\d+\s*$", t):
        return True
    if re.match(r"^\d+(\.\d+)*\.\s+.+\t\d+\s*$", t):
        return True
    return False


def paragraph_is_toc_like(style_name: str, text: str) -> bool:
    if is_toc_style_name(style_name):
        return True
    if is_toc_entry_text(text):
        return True
    return False


def _prepare_doc_for_preview(doc: aw.Document) -> None:
    """更新域与版式，使目录/页码等显示为渲染结果而非域代码。"""
    for fn_name in ("update_fields", "update_page_layout"):
        try:
            fn = getattr(doc, fn_name, None)
            if callable(fn):
                fn()
        except Exception:
            pass


def _clean_display_text(text: str) -> str:
    """去除控制字符、零宽字符等无意义符号，提升阅读体验。"""
    if not text:
        return ""
    cleaned: list[str] = []
    for ch in text:
        if ch in "\n\t":
            cleaned.append(ch)
            continue
        cat = unicodedata.category(ch)
        if cat.startswith("C"):
            continue
        cleaned.append(ch)
    text = "".join(cleaned)
    text = re.sub(r"[\u200b\u200c\u200d\ufeff\u00ad]", "", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _paragraph_run_format(para: aw.Paragraph) -> dict:
    font_name = ""
    font_size = None
    bold = False
    italic = False
    try:
        runs = para.runs
        if runs.count > 0:
            run = runs[0]
            font = run.font
            font_name = (font.name or "").strip()
            font_size = _points(font.size)
            bold = bool(font.bold)
            italic = bool(font.italic)
    except Exception:
        pass
    if not font_name:
        try:
            style_font = para.paragraph_format.style.font
            font_name = (style_font.name or "").strip()
            if font_size is None:
                font_size = _points(style_font.size)
            if not bold:
                bold = bool(style_font.bold)
            if not italic:
                italic = bool(style_font.italic)
        except Exception:
            pass
    pf = para.paragraph_format
    return {
        "font_name": font_name or "默认",
        "font_size_pt": font_size,
        "bold": bold,
        "italic": italic,
        "alignment": _alignment_name(pf.alignment),
        "indent_pt": _points(pf.left_indent),
        "first_line_indent_pt": _points(pf.first_line_indent),
        "space_before_pt": _points(pf.space_before),
        "space_after_pt": _points(pf.space_after),
    }


def _iter_paragraphs(doc: aw.Document):
    nodes = doc.get_child_nodes(aw.NodeType.PARAGRAPH, True)
    for i in range(nodes.count):
        yield nodes[i].as_paragraph()


def _document_text(doc: aw.Document) -> str:
    return doc.get_text() or ""


def can_convert_pdf() -> bool:
    """Aspose 可用且授权文件可加载时返回 True。"""
    try:
        import aspose.words as aw  # noqa: F401
    except ImportError:
        return False
    try:
        from app.services.aspose_runtime import license_path

        lp = license_path()
        return bool(lp and os.path.isfile(lp))
    except Exception:
        return False


def convert_docx_to_pdf(docx_bytes: bytes) -> bytes:
    """使用 Aspose.Words 将 DOCX 转为 PDF（与项目许可证一致）。"""
    doc = _load_document(docx_bytes)
    out = BytesIO()
    doc.save(out, aw.SaveFormat.PDF)
    data = out.getvalue()
    if not data:
        raise RuntimeError("Aspose DOCX→PDF 转换结果为空")
    return data


def _extract_placeholders_from_xml(docx_bytes: bytes) -> list[str]:
    """不依赖 Aspose 的占位符提取（上传兜底）。"""
    import zipfile
    from xml.etree import ElementTree
    try:
        with zipfile.ZipFile(BytesIO(docx_bytes)) as zf:
            xml = zf.read("word/document.xml")
        root = ElementTree.fromstring(xml)
        texts = []
        for t in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"):
            if t.text:
                texts.append(t.text)
        blob = " ".join(texts)
    except Exception:
        blob = docx_bytes.decode("utf-8", errors="ignore")
    found: list[str] = []
    for m in PLACEHOLDER_RE.finditer(blob):
        key = m.group(1)
        if key not in found:
            found.append(key)
    return found


def _aspose_ready() -> bool:
    from app.services.docx_ooxml import aspose_available
    return aspose_available()


def _ooxml_replace_all(docx_bytes: bytes, old: str, new: str) -> bytes:
    """在没有 Aspose 时替换全部出现。新文本仍含原文时停止，避免死循环。"""
    from app.services.docx_ooxml import document_text, replace_text

    if not old or old == new or new is None:
        return docx_bytes
    data = docx_bytes
    for _ in range(40):
        try:
            current = document_text(data)
        except Exception:
            return data
        before = current.count(old)
        if before <= 0:
            break
        try:
            nxt = replace_text(data, old, new)
        except Exception:
            break
        try:
            after = document_text(nxt).count(old)
        except Exception:
            return data
        if after >= before:
            break
        data = nxt
    return data


def _render_document_ooxml(
    template_bytes: bytes,
    fields: dict,
    chapters: dict | None = None,
    source_snapshot: dict | None = None,
) -> bytes:
    from app.services.docx_ooxml import document_text

    mapping = {k: ("" if v is None else str(v)) for k, v in (fields or {}).items()}
    if chapters:
        for k, v in chapters.items():
            content = v.get("content", v) if isinstance(v, dict) else str(v)
            mapping[f"ai::{k}"] = content
            mapping[k] = content
    if "bid_amount" in mapping and "bid_amount_upper" not in mapping:
        mapping["bid_amount_upper"] = mapping["bid_amount"]
    try:
        text_before = document_text(template_bytes)
    except Exception:
        return template_bytes
    data = template_bytes
    if PLACEHOLDER_RE.search(text_before):
        for key in PLACEHOLDER_RE.findall(text_before):
            mapping.setdefault(key, "")
        seen: set[str] = set()
        for match in PLACEHOLDER_RE.finditer(text_before):
            token = match.group(0)
            if token in seen:
                continue
            seen.add(token)
            data = _ooxml_replace_all(data, token, mapping.get(match.group(1), ""))
        for key, val in mapping.items():
            if key.startswith("ai::"):
                data = _ooxml_replace_all(data, f"【AI_GENERATED:{key[4:]}】", val)
            else:
                data = _ooxml_replace_all(data, f"【AI_GENERATED:{key}】", val)
        return data
    snap = source_snapshot or {}
    if isinstance(snap.get("fields"), dict):
        snap = {
            k: (v.get("value") if isinstance(v, dict) else v)
            for k, v in snap["fields"].items()
        }
    pairs: list[tuple[str, str]] = []
    for key, new_val in mapping.items():
        if str(key).startswith("ai::") or str(key).startswith("_"):
            continue
        old_val = snap.get(key) if isinstance(snap, dict) else None
        if isinstance(old_val, dict):
            old_val = old_val.get("value")
        if not old_val:
            continue
        new_s = "" if new_val is None else str(new_val)
        if not new_s or str(old_val) == new_s:
            continue
        pairs.append((str(old_val), new_s))
    for old, new in sorted(pairs, key=lambda item: len(item[0]), reverse=True):
        data = _ooxml_replace_all(data, old, new)
    return data


def extract_placeholders(docx_bytes: bytes) -> list[str]:
    if not _aspose_ready():
        return _extract_placeholders_from_xml(docx_bytes)
    doc = _load_document(docx_bytes)
    found: list[str] = []
    for m in PLACEHOLDER_RE.finditer(_document_text(doc)):
        if m.group(1) not in found:
            found.append(m.group(1))
    return found


def safe_extract_placeholders(docx_bytes: bytes) -> list[str]:
    try:
        return extract_placeholders(docx_bytes)
    except Exception:
        return _extract_placeholders_from_xml(docx_bytes)


def extract_structure(docx_bytes: bytes) -> dict:
    doc = _load_document(docx_bytes)
    headings = []
    paragraphs = []
    for para in _iter_paragraphs(doc):
        style = _paragraph_style_name(para)
        text = para.get_text().strip()
        if not text:
            continue
        if style.startswith("Heading") or style.startswith("标题"):
            headings.append({"level": _heading_level(style), "text": text})
        paragraphs.append({"style": style, "text": text})
    return {"headings": headings, "paragraphs": paragraphs[:200]}


def _table_preview_rows(table: aw.Table) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in iter_collection(table.rows):
        cells: list[str] = []
        for cell in iter_collection(row.cells):
            cell_text = _clean_display_text(cell.get_text() or "")
            cells.append(cell_text)
        if any(cells):
            rows.append(cells)
    return rows


def _append_preview_paragraph(
    paragraphs: list[dict],
    headings: list[dict],
    heading_formats: dict[int, dict],
    body_format_samples: list[dict],
    para: aw.Paragraph,
    idx: int,
) -> bool:
    style = _paragraph_style_name(para)
    raw_text = para.get_text() or ""
    text = _clean_display_text(raw_text)
    if not text or re.fullmatch(r"[\s\W_]+", text) or is_field_code_text(text):
        return False
    fmt = _paragraph_run_format(para)
    is_heading = style.startswith("Heading") or style.startswith("标题")
    level = _heading_level(style) if is_heading else 0
    if is_heading:
        headings.append({"level": level, "text": text, **fmt})
        heading_formats[level] = fmt
    elif len(body_format_samples) < 5:
        body_format_samples.append(fmt)
    paragraphs.append({
        "index": idx,
        "text": text,
        "style": style,
        "is_heading": is_heading,
        "level": level,
        **fmt,
    })
    return True


def _extract_preview_ooxml(docx_bytes: bytes, max_paragraphs: int = 800) -> dict:
    from app.services.docx_ooxml import paragraph_records

    try:
        records = paragraph_records(docx_bytes)
    except Exception:
        return {"headings": [], "paragraphs": [], "truncated": False, "format_info": {}}
    paragraphs = []
    headings = []
    truncated = False
    for idx, rec in enumerate(records):
        text = (rec.get("text") or "").strip()
        if not text:
            continue
        style = rec.get("style") or ""
        is_heading = style.lower().startswith("heading") or "标题" in style
        item = {
            "index": idx,
            "text": text,
            "style": style or "Normal",
            "is_heading": is_heading,
            "level": 1 if is_heading else 0,
        }
        paragraphs.append(item)
        if is_heading:
            headings.append({"level": 1, "text": text})
        if len(paragraphs) >= max_paragraphs:
            truncated = True
            break
    return {
        "headings": headings,
        "paragraphs": paragraphs,
        "truncated": truncated,
        "format_info": {},
    }


def extract_preview(docx_bytes: bytes, max_paragraphs: int = 800) -> dict:
    if not _aspose_ready():
        return _extract_preview_ooxml(docx_bytes, max_paragraphs)
    doc = _load_document(docx_bytes)
    _prepare_doc_for_preview(doc)
    headings = []
    paragraphs = []
    heading_formats: dict[int, dict] = {}
    body_format_samples: list[dict] = []
    para_idx = 0
    truncated = False

    for section in iter_collection(doc.sections):
        body = section.body
        for child in body.get_child_nodes(aw.NodeType.ANY, False):
            if truncated:
                break
            if child.node_type == aw.NodeType.PARAGRAPH:
                para = child.as_paragraph()
                if _append_preview_paragraph(
                    paragraphs, headings, heading_formats, body_format_samples, para, para_idx,
                ):
                    para_idx += 1
                    if len(paragraphs) >= max_paragraphs:
                        truncated = True
                        break
            elif child.node_type == aw.NodeType.TABLE:
                table = child.as_table()
                rows = _table_preview_rows(table)
                if not rows:
                    continue
                paragraphs.append({
                    "index": para_idx,
                    "text": "",
                    "style": "Table",
                    "is_heading": False,
                    "is_table": True,
                    "table_rows": rows,
                    "level": 0,
                })
                para_idx += 1
                if len(paragraphs) >= max_paragraphs:
                    truncated = True
                    break

    default_body = body_format_samples[0] if body_format_samples else {}
    return {
        "headings": headings,
        "paragraphs": paragraphs,
        "truncated": truncated,
        "format_info": {
            "default_body": default_body,
            "heading_styles": [
                {"level": lvl, **heading_formats[lvl]}
                for lvl in sorted(heading_formats.keys())
            ],
        },
    }


def _replace_options(highlight: bool) -> aw.replacing.FindReplaceOptions:
    options = aw.replacing.FindReplaceOptions()
    if highlight:
        try:
            options.apply_font.highlight_color = aw.HighlightColor.YELLOW
        except Exception:
            pass
    return options


def _replace_text(doc: aw.Document, old: str, new: str, highlight: bool = False) -> None:
    if not old or new is None:
        return
    doc.range.replace(str(old), str(new), _replace_options(highlight))


def apply_literal_replacements(
    docx_bytes: bytes,
    replacements: list[tuple[str, str]],
    *,
    highlight: bool = False,
) -> bytes:
    """将文档中的指定原文批量替换为目标文本（用于模板工程化）。"""
    if not _aspose_ready():
        data = docx_bytes
        for old, new in sorted(replacements or [], key=lambda item: len(item[0] or ""), reverse=True):
            if old and new is not None and old != new:
                data = _ooxml_replace_all(data, old, new)
        return data
    doc = _load_document(docx_bytes)
    for old, new in sorted(replacements, key=lambda x: len(x[0]), reverse=True):
        if old and new is not None and old != new:
            _replace_text(doc, old, new, highlight=highlight)
    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    return out.getvalue()


def smart_replace_document(
    template_bytes: bytes,
    old_values: dict,
    new_values: dict,
    highlight: bool = True,
) -> bytes:
    """历史标书智能替换：将旧字段值替换为新字段值。"""
    doc = _load_document(template_bytes)
    pairs = []
    for key, new_val in (new_values or {}).items():
        old_val = (old_values or {}).get(key)
        if not old_val or not new_val:
            continue
        if str(old_val) == str(new_val):
            continue
        pairs.append((str(old_val), str(new_val)))
    for old, new in sorted(pairs, key=lambda x: len(x[0]), reverse=True):
        _replace_text(doc, old, new, highlight=highlight)
    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    return out.getvalue()


def render_document(
    template_bytes: bytes,
    fields: dict,
    chapters: dict | None = None,
    highlight: bool = True,
    source_snapshot: dict | None = None,
) -> bytes:
    mapping = {k: ("" if v is None else str(v)) for k, v in (fields or {}).items()}
    if chapters:
        for k, v in chapters.items():
            content = v.get("content", v) if isinstance(v, dict) else str(v)
            mapping[f"ai::{k}"] = content
            mapping[k] = content

    # 兼容旧字段名
    if "bid_amount" in mapping and "bid_amount_upper" not in mapping:
        mapping["bid_amount_upper"] = mapping["bid_amount"]

    if not _aspose_ready():
        return _render_document_ooxml(
            template_bytes, fields, chapters, source_snapshot,
        )

    doc = _load_document(template_bytes)
    text_before = _document_text(doc)
    has_placeholders = bool(PLACEHOLDER_RE.search(text_before))

    if has_placeholders:
        # 模板内所有 {{key}} 均替换；未提供的键用空串，避免可选字段阻断导出
        for key in PLACEHOLDER_RE.findall(text_before):
            if key not in mapping:
                mapping[key] = ""
        for key, val in mapping.items():
            if key.startswith("ai::"):
                continue
            _replace_text(doc, f"{{{{{key}}}}}", val, highlight)
        for key, val in mapping.items():
            if key.startswith("ai::"):
                _replace_text(doc, f"【AI_GENERATED:{key[4:]}】", val, highlight)
            else:
                _replace_text(doc, f"【AI_GENERATED:{key}】", val, highlight)
    elif source_snapshot:
        # 无占位符时按快照智能替换
        pairs = []
        for key, new_val in mapping.items():
            if key.startswith("ai::"):
                continue
            old_val = (source_snapshot or {}).get(key)
            if old_val and new_val and str(old_val) != str(new_val):
                pairs.append((str(old_val), str(new_val)))
        for old, new in sorted(pairs, key=lambda x: len(x[0]), reverse=True):
            _replace_text(doc, old, new, highlight)
        for key, val in mapping.items():
            if key.startswith("ai::"):
                _replace_text(doc, f"【AI_GENERATED:{key[4:]}】", val, highlight)

    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    return out.getvalue()


def _insert_image_bytes(builder: aw.DocumentBuilder, data: bytes, width_pt: float = 420):
    stream = BytesIO(data)
    builder.insert_image(stream, width_pt, 0)


def embed_qualifications(
    docx_bytes: bytes,
    qual_files: list[dict],
) -> bytes:
    """
    将资质附件追加到文档末尾。
    qual_files: [{name, category, section_hint, file_type, data: bytes}]
    """
    doc = _load_document(docx_bytes)
    builder = aw.DocumentBuilder(doc)
    builder.move_to_document_end()
    builder.insert_break(aw.BreakType.PAGE_BREAK)
    builder.paragraph_format.style_identifier = aw.StyleIdentifier.HEADING1
    builder.writeln("附件：资质与证明材料")
    builder.paragraph_format.style_identifier = aw.StyleIdentifier.NORMAL

    for q in qual_files or []:
        name = q.get("name") or "材料"
        category = q.get("category") or ""
        hint = q.get("section_hint") or ""
        ftype = (q.get("file_type") or "").lower().lstrip(".")
        data = q.get("data") or b""
        builder.paragraph_format.style_identifier = aw.StyleIdentifier.HEADING2
        builder.writeln(f"{category} / {name}" + (f"（{hint}）" if hint else ""))
        builder.paragraph_format.style_identifier = aw.StyleIdentifier.NORMAL
        if not data:
            builder.writeln("（文件缺失）")
            continue
        try:
            if ftype in ("jpg", "jpeg", "png", "bmp", "gif"):
                _insert_image_bytes(builder, data)
                builder.writeln("")
            elif ftype == "docx":
                src = aw.Document(BytesIO(data))
                builder.insert_document(src, aw.ImportFormatMode.KEEP_SOURCE_FORMATTING)
                builder.writeln("")
            elif ftype == "pdf":
                # 尝试用 Aspose 打开 PDF；失败则写说明
                try:
                    pdf_doc = aw.Document(BytesIO(data))
                    builder.insert_document(pdf_doc, aw.ImportFormatMode.KEEP_SOURCE_FORMATTING)
                except Exception:
                    builder.writeln(f"[PDF 附件已关联：{name}，请在系统资质库中查看原件]")
            else:
                builder.writeln(f"[附件类型 {ftype or 'unknown'}：{name}]")
        except Exception as e:
            builder.writeln(f"[嵌入失败：{name} — {e}]")

    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    return out.getvalue()


def validate_export(docx_bytes: bytes, required_fields: list[str], fields: dict) -> dict:
    issues = []
    warnings = []
    for key in required_fields:
        val = fields.get(key)
        if not val:
            issues.append({"level": "red", "message": f"关键字段未填写：{key}"})
    # 金额一致性轻量提示
    upper = str(fields.get("bid_amount_upper") or fields.get("bid_amount") or "")
    lower = str(fields.get("bid_amount_lower") or "")
    if upper and lower and ("万" in upper or "元" in upper) and lower:
        # 仅提示，不阻断
        if upper.replace(" ", "") == lower.replace(" ", ""):
            warnings.append({"level": "yellow", "message": "投标总价大小写内容相同，请核对"})

    text_sample = ""
    try:
        doc = _load_document(docx_bytes)
        text_sample = _document_text(doc)
    except Exception as e:
        issues.append({"level": "red", "message": f"文档无法解析：{e}"})
    leftover = PLACEHOLDER_RE.findall(text_sample)
    if leftover:
        issues.append({"level": "red", "message": f"仍有未替换占位符：{', '.join(sorted(set(leftover)))}"})
    if "【AI_GENERATED:" in text_sample:
        warnings.append({"level": "yellow", "message": "仍有未生成的 AI 章节标记"})
    status = "green" if not issues and not warnings else ("yellow" if not issues else "red")
    return {"status": status, "issues": issues, "warnings": warnings}


def replace_paragraph_text(docx_bytes: bytes, paragraph_index: int, new_text: str) -> bytes:
    """按段落索引替换正文（保留段落样式）。"""
    doc = _load_document(docx_bytes)
    nodes = doc.get_child_nodes(aw.NodeType.PARAGRAPH, True)
    if paragraph_index < 0 or paragraph_index >= nodes.count:
        raise ValueError(f"段落索引越界: {paragraph_index}")
    para = nodes[paragraph_index].as_paragraph()
    para.remove_all_children()
    run = aw.Run(doc, new_text or "")
    para.append_child(run)
    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    return out.getvalue()


def insert_table_at_paragraph(
    docx_bytes: bytes,
    paragraph_index: int,
    rows: int = 3,
    cols: int = 3,
) -> bytes:
    """在指定段落后插入表格（MVP：空表 + 表头占位）。"""
    doc = _load_document(docx_bytes)
    nodes = doc.get_child_nodes(aw.NodeType.PARAGRAPH, True)
    if paragraph_index < 0 or paragraph_index >= nodes.count:
        raise ValueError(f"段落索引越界: {paragraph_index}")
    builder = aw.DocumentBuilder(doc)
    builder.move_to_paragraph(paragraph_index, -1)
    table = builder.start_table()
    for r in range(max(1, rows)):
        for c in range(max(1, cols)):
            builder.insert_cell()
            builder.write(f"列{c + 1}" if r == 0 else "")
        builder.end_row()
    builder.end_table()
    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    return out.getvalue()


def insert_image_at_paragraph(
    docx_bytes: bytes,
    paragraph_index: int,
    image_bytes: bytes,
    *,
    width_pt: float = 420,
) -> bytes:
    """在指定段落后插入图片。"""
    if not image_bytes:
        raise ValueError("图片数据为空")
    doc = _load_document(docx_bytes)
    nodes = doc.get_child_nodes(aw.NodeType.PARAGRAPH, True)
    if paragraph_index < 0 or paragraph_index >= nodes.count:
        raise ValueError(f"段落索引越界: {paragraph_index}")
    para = nodes[paragraph_index].as_paragraph()
    builder = aw.DocumentBuilder(doc)
    builder.move_to(para)
    builder.insert_break(aw.BreakType.PARAGRAPH_BREAK)
    _insert_image_bytes(builder, image_bytes, width_pt=width_pt)
    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    return out.getvalue()


def replace_text_snippet(docx_bytes: bytes, old_text: str, new_text: str, *, highlight: bool = False) -> bytes:
    """替换文档中指定文本片段（用于 Agent 局部修改）。"""
    if not old_text:
        raise ValueError("old_text 不能为空")
    doc = _load_document(docx_bytes)
    _replace_text(doc, old_text, new_text or "", highlight=highlight)
    out = BytesIO()
    doc.save(out, aw.SaveFormat.DOCX)
    return out.getvalue()


def _apply_mappings_to_text(text: str, approved: list[dict]) -> tuple[str, list[str]]:
    display = text
    applied_keys: list[str] = []
    for m in approved:
        original = m.get("original_text") or ""
        key = m.get("key") or ""
        if original and original in display:
            if m.get("bind_type") == "qual":
                qid = m.get("qualification_id") or key
                placeholder = f"【QUAL_SLOT:{qid}】"
            else:
                placeholder = f"{{{{{key}}}}}"
            display = display.replace(original, placeholder)
            applied_keys.append(key)
    return display, applied_keys


def simulate_mapping_preview(paragraphs: list[dict], mappings: list[dict]) -> list[dict]:
    """在前端/后端预览映射效果，不修改实际文档。"""
    approved = [
        m for m in mappings
        if m.get("approved", True) and m.get("action", "replace") != "keep"
        and (m.get("original_text") or "").strip() and (m.get("key") or "").strip()
    ]
    approved.sort(key=lambda x: len(x.get("original_text") or ""), reverse=True)
    result = []
    for p in paragraphs:
        item = dict(p)
        if p.get("is_table") and p.get("table_rows"):
            rows = p.get("table_rows") or []
            display_rows = []
            all_keys: list[str] = []
            changed = False
            for row in rows:
                new_row = []
                for cell in row:
                    display, keys = _apply_mappings_to_text(cell or "", approved)
                    new_row.append(display)
                    all_keys.extend(keys)
                    if display != cell:
                        changed = True
                display_rows.append(new_row)
            item["table_rows"] = rows
            item["display_table_rows"] = display_rows
            item["applied_keys"] = all_keys
            item["changed"] = changed
        else:
            text = p.get("text") or ""
            display, applied_keys = _apply_mappings_to_text(text, approved)
            item["display_text"] = display
            item["applied_keys"] = applied_keys
            item["changed"] = display != text
        result.append(item)
    return result
