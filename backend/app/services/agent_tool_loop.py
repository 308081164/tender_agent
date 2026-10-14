"""Agent tool-calling 循环。默认开启，每轮最多 8 步，并留下可见工具轨迹。"""
from __future__ import annotations

import json
import os
from typing import Any

from sqlalchemy.orm import Session

from app.services import agent_tools, ai
from app.services.agent_capabilities import (
    ANCHOR_MISSING,
    MAX_TOOL_STEPS,
    apply_project_field_patch,
    check_against_tender,
    public_tool_trace,
    resolve_document_anchor,
    tender_record,
    trace_sentence,
)


def tool_loop_enabled() -> bool:
    """默认开启。只有显式 AGENT_TOOL_LOOP=0/false/off 才关闭。"""
    flag = os.environ.get("AGENT_TOOL_LOOP", "").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    return True


TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "read_workspace_file",
            "description": "读取当前会话工程目录下的文本文件",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "相对路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_workspace_file",
            "description": "写入或覆盖工程目录下的文本文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_project_context",
            "description": "获取绑定标书项目的结构化上下文",
            "parameters": {
                "type": "object",
                "properties": {"project_id": {"type": "integer"}},
                "required": ["project_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "检索公开互联网资料（招标惯例、保证金、中标公告等）。"
                "用户说联网、网上查、搜索一下、查资料、公开资料时使用。"
                "只根据返回的 title 与 url 引用，禁止编造链接。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "打开用户指定的单个 http 或 https 链接并提取正文。不要用于本地文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "http(s) URL"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_project_fields",
            "description": "更新标书项目 fields 字典中的字段（键值对）",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer"},
                    "fields": {"type": "object", "additionalProperties": {"type": "string"}},
                },
                "required": ["project_id", "fields"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_project_attachment",
            "description": "读取当前标书项目已上传附件的解析摘录",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer"},
                    "name": {"type": "string", "description": "可选，按文件名过滤"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_tender_excerpt",
            "description": "读取项目招标文件解析出的评分点、废标项、工期、资质和关键日期",
            "parameters": {"type": "object", "properties": {"project_id": {"type": "integer"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_document_anchor",
            "description": "按用户选中的文字、章节或段落锚点改写文档。没有锚点时不要改到文首。",
            "parameters": {
                "type": "object",
                "properties": {
                    "instruction": {"type": "string"},
                    "paragraph_index": {"type": "integer"},
                    "block_id": {"type": "string"},
                    "selected_text": {"type": "string"},
                },
                "required": ["instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_preview_status",
            "description": "查询当前文档预览与 OnlyOffice 是否可用，不打开编辑器页面",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_against_tender",
            "description": "把当前文稿或给定段落对照招标文件摘录，发现工期或废标冲突",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "project_id": {"type": "integer"},
                },
            },
        },
    },
]


async def _execute_tool(
    db: Session,
    session,
    name: str,
    arguments: dict[str, Any],
    *,
    default_project_id: int | None,
    context: dict | None = None,
) -> dict[str, Any]:
    args = arguments or {}
    if name == "read_workspace_file":
        path = str(args.get("path") or "").strip()
        data = agent_tools.read_workspace_file(db, session, path)
        if data.get("binary"):
            return {"ok": True, "binary": True, "path": data.get("path"), "size_bytes": data.get("size_bytes")}
        content = data.get("content") or ""
        if len(content) > 6000:
            content = content[:5999] + "…"
        return {"ok": True, "path": data.get("path"), "content": content}
    if name == "write_workspace_file":
        path = str(args.get("path") or "").strip()
        content = str(args.get("content") or "")
        out = agent_tools.write_workspace_file(db, session, path, content)
        return {"ok": True, **out}
    if name == "get_project_context":
        pid = int(args.get("project_id") or default_project_id or 0)
        if pid <= 0:
            return {"ok": False, "error": "未绑定 project_id"}
        ctx = agent_tools.get_project_context(db, pid)
        return {"ok": True, "context": ctx}
    if name == "update_project_fields":
        from app.models import TenderProject

        pid = int(args.get("project_id") or default_project_id or 0)
        fields = args.get("fields") or {}
        if pid <= 0 or not isinstance(fields, dict) or db is None:
            return {"ok": False, "error": "参数无效"}
        p = db.query(TenderProject).filter(TenderProject.id == pid).first()
        if not p:
            return {"ok": False, "error": "项目不存在"}
        applied = apply_project_field_patch(db, p, fields)
        db.commit()
        return {"ok": True, "project_id": pid, **applied}
    if name == "read_project_attachment":
        from app.models import TenderProject

        pid = int(args.get("project_id") or default_project_id or 0)
        if pid <= 0 or db is None:
            return {"ok": False, "error": "未绑定 project_id"}
        p = db.query(TenderProject).filter(TenderProject.id == pid).first()
        if not p:
            return {"ok": False, "error": "项目不存在"}
        want = str(args.get("name") or "").strip()
        rows = []
        for item in (p.fields or {}).get("_attachments") or []:
            if not isinstance(item, dict):
                continue
            if want and want not in str(item.get("name") or ""):
                continue
            rows.append({
                "name": item.get("name") or "",
                "type": item.get("type") or "",
                "excerpt": (item.get("extracted_text") or "")[:2000],
            })
        return {"ok": True, "attachments": rows[:12]}
    if name == "read_tender_excerpt":
        from app.models import TenderProject

        pid = int(args.get("project_id") or default_project_id or 0)
        if pid <= 0 or db is None:
            return {"ok": False, "error": "未绑定 project_id"}
        p = db.query(TenderProject).filter(TenderProject.id == pid).first()
        if not p:
            return {"ok": False, "error": "项目不存在"}
        tender = tender_record(p.fields)
        if not tender:
            return {"ok": False, "error": "项目未挂招标文件"}
        public = {k: tender.get(k) for k in (
            "name", "scoring_points", "disqualification", "duration", "qualifications", "key_dates", "excerpt",
        )}
        return {"ok": True, "tender": public}
    if name == "edit_document_anchor":
        anchor = resolve_document_anchor(context, args)
        if not anchor.get("ok"):
            return {"ok": False, "error": ANCHOR_MISSING}
        return {
            "ok": True,
            "anchor": {
                "paragraph_index": anchor.get("paragraph_index"),
                "block_id": anchor.get("block_id") or "",
                "selected_text": anchor.get("selected_text") or "",
            },
            "instruction": str(args.get("instruction") or ""),
            "message": "已按锚点定位，不会插入到文首。",
        }
    if name == "get_preview_status":
        ws = getattr(session, "workspace", None) or {}
        onlyoffice = {"enabled": False, "healthy": False, "message": ""}
        try:
            from app.services.onlyoffice import status_payload

            raw = status_payload()
            onlyoffice = {
                "enabled": bool(raw.get("enabled")),
                "healthy": bool(raw.get("healthy")),
                "message": raw.get("message") or "",
            }
        except Exception as exc:
            onlyoffice = {"enabled": False, "healthy": False, "message": str(exc)}
        doc_key = bool(ws.get("draft_object_key") or ws.get("template_object_key"))
        return {
            "ok": True,
            "has_document": doc_key,
            "version": int(ws.get("version") or 0),
            "onlyoffice": onlyoffice,
        }
    if name == "check_against_tender":
        from app.models import TenderProject

        pid = int(args.get("project_id") or default_project_id or 0)
        if pid <= 0 or db is None:
            return {"ok": False, "error": "未绑定 project_id", "conflicts": []}
        p = db.query(TenderProject).filter(TenderProject.id == pid).first()
        if not p:
            return {"ok": False, "error": "项目不存在", "conflicts": []}
        draft = str(args.get("text") or "").strip()
        if not draft:
            from app.services.agent_capabilities import collect_document_text

            draft = collect_document_text(p)
        checked = check_against_tender(draft, tender_record(p.fields))
        return checked
    if name == "web_search":
        from app.services.web_search import search_web

        query = str(args.get("query") or "").strip()
        found = await search_web(query, db=db)
        public = {
            "ok": bool(found.get("ok")),
            "provider": found.get("provider") or "",
            "query": found.get("query") or query,
            "results": found.get("results") or [],
            "offline": bool(found.get("offline")),
            "empty_state": bool(found.get("empty_state")),
            "error": found.get("error") or "",
            "message": found.get("message") or "",
        }
        return public
    if name == "fetch_url":
        from app.services.web_search import fetch_url

        page = await fetch_url(str(args.get("url") or ""))
        text = page.get("text") or ""
        if len(text) > 4000:
            text = text[:3999] + "…"
        return {
            "ok": bool(page.get("ok")),
            "url": page.get("url") or "",
            "title": page.get("title") or "",
            "text": text,
            "error": page.get("error") or "",
            "message": page.get("message") or "",
        }
    return {"ok": False, "error": f"未知工具：{name}"}


async def _chat_with_tools(messages: list[dict], db: Session | None) -> dict[str, Any]:
    from app.services import settings_svc

    cfg = settings_svc.resolve_ai_config(db)
    order = ai.pick_model("text", cfg)
    for slug in order:
        call = ai._provider_call(slug, cfg)
        if not call:
            continue
        base_url, api_key, model = call
        try:
            return await _openai_tools_round(base_url, api_key, model, messages, TOOL_SPECS)
        except Exception:
            continue
    return {}


async def _openai_tools_round(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict],
) -> dict[str, Any]:
    import httpx

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload: dict = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.3,
    }
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()


def _sources_from_tool_log(tool_log: list[dict]) -> list[dict[str, str]]:
    from app.services.web_search import sources_payload

    rows: list[dict[str, str]] = []
    for entry in tool_log:
        result = entry.get("result") or {}
        if entry.get("tool") == "web_search":
            rows.extend(result.get("results") or [])
        elif entry.get("tool") == "fetch_url" and result.get("ok") and result.get("url"):
            rows.append({
                "title": result.get("title") or result.get("url"),
                "url": result.get("url"),
                "snippet": (result.get("text") or "")[:320],
            })
    return sources_payload(rows)


def _with_tool_trace(content: str, tool_log: list[dict], meta: dict[str, Any]) -> dict[str, Any]:
    trace = public_tool_trace(tool_log)
    if trace:
        meta = {**meta, "tool_loop": True, "tool_trace": trace}
        line = trace_sentence(trace)
        if line and line not in content:
            content = f"{content.rstrip()}\n\n{line}"
    for entry in tool_log:
        if entry.get("tool") != "edit_document_anchor":
            continue
        result = entry.get("result") or {}
        if not result.get("ok"):
            if ANCHOR_MISSING not in content:
                content = f"{content.rstrip()}\n\n{ANCHOR_MISSING}".strip()
            meta["anchor_missing"] = True
            continue
        anchor = result.get("anchor") or {}
        meta["needs_workspace_edit"] = True
        meta["instruction"] = result.get("instruction") or meta.get("instruction") or ""
        meta["selected_text"] = anchor.get("selected_text") or ""
        if anchor.get("paragraph_index") is not None:
            meta["paragraph_index"] = anchor.get("paragraph_index")
        if anchor.get("block_id"):
            meta["block_id"] = anchor.get("block_id")
    return {"answer": content, "metadata": meta}


async def run_tool_loop(
    *,
    db: Session,
    session,
    messages: list[dict],
    workspace: dict | None,
    context: dict | None,
    max_steps: int = MAX_TOOL_STEPS,
) -> dict[str, Any] | None:
    """若 LLM 返回最终文本则输出；否则 None 表示应回退普通对话。"""
    if not tool_loop_enabled() or session is None:
        return None

    from app.services import agent_runtime

    ws = workspace or {}
    ctx = context or {}
    pid = agent_runtime.resolve_project_id(ws, ctx)
    working = list(messages)
    tool_log: list[dict] = []
    limit = max(1, min(int(max_steps or MAX_TOOL_STEPS), MAX_TOOL_STEPS))

    for _ in range(limit):
        data = await _chat_with_tools(working, db)
        if not data:
            if tool_log:
                return _with_tool_trace("工具调用没有得到模型的后续回复。", tool_log, {"intent": "general"})
            return None
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        tool_calls = msg.get("tool_calls") or []
        if tool_calls:
            working.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tool_calls})
            for tc in tool_calls[:4]:
                fn = tc.get("function") or {}
                name = fn.get("name") or ""
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = await _execute_tool(
                    db, session, name, args, default_project_id=pid, context=ctx,
                )
                tool_log.append({"tool": name, "result": result})
                working.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id") or name,
                    "content": json.dumps(result, ensure_ascii=False)[:12000],
                })
            continue
        content = (msg.get("content") or "").strip()
        if content:
            sources = _sources_from_tool_log(tool_log)
            web_attempts = [item for item in tool_log if item.get("tool") in ("web_search", "fetch_url")]
            meta: dict[str, Any] = {}
            if sources:
                from app.services.web_search import format_sources_block, strip_unknown_urls

                allowed = {item["url"] for item in sources}
                content = strip_unknown_urls(content, allowed).strip()
                block = format_sources_block(sources)
                if block and block not in content:
                    content = f"{content.rstrip()}\n\n{block}"
                meta = {
                    "intent": "web_search",
                    "sources": sources,
                    "web_search": {"ok": True, "searched": True},
                }
            elif web_attempts:
                failed = next(
                    (
                        (item.get("result") or {})
                        for item in web_attempts
                        if not (item.get("result") or {}).get("ok")
                    ),
                    web_attempts[-1].get("result") or {},
                )
                note = (failed.get("message") or "联网检索没有返回可引用的公开来源。").strip()
                if note not in content:
                    content = f"{content.rstrip()}\n\n{note}"
                meta = {
                    "intent": "web_search",
                    "sources": [],
                    "web_search": {
                        "ok": False,
                        "offline": bool(failed.get("offline")),
                        "empty_state": bool(failed.get("empty_state")),
                        "error": failed.get("error") or "",
                        "message": note,
                    },
                }
            return _with_tool_trace(content, tool_log, meta)
        if tool_log:
            return _with_tool_trace("工具已执行，但模型没有给出文字回复。", tool_log, {"intent": "general"})
        return None
    if tool_log:
        return _with_tool_trace(
            f"已达到每轮 {limit} 步工具上限。",
            tool_log,
            {"intent": "general", "tool_limit": True},
        )
    return None
