"""创作模式：空白/结构模板的规划与分块生成。"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.services import ai
from app.services.doc_engine.compose_policy import should_generate_ai_narrative


def _outline_context_block(
    docx_bytes: bytes | None,
    manifest: dict[str, Any] | None,
    *,
    max_chars: int = 3500,
) -> str:
    if not docx_bytes:
        return ""
    from app.services.doc_engine.document_map import build_document_map, compact_outline_for_agent

    try:
        doc_map = build_document_map(docx_bytes, manifest)
        compact = compact_outline_for_agent(doc_map, max_sections=22)
        raw = json.dumps(compact, ensure_ascii=False)
        if len(raw) > max_chars:
            return raw[: max_chars - 1] + "…"
        return raw
    except Exception:
        return ""


async def build_composition_plan(
    manifest: dict[str, Any],
    fields: dict[str, Any],
    requirements: str,
    company_context: str = "",
    db: Session | None = None,
    *,
    docx_bytes: bytes | None = None,
) -> dict[str, Any]:
    """为创作模式生成块级写作计划。"""
    blocks = manifest.get("blocks") or []
    ai_blocks = [b for b in blocks if b.get("type") == "ai_section"]
    field_blocks = [b for b in blocks if b.get("type") == "field_slot"]
    table_blocks = [b for b in blocks if b.get("type") == "table_slot"]

    plan_items = []
    for b in field_blocks:
        key = b.get("bind") or ""
        plan_items.append({
            "block_id": b.get("id"),
            "type": "field_slot",
            "bind": key,
            "source": "fields",
            "value": fields.get(key, ""),
        })

    eligible_ai = [
        b for b in ai_blocks
        if should_generate_ai_narrative(str(b.get("title") or ""), docx_bytes)
    ]

    outline_ctx = _outline_context_block(docx_bytes, manifest)

    if eligible_ai:
        catalog = json.dumps(
            [{"id": b.get("id"), "title": b.get("title")} for b in eligible_ai],
            ensure_ascii=False,
        )
        prompt = (
            "你是铁路行业标书撰写专家。根据项目信息与编写要求，为下列章节生成写作要点提纲。\n"
            f"编写要求：{requirements}\n"
            f"项目信息：{json.dumps(fields, ensure_ascii=False)}\n"
            f"企业背景：{(company_context or '')[:2000]}\n"
            f"章节列表：{catalog}\n"
        )
        if outline_ctx:
            prompt += (
                f"当前模板/草稿结构（Document Map，含 region_type 与 allows_ai_narrative）：\n"
                f"{outline_ctx}\n"
                "禁止为 form_table、letter_skeleton 或 allows_ai_narrative=false 的章节规划叙事正文。\n"
            )
        prompt += (
            "\n返回 JSON 数组，每项含 block_id, outline(字符串数组), constraints(字符串数组)。只返回 JSON。"
        )
        raw = await ai.chat_completion([
            {"role": "system", "content": "你是标书创作规划助手，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ], db=db)
        llm_plan = _parse_json_array(raw)
        by_id = {x.get("block_id"): x for x in llm_plan if x.get("block_id")}
        for b in eligible_ai:
            bid = b.get("id")
            extra = by_id.get(bid) or {}
            plan_items.append({
                "block_id": bid,
                "type": "ai_section",
                "title": b.get("title"),
                "outline": extra.get("outline") or [f"撰写「{b.get('title')}」正式段落"],
                "constraints": extra.get("constraints") or ["不得编造资质编号", "与项目信息一致"],
            })
    else:
        for b in eligible_ai:
            plan_items.append({
                "block_id": b.get("id"),
                "type": "ai_section",
                "title": b.get("title"),
                "outline": [f"撰写「{b.get('title')}」"],
                "constraints": [],
            })

    for b in table_blocks:
        plan_items.append({
            "block_id": b.get("id"),
            "type": "table_slot",
            "bind": b.get("bind"),
            "columns": b.get("columns") or [],
            "title": b.get("title") or b.get("bind"),
        })

    return {"items": plan_items, "mode": manifest.get("mode") or "create"}


async def generate_block_contents(
    plan: dict[str, Any],
    fields: dict[str, Any],
    requirements: str,
    company_context: str = "",
    db: Session | None = None,
    *,
    docx_bytes: bytes | None = None,
    manifest: dict[str, Any] | None = None,
) -> tuple[dict[str, str], dict[str, list[dict[str, Any]]]]:
    """按计划分块生成文本内容与表格行数据。"""
    from app.services.doc_engine.table_compose import generate_table_rows_for_slot

    contents: dict[str, str] = {}
    table_updates: dict[str, list[dict[str, Any]]] = {}
    outline_ctx = _outline_context_block(docx_bytes, manifest)
    for item in plan.get("items") or []:
        if item.get("type") == "table_slot":
            bind = item.get("bind") or ""
            if bind:
                rows = await generate_table_rows_for_slot(
                    item, fields, requirements, company_context, db=db,
                )
                if rows:
                    table_updates[bind] = rows
            continue
        if item.get("type") == "field_slot":
            key = item.get("bind") or ""
            if key:
                contents[key] = str(item.get("value") or fields.get(key) or "")
            continue
        if item.get("type") != "ai_section":
            continue
        title = item.get("title") or item.get("block_id")
        if not should_generate_ai_narrative(str(title or ""), docx_bytes):
            continue
        from app.services.doc_engine.document_map import region_allows_ai_narrative_write

        if docx_bytes and not region_allows_ai_narrative_write(
            docx_bytes, str(title or ""), manifest=manifest,
        ):
            continue
        outline = item.get("outline") or []
        constraints = item.get("constraints") or []
        prompt = (
            f"请为标书章节「{title}」撰写正式中文正文，约300-500字。\n"
            f"编写要求：{requirements}\n"
            f"要点：{'；'.join(outline)}\n"
            f"约束：{'；'.join(constraints)}\n"
            f"项目信息：{json.dumps(fields, ensure_ascii=False)}\n"
            f"企业背景：{(company_context or '')[:2000]}\n"
        )
        if outline_ctx:
            prompt += (
                f"文档结构摘要：{outline_ctx[:1200]}\n"
                "若该章节在 Map 中为 form_table 或已有表格填位，不要写套话，应简短或跳过。\n"
            )
        prompt += "只输出正文，不要标题，不要 markdown。"
        text = await ai.chat_completion([
            {"role": "system", "content": "你是铁路行业标书撰写助手。"},
            {"role": "user", "content": prompt},
        ], db=db)
        if not text:
            from app.services.ai import local_chapter_text
            text = local_chapter_text(title, fields)
        contents[title] = text.strip()
        contents[item.get("block_id", "")] = text.strip()
    return contents, table_updates


def _parse_json_array(raw: str | None) -> list[dict]:
    if not raw:
        return []
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []
