"""基于 Aspose + LLM 的文档生成与局部编辑 Agent。"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.services import ai, word

PLACEHOLDER_RE = word.PLACEHOLDER_RE
AI_MARKER_RE = re.compile(r"【AI_GENERATED:([^】]+)】")


def _extract_generation_targets(docx_bytes: bytes) -> list[dict]:
    preview = word.extract_preview(docx_bytes, max_paragraphs=500)
    targets: list[dict] = []
    seen: set[str] = set()
    for p in preview.get("paragraphs") or []:
        text = p.get("text") or ""
        for m in PLACEHOLDER_RE.finditer(text):
            key = m.group(1)
            if key not in seen:
                seen.add(key)
                targets.append({"type": "placeholder", "key": key, "sample": text[:200]})
        for m in AI_MARKER_RE.finditer(text):
            key = m.group(1)
            if key not in seen:
                seen.add(key)
                targets.append({"type": "ai_section", "key": key, "sample": text[:200]})
    return targets


async def generate_document_from_template(
    docx_bytes: bytes,
    requirements: str,
    db: Session | None = None,
    company_context: str = "",
) -> tuple[bytes, dict[str, Any]]:
    """严格基于模板结构生成新标书：保留版式，替换占位符与 AI 章节。"""
    preview = word.extract_preview(docx_bytes, max_paragraphs=500)
    full_text = "\n".join(p.get("text") or "" for p in preview.get("paragraphs") or [])
    targets = _extract_generation_targets(docx_bytes)

    prompt = (
        "你是铁路行业标书撰写专家。请根据「编写要求」为模板中的字段与章节生成内容。\n"
        "必须严格保持专业、正式文风，数字前后一致，不得编造无法核实的资质编号。\n\n"
        f"编写要求：\n{requirements}\n\n"
        f"企业背景：\n{(company_context or '')[:2000]}\n\n"
        f"模板结构节选：\n{full_text[:10000]}\n\n"
        f"需生成的键列表：{json.dumps(targets, ensure_ascii=False)}\n\n"
        "请返回 JSON 对象，键为字段名或章节名，值为对应正文（字符串）。"
        "只返回 JSON，不要 markdown。"
    )
    raw = await ai.chat_completion([
        {"role": "system", "content": "你是标书生成助手，只输出合法 JSON 对象。"},
        {"role": "user", "content": prompt},
    ], db=db)

    generated: dict[str, str] = {}
    if raw:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                generated = {str(k): str(v) for k, v in data.items()}
        except json.JSONDecodeError:
            pass

    if not generated:
        # 兜底：从 requirements 提取简单字段
        generated = {
            "project_name": _guess_project_name(requirements),
            "tender_no": "",
        }

    chapters = {k: {"content": v, "source": "ai"} for k, v in generated.items() if k}
    result_bytes = word.render_document(
        docx_bytes,
        fields=generated,
        chapters=chapters,
        highlight=False,
    )
    meta = {
        "generated_keys": list(generated.keys()),
        "target_count": len(targets),
        "engine": "aspose+llm",
    }
    return result_bytes, meta


def _guess_project_name(requirements: str) -> str:
    m = re.search(r"[「『\"](.+?)[」』\"]", requirements)
    if m:
        return m.group(1).strip()[:120]
    m = re.search(r"项目[名称名]*[：:]\s*(.+)", requirements)
    if m:
        return m.group(1).strip()[:120]
    return "投标项目"


async def edit_document_fragment(
    docx_bytes: bytes,
    instruction: str,
    *,
    selected_text: str = "",
    paragraph_index: int | None = None,
    db: Session | None = None,
    company_context: str = "",
) -> tuple[bytes, str, dict[str, Any]]:
    """根据用户指令修改文档片段（多轮对话场景）。"""
    context_text = selected_text
    if paragraph_index is not None and not context_text:
        preview = word.extract_preview(docx_bytes, max_paragraphs=500)
        paras = preview.get("paragraphs") or []
        match = next((p for p in paras if p.get("index") == paragraph_index), None)
        if match:
            context_text = match.get("text") or ""

    prompt = (
        "你是标书编辑助手。根据修改指令输出修订后的文本。\n"
        "要求：保持正式文风，仅修改必要内容，不要添加解释。\n\n"
        f"企业背景：{(company_context or '')[:1500]}\n\n"
        f"原文：\n{context_text}\n\n"
        f"修改指令：{instruction}\n\n"
        "请只输出修订后的正文，不要 markdown，不要前后说明。"
    )
    revised = await ai.chat_completion([
        {"role": "system", "content": "你是标书正文编辑助手。"},
        {"role": "user", "content": prompt},
    ], db=db)
    revised = (revised or context_text).strip()
    if not revised:
        raise ValueError("AI 未返回有效修订内容")

    if selected_text and selected_text in (context_text or selected_text):
        new_bytes = word.replace_text_snippet(docx_bytes, selected_text, revised)
        mode = "snippet"
    elif paragraph_index is not None:
        new_bytes = word.replace_paragraph_text(docx_bytes, paragraph_index, revised)
        mode = "paragraph"
    elif context_text:
        new_bytes = word.replace_text_snippet(docx_bytes, context_text, revised)
        mode = "snippet"
    else:
        raise ValueError("请提供选中文本或段落索引")

    return new_bytes, revised, {"mode": mode, "paragraph_index": paragraph_index}
