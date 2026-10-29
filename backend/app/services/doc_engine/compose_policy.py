"""创作/合成策略：表单填表 vs 叙事段落、结构化函件勿重复生成。"""
from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree as ET

from app.services.docx_ooxml import document_text
from app.services.word import is_heading_style_name, paragraph_is_toc_like

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

LETTER_TITLE_TOKENS = ("投标函", "竞标函", "投标书", "投标声明")
LETTER_BODY_MARKERS = (
    "致：",
    "致:",
    "采购人",
    "招标人",
    "盖单位章",
    "法定代表人",
    "授权代表",
    "年月日",
    "我方参加",
    "按招标文件",
    "谈判编号",
    "包件号",
)
FORM_TABLE_TITLE_TOKENS = (
    "基本情况表",
    "许可",
    "认证",
    "人员表",
    "设备表",
    "分析表",
    "承诺",
)
FORM_TABLE_HEADER_TOKENS = ("序号", "认证名称", "证书编号", "编号", "名称", "备注")
NARRATIVE_SECTION_TOKENS = (
    "技术规格书",
    "技术方案",
    "供货方案",
    "服务方案",
    "实施方案",
)
NARRATIVE_AI_MARKERS = (
    "针对招标项目「",
    "针对「",
    "作如下说明",
    "我方将严格遵循招标文件",
)


def title_is_structured_letter(title: str) -> bool:
    t = (title or "").strip()
    return any(tok in t for tok in LETTER_TITLE_TOKENS)


def title_prefers_table_fill(title: str) -> bool:
    t = (title or "").strip()
    if title_requires_narrative_body(t):
        return False
    return any(tok in t for tok in FORM_TABLE_TITLE_TOKENS)


def title_requires_narrative_body(title: str) -> bool:
    t = (title or "").strip()
    return any(tok in t for tok in NARRATIVE_SECTION_TOKENS)


def _paragraph_text(node: ET.Element) -> str:
    return "".join((item.text or "") for item in node.iter(f"{{{W}}}t"))


def _paragraph_style(node: ET.Element) -> str:
    ppr = node.find(f"{{{W}}}pPr")
    if ppr is None:
        return ""
    ps = ppr.find(f"{{{W}}}pStyle")
    if ps is None:
        return ""
    return ps.get(f"{{{W}}}val") or ""


def _is_heading_node(node: ET.Element, text: str) -> bool:
    style = _paragraph_style(node)
    return is_heading_style_name(style) or style.lower().startswith("heading") or "标题" in style


def _table_header_text(tbl: ET.Element) -> str:
    parts: list[str] = []
    for cell in tbl.iter(f"{{{W}}}tc"):
        for para in cell.iter(f"{{{W}}}p"):
            t = _paragraph_text(para).strip()
            if t:
                parts.append(t)
        if len(parts) >= 8:
            break
    return " ".join(parts)


def _table_data_row_count(tbl: ET.Element, header_rows: int = 1) -> int:
    rows = tbl.findall(f"{{{W}}}tr")
    if len(rows) <= header_rows:
        return 0
    count = 0
    for row in rows[header_rows:]:
        cells = row.findall(f"{{{W}}}tc")
        texts = [_paragraph_text(c).strip() for c in cells]
        if any(texts):
            count += 1
    return count


def _body_elements(docx_bytes: bytes) -> list[tuple[str, ET.Element]]:
    from app.services.docx_ooxml import _document_root, _body

    root = _document_root(docx_bytes)
    body = _body(root)
    out: list[tuple[str, ET.Element]] = []
    for child in list(body):
        if child.tag == f"{{{W}}}p":
            out.append(("p", child))
        elif child.tag == f"{{{W}}}tbl":
            out.append(("tbl", child))
    return out


def section_slice_after_heading(docx_bytes: bytes, heading_title: str) -> list[tuple[str, ET.Element]]:
    """从首个匹配标题到下一同级标题之间的正文块（段落+表格）。"""
    needle = (heading_title or "").strip()
    if not needle:
        return []
    elements = _body_elements(docx_bytes)
    start = -1
    for idx, (kind, node) in enumerate(elements):
        if kind != "p":
            continue
        text = _paragraph_text(node).strip()
        style = _paragraph_style(node)
        if needle not in text or paragraph_is_toc_like(style, text):
            continue
        if text == needle or _is_heading_node(node, text):
            start = idx + 1
            break
    if start < 0:
        for idx, (kind, node) in enumerate(elements):
            if kind != "p":
                continue
            text = _paragraph_text(node).strip()
            style = _paragraph_style(node)
            if needle not in text or paragraph_is_toc_like(style, text):
                continue
            start = idx + 1
            break
    if start < 0:
        return []
    slice_out: list[tuple[str, ET.Element]] = []
    for kind, node in elements[start:]:
        if kind == "p":
            text = _paragraph_text(node).strip()
            style = _paragraph_style(node)
            if text and paragraph_is_toc_like(style, text):
                continue
            if text and _is_heading_node(node, text) and needle not in text and slice_out:
                break
        slice_out.append((kind, node))
    return slice_out


def table_section_data_rows(docx_bytes: bytes, heading_title: str) -> int:
    """章节范围内表格数据行数（用于验收纯表格章节）。"""
    total = 0
    for kind, node in section_slice_after_heading(docx_bytes, heading_title):
        if kind != "tbl":
            continue
        total += _table_data_row_count(node, header_rows=1)
    return total


def section_has_letter_skeleton(docx_bytes: bytes, heading_title: str) -> bool:
    """章节内是否已有模板函件正文骨架（勿再生成整段叙事）。"""
    if not title_is_structured_letter(heading_title):
        return False
    parts = section_slice_after_heading(docx_bytes, heading_title)
    texts: list[str] = []
    for kind, node in parts:
        if kind == "p":
            t = _paragraph_text(node).strip()
            if t:
                texts.append(t)
    body = "\n".join(texts)
    if len(re.sub(r"\s+", "", body)) < 80:
        return False
    hits = sum(1 for m in LETTER_BODY_MARKERS if m in body)
    return hits >= 2


def section_followed_by_form_table(docx_bytes: bytes, heading_title: str) -> bool:
    if title_prefers_table_fill(heading_title):
        return True
    parts = section_slice_after_heading(docx_bytes, heading_title)
    for kind, node in parts[:4]:
        if kind != "tbl":
            continue
        header = _table_header_text(node)
        if any(tok in header for tok in FORM_TABLE_HEADER_TOKENS):
            return True
        if "基本情况" in header or "许可" in header or "认证" in header:
            return True
    return False


def should_infer_ai_section_block(title: str, docx_bytes: bytes) -> bool:
    t = (title or "").strip()
    if not t:
        return False
    if title_requires_narrative_body(t):
        return True
    if title_is_structured_letter(t):
        return False
    if section_has_letter_skeleton(docx_bytes, t):
        return False
    if section_followed_by_form_table(docx_bytes, t):
        return False
    return True


def should_generate_ai_narrative(title: str, docx_bytes: bytes | None = None) -> bool:
    t = (title or "").strip()
    if not t:
        return False
    if title_requires_narrative_body(t):
        if title_is_structured_letter(t):
            return False
        if docx_bytes and section_has_letter_skeleton(docx_bytes, t):
            return False
        return True
    if title_is_structured_letter(t):
        return False
    if title_prefers_table_fill(t):
        return False
    if docx_bytes:
        if section_has_letter_skeleton(docx_bytes, t):
            return False
        if section_followed_by_form_table(docx_bytes, t):
            return False
    return True


def should_apply_ai_section_content(
    block: dict[str, Any],
    docx_bytes: bytes,
    *,
    manifest: dict[str, Any] | None = None,
) -> bool:
    if (block or {}).get("type") != "ai_section":
        return True
    title = str(block.get("title") or "").strip()
    if not should_generate_ai_narrative(title, docx_bytes):
        return False
    if manifest and _table_slot_covers_section(manifest, title):
        return False
    return True


def _table_slot_covers_section(manifest: dict[str, Any], heading_title: str) -> bool:
    ht = (heading_title or "").strip()
    if not ht:
        return False
    for block in manifest.get("blocks") or []:
        if block.get("type") != "table_slot":
            continue
        bt = str(block.get("title") or block.get("bind") or "").strip()
        if not bt:
            continue
        if bt in ht or ht in bt:
            return True
        if title_prefers_table_fill(ht) and title_prefers_table_fill(bt):
            return True
    return False


def filter_chapters_for_render(chapters: dict[str, Any] | None, docx_bytes: bytes) -> dict[str, Any]:
    """导出/装配前去掉会重复结构化函件正文的章节缓存。"""
    if not chapters:
        return {}
    out: dict[str, Any] = {}
    for key, val in chapters.items():
        if not key or str(key).startswith("_"):
            out[key] = val
            continue
        title = str(key)
        if not should_generate_ai_narrative(title, docx_bytes):
            continue
        out[key] = val
    return out


def count_letter_body_blocks(docx_bytes: bytes, heading_title: str = "竞标函") -> int:
    """统计函件章节内 LLM 套话式正文段数量（不含模板自带函件正文）。"""
    parts = section_slice_after_heading(docx_bytes, heading_title)
    count = 0
    for kind, node in parts:
        if kind != "p":
            continue
        text = _paragraph_text(node).strip()
        if not text or len(re.sub(r"\s+", "", text)) < 80:
            continue
        if any(m in text for m in NARRATIVE_AI_MARKERS):
            count += 1
    return count


def find_ai_narrative_above_empty_form_table(docx_bytes: bytes) -> list[str]:
    """长 AI 套话紧挨空「基本情况表」类表格时返回描述。"""
    issues: list[str] = []
    elements = _body_elements(docx_bytes)
    for idx, (kind, node) in enumerate(elements):
        if kind != "tbl":
            continue
        header = _table_header_text(node)
        if "基本情况" not in header and not (
            "许可" in header and "认证" in header
        ):
            continue
        if _table_data_row_count(node, header_rows=1) > 0:
            continue
        prev_text = ""
        for j in range(idx - 1, max(idx - 4, -1), -1):
            pk, pnode = elements[j]
            if pk != "p":
                continue
            t = _paragraph_text(pnode).strip()
            if not t:
                continue
            prev_text = t
            break
        if not prev_text:
            continue
        n = len(re.sub(r"\s+", "", prev_text))
        if n >= 80 and any(m in prev_text for m in NARRATIVE_AI_MARKERS):
            issues.append(f"paragraph_before_empty_table:{header[:40]}")
    return issues


def certification_table_data_rows(docx_bytes: bytes) -> int:
    try:
        text = document_text(docx_bytes)
    except Exception:
        text = ""
    if "认证" not in text and "许可" not in text:
        return 0
    best = 0
    for _, node in _body_elements(docx_bytes):
        header = _table_header_text(node)
        if "认证" not in header and "许可" not in header:
            continue
        best = max(best, _table_data_row_count(node, header_rows=1))
    return best
