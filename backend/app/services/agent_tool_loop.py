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
            "description": "把当前文稿对照招标文件的工期、废标项、评分点、资质和关键日期",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "project_id": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_table",
            "description": "在选中锚点的段落后插入表格。没有段落号时不要插入，更不要插到文首。",
            "parameters": {
                "type": "object",
                "properties": {
                    "rows": {"type": "integer"},
                    "cols": {"type": "integer"},
                    "paragraph_index": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_image",
            "description": "在选中锚点的段落后插入已上传的图片。没有段落号时不要插入。",
            "parameters": {
                "type": "object",
                "properties": {
                    "paragraph_index": {"type": "integer"},
                    "attachment_object_key": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_document_outline",
            "description": (
                "读取当前标书草稿的结构大纲（章节类型、空表单元格、是否允许 AI 叙事）。"
                "修改文档或填表前应先调用此工具或 read_document_section。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "refresh": {"type": "boolean", "description": "强制从 DOCX 重建大纲"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_document_section",
            "description": "按章节标题读取正文段落与表格摘要（不含全文一次性灌入）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "heading_title": {"type": "string", "description": "章节标题，需与文档中一致或包含匹配"},
                },
                "required": ["heading_title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_empty_form_slots",
            "description": "列出当前草稿中表单表格的空单元格坐标（tbl:t:r:c）。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fill_table_cells",
            "description": (
                "向表格单元格写入文字。优先使用 location（如 tbl:0:r:1:c:2），"
                "或 table_index+row+col。不要对 letter_skeleton/form_table 章节用 insert 段落代替填表。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cells": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "location": {"type": "string"},
                                "table_index": {"type": "integer"},
                                "row": {"type": "integer"},
                                "col": {"type": "integer"},
                                "text": {"type": "string"},
                            },
                        },
                    },
                },
                "required": ["cells"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_image_at_table_cell",
            "description": "将已上传图片插入指定表格单元格（证照贴图）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "table_index": {"type": "integer"},
                    "row": {"type": "integer"},
                    "col": {"type": "integer"},
                    "attachment_object_key": {"type": "string"},
                    "width_pt": {"type": "number"},
                },
                "required": ["table_index", "row", "col", "attachment_object_key"],
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
        return await _edit_document_anchor(db, session, args, context, default_project_id)
    if name == "insert_table":
        return await _insert_table_tool(db, session, args, context)
    if name == "insert_image":
        return await _insert_image_tool(db, session, args, context)
    if name == "read_document_outline":
        from app.services import agent_document_tools

        return agent_document_tools.read_document_outline(
            db, session, refresh=bool(args.get("refresh")),
        )
    if name == "read_document_section":
        from app.services import agent_document_tools

        return agent_document_tools.read_document_section(
            db, session, str(args.get("heading_title") or ""),
        )
    if name == "list_empty_form_slots":
        from app.services import agent_document_tools

        return agent_document_tools.list_empty_form_slots(db, session)
    if name == "fill_table_cells":
        from app.services import agent_document_tools

        cells = args.get("cells") or []
        return agent_document_tools.fill_table_cells(db, session, cells if isinstance(cells, list) else [])
    if name == "insert_image_at_table_cell":
        from app.services import agent_document_tools

        return agent_document_tools.insert_image_at_table_cell(
            db,
            session,
            table_index=int(args.get("table_index") or 0),
            row=int(args.get("row") or 0),
            col=int(args.get("col") or 0),
            attachment_object_key=str(args.get("attachment_object_key") or ""),
            width_pt=args.get("width_pt"),
        )
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
        from app.models import Qualification, TenderProject

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
        records = [
            {"name": row.name or "", "keywords": row.keywords or "", "category": row.category or ""}
            for row in db.query(Qualification).all()
        ]
        checked = check_against_tender(draft, tender_record(p.fields), qualifications=records)
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


async def _edit_document_anchor(db, session, args, context, default_project_id) -> dict[str, Any]:
    from app.services import document_agent, storage
    from app.services.agent_capabilities import project_memory_text
    from app.services.agent_workspace import normalize_relative_path, resolve_session_workspace_root

    anchor = resolve_document_anchor(context, args)
    if not anchor.get("ok"):
        return {"ok": False, "error": ANCHOR_MISSING}
    instruction = str(args.get("instruction") or (context or {}).get("instruction") or "").strip()
    memory = project_memory_text(db, getattr(session, "workspace", None), context)
    path = str(anchor.get("path") or "").strip()
    if path and not path.lower().endswith(".docx"):
        from app.services import agent_tools

        current = agent_tools.read_workspace_file(db, session, path)
        original = current.get("content") or ""
        revised = await document_agent.revise_plain_text(
            original, instruction, db=db, memory=memory,
        )
        agent_tools.write_workspace_file(db, session, path, revised)
        return {
            "ok": True,
            "path": path,
            "modified": True,
            "anchor": {"path": path, "selected_text": anchor.get("selected_text") or ""},
            "message": f"已按 @ 引用修改文件 {path}。",
        }

    ws = dict(getattr(session, "workspace", None) or {})
    doc_key = ws.get("draft_object_key") or ws.get("template_object_key")
    doc_bytes = None
    if path.lower().endswith(".docx"):
        root = resolve_session_workspace_root(db, session)
        target = normalize_relative_path(root, path)
        doc_bytes = target.read_bytes()
    elif doc_key:
        doc_bytes = storage.download_bytes(doc_key)
    if not doc_bytes:
        return {"ok": False, "error": "工作区没有可修改的文档"}
    from app.services.document_anchor import finalize_document_anchor

    anchor = finalize_document_anchor(anchor, doc_bytes)
    new_bytes, revised, meta = await document_agent.edit_document_fragment(
        doc_bytes,
        instruction or "按锚点修订",
        selected_text=anchor.get("selected_text") or "",
        paragraph_index=anchor.get("paragraph_index"),
        location=str(anchor.get("location") or ""),
        db=db,
        company_context=memory,
    )
    if path.lower().endswith(".docx"):
        target.write_bytes(new_bytes)
        saved_key = path
    else:
        from datetime import datetime

        saved_key = f"chat/{getattr(session, 'id', 0)}/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_anchor.docx"
        storage.upload_bytes(
            saved_key, new_bytes,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        ws["draft_object_key"] = saved_key
        ws["version"] = int(ws.get("version") or 0) + 1
        session.workspace = ws
        if db is not None:
            db.commit()
    return {
        "ok": True,
        "modified": True,
        "object_key": saved_key,
        "revised": (revised or "")[:500],
        "anchor": {
            "paragraph_index": anchor.get("paragraph_index"),
            "block_id": anchor.get("block_id") or "",
            "selected_text": anchor.get("selected_text") or "",
            "location": anchor.get("location") or "",
            "table_index": anchor.get("table_index"),
            "row": anchor.get("row"),
            "col": anchor.get("col"),
            "path": path,
        },
        "mode": meta.get("mode"),
        "message": "已按锚点改写文档，没有插入到文首。",
    }


async def _insert_table_tool(db, session, args, context) -> dict[str, Any]:
    from app.services import document_agent

    anchor = resolve_document_anchor(context, args)
    if not anchor_can_insert(anchor):
        return {"ok": False, "error": ANCHOR_MISSING}
    doc_bytes, doc_key, ws = _load_open_docx(session)
    if doc_bytes is None:
        return {"ok": False, "error": "请先打开标书草稿"}
    rows = int(args.get("rows") or (context or {}).get("rows") or 3)
    cols = int(args.get("cols") or (context or {}).get("cols") or 3)
    new_bytes, meta = document_agent.insert_table_in_document(
        doc_bytes, paragraph_index=int(anchor["paragraph_index"]), rows=rows, cols=cols,
    )
    saved = _store_open_docx(db, session, ws, doc_key, new_bytes, "table")
    return {"ok": True, "modified": True, "object_key": saved, "anchor": meta, "message": "已在选中位置插入表格。"}


async def _insert_image_tool(db, session, args, context) -> dict[str, Any]:
    from app.services import document_agent, storage
    from app.services.document_anchor import anchor_has_table_cell, finalize_document_anchor

    anchor = resolve_document_anchor(context, args)
    if not anchor_can_insert(anchor):
        return {"ok": False, "error": ANCHOR_MISSING}
    image_key = str(args.get("attachment_object_key") or (context or {}).get("attachment_object_key") or "")
    if not image_key:
        return {"ok": False, "error": "请先上传图片"}
    doc_bytes, doc_key, ws = _load_open_docx(session)
    if doc_bytes is None:
        return {"ok": False, "error": "请先打开标书草稿"}
    anchor = finalize_document_anchor(anchor, doc_bytes)
    image_bytes = storage.download_bytes(image_key)
    if anchor_has_table_cell(anchor):
        from app.services.doc_engine.indexer import insert_image_in_table_cell

        loc = str(anchor.get("location") or "")
        ti = int(anchor.get("table_index", 0))
        row = int(anchor.get("row", 0))
        col = int(anchor.get("col", 0))
        new_bytes = insert_image_in_table_cell(doc_bytes, ti, row, col, image_bytes)
        saved = _store_open_docx(db, session, ws, doc_key, new_bytes, "cell_image")
        return {
            "ok": True,
            "modified": True,
            "object_key": saved,
            "anchor": {"location": loc, "table_index": ti, "row": row, "col": col},
            "message": f"已在表格单元格 {loc} 插入图片。",
        }
    new_bytes, meta = document_agent.insert_image_in_document(
        doc_bytes, image_bytes, paragraph_index=int(anchor["paragraph_index"]),
    )
    saved = _store_open_docx(db, session, ws, doc_key, new_bytes, "image")
    return {"ok": True, "modified": True, "object_key": saved, "anchor": meta, "message": "已在选中位置插入图片。"}


def _load_open_docx(session):
    from app.services import storage

    ws = dict(getattr(session, "workspace", None) or {})
    doc_key = ws.get("draft_object_key") or ws.get("template_object_key")
    if not doc_key:
        return None, "", ws
    return storage.download_bytes(doc_key), doc_key, ws


def _store_open_docx(db, session, ws, previous_key, new_bytes, suffix) -> str:
    from datetime import datetime

    from app.services import storage

    saved = f"chat/{getattr(session, 'id', 0)}/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{suffix}.docx"
    storage.upload_bytes(
        saved, new_bytes,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    ws = dict(ws)
    ws["draft_object_key"] = saved
    ws["version"] = int(ws.get("version") or 0) + 1
    session.workspace = ws
    if db is not None:
        db.commit()
    return saved


def anchor_can_insert(anchor: dict) -> bool:
    from app.services.agent_capabilities import anchor_can_insert as _can

    return _can(anchor)


from contextvars import ContextVar

_loop_control: ContextVar[dict[str, Any] | None] = ContextVar("agent_loop_control", default=None)


async def _chat_with_tools(messages: list[dict], db: Session | None = None) -> dict[str, Any]:
    from app.services import settings_svc

    cfg = settings_svc.resolve_ai_config(db)
    order = ai.pick_model("text", cfg)
    for slug in order:
        call = ai._provider_call(slug, cfg)
        if not call:
            continue
        base_url, api_key, model = call
        started = False
        try:
            return await _openai_tools_stream(base_url, api_key, model, messages, TOOL_SPECS)
        except Exception:
            control = _loop_control.get() or {}
            started = bool(control.get("started"))
            if started:
                raise
            continue
    return {}


async def _openai_tools_stream(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    tools: list[dict],
) -> dict[str, Any]:
    """从模型 HTTP 流里逐个 token 往外送，不把整段答案切成固定字数。"""
    import httpx

    control = _loop_control.get() or {}
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    force = control.get("force_tool")
    payload: dict = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": (
            {"type": "function", "function": {"name": force}}
            if force and not control.get("force_used")
            else "auto"
        ),
        "temperature": 0.3,
        "stream": True,
    }
    if force and not control.get("force_used"):
        control["force_used"] = True
    content_parts: list[str] = []
    tool_acc: dict[int, dict[str, Any]] = {}
    async with httpx.AsyncClient(timeout=90) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                text = delta.get("content") or ""
                if text:
                    content_parts.append(text)
                    control["started"] = True
                    sink = control.get("on_token")
                    if sink:
                        await sink(text)
                for tc in delta.get("tool_calls") or []:
                    idx = int(tc.get("index") or 0)
                    slot = tool_acc.setdefault(idx, {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    })
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["function"]["name"] += fn["name"]
                    if fn.get("arguments"):
                        slot["function"]["arguments"] += fn["arguments"]
    message: dict[str, Any] = {"content": "".join(content_parts)}
    if tool_acc:
        message["tool_calls"] = [tool_acc[i] for i in sorted(tool_acc)]
    return {"choices": [{"message": message}]}


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
        result = entry.get("result") or {}
        if result.get("modified"):
            meta["workspace_updated"] = True
            if result.get("object_key"):
                meta["draft_object_key"] = result.get("object_key")
        if entry.get("tool") not in (
            "edit_document_anchor",
            "insert_table",
            "insert_image",
            "fill_table_cells",
            "insert_image_at_table_cell",
        ):
            continue
        if not result.get("ok"):
            if ANCHOR_MISSING not in content:
                content = f"{content.rstrip()}\n\n{ANCHOR_MISSING}".strip()
            meta["anchor_missing"] = True
            continue
        if result.get("modified"):
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
    on_token=None,
    on_tool=None,
    force_tool: str | None = None,
) -> dict[str, Any] | None:
    """若 LLM 返回最终文本则输出；否则 None 表示应回退普通对话。

    上限按工具执行次数计算，不是按模型回合，也不在一回合里再截成 4 次。
    """
    if not tool_loop_enabled() or session is None:
        return None

    from app.services import agent_runtime

    ws = workspace or {}
    ctx = context or {}
    pid = agent_runtime.resolve_project_id(ws, ctx)
    working = list(messages)
    tool_log: list[dict] = []
    limit = max(1, min(int(max_steps or MAX_TOOL_STEPS), MAX_TOOL_STEPS))
    control = {"on_token": on_token, "force_tool": force_tool, "force_used": False, "started": False}
    token = _loop_control.set(control)
    executed = 0
    try:
        while executed < limit:
            data = await _chat_with_tools(working, db)
            if not data:
                if tool_log:
                    return _mark_streamed(
                        _with_tool_trace("工具调用没有得到模型的后续回复。", tool_log, {"intent": "general"}),
                        control,
                    )
                return None
            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                working.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": tool_calls})
                for tc in tool_calls:
                    if executed >= limit:
                        break
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
                    executed += 1
                    if on_tool:
                        await on_tool({"tool": name, "ok": bool((result or {}).get("ok", True))})
                    working.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id") or name,
                        "content": json.dumps(result, ensure_ascii=False, default=str)[:12000],
                    })
                if executed >= limit:
                    break
                continue
            content = (msg.get("content") or "").strip()
            if content:
                return _mark_streamed(_finish_tool_answer(content, tool_log), control)
            if tool_log:
                return _mark_streamed(
                    _with_tool_trace("工具已执行，但模型没有给出文字回复。", tool_log, {"intent": "general"}),
                    control,
                )
            return None
        if tool_log:
            return _mark_streamed(
                _with_tool_trace(
                    f"已达到每轮 {limit} 步工具上限。",
                    tool_log,
                    {"intent": "general", "tool_limit": True},
                ),
                control,
            )
        return None
    finally:
        _loop_control.reset(token)


def _finish_tool_answer(content: str, tool_log: list[dict]) -> dict[str, Any]:
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


def _mark_streamed(result: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
    if control.get("started"):
        meta = dict(result.get("metadata") or {})
        meta["tokens_streamed"] = True
        result["metadata"] = meta
    return result
