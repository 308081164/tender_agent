"""空白/骨架模板：按章节标题批量撰写完整标书正文并写入工作区草稿。"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models import ChatSession, CompanyProfile, TenderProject
from app.services import storage, word
from app.services.ai import generate_chapter, local_chapter_text
from app.services.doc_engine.compose_policy import should_generate_ai_narrative
from app.services.docx_ooxml import document_text, paragraph_records, write_section_bodies
from app.services.field_defaults import fill_field_defaults

PLACEHOLDER_RE = word.PLACEHOLDER_RE
MIN_SECTION_CHARS = 260
MIN_TOTAL_CHARS = 2500
MIN_FILLED_SECTIONS = 5

# (标题关键词, 章节模板键)
_SECTION_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("投标函", "投标书", "投标声明"), "投标函"),
    (("技术方案", "技术部分", "技术响应"), "技术方案"),
    (("施工组织", "施工方案"), "施工组织设计"),
    (("人员", "项目团队", "组织机构"), "人员配置说明"),
    (("质量", "安全", "质量保证"), "质量与安全保证措施"),
    (("工期", "进度", "里程碑"), "工期保障措施"),
    (("商务", "报价", "分项报价", "投标报价"), "分项报价说明"),
    (("资质", "资格", "业绩"), "资质与业绩说明"),
    (("售后", "服务", "维保"), "售后服务方案"),
    (("投标人简介", "企业简介", "公司介绍", "投标人概况"), "投标人简介"),
    (("工程概况", "项目理解"), "工程概况补充"),
)


def _company_block(db: Session | None) -> tuple[str, str]:
    if db is None:
        return "", ""
    row = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    if not row:
        return "", ""
    name = (row.full_name or "").strip()
    intro = (row.intro or "").strip()
    qual = (row.qual_overview or "").strip()
    parts = [p for p in (intro, qual) if p]
    return name, "\n\n".join(parts)


def _normalize_fields(db: Session, project: TenderProject) -> dict[str, Any]:
    fields = fill_field_defaults(db, project.fields or {})
    company_name, company_body = _company_block(db)
    if company_name and not str(fields.get("bidder_name") or "").strip():
        fields["bidder_name"] = company_name
    if company_name and not str(fields.get("bidder") or "").strip():
        fields["bidder"] = company_name
    return fields, company_body


def _template_key_for_heading(title: str) -> str:
    t = (title or "").strip()
    for keywords, key in _SECTION_RULES:
        if any(kw in t for kw in keywords):
            return key
    return t


def _pad_substantive(text: str, fields: dict, title: str, min_chars: int = MIN_SECTION_CHARS) -> str:
    body = (text or "").strip()
    if len(body) >= min_chars:
        return body
    extra = (
        f"针对「{fields.get('project_name', '本项目')}」，{title}部分将严格响应招标文件条款，"
        f"由{fields.get('bidder_name') or fields.get('bidder') or '投标人'}组织实施。"
        f"计划工期{fields.get('duration') or '按招标要求'}，项目经理{fields.get('project_manager') or '持证上岗'}，"
        f"安全质量目标符合国家及铁路行业现行标准，并接受{fields.get('tenderer') or '招标人'}监督检查。"
    )
    merged = f"{body}\n\n{extra}".strip() if body else extra
    fillers = [
        (
            f"我方在类似维保项目中积累了可复用的工艺与备件保障体系，"
            f"承诺按{fields.get('tenderer') or '招标人'}现场管理制度配合联调、验收与资料归档。"
        ),
        (
            f"服务团队将按周提交运行报告，按月组织巡检与隐患排查，"
            f"对关键设备建立一机一档，确保「{fields.get('project_name', '本项目')}」全生命周期可追踪。"
        ),
        (
            "对招标文件中的实质性条款均予以响应，遇争议事项按合同约定及行业惯例协商解决，"
            "必要时提供第三方检测报告与整改闭环材料。"
        ),
    ]
    idx = 0
    while len(merged) < min_chars:
        merged += "\n\n" + fillers[idx % len(fillers)]
        idx += 1
        if idx > 12:
            break
    return merged[:5000]


async def _section_body(
    heading: str,
    fields: dict,
    company_body: str,
    requirements: str,
    db: Session | None,
) -> str:
    key = _template_key_for_heading(heading)
    if key == "投标人简介" and company_body:
        base = company_body
    else:
        chapter = await generate_chapter(
            key,
            fields,
            db=db,
            company_context=company_body,
            template_reference=requirements,
        )
        base = (chapter.get("content") or "").strip() if isinstance(chapter, dict) else ""
        if not base:
            base = local_chapter_text(key, fields)
    if key == "投标人简介" and company_body and company_body not in base:
        base = f"{company_body}\n\n{base}"
    return _pad_substantive(base, fields, heading, min_chars=max(MIN_SECTION_CHARS, 420))


def list_heading_sections(docx_bytes: bytes) -> list[str]:
    titles: list[str] = []
    try:
        records = paragraph_records(docx_bytes)
    except Exception:
        return titles
    for rec in records:
        if rec.get("in_table"):
            continue
        style = (rec.get("style") or "").lower()
        text = (rec.get("text") or "").strip()
        if not text or len(text) > 48:
            continue
        heading = style.startswith("heading") or "标题" in style
        if heading:
            titles.append(text)
    return titles


def count_placeholders(docx_bytes: bytes) -> int:
    try:
        text = document_text(docx_bytes)
    except Exception:
        text = docx_bytes.decode("utf-8", errors="ignore")
    return len(PLACEHOLDER_RE.findall(text))


async def compose_full_bid_bytes(
    docx_bytes: bytes,
    fields: dict,
    *,
    requirements: str = "",
    db: Session | None = None,
    company_body: str = "",
) -> tuple[bytes, dict[str, Any]]:
    """在已有草稿/模板上填充字段并撰写各章节正文。"""
    rendered = word.render_document(docx_bytes, fields, highlight=False)
    headings = list_heading_sections(rendered)
    bodies: dict[str, str] = {}
    for title in headings:
        if not should_generate_ai_narrative(title, rendered):
            continue
        bodies[title] = await _section_body(
            title, fields, company_body, requirements, db,
        )
    if bodies:
        rendered = write_section_bodies(rendered, bodies, replace_if_shorter_than=MIN_SECTION_CHARS)
    meta = {
        "headings": headings,
        "filled_sections": len(bodies),
        "section_samples": {k: (v[:120] + "…") if len(v) > 120 else v for k, v in list(bodies.items())[:8]},
        "text_length": len(document_text(rendered)),
        "placeholders_left": count_placeholders(rendered),
    }
    return rendered, meta, bodies


async def compose_full_bid_for_project(
    db: Session,
    project: TenderProject,
    session: ChatSession | None = None,
    *,
    requirements: str = "",
) -> dict[str, Any]:
    from app.models import Template

    if not project.template_id:
        return {"ok": False, "reason": "no_template"}
    tpl = db.query(Template).filter(Template.id == project.template_id).first()
    if not tpl or not tpl.object_key:
        return {"ok": False, "reason": "template_missing"}
    fields, company_body = _normalize_fields(db, project)
    req = (requirements or "").strip() or str(fields.get("_writing_requirements") or "").strip()
    if not req:
        req = (
            f"为「{fields.get('project_name') or project.title}」编制完整投标文件，"
            f"招标人{fields.get('tenderer') or ''}，投标人{fields.get('bidder_name') or ''}。"
        )
    draft_key = str((project.fields or {}).get("_draft_object_key") or "")
    try:
        base = storage.download_bytes(draft_key) if draft_key else storage.download_bytes(tpl.object_key)
    except Exception:
        base = b""
    if not base:
        return {"ok": False, "reason": "doc_unreadable"}

    new_bytes, meta, bodies = await compose_full_bid_bytes(
        base, fields, requirements=req, db=db, company_body=company_body,
    )
    heading_n = len(meta.get("headings") or [])
    need_sections = max(2, min(MIN_FILLED_SECTIONS, heading_n or MIN_FILLED_SECTIONS))
    need_chars = min(MIN_TOTAL_CHARS, max(800, heading_n * 220))
    if meta.get("text_length", 0) < need_chars or meta.get("filled_sections", 0) < need_sections:
        return {
            "ok": False,
            "reason": "insufficient_content",
            "meta": meta,
            "need_sections": need_sections,
        }

    out_key = f"projects/{project.id}/full_bid.docx"
    storage.upload_bytes(
        out_key,
        new_bytes,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    stored = dict(project.fields or {})
    stored["_draft_object_key"] = out_key
    stored["_full_bid_prepared"] = True
    stored["_full_bid_meta"] = meta
    project.fields = stored
    flag_modified(project, "fields")

    chapters = dict(project.chapters or {})
    for title, content in bodies.items():
        key = _template_key_for_heading(title)
        chapters[key] = {"content": content, "source": "bid_full_compose", "title": title}
    project.chapters = chapters
    flag_modified(project, "chapters")
    project.current_step = max(project.current_step or 1, 3)
    project.updated_at = __import__("datetime").datetime.utcnow()

    if session is not None:
        fname = f"{fields.get('project_name') or project.title or '标书'}.docx"
        if not str(fname).lower().endswith(".docx"):
            fname = f"{fname}.docx"
        ws = dict(session.workspace or {})
        ws["draft_object_key"] = out_key
        ws["filename"] = fname
        ws["version"] = int(ws.get("version") or 0) + 1
        ws["last_action"] = "full_bid_compose"
        ws["project_id"] = project.id
        session.workspace = ws

    db.commit()
    db.refresh(project)
    return {
        "ok": True,
        "draft_object_key": out_key,
        "download_hint": f"/api/projects/{project.id}/export",
        "meta": meta,
    }


async def respond_full_bid_compose(
    db: Session,
    project: TenderProject,
    session: ChatSession | None,
    text: str = "",
) -> dict[str, Any]:
    report = await compose_full_bid_for_project(db, project, session, requirements=text)
    if not report.get("ok"):
        reason = report.get("reason") or "unknown"
        return {
            "answer": f"完整标书生成未完成（{reason}）。请确认模板章节标题与项目字段已填写，然后重试。",
            "mode": "action",
            "metadata": {"intent": "compose_full_bid", "compose_report": report},
        }
    meta = report.get("meta") or {}
    return {
        "answer": (
            f"已为「{project.title}」生成完整标书草稿：共撰写 {meta.get('filled_sections', 0)} 个章节，"
            f"正文约 {meta.get('text_length', 0)} 字；剩余占位符 {meta.get('placeholders_left', 0)} 处。"
            f"\n\n请在左侧预览核对投标函、技术方案、商务/报价、资质与人员工期等章节；"
            f"确认后可使用「下载 DOCX」或项目导出。"
        ),
        "mode": "action",
        "metadata": {
            "intent": "compose_full_bid",
            "workspace_updated": True,
            "compose_report": report,
            "actions": [
                {"type": "link", "label": "下载当前文档", "url": "/chat", "primary": True},
            ],
        },
    }
