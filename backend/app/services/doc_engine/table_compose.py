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
    if table_slot_skip_llm(slot):
        seeded = seed_rows_for_slot(slot, fields, db=db)
        return seeded or []
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


def _slot_blob(slot: dict[str, Any]) -> str:
    title = str(slot.get("title") or "")
    bind = str(slot.get("bind") or "")
    return f"{title}\n{bind}"


def table_slot_skip_llm(slot: dict[str, Any]) -> bool:
    """业绩/报价/资质类表格只用确定性填表，避免 LLM 写入当前标段信息。"""
    blob = _slot_blob(slot)
    if any(k in blob for k in ("认证", "许可", "资质", "证书")):
        return True
    if any(k in blob for k in ("业绩", "供货", "合同")):
        return True
    if any(k in blob for k in ("报价", "竞标物资报价", "物资描述", "成本分析")):
        return True
    return False


_HISTORICAL_PERFORMANCE_PROJECTS: list[dict[str, str]] = [
    {
        "project_name": "京沪高铁信号系统更新改造工程",
        "tender_no": "ZGTL-2019-SX-G01",
        "year": "2020",
        "amount": "1260万元",
        "owner": "中国铁路北京局集团有限公司",
        "material": "铁路信号监测与联锁设备",
    },
    {
        "project_name": "深圳地铁16号线弱电系统维保服务",
        "tender_no": "SZDT-16-WB-2021",
        "year": "2022",
        "amount": "860万元",
        "owner": "深圳地铁集团有限公司",
        "material": "弱电及通信系统维保",
    },
    {
        "project_name": "成兰铁路四电集成工程信号子系统",
        "tender_no": "CLTL-4D-2018-07",
        "year": "2019",
        "amount": "2150万元",
        "owner": "成兰铁路有限责任公司",
        "material": "四电集成信号设备",
    },
]


def _performance_projects_for_fields(fields: dict[str, Any]) -> list[dict[str, str]]:
    cur_name = str(fields.get("project_name") or "").strip()
    cur_no = str(fields.get("tender_no") or "").strip()
    out: list[dict[str, str]] = []
    for proj in _HISTORICAL_PERFORMANCE_PROJECTS:
        pname = proj.get("project_name") or ""
        tno = proj.get("tender_no") or ""
        if cur_name and cur_name in pname:
            continue
        if cur_no and cur_no == tno:
            continue
        out.append(proj)
    return out[:6]


def _cell_from_fields(col: str, fields: dict[str, Any]) -> str:
    c = _clean_col(col)
    if "谈判" in c or "招标编号" in c or "项目编号" in c:
        return str(fields.get("tender_no") or "").strip()
    if "包件" in c:
        return str(fields.get("package_no") or "").strip()
    if any(k in c for k in ("竞标人", "投标人", "供应商", "单位名称")):
        return str(fields.get("bidder_name") or fields.get("bidder") or "").strip()
    if "物资" in c and "类别" in c:
        return str(fields.get("material_type") or "").strip()
    if "物资" in c or "名称" in c and "项目" not in c:
        return str(fields.get("material_type") or fields.get("project_name") or "").strip()
    if any(k in c for k in ("报价", "总价", "金额", "单价")):
        lower = str(fields.get("bid_amount_lower") or fields.get("bid_amount") or "").strip()
        upper = str(fields.get("bid_amount_upper") or "").strip()
        if lower and upper:
            return f"{lower}（{upper}）"
        return lower or upper
    if "采购人" in c or "招标人" in c:
        return str(fields.get("tenderer") or "").strip()
    if "工期" in c or "供货期" in c:
        return str(fields.get("duration") or "").strip()
    if "质保" in c:
        return str(fields.get("warranty_period") or "").strip()
    return ""


def _cell_from_performance(col: str, index: int, proj: dict[str, str]) -> str:
    c = _clean_col(col)
    if "序号" in c:
        return str(index)
    if any(k in c for k in ("项目", "工程", "合同")):
        return proj.get("project_name") or ""
    if "编号" in c or "谈判" in c:
        return proj.get("tender_no") or ""
    if any(k in c for k in ("物资", "产品", "设备")):
        return proj.get("material") or ""
    if "时间" in c or "年份" in c or "年度" in c:
        return proj.get("year") or ""
    if any(k in c for k in ("金额", "总价", "合同价")):
        return proj.get("amount") or ""
    if any(k in c for k in ("采购人", "业主", "招标人", "甲方")):
        return proj.get("owner") or ""
    return ""


def _seed_performance_rows(columns: list[str], fields: dict[str, Any]) -> list[dict[str, Any]]:
    projects = _performance_projects_for_fields(fields)
    if not projects:
        return []
    rows: list[dict[str, Any]] = []
    for idx, proj in enumerate(projects, 1):
        row = {_clean_col(col): _cell_from_performance(col, idx, proj) for col in columns}
        if any(str(v).strip() for v in row.values()):
            rows.append(row)
    return rows


def _seed_quote_rows(columns: list[str], fields: dict[str, Any]) -> list[dict[str, Any]]:
    if not columns:
        return []
    row = {_clean_col(col): _cell_from_fields(col, fields) for col in columns}
    if not any(str(v).strip() for v in row.values()):
        return []
    return [row]


def _clean_col(col: str) -> str:
    return (col or "").replace("\x07", "").replace("\a", "").strip()


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
    blob = f"{title}\n{bind}"
    if any(k in blob for k in ("业绩", "供货", "合同")):
        perf = _seed_performance_rows(columns, fields)
        if perf:
            return perf
    if any(k in blob for k in ("报价", "竞标物资报价", "物资描述", "成本分析")):
        quote = _seed_quote_rows(columns, fields)
        if quote:
            return quote
    if not any(k in title or k in bind for k in ("认证", "许可", "资质", "证书")):
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
        row = {col: _column_value(_clean_col(col), idx, qual) for col in columns}
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
