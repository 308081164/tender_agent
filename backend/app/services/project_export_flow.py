"""创作工作台：对话式导出（预审查 → 用户确认 → 导出）。"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models import ChatSession, TenderProject
from app.services import checklist as checklist_svc, storage, word
from app.models import ChecklistItem, Qualification, Template
from app.services.field_verify import unconfirmed_sensitive_keys

logger = logging.getLogger(__name__)

EXPORT_FLOW_IDLE = "idle"
EXPORT_FLOW_REVIEWING = "reviewing"
EXPORT_FLOW_AWAITING_ACK = "awaiting_user_ack"
EXPORT_FLOW_EXPORTING = "exporting"
EXPORT_FLOW_DONE = "done"

_EXPORT_START_RE = re.compile(
    r"(导出标书|导出.{0,6}word|帮我导出|请.{0,4}导出|下载标书|生成.{0,4}docx|export)",
    re.IGNORECASE,
)
_EXPORT_ACK_RE = re.compile(
    r"(没问题了?|可以导出|确认导出|导出吧|同意导出|就这样|开始导出|直接导出)",
    re.IGNORECASE,
)


def _card_id() -> str:
    return uuid.uuid4().hex[:12]


def extract_review_highlight_texts(review: dict[str, Any] | None) -> list[str]:
    if not review:
        return []
    texts: list[str] = []
    for item in (review.get("issues") or []) + (review.get("warnings") or []):
        msg = item.get("message") or ""
        m = re.search(r"[「『\"](.+?)[」』\"]", msg)
        if m and m.group(1):
            texts.append(m.group(1))
        if item.get("field") and len(str(item.get("field"))) > 1:
            texts.append(str(item["field"]))
        if item.get("excerpt"):
            texts.append(str(item["excerpt"]))
    out: list[str] = []
    seen: set[str] = set()
    for t in texts:
        t = t.strip()
        if len(t) < 2 or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out[:12]


def detect_export_start(text: str) -> bool:
    q = (text or "").strip()
    if not q:
        return False
    if _EXPORT_START_RE.search(q):
        return True
    return ("可以了" in q or "好了" in q) and ("导出" in q or "下载" in q)


def detect_export_ack(text: str) -> bool:
    return bool(_EXPORT_ACK_RE.search((text or "").strip()))


def _company_context(db: Session) -> str:
    from app.models import CompanyProfile

    c = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    if not c:
        return ""
    return "\n".join(p for p in [c.full_name, c.intro, c.qual_overview] if p)


def _fill_field_defaults(db: Session, fields: dict | None) -> dict:
    from app.services.field_defaults import fill_field_defaults

    return fill_field_defaults(db, fields or {})


def _ensure_checklist(db: Session, project: TenderProject) -> dict[str, Any]:
    if project.checklist_result:
        return dict(project.checklist_result)
    tpl_code = "common"
    tpl_kind = "template"
    if project.template_id:
        tpl = db.query(Template).filter(Template.id == project.template_id).first()
        if tpl:
            tpl_code = getattr(tpl, "template_code", "common") or "common"
            tpl_kind = getattr(tpl, "kind", "template") or "template"
    q = db.query(ChecklistItem)
    if tpl_kind == "skeleton" or tpl_code == "common":
        q = q.filter(ChecklistItem.template_code == "common")
    else:
        q = q.filter(ChecklistItem.template_code.in_([tpl_code, "common"]))
    items = q.all()
    checklist = [
        {"id": i.id, "section": i.section, "name": i.name, "required": i.required, "remark": i.remark}
        for i in items
    ]
    quals = db.query(Qualification).all()
    qual_dicts = [
        {
            "id": q.id,
            "name": q.name,
            "category": q.category,
            "keywords": q.keywords,
            "is_long_term": q.is_long_term,
            "valid_to": q.valid_to,
        }
        for q in quals
    ]
    headings: list[str] = []
    if project.template_id:
        tpl = db.query(Template).filter(Template.id == project.template_id).first()
        if tpl:
            try:
                tpl_bytes = storage.download_bytes(tpl.object_key)
                structure = word.extract_structure(tpl_bytes)
                headings = [h["text"] for h in structure.get("headings", [])]
                headings.extend(para.get("text", "") for para in structure.get("paragraphs", [])[:80])
            except Exception as err:
                logger.warning("checklist template parse: %s", err)
    result = checklist_svc.run_checklist(
        checklist,
        project.chapters or {},
        project.fields or {},
        qual_dicts,
        project.inserted_quals or [],
        headings,
    )
    if tpl_kind == "skeleton":
        critical_reds = [
            i
            for i in result.get("items", [])
            if i.get("level") == "red"
            and (
                str(i.get("id", "")).startswith("field-")
                or str(i.get("id", "")).startswith("qual-")
            )
        ]
        result["can_export"] = len(critical_reds) == 0
        if result["can_export"] and result.get("status") == "red":
            result["status"] = "yellow"
    project.checklist_result = result
    flag_modified(project, "checklist_result")
    db.commit()
    return result


async def run_pre_export_review(db: Session, project_id: int) -> dict[str, Any]:
    """条目校验 + doc-review，与导出 API 前置一致。"""
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise ValueError("项目不存在")
    if not p.template_id:
        raise ValueError("未选择模板")
    checklist = _ensure_checklist(db, p)
    db.refresh(p)
    if not checklist.get("can_export", True):
        return {
            "ok": False,
            "stage": "checklist",
            "checklist": checklist,
            "review": None,
            "can_export": False,
        }

    tpl = db.query(Template).filter(Template.id == p.template_id).first()
    if not tpl:
        raise ValueError("模板不存在")
    tpl_bytes = storage.download_bytes(tpl.object_key)
    export_fields = _fill_field_defaults(db, p.fields)
    from app.services.doc_engine.engine import render_project_document, review_project_document

    snap = getattr(tpl, "source_snapshot", None) or {}
    writing_req = str(export_fields.get("_writing_requirements") or "")
    doc_bytes, _ = await render_project_document(
        tpl_bytes,
        tpl.placeholders,
        export_fields,
        p.chapters,
        source_snapshot=snap if getattr(tpl, "kind", "") == "history" else None,
        highlight=False,
        requirements=writing_req,
        company_context=_company_context(db),
        db=db,
        mode="replace" if getattr(tpl, "kind", "") == "history" else None,
    )
    required = ["project_name", "tender_no", "tenderer", "project_manager"]
    review = await review_project_document(
        doc_bytes, tpl.placeholders, export_fields, snap, required, db=db
    )
    merged = dict(p.checklist_result or {})
    merged["doc_review"] = review
    merged["can_export"] = review.get("can_export", False) and merged.get("can_export", True)
    p.checklist_result = merged
    flag_modified(p, "checklist_result")
    db.commit()
    ok = bool(review.get("can_export")) and merged.get("can_export", True)
    return {
        "ok": ok,
        "stage": "doc_review",
        "checklist": merged,
        "review": review,
        "can_export": ok,
    }


async def execute_project_export(db: Session, project_id: int) -> dict[str, Any]:
    """执行导出并返回 export_id / 下载链接（供对话 actions）。"""
    from datetime import datetime

    from app.models import ProjectExport
    from app.services.doc_engine.engine import render_project_document, review_project_document
    p = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not p:
        raise ValueError("项目不存在")
    if not p.template_id:
        raise ValueError("未选择模板")

    pre = await run_pre_export_review(db, project_id)
    if not pre.get("can_export"):
        raise ValueError("文档审阅未通过，无法导出")

    pending_sensitive = unconfirmed_sensitive_keys(p.fields, db, project=p)
    if pending_sensitive:
        names = "、".join(x.get("name") or x.get("key") for x in pending_sensitive[:6])
        raise ValueError(f"存在未确认的敏感字段：{names}")

    tpl = db.query(Template).filter(Template.id == p.template_id).first()
    if getattr(tpl, "kind", "") == "tender_doc":
        raise ValueError("招标文件不能作为导出起点")
    tpl_bytes = storage.download_bytes(tpl.object_key)
    chapters = dict(p.chapters or {})
    quals = []
    if p.inserted_quals:
        quals = db.query(Qualification).filter(Qualification.id.in_(p.inserted_quals)).all()
        chapters["资质材料清单"] = {
            "content": "\n".join(f"- {q.category} / {q.name}（{q.issuer}）" for q in quals),
            "source": "system",
        }
    snap = getattr(tpl, "source_snapshot", None) or {}
    export_fields = _fill_field_defaults(db, p.fields)
    qual_files = []
    for q in quals:
        data = b""
        if q.object_key:
            try:
                data = storage.download_bytes(q.object_key)
            except Exception:
                data = b""
        qual_files.append({
            "name": q.name,
            "category": q.category,
            "section_hint": getattr(q, "section_hint", "") or "",
            "file_type": q.file_type,
            "ocr_text": getattr(q, "ocr_text", "") or "",
            "data": data,
        })
    writing_req = (export_fields.get("_writing_requirements") or "") or (
        (p.chapters or {}).get("_writing_requirements") or ""
    )
    doc_bytes, _render_meta = await render_project_document(
        tpl_bytes,
        tpl.placeholders,
        export_fields,
        chapters,
        source_snapshot=snap if getattr(tpl, "kind", "") == "history" else None,
        qual_files=qual_files,
        highlight=True,
        requirements=str(writing_req),
        company_context=_company_context(db),
        db=db,
        mode="replace" if getattr(tpl, "kind", "") == "history" else None,
    )
    required = ["project_name", "tender_no", "tenderer", "project_manager"]
    if not (export_fields.get("bid_amount_upper") or export_fields.get("bid_amount")):
        required.append("bid_amount_upper")
    validation = await review_project_document(
        doc_bytes,
        tpl.placeholders,
        export_fields,
        snap if getattr(tpl, "kind", "") == "history" else None,
        required,
        db=db,
    )
    if not validation.get("can_export", validation.get("status") != "red"):
        raise ValueError("文档审阅未通过，无法导出")

    filename = f"{(p.fields or {}).get('project_name') or p.title or 'bid'}.docx"
    stamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    out_key = f"exports/project_{p.id}_{stamp}.docx"
    storage.upload_bytes(
        out_key,
        doc_bytes,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    export_row = ProjectExport(
        project_id=p.id,
        object_key=out_key,
        filename=filename,
    )
    db.add(export_row)
    p.status = "exported"
    p.current_step = 6
    p.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(export_row)
    fields = dict(p.fields or {})
    audit = list(fields.get("_export_audit_log") or [])
    audit.append({
        "export_id": export_row.id,
        "at": datetime.utcnow().isoformat(),
        "sensitive_confirmed": dict(fields.get("_sensitive_confirmed") or {}),
    })
    fields["_export_audit_log"] = audit[-20:]
    p.fields = fields
    flag_modified(p, "fields")
    db.commit()
    try:
        from app.services.agent_workspace import mirror_bytes_to_project_workspace

        mirror_bytes_to_project_workspace(p, f"产出/{filename}", doc_bytes)
    except Exception:
        pass

    download_url = f"/api/projects/{p.id}/exports/{export_row.id}/download"
    inline_url = f"/api/projects/{p.id}/exports/{export_row.id}/download?inline=1"
    return {
        "export_id": export_row.id,
        "filename": filename,
        "download_url": download_url,
        "inline_url": inline_url,
        "validation_status": validation.get("status"),
    }


def _persist_workspace(session: ChatSession, ws: dict[str, Any]) -> None:
    session.workspace = ws
    flag_modified(session, "workspace")


async def try_handle_export_flow(
    text: str,
    db: Session,
    session: ChatSession,
    workspace: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """绑定 project_id 的会话内处理导出状态机；None 表示未接管。"""
    ws = dict(workspace or {})
    pid = ws.get("project_id")
    if not pid:
        return None

    flow = str(ws.get("export_flow") or EXPORT_FLOW_IDLE)
    q = (text or "").strip()
    if not q:
        return None

    project_id = int(pid)

    if flow == EXPORT_FLOW_AWAITING_ACK and detect_export_ack(q):
        ws["export_flow"] = EXPORT_FLOW_EXPORTING
        _persist_workspace(session, ws)
        db.commit()
        try:
            result = await execute_project_export(db, project_id)
        except Exception as err:
            ws["export_flow"] = EXPORT_FLOW_IDLE
            _persist_workspace(session, ws)
            db.commit()
            logger.warning("workspace export failed project=%s: %s", project_id, err)
            return {
                "answer": f"导出未完成：{err}\n\n请根据提示修改后，再说「请帮我导出标书」。",
                "mode": "action",
                "metadata": {
                    "intent": "export_project",
                    "export_flow": EXPORT_FLOW_IDLE,
                    "workspace_updated": True,
                },
            }

        ws["export_flow"] = EXPORT_FLOW_DONE
        ws["last_export"] = result
        ws.pop("review_highlight_texts", None)
        _persist_workspace(session, ws)
        db.commit()
        fname = result.get("filename") or "标书.docx"
        return {
            "answer": (
                f"✅ 标书已导出：**{fname}**\n\n"
                "请下载 Word 并在本地打开核对；左侧预览也会更新。"
            ),
            "mode": "action",
            "metadata": {
                "intent": "export_project",
                "export_flow": EXPORT_FLOW_DONE,
                "export_result": result,
                "workspace_updated": True,
                "actions": [
                    {
                        "type": "link",
                        "label": "下载 Word",
                        "url": result.get("download_url"),
                        "primary": True,
                    },
                    {
                        "type": "link",
                        "label": "在线查看",
                        "url": result.get("inline_url"),
                    },
                ],
                "cards": [{
                    "id": _card_id(),
                    "type": "doc_review",
                    "title": "导出完成",
                    "state": "done",
                    "payload": {
                        "status": result.get("validation_status") or "green",
                        "can_export": True,
                        "issue_count": 0,
                        "export_id": result.get("export_id"),
                    },
                }],
            },
        }

    if flow == EXPORT_FLOW_AWAITING_ACK:
        return {
            "answer": (
                "导出前请先确认：左侧文档中 **AI 高亮** 的句子是否都已看过？"
                "若无问题，请回复「可以导出」或「没问题了」。"
            ),
            "mode": "action",
            "metadata": {
                "intent": "export_project",
                "export_flow": EXPORT_FLOW_AWAITING_ACK,
            },
        }

    if not detect_export_start(q):
        return None

    ws["export_flow"] = EXPORT_FLOW_REVIEWING
    _persist_workspace(session, ws)
    db.commit()

    try:
        pre = await run_pre_export_review(db, project_id)
    except Exception as err:
        ws["export_flow"] = EXPORT_FLOW_IDLE
        _persist_workspace(session, ws)
        db.commit()
        return {
            "answer": f"预导出审查未能完成：{err}",
            "mode": "action",
            "metadata": {
                "intent": "export_project",
                "export_flow": EXPORT_FLOW_IDLE,
                "workspace_updated": True,
            },
        }

    review = pre.get("review") or {}
    if not pre.get("can_export"):
        ws["export_flow"] = EXPORT_FLOW_IDLE
        highlights = extract_review_highlight_texts(review)
        if highlights:
            ws["review_highlight_texts"] = highlights
        _persist_workspace(session, ws)
        db.commit()
        issues = review.get("issues") or []
        lines = ["审查未通过，暂不能导出。请先处理下列问题，改完后再说「请帮我导出」：", ""]
        for item in issues[:8]:
            lines.append(f"- {item.get('message') or item}")
        if pre.get("stage") == "checklist":
            lines.append("\n条目校验也未通过，请打开「交付」查看清单。")
        return {
            "answer": "\n".join(lines),
            "mode": "action",
            "metadata": {
                "intent": "export_project",
                "export_flow": EXPORT_FLOW_IDLE,
                "workspace_updated": True,
                "cards": [{
                    "id": _card_id(),
                    "type": "doc_review",
                    "title": "导出前审查",
                    "state": "active",
                    "payload": {
                        **review,
                        "can_export": False,
                        "issue_count": len(issues),
                    },
                }],
            },
        }

    highlights = extract_review_highlight_texts(review)
    ws["export_flow"] = EXPORT_FLOW_AWAITING_ACK
    ws["export_pre_review"] = review
    if highlights:
        ws["review_highlight_texts"] = highlights
    else:
        ws.pop("review_highlight_texts", None)
    _persist_workspace(session, ws)
    db.commit()

    warn_n = len(review.get("warnings") or [])
    hl_hint = (
        "请先在左侧文档预览中查看 **AI 高亮** 的句子（审查提示项）。"
        if highlights or warn_n
        else "文档审查已通过。"
    )
    return {
        "answer": (
            "✅ 导出前审查已通过。\n\n"
            f"{hl_hint}\n\n"
            "确认无误后，请回复「可以导出」或「没问题了」，我将生成 Word 并提供下载链接。"
        ),
        "mode": "action",
        "metadata": {
            "intent": "export_project",
            "export_flow": EXPORT_FLOW_AWAITING_ACK,
            "workspace_updated": True,
            "cards": [{
                "id": _card_id(),
                "type": "doc_review",
                "title": "导出前审查",
                "state": "done",
                "payload": {
                    **review,
                    "can_export": True,
                    "issue_count": len(review.get("issues") or []),
                    "warning_count": warn_n,
                },
            }],
        },
    }
