"""新建标书工作流：根据模板类型决定占位符替换或 AI 创作路径。"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import Template
from app.services import ai, word
from app.services import storage


def resolve_template_mode(tpl: Template | None) -> dict[str, Any]:
    if not tpl:
        return {
            "mode": "compose",
            "kind": "",
            "label": "未选择模板",
            "description": "请先选择模板",
            "placeholder_count": 0,
            "needs_ai_compose": True,
            "needs_placeholder_replace": False,
            "skip_step3_generation": False,
        }
    kind = tpl.kind or "template"
    ph_list = (tpl.placeholders or {}).get("list") or []
    ph_count = len(ph_list)
    ai_ref = bool((tpl.placeholders or {}).get("ai_reference_full_doc"))

    if kind == "history" or (kind == "template" and ph_count > 0):
        return {
            "mode": "replace",
            "kind": kind,
            "label": "完整标书 · 占位符替换",
            "description": "已录入的项目信息将在导出时自动替换模板中的占位符，无需 AI 盲写章节。",
            "placeholder_count": ph_count,
            "needs_ai_compose": False,
            "needs_placeholder_replace": True,
            "skip_step3_generation": True,
        }
    if kind == "skeleton" or ai_ref:
        return {
            "mode": "compose",
            "kind": kind,
            "label": "空白/结构模板 · AI 创作",
            "description": "系统将审视模板结构，通过对话收集项目细节后分块创作内容。",
            "placeholder_count": ph_count,
            "needs_ai_compose": True,
            "needs_placeholder_replace": False,
            "skip_step3_generation": False,
        }
    return {
        "mode": "replace" if ph_count > 0 else "compose",
        "kind": kind,
        "label": "工程化模板",
        "description": "根据模板占位符与结构自动选择生成方式。",
        "placeholder_count": ph_count,
        "needs_ai_compose": ph_count == 0,
        "needs_placeholder_replace": ph_count > 0,
        "skip_step3_generation": ph_count > 0,
    }


def get_workflow_plan(db: Session, template_id: int | None) -> dict[str, Any]:
    tpl = db.query(Template).filter(Template.id == template_id).first() if template_id else None
    plan = resolve_template_mode(tpl)
    if tpl:
        plan["template_id"] = tpl.id
        plan["template_name"] = tpl.name
        plan["enabled"] = bool(tpl.enabled)
    return plan


async def guided_intake_questions(
    db: Session,
    template_id: int,
    fields: dict[str, Any],
    *,
    answered: dict[str, str] | None = None,
) -> dict[str, Any]:
    """根据模板与已填字段，生成引导式信息收集问题。"""
    tpl = db.query(Template).filter(Template.id == template_id).first()
    if not tpl or not tpl.object_key:
        return {"questions": [], "ready": True, "summary": ""}

    try:
        doc_bytes = storage.download_bytes(tpl.object_key)
        preview = word.extract_preview(doc_bytes, max_paragraphs=120)
        excerpt = "\n".join(p["text"] for p in preview.get("paragraphs") or [] if p.get("text"))[:6000]
    except Exception:
        excerpt = ""

    manifest = (tpl.placeholders or {}).get("manifest") or {}
    blocks = manifest.get("blocks") or []
    ai_blocks = [b for b in blocks if b.get("type") in ("ai_section", "table_slot")]

    import json
    prompt = (
        "你是标书编制顾问。用户将基于空白/结构模板创作标书，请审视模板并生成需要向用户确认的关键信息问题。\n\n"
        f"模板名称：{tpl.name}\n"
        f"模板类型：{tpl.kind}\n"
        f"已填字段：{json.dumps(fields or {}, ensure_ascii=False)[:2000]}\n"
        f"模板节选：{excerpt[:4000]}\n"
        f"AI 区块：{json.dumps(ai_blocks[:12], ensure_ascii=False)}\n\n"
        "输出 JSON：{\"questions\":[{\"id\":\"q1\",\"text\":\"问题\",\"hint\":\"填写提示\",\"field_key\":\"可选关联字段key\"}],"
        "\"ready\":false,\"summary\":\"已掌握的信息摘要\"}\n"
        "规则：3-6 个问题，聚焦招标条款、评分点、工期、供货范围、特殊要求；不要重复已填字段；只返回 JSON。"
    )
    raw = await ai.chat_completion([
        {"role": "system", "content": "你只输出合法 JSON 对象。"},
        {"role": "user", "content": prompt},
    ], db=db)
    if not raw:
        return {
            "questions": [
                {"id": "req", "text": "请补充招标条款、评分点与工期/供货要求", "hint": "可粘贴招标文件相关段落", "field_key": ""},
            ],
            "ready": False,
            "summary": "",
        }
    try:
        text = raw.strip()
        if text.startswith("```"):
            import re
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        data = json.loads(text)
        if answered:
            data["answered"] = answered
        return data
    except Exception:
        return {
            "questions": [
                {"id": "req", "text": "请补充编写要求（招标条款、评分点等）", "hint": "", "field_key": ""},
            ],
            "ready": False,
            "summary": "",
        }
