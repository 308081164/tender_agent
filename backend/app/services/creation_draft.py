"""进入创作时读模板，把第二步和企业档案写进草稿。

历史标书上的旧项目名、编号、金额走 detect_placeholder_candidates / apply，
再交给 render_document。用户看不到占位符编辑器。
"""
from __future__ import annotations

import json
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models import CompanyProfile, FieldDef, Qualification, Template, TenderProject
from app.services import storage, template_detect, word
from app.services.doc_engine.compose_policy import should_generate_ai_narrative
from app.services.docx_ooxml import document_text, paragraph_records
from app.services.field_defaults import fill_field_defaults

STANDARD_KEYS = (
    "project_name",
    "tender_no",
    "tenderer",
    "bidder_name",
    "duration",
    "bid_amount",
    "bid_amount_upper",
    "bid_amount_lower",
    "phone",
    "legal_name",
    "address",
)
PRICE_KEYS = ("bid_amount", "bid_amount_upper", "bid_amount_lower")
STEP2_KNOWN = ("project_name", "tender_no", "tenderer", "duration")
FIELD_LABELS = {
    "project_name": "项目名称",
    "tender_no": "招标编号",
    "tenderer": "招标人",
    "bidder_name": "投标人",
    "duration": "工期",
    "bid_amount": "报价",
    "bid_amount_upper": "报价",
    "bid_amount_lower": "报价",
    "phone": "电话",
    "legal_name": "法定代表人",
    "address": "地址",
}

RAILWAY_BLANK_COVER_LINES: tuple[tuple[str, str, str], ...] = (
    ("谈判编号：CRCEBG5-2026-CQSNTP011", "tender_no", "谈判编号：{val}"),
    ("包件号：DL05", "package_no", "包件号：{val}"),
    ("竞标人：和远智能科技股份有限公司（盖单位章）", "bidder_name", "竞标人：{val}（盖单位章）"),
    ("2026年 04 月 28 日", "bid_date", "{val}"),
)


def _format_bid_date_line(fields: dict[str, Any]) -> str:
    raw = str(fields.get("bid_date") or fields.get("sign_date") or "").strip()
    if not raw:
        return ""
    if "年" in raw and "月" in raw:
        return raw
    parts = raw.replace("/", "-").split("-")
    if len(parts) >= 3:
        y, m, d = parts[0], int(parts[1]), int(parts[2])
        return f"{y}年{m}月{d}日"
    return raw


def apply_railway_blank_cover_lines(docx_bytes: bytes, fields: dict[str, Any]) -> bytes:
    pairs: list[tuple[str, str]] = []
    bid_line = _format_bid_date_line(fields)
    for old, key, fmt in RAILWAY_BLANK_COVER_LINES:
        if key == "bid_date":
            val = bid_line
        else:
            val = str(fields.get(key) or "").strip()
        if not val:
            continue
        new_line = fmt.format(val=val)
        if old != new_line:
            pairs.append((old, new_line))
    if not pairs:
        return docx_bytes
    return word.apply_literal_replacements(docx_bytes, pairs, highlight=False)


def _deterministic_field_mappings(docx_bytes: bytes, fields: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        text = document_text(docx_bytes)
    except Exception:
        text = ""
    out: list[dict[str, Any]] = []
    for snippet, key in (
        ("CRCEBG5-2026-CQSNTP011", "tender_no"),
        ("DL05", "package_no"),
        ("和远智能科技股份有限公司", "bidder_name"),
    ):
        val = str(fields.get(key) or "").strip()
        if snippet in text and val and snippet != val:
            out.append({
                "key": key,
                "field_name": FIELD_LABELS.get(key, key),
                "original_text": snippet,
                "confidence": 1.0,
                "reason": "铁路空白模板样例值",
                "source": "deterministic",
                "bind_type": "field",
                "approved": True,
            })
    return out


def _norm(value: str) -> str:
    return "".join(str(value or "").split())


def _similar(left: str, right: str) -> bool:
    a = _norm(left)
    b = _norm(right)
    if not a or not b or a == b:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.72


def _docx_filename(name: str) -> str:
    text = (name or "模板").strip() or "模板"
    if text.lower().endswith(".docx"):
        return text
    return f"{text}.docx"


def _company(db: Session) -> CompanyProfile | None:
    return db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()


def _field_defs_for_detect(db: Session) -> list[dict]:
    rows = db.query(FieldDef).order_by(FieldDef.sort_order.asc()).all()
    catalog = [
        {
            "key": row.key,
            "name": row.name,
            "field_type": row.field_type,
            "module": row.module,
            "required": bool(row.required),
        }
        for row in rows
        if row.key
    ]
    present = {item["key"] for item in catalog}
    for key in STANDARD_KEYS:
        if key not in present:
            catalog.append({
                "key": key,
                "name": FIELD_LABELS.get(key, key),
                "field_type": "文本",
                "module": "",
                "required": False,
            })
    return catalog


def _section_starter(title: str, project_name: str) -> str:
    name = project_name or "本项目"
    if "投标函" in title:
        return f"我方参加「{name}」投标，现提交投标函，并按招标文件要求编制。"
    if "技术方案" in title:
        return f"针对「{name}」，技术方案从实施范围、质量措施和进度安排写起。"
    return f"「{title}」按「{name}」的招标要求开始编写。"


def _empty_sections(data: bytes) -> list[str]:
    try:
        records = [item for item in paragraph_records(data) if not item.get("in_table")]
    except Exception:
        return []
    titles: list[str] = []
    for idx, rec in enumerate(records):
        style = rec.get("style") or ""
        text = (rec.get("text") or "").strip()
        heading = style.lower().startswith("heading") or "标题" in style
        if not heading or not text or len(text) > 40:
            continue
        nxt = records[idx + 1] if idx + 1 < len(records) else None
        nxt_text = ((nxt or {}).get("text") or "").strip()
        if nxt is not None and len(nxt_text) > 30:
            continue
        if not should_generate_ai_narrative(text, data):
            continue
        titles.append(text)
    return titles


def should_write_draft(project: TenderProject) -> bool:
    if not project.template_id:
        return False
    if (project.current_step or 1) >= 3:
        return True
    fields = project.fields or {}
    return any(str(fields.get(key) or "").strip() for key in STEP2_KNOWN)


def _signature(project: TenderProject, fields: dict, company: CompanyProfile | None) -> str:
    kept = {
        key: str(fields.get(key) or "")
        for key in list(STANDARD_KEYS) + ["_writing_requirements"]
    }
    payload = {
        "template_id": project.template_id,
        "fields": kept,
        "company": getattr(company, "full_name", "") or "",
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _known_lines(fields: dict, company: CompanyProfile | None) -> list[dict[str, str]]:
    known: list[dict[str, str]] = []
    for key in STEP2_KNOWN:
        value = str(fields.get(key) or "").strip()
        if not value:
            continue
        known.append({"key": key, "name": FIELD_LABELS.get(key, key), "value": value})
    full_name = (getattr(company, "full_name", "") or "").strip() if company else ""
    if full_name and not any(item["key"] == "bidder_name" and item["value"] == full_name for item in known):
        known.append({"key": "company", "name": "企业名称", "value": full_name})
    return known


def _price_value(fields: dict) -> str:
    for key in PRICE_KEYS:
        value = str(fields.get(key) or "").strip()
        if value:
            return value
    return ""


def _select_mappings(
    candidates: list[dict],
    fields: dict,
    company_name: str,
) -> tuple[list[dict], list[dict], list[dict]]:
    """返回 (要应用的映射, 已写入说明, 仍要人决定的事)。"""
    mappings: list[dict] = []
    written: list[dict] = []
    opens: list[dict] = []
    seen_open: set[str] = set()
    price_open = False

    def _open(kind: str, text: str, field_key: str = "") -> None:
        if kind in seen_open:
            return
        seen_open.add(kind)
        item = {"kind": kind, "text": text}
        if field_key:
            item["field_key"] = field_key
        opens.append(item)

    for cand in candidates or []:
        key = str(cand.get("key") or "").strip()
        original = str(cand.get("original_text") or "").strip()
        if not key or not original or cand.get("bind_type") == "qual":
            continue
        if cand.get("bind_type") == "runtime" or key.startswith("runtime_"):
            continue
        confidence = float(cand.get("confidence") or 0)
        status = cand.get("match_status") or ""
        applicable = (status == "matched" and confidence >= 0.55) or (
            key in STANDARD_KEYS and confidence >= 0.6 and (cand.get("bind_type") or "field") == "field"
        )
        if not applicable:
            if status == "low_confidence" and key in ("bidder_name", "tenderer") and _similar(original, company_name or fields.get(key) or ""):
                _open(
                    "company_name",
                    f"文中的公司名「{original}」和企业档案不完全一致，请确认用哪一个。",
                    "bidder_name",
                )
            continue
        new_val = str(fields.get(key) or "").strip()
        if key in PRICE_KEYS:
            new_val = new_val or _price_value(fields)
        if key == "duration" and new_val and _norm(original) != _norm(new_val):
            _open(
                "duration_conflict",
                f"文中工期是「{original}」，第二步填写的是「{new_val}」。请确认用哪一个，我先不改这一处。",
                "duration",
            )
            continue
        if key in ("bidder_name", "tenderer") and company_name and _similar(original, company_name):
            _open(
                "company_name",
                f"文中的公司名「{original}」和档案「{company_name}」接近但并不相同，请确认用哪一个。",
                key,
            )
            continue
        if key in PRICE_KEYS and not new_val:
            price_open = True
        elif not new_val:
            continue
        if _norm(original) == _norm(new_val):
            continue
        mappings.append({
            "key": key,
            "field_name": cand.get("field_name") or FIELD_LABELS.get(key, key),
            "original_text": original,
            "approved": True,
            "action": "replace",
            "bind_type": "field",
        })
        written.append({
            "key": key,
            "name": FIELD_LABELS.get(key, cand.get("field_name") or key),
            "value": new_val,
            "original": original,
            "detail": f"「{original}」→「{new_val or '（待填）'}」",
        })

    if not _price_value(fields):
        price_open = True
    if price_open:
        _open("price", "报价还没有确定，请直接回复投标总价。", "bid_amount")
    return mappings, written, opens


def _qualification_decision(db: Session, data: bytes) -> dict | None:
    try:
        text = document_text(data)
    except Exception:
        text = ""
    if not any(token in text for token in ("资质", "证明", "信誉", "业绩")):
        return None
    quals = db.query(Qualification).order_by(Qualification.id.asc()).all()
    if len(quals) < 2:
        return None
    names = "、".join(q.name for q in quals[:6])
    return {
        "kind": "qualification",
        "text": f"资质章节可以插入这些材料：{names}。请告诉我要插入哪一份。",
    }


def format_creation_greeting(report: dict) -> str:
    name = report.get("template_name") or "当前模板"
    lines = [
        f"已接入「{name}」。模板已经在左侧文档工作区打开，编写、审查和导出都在这条对话里完成。",
    ]
    known = report.get("known") or []
    if known:
        lines.append("")
        lines.append("已掌握：")
        for item in known:
            lines.append(f"- {item.get('name')}：{item.get('value')}")
    written = report.get("written") or []
    sections = report.get("empty_sections") or []
    if written:
        lines.append("")
        lines.append("已写入草稿：")
        for item in written:
            lines.append(f"- {item.get('name')}：{item.get('detail') or item.get('value')}")
    elif sections:
        lines.append("")
        lines.append("这是空白模板，已在草稿中开始写这些章节：" + "、".join(sections) + "。")
        lines.append("对应标题下的空段已经起稿，不必再画占位符。")
    else:
        lines.append("")
        lines.append("模板正文已读入工作区。")
    opens = report.get("open_decisions") or []
    if opens:
        lines.append("")
        lines.append("仍需你决定：")
        for idx, item in enumerate(opens, 1):
            lines.append(f"{idx}. {item.get('text')}")
    else:
        lines.append("")
        lines.append("第二步已经填写、且没有冲突的字段不再询问。可以直接继续写。")
    return "\n".join(lines)


def open_decision_card(report: dict) -> dict | None:
    fields = []
    for item in report.get("open_decisions") or []:
        if item.get("kind") != "price":
            continue
        fields.append({
            "key": "bid_amount",
            "name": "报价",
            "field_type": "金额",
            "required": False,
            "default": "",
        })
    if not fields:
        return None
    return {
        "id": "creation-open-decisions",
        "type": "field_collect",
        "title": "需要你决定",
        "state": "active",
        "payload": {
            "fields": fields,
            "template_name": report.get("template_name") or "",
            "confirm_action": "confirm_fields",
            "cancel_action": "dismiss_card",
        },
    }


def get_project_render_base_docx(project: TenderProject, tpl: Template) -> tuple[bytes, dict | None]:
    """导出/预览优先用创作草稿（含占位符映射与字段初填），否则回退原始模板。"""
    stored = dict(project.fields or {})
    draft_key = str(stored.get("_draft_object_key") or "").strip()
    snap = getattr(tpl, "source_snapshot", None) or {}
    snap_dict = snap if isinstance(snap, dict) else {}
    if draft_key and stored.get("_creation_prepared"):
        try:
            data = storage.download_bytes(draft_key)
            if data:
                return data, snap_dict or None
        except Exception:
            pass
    if not tpl.object_key:
        raise ValueError("template_missing")
    return storage.download_bytes(tpl.object_key), snap_dict or None


def _bind_session(session, project: TenderProject, filename: str) -> None:
    if session is None:
        return
    ws = dict(getattr(session, "workspace", None) or {})
    draft_key = (project.fields or {}).get("_draft_object_key") or ""
    ws["project_id"] = project.id
    if project.template_id:
        ws["template_id"] = project.template_id
    if draft_key:
        ws["draft_object_key"] = draft_key
    ws["filename"] = filename
    ws["version"] = max(int(ws.get("version") or 0), 1)
    ws["last_action"] = "creation_draft"
    session.workspace = ws


async def materialize_creation_draft(db: Session, project: TenderProject, session=None) -> dict[str, Any]:
    """读模板并写入草稿。没有模板时只返回空报告，不报错阻断会话。"""
    if not project.template_id:
        return {"ok": False, "reason": "no_template"}
    tpl = db.query(Template).filter(Template.id == project.template_id).first()
    if not tpl or not tpl.object_key:
        return {"ok": False, "reason": "template_missing"}
    try:
        data = storage.download_bytes(tpl.object_key)
    except Exception:
        return {"ok": False, "reason": "template_unreadable"}
    if not data:
        return {"ok": False, "reason": "template_empty"}

    company = _company(db)
    fields = fill_field_defaults(db, project.fields or {})
    company_name = (company.full_name or "").strip() if company else ""
    if company_name and not str(fields.get("bidder_name") or "").strip():
        fields["bidder_name"] = company_name
    signature = _signature(project, fields, company)
    stored = dict(project.fields or {})
    filename = _docx_filename(tpl.name)
    cached = stored.get("_creation_report") if isinstance(stored.get("_creation_report"), dict) else None
    if stored.get("_creation_signature") == signature and stored.get("_draft_object_key") and cached:
        _bind_session(session, project, filename)
        db.commit()
        return cached

    sections = _empty_sections(data)
    existing = word.safe_extract_placeholders(data)
    try:
        detected = await template_detect.detect_placeholder_candidates(
            data, _field_defs_for_detect(db), db=db,
        )
    except Exception:
        detected = {"candidates": []}
    mappings, written, opens = _select_mappings(
        detected.get("candidates") or [], fields, company_name,
    )
    det = _deterministic_field_mappings(data, fields)
    seen_keys = {m.get("key") for m in mappings}
    for item in det:
        if item.get("key") in seen_keys:
            continue
        mappings.append(item)
        written.append({
            "key": item["key"],
            "name": item.get("field_name") or item["key"],
            "value": str(fields.get(item["key"]) or ""),
            "detail": item.get("reason") or "",
            "original": item.get("original_text") or "",
        })
    qual = _qualification_decision(db, data)
    if qual:
        opens.append(qual)

    working = data
    snapshot: dict[str, str] = {}
    if mappings:
        working, snapshot, _placeholders = template_detect.apply_placeholder_mappings(data, mappings)
        if snapshot:
            merged_snap = dict(tpl.source_snapshot or {})
            merged_snap.update(snapshot)
            tpl.source_snapshot = merged_snap
            flag_modified(tpl, "source_snapshot")
    rendered = word.render_document(
        working,
        fields,
        highlight=False,
        source_snapshot=snapshot or None,
    )
    rendered = apply_railway_blank_cover_lines(rendered, fields)
    try:
        rendered_text = document_text(rendered)
    except Exception:
        rendered_text = ""
    for item in written:
        original = item.get("original") or ""
        if original and original in rendered_text:
            rendered = word._ooxml_replace_all(rendered, original, item.get("value") or "")
            try:
                rendered_text = document_text(rendered)
            except Exception:
                rendered_text = ""
    # 单元格里还留着旧事实时，不能报「已写入」。
    written = [
        item for item in written
        if not (item.get("original") and item.get("original") in rendered_text)
        and (not item.get("value") or item.get("value") in rendered_text)
    ]
    starters = {
        title: _section_starter(title, str(fields.get("project_name") or "").strip())
        for title in sections
    }
    if starters:
        from app.services.docx_ooxml import write_section_starters
        rendered = write_section_starters(rendered, starters)

    from app.services.doc_engine.assembler import _fill_parenthesis_form_tokens

    rendered = _fill_parenthesis_form_tokens(rendered, fields, highlight=False)

    from app.services.doc_engine.manifest import get_manifest
    from app.services.doc_engine.parser import parse_template_manifest
    from app.services.doc_engine.table_compose import apply_table_rows_to_docx, seed_table_field_rows

    manifest = get_manifest(tpl.placeholders) or parse_template_manifest(data)
    stored_fields = dict(stored)
    stored_fields.update(fields)
    stored_fields = seed_table_field_rows(db, manifest, stored_fields, company)
    fields = dict(stored_fields)
    rendered = apply_table_rows_to_docx(rendered, manifest, fields)

    draft_key = f"projects/{project.id}/creation_draft.docx"
    storage.upload_bytes(
        draft_key,
        rendered,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    report = {
        "ok": True,
        "template_id": tpl.id,
        "template_name": tpl.name,
        "template_kind": tpl.kind or "",
        "filename": filename,
        "draft_object_key": draft_key,
        "known": _known_lines(fields, company),
        "written": [
            {"key": item["key"], "name": item["name"], "value": item.get("value") or "", "detail": item.get("detail") or ""}
            for item in written
        ],
        "open_decisions": opens,
        "empty_sections": sections,
        "existing_placeholders": existing,
        "replaced_old_values": [item.get("original") for item in written if item.get("original")],
    }
    stored.update(fields)
    stored["_draft_object_key"] = draft_key
    stored["_creation_signature"] = signature
    stored["_creation_report"] = report
    stored["_creation_prepared"] = True
    project.fields = stored
    flag_modified(project, "fields")
    from app.services.agent_document_tools import refresh_project_document_map

    refresh_project_document_map(db, project, rendered, manifest)
    _bind_session(session, project, filename)
    db.commit()
    db.refresh(project)
    return report


async def respond_creation_handoff(db: Session, project: TenderProject, session, text: str = "") -> dict[str, Any]:
    """用户要求把基础信息填进模板并打开工作区时的回复。"""
    report = await materialize_creation_draft(db, project, session)
    if not report.get("ok"):
        report = {
            "template_name": "",
            "known": _known_lines(fill_field_defaults(db, project.fields or {}), _company(db)),
            "written": [],
            "open_decisions": [],
            "empty_sections": [],
        }
    answer = format_creation_greeting(report)
    card = open_decision_card(report)
    metadata: dict[str, Any] = {
        "intent": "creation_handoff",
        "skip_intake_chrome": True,
        "workspace_updated": True,
        "project_id": project.id,
        "creation_report": {
            "template_name": report.get("template_name"),
            "known": report.get("known") or [],
            "written": report.get("written") or [],
            "open_decisions": report.get("open_decisions") or [],
            "empty_sections": report.get("empty_sections") or [],
        },
        "actions": [
            {
                "type": "link",
                "label": "打开文档工作区",
                "url": f"/chat?project={project.id}",
                "primary": True,
            },
        ],
    }
    if card:
        metadata["cards"] = [card]
    if text:
        metadata["user_request"] = text[:200]
    return {"answer": answer, "mode": "action", "metadata": metadata}
