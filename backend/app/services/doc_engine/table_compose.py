"""表格槽：LLM 生成行数据与项目字段读写。"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.services import ai
from app.services.doc_engine.manifest import get_manifest
from app.services.doc_engine.parser import parse_template_manifest
from app.services.doc_engine.tables import parse_rows_data, resolve_table_rows


def list_table_slots(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    slots = []
    for b in manifest.get("blocks") or []:
        if b.get("type") != "table_slot":
            continue
        bind = b.get("bind") or ""
        slots.append({
            "id": b.get("id"),
            "bind": bind,
            "columns": b.get("columns") or [],
            "title": b.get("title") or bind or b.get("id"),
            "table_index": b.get("table_index"),
            "required": bool(b.get("required")),
        })
    return slots


def get_table_slot_rows(fields: dict[str, Any], bind: str) -> list[dict[str, Any]]:
    return parse_rows_data(fields.get(bind))


def set_table_slot_rows(fields: dict[str, Any], bind: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    out = dict(fields or {})
    out[bind] = rows
    return out


async def generate_table_rows_for_slot(
    slot: dict[str, Any],
    fields: dict[str, Any],
    requirements: str,
    company_context: str = "",
    db: Session | None = None,
) -> list[dict[str, Any]]:
    """为单个 table_slot 用 LLM 生成行数据。"""
    columns = slot.get("columns") or []
    if not columns:
        return []
    bind = slot.get("bind") or ""
    existing = resolve_table_rows({"bind": bind, "columns": columns}, fields)
    if existing:
        return existing

    title = slot.get("title") or bind
    prompt = (
        f"你是铁路行业标书数据助手。请为表格「{title}」生成行数据。\n"
        f"列定义：{json.dumps(columns, ensure_ascii=False)}\n"
        f"编写要求：{requirements}\n"
        f"项目信息：{json.dumps({k: v for k, v in fields.items() if not str(k).startswith('_')}, ensure_ascii=False)}\n"
        f"企业背景：{(company_context or '')[:1500]}\n\n"
        "返回 JSON 数组，每项为对象，键为列名。生成 2-6 行 realistic 数据，不要 markdown，只返回 JSON 数组。"
    )
    raw = await ai.chat_completion([
        {"role": "system", "content": "你只输出合法 JSON 数组。"},
        {"role": "user", "content": prompt},
    ], db=db)
    rows = _parse_json_array(raw)
    normalized = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized.append({col: str(row.get(col) or "") for col in columns})
    return normalized


async def generate_all_table_rows(
    manifest: dict[str, Any],
    fields: dict[str, Any],
    requirements: str,
    company_context: str = "",
    db: Session | None = None,
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for slot in list_table_slots(manifest):
        bind = slot.get("bind") or ""
        if not bind:
            continue
        rows = await generate_table_rows_for_slot(
            slot, fields, requirements, company_context, db=db,
        )
        if rows:
            result[bind] = rows
    return result


def table_slots_from_template(tpl_placeholders: dict | None, tpl_bytes: bytes) -> list[dict[str, Any]]:
    manifest = get_manifest(tpl_placeholders) or parse_template_manifest(tpl_bytes)
    return list_table_slots(manifest)


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
