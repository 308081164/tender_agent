"""创作模式：空白/结构模板的规划与分块生成。"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.services import ai


async def build_composition_plan(
    manifest: dict[str, Any],
    fields: dict[str, Any],
    requirements: str,
    company_context: str = "",
    db: Session | None = None,
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

    if ai_blocks:
        catalog = json.dumps(
            [{"id": b.get("id"), "title": b.get("title")} for b in ai_blocks],
            ensure_ascii=False,
        )
        prompt = (
            "你是铁路行业标书撰写专家。根据项目信息与编写要求，为下列章节生成写作要点提纲。\n"
            f"编写要求：{requirements}\n"
            f"项目信息：{json.dumps(fields, ensure_ascii=False)}\n"
            f"企业背景：{(company_context or '')[:2000]}\n"
            f"章节列表：{catalog}\n\n"
            "返回 JSON 数组，每项含 block_id, outline(字符串数组), constraints(字符串数组)。只返回 JSON。"
        )
        raw = await ai.chat_completion([
            {"role": "system", "content": "你是标书创作规划助手，只输出 JSON。"},
            {"role": "user", "content": prompt},
        ], db=db)
        llm_plan = _parse_json_array(raw)
        by_id = {x.get("block_id"): x for x in llm_plan if x.get("block_id")}
        for b in ai_blocks:
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
        for b in ai_blocks:
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
) -> tuple[dict[str, str], dict[str, list[dict[str, Any]]]]:
    """按计划分块生成文本内容与表格行数据。"""
    from app.services.doc_engine.table_compose import generate_table_rows_for_slot

    contents: dict[str, str] = {}
    table_updates: dict[str, list[dict[str, Any]]] = {}
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
        outline = item.get("outline") or []
        constraints = item.get("constraints") or []
        prompt = (
            f"请为标书章节「{title}」撰写正式中文正文，约300-500字。\n"
            f"编写要求：{requirements}\n"
            f"要点：{'；'.join(outline)}\n"
            f"约束：{'；'.join(constraints)}\n"
            f"项目信息：{json.dumps(fields, ensure_ascii=False)}\n"
            f"企业背景：{(company_context or '')[:2000]}\n"
            "只输出正文，不要标题，不要 markdown。"
        )
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
