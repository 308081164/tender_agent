"""Word 模板解析、占位符替换、智能替换与资质嵌入（Aspose.Words）。"""
from __future__ import annotations

import re
import tempfile
from io import BytesIO
from pathlib import Path

import aspose.words as aw

from app.services.aspose_runtime import ensure_license

PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")
AI_MARKER_RE = re.compile(r"【AI_GENERATED:([^】]+)】")


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


def _iter_paragraphs(doc: aw.Document):
    nodes = doc.get_child_nodes(aw.NodeType.PARAGRAPH, True)
    for i in range(nodes.count):
        yield nodes[i].as_paragraph()


def _document_text(doc: aw.Document) -> str:
    return doc.get_text() or ""


def can_convert_pdf() -> bool:
    """Aspose.Words 已集成，可用于 DOCX→PDF（无需 LibreOffice）。"""
    try:
        import aspose.words as aw  # noqa: F401
        return True
    except ImportError:
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


def extract_placeholders(docx_bytes: bytes) -> list[str]:
    doc = _load_document(docx_bytes)
    found: list[str] = []
    for m in PLACEHOLDER_RE.finditer(_document_text(doc)):
        if m.group(1) not in found:
            found.append(m.group(1))
    return found


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


def extract_preview(docx_bytes: bytes, max_paragraphs: int = 800) -> dict:
    doc = _load_document(docx_bytes)
    headings = []
    paragraphs = []
    for para in _iter_paragraphs(doc):
        style = _paragraph_style_name(para)
        text = para.get_text().strip()
        if not text:
            continue
        is_heading = style.startswith("Heading") or style.startswith("标题")
        level = _heading_level(style) if is_heading else 0
        if is_heading:
            headings.append({"level": level, "text": text})
        paragraphs.append({
            "text": text,
            "style": style,
            "is_heading": is_heading,
            "level": level,
        })
        if len(paragraphs) >= max_paragraphs:
            break
    return {
        "headings": headings,
        "paragraphs": paragraphs,
        "truncated": len(paragraphs) >= max_paragraphs,
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
