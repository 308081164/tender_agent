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
    seeded = seed_rows_for_slot(slot, fields, db=db)
    if seeded:
        return seeded

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


def _column_value(col: str, index: int, qual: Any) -> str:
    if "序号" in col:
        return str(index)
    if any(k in col for k in ("认证", "名称", "证书")):
        return str(getattr(qual, "name", "") or "")
    if "编号" in col or "证号" in col:
        hint = str(getattr(qual, "ocr_text", "") or "").strip()
        if hint:
            return hint[:64]
        return str(getattr(qual, "file_name", "") or "")[:64]
    if "发证" in col or "机构" in col:
        return str(getattr(qual, "issuer", "") or "")
    if "有效期" in col:
        if getattr(qual, "is_long_term", False):
            return "长期"
        vf = getattr(qual, "valid_from", None)
        vt = getattr(qual, "valid_to", None)
        if vf and vt:
            return f"{vf}至{vt}"
    return str(getattr(qual, "category", "") or "")


def seed_rows_for_slot(
    slot: dict[str, Any],
    fields: dict[str, Any],
    *,
    db: Session | None = None,
    company: Any = None,
) -> list[dict[str, Any]]:
    columns = slot.get("columns") or []
    bind = slot.get("bind") or ""
    if not columns or not bind:
        return []
    title = str(slot.get("title") or bind)
    if not any(k in title for k in ("认证", "许可", "资质", "证书")):
        return []
    quals = []
    overview = ""
    if db is not None:
        from app.models import Qualification

        quals = db.query(Qualification).order_by(
            Qualification.sort_order.asc(), Qualification.id.asc(),
        ).all()
        if company is None:
            from app.models import CompanyProfile

            company = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    if company is not None:
        overview = str(getattr(company, "qual_overview", "") or "").strip()
    rows: list[dict[str, Any]] = []
    for idx, qual in enumerate(quals[:12], 1):
        row = {col: _column_value(col, idx, qual) for col in columns}
        if any(str(v).strip() for v in row.values()):
            rows.append(row)
    if not rows and overview:
        parts = re.split(r"[、，,；;]", overview)
        for idx, part in enumerate([p.strip() for p in parts if p.strip()][:8], 1):
            row = {}
            for col in columns:
                if "序号" in col:
                    row[col] = str(idx)
                elif any(k in col for k in ("认证", "名称")):
                    row[col] = part
                else:
                    row[col] = ""
            rows.append(row)
    return rows


def seed_table_field_rows(
    db: Session | None,
    manifest: dict[str, Any],
    fields: dict[str, Any],
    company: Any = None,
) -> dict[str, Any]:
    out = dict(fields or {})
    for slot in list_table_slots(manifest):
        bind = slot.get("bind") or ""
        if not bind:
            continue
        if resolve_table_rows(slot, out):
            continue
        rows = seed_rows_for_slot(slot, out, db=db, company=company)
        if rows:
            out[bind] = rows
    return out


def apply_table_rows_to_docx(
    docx_bytes: bytes,
    manifest: dict[str, Any],
    fields: dict[str, Any],
) -> bytes:
    from app.services.doc_engine.tables import fill_table_slot

    data = docx_bytes
    for slot in list_table_slots(manifest):
        rows = resolve_table_rows(slot, fields)
        if not rows:
            continue
        data = fill_table_slot(
            data,
            int(slot.get("table_index") or 0),
            slot.get("columns") or [],
            rows,
            header_rows=int(slot.get("header_rows") or 1),
            template_row=slot.get("template_row"),
        )
    return data
