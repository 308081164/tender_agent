"""创作工作台：主动开场与引导补全（与通用 Agent 体感对齐）。"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session
from app.models import ChatMessage, ChatSession, TenderProject
from app.services import agent_tools
from app.services.project_context import build_project_context

logger = logging.getLogger(__name__)

WORKSPACE_OPENING_KIND = "workspace_opening"


def _priority_questions(ctx: dict[str, Any], intake: dict[str, Any]) -> list[str]:
    cl = ctx.get("field_checklist") or {}
    lines: list[str] = []
    for m in (cl.get("missing_required") or [])[:3]:
        lines.append(f"「{m.get('name', m.get('key'))}」")
    for v in (cl.get("needs_verify") or [])[:2]:
        if len(lines) >= 3:
            break
        lines.append(f"「{v.get('name', v.get('key'))}」（请确认是否正确）")
    if not lines:
        for q in (intake.get("questions") or [])[:3]:
            text = (q.get("text") or "").strip()
            if text:
                lines.append(text)
    return lines[:3]


def _opening_body(ctx: dict[str, Any], intake: dict[str, Any]) -> str:
    tpl = ctx.get("template") or {}
    cl = ctx.get("field_checklist") or {}
    missing_n = len(cl.get("missing_required") or [])
    verify_items = [v for v in (cl.get("needs_verify") or []) if not v.get("confirmed")]
    verify_n = len(verify_items)
    tpl_name = tpl.get("name") or "当前模板"
    lines = [
        f"您好，我已接入「{tpl_name}」。编写、审查和导出都在这条 Agent 对话里完成。",
        f"进度摘要：必填待填 {missing_n} 项"
        + (f"，待核实 {verify_n} 项" if verify_n else "（基础信息已信任向导录入）"),
    ]
    pri = _priority_questions(ctx, intake)
    if pri:
        lines.append("")
        lines.append("建议优先补充：")
        for i, q in enumerate(pri, 1):
            lines.append(f"{i}. {q}")
    else:
        lines.append("")
        lines.append("基础字段已较完整，您可以直接描述编写要求，或上传招标文件让我解析。")
    lines.append("")
    lines.append("勾选「引导补全」时，我会在您保存字段后继续追问下一项；敏感项需您点选确认。")
    return "\n".join(lines)


async def build_guided_intake_metadata(
    db: Session,
    project_id: int,
    *,
    guided: bool = True,
) -> dict[str, Any]:
    """生成 field_collect 卡片与追问文案（供聊天与工作台开场复用）。"""
    meta: dict[str, Any] = {}
    if not guided:
        return meta
    try:
        ctx_pack = build_project_context(db, project_id)
        tpl = ctx_pack.get("template") or {}
        intake = await agent_tools.list_missing_intake_questions(db, project_id)
        card_fields = intake.get("field_cards") or []
        if card_fields:
            meta.setdefault("cards", []).append({
                "id": uuid.uuid4().hex[:12],
                "type": "field_collect",
                "title": "待填基础信息",
                "state": "active",
                "payload": {
                    "fields": card_fields,
                    "template_name": tpl.get("name"),
                    "confirm_action": "confirm_fields",
                    "cancel_action": "dismiss_card",
                },
            })
        elif (intake.get("questions") or [])[:3]:
            qtext = "\n".join(f"- {q.get('text')}" for q in intake["questions"][:3])
            meta["guided_followup_text"] = f"为继续完善标书，请补充：\n{qtext}"
    except Exception as err:
        logger.warning("guided intake metadata failed project=%s: %s", project_id, err)
    return meta


async def build_workspace_followup(
    db: Session,
    project_id: int,
    *,
    guided: bool = True,
) -> str | None:
    """字段保存后追加的短追问（无则返回 None）。"""
    if not guided:
        return None
    try:
        ctx = build_project_context(db, project_id)
        cl = ctx.get("field_checklist") or {}
        missing = cl.get("missing_required") or []
        verify = [v for v in (cl.get("needs_verify") or []) if not v.get("confirmed")]
        if missing:
            name = missing[0].get("name", missing[0].get("key"))
            return f"已记录。下一项必填：{name} —— 请直接回复或在「可编辑」面板填写。"
        if verify:
            name = verify[0].get("name", verify[0].get("key"))
            val = verify[0].get("value") or "（空）"
            return f"请确认敏感/待核实字段「{name}」：当前为「{val[:80]}」。若无误请点左侧「确认」，或告诉我正确值。"
        intake = await agent_tools.list_missing_intake_questions(db, project_id)
        qs = intake.get("questions") or []
        if qs:
            return f"下一问题：{qs[0].get('text', '')}"
    except Exception as err:
        logger.warning("workspace followup failed project=%s: %s", project_id, err)
    return None


def _session_has_opening(session: ChatSession) -> bool:
    for m in session.messages or []:
        if m.role != "assistant":
            continue
        meta = getattr(m, "metadata_json", None) or {}
        if meta.get("kind") == WORKSPACE_OPENING_KIND:
            return True
    return False


async def ensure_workspace_opening_message(
    db: Session,
    session: ChatSession,
    project: TenderProject,
    *,
    guided: bool | None = None,
) -> ChatMessage | None:
    """进入创作工作台时注入首条 assistant 开场（幂等）。"""
    db.refresh(session)
    if _session_has_opening(session):
        return None

    ws = dict(session.workspace or {})
    if guided is None:
        guided = bool(ws.get("guided_intake", True))

    ctx = build_project_context(db, project.id)
    intake = await agent_tools.list_missing_intake_questions(db, project.id)
    content = _opening_body(ctx, intake)
    meta = await build_guided_intake_metadata(db, project.id, guided=guided)
    meta["kind"] = WORKSPACE_OPENING_KIND
    meta["project_context"] = ctx

    bot = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=content,
        source="workspace_agent",
        metadata_json=meta,
    )
    db.add(bot)
    session.updated_at = bot.created_at if bot.created_at else session.updated_at
    db.commit()
    db.refresh(bot)
    db.refresh(session)
    return bot


async def append_workspace_followup_message(
    db: Session,
    session: ChatSession,
    project: TenderProject,
    *,
    guided: bool = True,
) -> ChatMessage | None:
    text = await build_workspace_followup(db, project.id, guided=guided)
    if not text:
        return None
    meta = await build_guided_intake_metadata(db, project.id, guided=guided)
    meta["kind"] = "workspace_followup"
    bot = ChatMessage(
        session_id=session.id,
        role="assistant",
        content=text,
        source="workspace_agent",
        metadata_json=meta,
    )
    db.add(bot)
    db.commit()
    db.refresh(bot)
    return bot
