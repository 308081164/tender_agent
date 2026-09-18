"""资质附件 AI 智能识别：从图像/PDF/DOCX 等提取并结构化填表字段。"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.services import ai
from app.services.ocr_service import extract_text_from_file

QUAL_CATEGORIES = [
    "企业资质包", "业绩包", "人员资质包", "财务包", "信誉包", "授权包", "其他",
]

SYSTEM_PROMPT = """你是标书资质材料识别助手。根据附件提取的文本，输出 JSON 对象，字段如下：
- category: 分类，从以下选一：企业资质包、业绩包、人员资质包、财务包、信誉包、授权包、其他
- name: 材料/证书名称
- issuer: 颁发机构
- keywords: 关键词标签，多个用中文分号分隔
- section_hint: 建议插入的标书章节提示（简短）
- valid_from: 生效日期 YYYY-MM-DD，无法识别则 null
- valid_to: 失效日期 YYYY-MM-DD，长期有效则 null
- is_long_term: 是否长期有效 true/false

只输出 JSON，不要 markdown 代码块。"""


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        text = m.group(0)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _normalize_result(data: dict[str, Any], file_type: str, file_name: str) -> dict[str, Any]:
    category = str(data.get("category") or "").strip()
    if category not in QUAL_CATEGORIES:
        category = "其他"

    def date_str(key: str) -> str | None:
        val = data.get(key)
        if not val:
            return None
        s = str(val).strip()[:10]
        if re.match(r"\d{4}-\d{2}-\d{2}", s):
            return s
        return None

    is_long = bool(data.get("is_long_term"))
    return {
        "category": category,
        "name": str(data.get("name") or file_name.rsplit(".", 1)[0] or "").strip(),
        "issuer": str(data.get("issuer") or "").strip(),
        "keywords": str(data.get("keywords") or "").strip(),
        "section_hint": str(data.get("section_hint") or "").strip(),
        "valid_from": date_str("valid_from"),
        "valid_to": date_str("valid_to") if not is_long else None,
        "is_long_term": is_long,
        "file_type": (file_type or "").lower().lstrip("."),
        "file_name": file_name,
        "ocr_text": "",
        "source": "ai",
    }


def _rule_based_extract(text: str, file_name: str, file_type: str) -> dict[str, Any]:
    """无 LLM Key 时的规则兜底。"""
    name = file_name.rsplit(".", 1)[0] if file_name else "资质材料"
    issuer = ""
    m = re.search(r"(颁发单位|发证机关|颁发机构)[：:\s]*([^\n，,；;]+)", text)
    if m:
        issuer = m.group(2).strip()

    valid_from = None
    valid_to = None
    is_long = "长期" in text or "永久" in text
    m_from = re.search(r"(有效期自|生效日期|发证日期)[：:\s]*(\d{4}[-年/.]\d{1,2}[-月/.]\d{1,2})", text)
    if m_from:
        valid_from = re.sub(r"[年月/.]", "-", m_from.group(2)).replace("--", "-")[:10]
    m_to = re.search(r"(有效期至|失效日期|截止日期)[：:\s]*(\d{4}[-年/.]\d{1,2}[-月/.]\d{1,2})", text)
    if m_to:
        valid_to = re.sub(r"[年月/.]", "-", m_to.group(2)).replace("--", "-")[:10]

    category = "企业资质包"
    if any(k in text for k in ("业绩", "合同", "中标")):
        category = "业绩包"
    elif any(k in text for k in ("身份证", "职称", "建造师", "人员")):
        category = "人员资质包"

    return {
        "category": category,
        "name": name,
        "issuer": issuer,
        "keywords": "",
        "section_hint": "",
        "valid_from": valid_from,
        "valid_to": valid_to if not is_long else None,
        "is_long_term": is_long,
        "file_type": (file_type or "").lower().lstrip("."),
        "file_name": file_name,
        "ocr_text": text[:8000],
        "source": "rules",
    }


async def analyze_qualification_file(
    data: bytes,
    file_name: str,
    file_type: str,
    *,
    db: Session | None = None,
) -> dict[str, Any]:
    ftype = (file_type or "").lower().lstrip(".")
    if not ftype and "." in file_name:
        ftype = file_name.rsplit(".", 1)[-1].lower()

    text = extract_text_from_file(data, ftype, name=file_name)
    if not text.strip():
        text = f"文件名: {file_name}"

    raw = await ai.chat_completion([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"文件名: {file_name}\n文件类型: {ftype}\n\n附件文本:\n{text[:6000]}"},
    ], db=db)

    if raw.strip():
        parsed = _parse_json_object(raw)
        result = _normalize_result(parsed, ftype, file_name)
        result["ocr_text"] = text[:8000]
        return result

    return _rule_based_extract(text, file_name, ftype)
