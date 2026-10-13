"""Agent 运行时：每轮对话上下文注入与 general 对话消息构建。"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session


def resolve_project_id(
    workspace: dict | None,
    context: dict | None,
) -> int | None:
    ws = workspace or {}
    ctx = context or {}
    raw = ctx.get("project_id") or ws.get("project_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _truncate(s: str, limit: int) -> str:
    s = (s or "").strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def build_project_context_pack(db: Session, project_id: int) -> dict[str, Any]:
    from app.services.project_context import build_project_context

    return build_project_context(db, project_id)


def build_context_system_block(
    ctx_pack: dict[str, Any] | None,
    *,
    workspace: dict | None = None,
    context: dict | None = None,
) -> str:
    """将项目上下文、选段与编写要求格式化为 system 附加块。"""
    parts: list[str] = [
        "你是标书智能体 Copilot，绑定当前投标项目时可读写项目字段、引导补全、"
        "协助文档修订。回答须结合下方「当前项目上下文」；勿编造资质编号与金额。",
    ]
    if ctx_pack:
        try:
            slim = {
                "project": ctx_pack.get("project"),
                "template": ctx_pack.get("template"),
                "field_checklist": ctx_pack.get("field_checklist"),
                "capabilities": ctx_pack.get("capabilities"),
                "stats": ctx_pack.get("stats"),
            }
            parts.append(
                "当前项目上下文（JSON，与用户问题同等重要）：\n"
                + _truncate(json.dumps(slim, ensure_ascii=False), 12000),
            )
        except Exception:
            pass
    ctx = context or {}
    sel = (ctx.get("selected_text") or "").strip()
    if sel:
        parts.append(f"用户当前选中的文档片段：\n{_truncate(sel, 4000)}")
    ws_file = (ctx.get("workspace_file") or ctx.get("selected_workspace_file") or "").strip()
    ws_body = (ctx.get("workspace_file_content") or "").strip()
    if ws_file:
        block = (
            "用户当前在工程目录文件树中选中的文件（相对路径，可用 read_workspace_file 读取/修改）："
            f"\n{ws_file}"
        )
        if ws_body:
            note = "（内容已截断）" if ctx.get("workspace_file_truncated") else ""
            block += f"\n\n文件正文{note}：\n{_truncate(ws_body, 8000)}"
        parts.append(block)
    refs = ctx.get("reference_snippets") or []
    if isinstance(refs, str):
        refs = [refs]
    ref_text = "\n---\n".join(_truncate(str(r), 1500) for r in refs if r)
    if ref_text:
        parts.append(f"用户提供的参考摘录：\n{ref_text}")
    ws = workspace or {}
    wr = (ws.get("_writing_requirements") or ctx.get("writing_requirements") or "").strip()
    if wr:
        parts.append(f"项目编写要求摘要：\n{_truncate(wr, 2000)}")
    if ctx_pack:
        cl = ctx_pack.get("field_checklist") or {}
        miss = cl.get("missing_required") or []
        if miss:
            names = [m.get("name") or m.get("key") for m in miss[:8]]
            parts.append("优先待填字段：" + "、".join(str(n) for n in names if n))
    return "\n\n".join(parts)


def augment_messages(
    messages: list[dict],
    db: Session | None,
    *,
    workspace: dict | None = None,
    context: dict | None = None,
) -> list[dict]:
    """在 messages 前注入/合并项目上下文 system。"""
    if not db:
        return list(messages)
    pid = resolve_project_id(workspace, context)
    ctx_pack = None
    if pid:
        try:
            ctx_pack = build_project_context_pack(db, pid)
        except Exception:
            ctx_pack = None
    block = build_context_system_block(ctx_pack, workspace=workspace, context=context)
    if not block:
        return list(messages)
    out = list(messages)
    if out and out[0].get("role") == "system":
        merged = (out[0].get("content") or "").strip() + "\n\n" + block
        out[0] = {"role": "system", "content": merged}
    else:
        out.insert(0, {"role": "system", "content": block})
    return out


def top_faq_snippets(question: str, faq_items: list[dict], *, limit: int = 3) -> list[dict]:
    from app.services.ai import _score_faq_match

    scored: list[tuple[float, dict]] = []
    for item in faq_items or []:
        score = _score_faq_match(question, item)
        if score >= 0.2:
            scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in scored[:limit]]


def build_general_messages(
    question: str,
    faq_items: list[dict],
    history: list[dict] | None,
    db: Session | None,
    *,
    workspace: dict | None = None,
    context: dict | None = None,
) -> list[dict]:
    """general 意图：FAQ 作 RAG 片段，保留自由对话。"""
    q = question.strip()
    hist = []
    for m in (history or [])[-8:]:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            hist.append({"role": role, "content": content})

    rag = top_faq_snippets(q, faq_items)
    rag_block = ""
    if rag:
        lines = []
        for i, item in enumerate(rag, 1):
            lines.append(
                f"{i}. Q: {item.get('question', '')}\n   A: {_truncate(item.get('answer') or '', 800)}",
            )
        rag_block = (
            "以下为企业 FAQ 参考片段（可引用，勿与项目上下文矛盾；无相关内容时可忽略）：\n"
            + "\n".join(lines)
        )

    system = (
        "你是标书智能体 Copilot，兼具企业投标问答与标书编写协助。"
        "请自然、主动地回答问题，结合项目上下文给出可执行建议。"
        "当用户提供本机文件夹绝对路径并要求导入资质时，引导使用 📁 选择文件夹。"
        "不要编造无法核实的企业事实。"
    )
    if rag_block:
        system += "\n\n" + rag_block

    messages: list[dict] = [{"role": "system", "content": system}, *hist, {"role": "user", "content": q}]
    return augment_messages(messages, db, workspace=workspace, context=context)
