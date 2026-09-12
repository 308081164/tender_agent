"""Agent 语义路由：LLM 初判意图 + 系统工具调用 + 上下文合成回复。"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.services import agent_flows, agent_query_tools, ai

INTENT_LABELS = [
    "meta",
    "teach",
    "query_company",
    "query_template_stats",
    "query_recent_projects",
    "search_project",
    "search_template",
    "create_template",
    "generate_document",
    "bulk_replace",
    "create_project",
    "edit_fragment",
    "search_info",
    "general",
]

_TEACH_KEYWORDS = ("怎么用", "如何使用", "怎么操作", "教学", "引导", "帮助", "教程", "不会用")


def _is_meta_question(text: str) -> bool:
    from app.services.chat_assistant import _is_meta_question as _meta
    return _meta(text)


def _keyword_route(text: str) -> tuple[str, dict[str, Any], float]:
    q = text.strip()

    if _is_meta_question(q):
        return "meta", {}, 0.99

    if any(k in q for k in _TEACH_KEYWORDS):
        return "teach", {}, 0.92

    if re.search(r"(全称|公司名称|企业名称|叫什么)", q):
        return "query_company", {}, 0.9

    if re.search(r"(多少|几个|数量|统计).*(模板|脚本|标书模板)", q) or re.search(r"(模板|脚本).*(多少|几个)", q):
        return "query_template_stats", {}, 0.88

    if re.search(r"(最近|近一周|近7天|这周).*(标书|项目)", q):
        days = 7
        m = re.search(r"近(\d+)天", q)
        if m:
            days = int(m.group(1))
        return "query_recent_projects", {"days": days}, 0.88

    if re.search(r"(找出|找到|查找|搜索|发给我|发我).*(标书|项目|文件)", q):
        name = re.sub(r".*(找出|找到|查找|搜索|发给我|发我)", "", q)
        name = re.sub(r"(标书|项目|文件|请|把|将|的).*$", "", name).strip("「」\"' ")
        return "search_project", {"query": name or q}, 0.82

    if re.search(r"(找出|找到|查找).*(模板)", q):
        name = re.sub(r".*(找出|找到|查找)", "", q)
        name = re.sub(r"(模板|请|把|将).*$", "", name).strip()
        return "search_template", {"query": name or q}, 0.82

    bulk = agent_query_tools.parse_bulk_replace(q)
    if bulk:
        return "bulk_replace", {"old_text": bulk[0], "new_text": bulk[1]}, 0.9

    return "general", {}, 0.0


async def _llm_route(
    text: str,
    snapshot: dict[str, Any],
    history: list[dict],
    db: Session | None,
) -> tuple[str, dict[str, Any], float]:
    hist = "\n".join(
        f"{m.get('role')}: {(m.get('content') or '')[:120]}"
        for m in (history or [])[-6:]
    )
    prompt = (
        "你是标书智能体意图分类器。根据用户消息与系统状态，输出 JSON："
        '{"intent":"...", "params":{}, "confidence":0.0}\n'
        f"可选 intent：{', '.join(INTENT_LABELS)}\n\n"
        f"系统状态：{json.dumps(snapshot, ensure_ascii=False)}\n"
        f"近期对话：\n{hist or '无'}\n\n"
        f"用户消息：{text}\n\n"
        "规则：\n"
        "- 问身份/能力 → meta\n"
        "- 问怎么用/教学 → teach\n"
        "- 问公司全称/企业信息 → query_company\n"
        "- 问模板/脚本数量 → query_template_stats\n"
        "- 问最近创建的标书 → query_recent_projects\n"
        "- 找某个标书/项目 → search_project，params.query 为关键词\n"
        "- 上传文件后要生成标书 → generate_document\n"
        "- 上传文件后要建模板 → create_template\n"
        "- 全文替换 → bulk_replace，params 含 old_text/new_text\n"
        "- 企业资质业绩 → search_info\n"
        "只返回 JSON。"
    )
    raw = await ai.chat_completion([
        {"role": "system", "content": "你只输出合法 JSON 对象。"},
        {"role": "user", "content": prompt},
    ], db=db)
    if not raw:
        return "general", {}, 0.0
    try:
        text_json = raw.strip()
        if text_json.startswith("```"):
            text_json = re.sub(r"^```(?:json)?\s*", "", text_json)
            text_json = re.sub(r"\s*```$", "", text_json)
        data = json.loads(text_json)
        intent = str(data.get("intent") or "general")
        if intent not in INTENT_LABELS:
            intent = "general"
        params = data.get("params") if isinstance(data.get("params"), dict) else {}
        conf = float(data.get("confidence") or 0.5)
        return intent, params, conf
    except (json.JSONDecodeError, TypeError, ValueError):
        return "general", {}, 0.0


async def route_intent(
    text: str,
    db: Session | None,
    history: list[dict] | None,
    workspace: dict | None,
) -> tuple[str, dict[str, Any], float]:
    intent, params, score = _keyword_route(text)
    if score >= 0.85:
        return intent, params, score
    snapshot = (
        agent_query_tools.build_system_snapshot(db, workspace)
        if db is not None
        else {"workspace_has_doc": bool((workspace or {}).get("draft_object_key"))}
    )
    li, lp, ls = await _llm_route(text, snapshot, history or [], db)
    if ls >= 0.55:
        return li, lp, ls
    if score >= 0.75:
        return intent, params, score
    return li if ls > 0 else intent, lp if ls > 0 else params, max(score, ls)


def _actions_from_projects(projects: list[dict]) -> list[dict]:
    actions = []
    for p in projects[:5]:
        actions.append({
            "type": "link",
            "label": f"打开「{p.get('title', '')[:20]}」",
            "url": p.get("edit_url") or f"/projects/{p.get('id')}",
            "primary": len(actions) == 0,
        })
    return actions


async def _synthesize(
    user_text: str,
    intent: str,
    tool_payload: dict[str, Any],
    history: list[dict],
    db: Session | None,
) -> str:
    hist = []
    for m in (history or [])[-8:]:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            hist.append({"role": role, "content": content})

    system = (
        "你是标书智能体助手。请基于「系统查询结果」准确、简洁地回答用户，"
        "保持多轮对话连贯；数字与名称必须与系统数据一致，不可编造。"
        "若结果为空，如实说明并给出下一步建议。可使用 Markdown 列表。"
    )
    user = (
        f"用户问题：{user_text}\n\n"
        f"意图：{intent}\n\n"
        f"系统查询结果：\n{json.dumps(tool_payload, ensure_ascii=False, indent=2)}"
    )
    answer = await ai.chat_completion([
        {"role": "system", "content": system},
        *hist,
        {"role": "user", "content": user},
    ], db=db)
    if answer:
        return answer.strip()
    return tool_payload.get("fallback_answer") or "已查询系统数据，请查看上方操作按钮。"


async def _handle_teach(text: str, db: Session | None, history: list[dict]) -> dict[str, Any]:
    guide = {
        "topics": [
            {"title": "新建标书", "steps": ["首页 → 新建标书", "选择模板或历史标书", "按六步向导填写并导出"]},
            {"title": "文档 Agent", "steps": ["进入文档工作区", "上传 DOCX", "说明编写要求或选中片段修改"]},
            {"title": "模板工程化", "steps": ["数据管理 → 模板", "上传标书 → 智能识别占位符", "确认后用于新建标书"]},
            {"title": "导入测试材料", "steps": ["解压测试材料包", "复制到 customer_data", "数据管理 → 强制重新导入"]},
        ],
        "user_question": text,
    }
    answer = await _synthesize(text, "teach", guide, history, db)
    return {
        "answer": answer,
        "mode": "teach",
        "metadata": {
            "intent": "teach",
            "actions": [
                {"type": "link", "label": "新建标书", "url": "/projects/new", "primary": True},
                {"type": "link", "label": "文档工作区", "url": "/chat"},
                {"type": "link", "label": "数据管理", "url": "/admin"},
            ],
        },
    }


async def process_with_semantic_router(
    text: str,
    db: Session,
    history: list[dict] | None,
    faq_items: list[dict] | None,
    *,
    workspace: dict | None = None,
    context: dict | None = None,
    session=None,
) -> dict[str, Any] | None:
    """语义路由处理；返回 None 表示交给旧版 chat_assistant 流程。"""
    intent, params, confidence = await route_intent(text, db, history, workspace)
    hist = history or []
    faqs = faq_items or []
    ws = workspace or {}

    if intent == "meta" and confidence >= 0.5:
        from app.services.chat_assistant import _handle_meta_question
        return await _handle_meta_question()

    if intent == "teach" and confidence >= 0.5:
        return await _handle_teach(text, db, hist)

    if intent == "query_company" and confidence >= 0.5:
        if db is None:
            return None
        data = agent_query_tools.get_company_summary(db)
        if not data.get("found"):
            data["fallback_answer"] = "系统中尚未录入企业档案，请前往「数据管理 → 企业档案」填写。"
        else:
            data["fallback_answer"] = f"公司全称：{data.get('full_name') or '未填写'}"
        answer = await _synthesize(text, intent, data, hist, db)
        return {
            "answer": answer,
            "mode": "query",
            "metadata": {
                "intent": intent,
                "tool_data": data,
                "actions": [{"type": "link", "label": "企业档案", "url": "/admin/company", "primary": True}],
            },
        }

    if intent == "query_template_stats" and confidence >= 0.5:
        if db is None:
            return None
        data = agent_query_tools.count_templates(db)
        data["fallback_answer"] = (
            f"当前共有 {data['total']} 个标书模板/脚本，其中 {data['enabled']} 个已启用。"
        )
        answer = await _synthesize(text, intent, data, hist, db)
        return {
            "answer": answer,
            "mode": "query",
            "metadata": {
                "intent": intent,
                "tool_data": data,
                "actions": [{"type": "link", "label": "模板管理", "url": "/admin/templates", "primary": True}],
            },
        }

    if intent == "query_recent_projects" and confidence >= 0.5:
        if db is None:
            return None
        days = int(params.get("days") or 7)
        projects = agent_query_tools.list_recent_projects(db, days=days)
        data = {"days": days, "count": len(projects), "projects": projects}
        data["fallback_answer"] = f"最近 {days} 天共创建 {len(projects)} 个标书项目。"
        answer = await _synthesize(text, intent, data, hist, db)
        return {
            "answer": answer,
            "mode": "query",
            "metadata": {
                "intent": intent,
                "tool_data": data,
                "actions": _actions_from_projects(projects),
            },
        }

    if intent == "search_project" and confidence >= 0.5:
        if db is None:
            return None
        query = str(params.get("query") or text)
        projects = agent_query_tools.search_projects(db, query)
        data = {"query": query, "count": len(projects), "projects": projects}
        if not projects:
            data["fallback_answer"] = f"未找到与「{query}」匹配的标书项目，可尝试更短的关键词。"
        answer = await _synthesize(text, intent, data, hist, db)
        return {
            "answer": answer,
            "mode": "query",
            "metadata": {
                "intent": intent,
                "tool_data": data,
                "actions": _actions_from_projects(projects),
            },
        }

    if intent == "search_template" and confidence >= 0.5:
        if db is None:
            return None
        query = str(params.get("query") or text)
        templates = agent_query_tools.search_templates(db, query)
        data = {"query": query, "count": len(templates), "templates": templates}
        actions = [
            {"type": "link", "label": f"模板：{t['name'][:18]}", "url": "/admin/templates", "primary": i == 0}
            for i, t in enumerate(templates[:5])
        ]
        answer = await _synthesize(text, intent, data, hist, db)
        return {
            "answer": answer,
            "mode": "query",
            "metadata": {"intent": intent, "tool_data": data, "actions": actions},
        }

    if intent == "bulk_replace" and confidence >= 0.5:
        old_t = str(params.get("old_text") or "")
        new_t = str(params.get("new_text") or "")
        if not ws.get("draft_object_key") and not ws.get("template_object_key"):
            return {
                "answer": "请先在工作区左侧上传或打开一份 DOCX，再告诉我需要替换的内容。",
                "mode": "action",
                "metadata": {
                    "intent": intent,
                    "actions": [{"type": "link", "label": "文档工作区", "url": "/chat", "primary": True}],
                },
            }
        return {
            "answer": f"将对当前文档执行全文替换：「{old_t}」→「{new_t}」。正在处理…",
            "mode": "action",
            "metadata": {
                "intent": intent,
                "needs_workspace_bulk_replace": True,
                "old_text": old_t,
                "new_text": new_t,
            },
        }

    if intent == "create_template" and confidence >= 0.55:
        if session is not None:
            return await agent_flows.start_template_create(db, session)
        from app.services.chat_assistant import _handle_create_template
        return await _handle_create_template(db, session)

    if intent == "generate_document" and confidence >= 0.55:
        from app.services.chat_assistant import _handle_generate_document
        return await _handle_generate_document(db, text, ws)

    if intent == "create_project" and confidence >= 0.55:
        from app.services.chat_assistant import _handle_create_project
        return await _handle_create_project(db, text, session=session)

    if intent == "edit_fragment" and confidence >= 0.55:
        from app.services.chat_assistant import _handle_edit_fragment
        return await _handle_edit_fragment(text, context)

    if intent == "search_info" and confidence >= 0.55:
        from app.services.chat_assistant import _handle_search_info
        return await _handle_search_info(db, text, hist, faqs)

    return None
