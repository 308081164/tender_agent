"""最小 Agent tool-calling 循环（MVP，最多 3 步）。"""
from __future__ import annotations

import json
import os
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.services import agent_tools, ai


def tool_loop_enabled() -> bool:
    flag = os.environ.get("AGENT_TOOL_LOOP", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    return bool(get_settings().agent_tool_loop)


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
]


def _execute_tool(
    db: Session,
    session,
    name: str,
    arguments: dict[str, Any],
    *,
    default_project_id: int | None,
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
        if pid <= 0 or not isinstance(fields, dict):
            return {"ok": False, "error": "参数无效"}
        p = db.query(TenderProject).filter(TenderProject.id == pid).first()
        if not p:
            return {"ok": False, "error": "项目不存在"}
        merged = dict(p.fields or {})
        for k, v in fields.items():
            merged[str(k)] = str(v) if v is not None else ""
        p.fields = merged
        if merged.get("project_name"):
            p.title = str(merged["project_name"])[:180]
        db.commit()
        return {"ok": True, "project_id": pid, "updated_keys": list(fields.keys())}
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


async def run_tool_loop(
    *,
    db: Session,
    session,
    messages: list[dict],
    workspace: dict | None,
    context: dict | None,
    max_steps: int = 3,
) -> str | None:
    """若 LLM 返回最终文本则输出；否则 None 表示应回退普通对话。"""
    if not tool_loop_enabled() or session is None:
        return None

    from app.services import agent_runtime

    ws = workspace or {}
    ctx = context or {}
    pid = agent_runtime.resolve_project_id(ws, ctx)
    working = list(messages)
    tool_log: list[dict] = []

    for _ in range(max_steps):
        data = await _chat_with_tools(working, db)
        if not data:
            return None
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        tool_calls = msg.get("tool_calls") or []
        if tool_calls:
            working.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tool_calls})
            for tc in tool_calls[:2]:
                fn = tc.get("function") or {}
                name = fn.get("name") or ""
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = _execute_tool(db, session, name, args, default_project_id=pid)
                tool_log.append({"tool": name, "result": result})
                working.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id") or name,
                    "content": json.dumps(result, ensure_ascii=False)[:12000],
                })
            continue
        content = (msg.get("content") or "").strip()
        if content:
            if tool_log:
                content += "\n\n<!-- tools:" + json.dumps(tool_log, ensure_ascii=False)[:500] + " -->"
            return content
        return None
    return None
