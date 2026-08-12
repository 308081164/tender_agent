"""Chatbot 意图识别与任务路由。"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import CompanyProfile, FieldDef, Qualification, Template, TenderProject
from app.services import ai


FEATURE_CARDS = [
    {
        "id": "new_project",
        "title": "新建标书",
        "description": "从模板或历史标书开始创建投标项目",
        "icon": "📄",
        "url": "/projects/new",
        "intent": "create_project",
    },
    {
        "id": "template_from_doc",
        "title": "标书转模板",
        "description": "上传完整标书，AI 自动识别并替换为占位符",
        "icon": "🧩",
        "url": "/admin/templates/new",
        "intent": "create_template",
    },
    {
        "id": "qual_search",
        "title": "资质检索",
        "description": "查询企业资质、业绩与人员信息",
        "icon": "🏢",
        "url": "/admin/qualifications",
        "intent": "search_info",
    },
    {
        "id": "wizard_edit",
        "title": "标书微调",
        "description": "进入六步向导，精细编辑字段、章节与资质",
        "icon": "✏️",
        "url": "/",
        "intent": "edit_project",
    },
]

SUGGESTED_PROMPTS = [
    "帮我新建一份标书",
    "按模板生成一份新标书",
    "公司有哪些铁路相关资质？",
    "如何从已有标书创建模板？",
    "修改选中段落，使语气更正式",
]

INTENT_PATTERNS: list[tuple[str, list[str], float]] = [
    ("generate_document", [
        "按模板生成", "根据模板写", "严格按模板", "生成一份标书", "生成全新标书",
        "模板文档", "编写要求", "照模板格式", "按格式生成",
    ], 1.0),
    ("edit_fragment", [
        "修改选中", "修改这段", "改写这段", "润色", "替换为", "把这段", "选中内容",
    ], 0.95),
    ("create_project", [
        "新建标书", "创建标书", "开始做标书", "写一份标书", "新建项目", "创建项目",
    ], 0.9),
    ("create_template", [
        "创建模板", "做模板", "标书转模板", "转成模板", "占位符", "模板化", "工程化",
    ], 0.9),
    ("edit_project", [
        "微调", "修改章节", "编辑标书", "完善标书", "六步向导", "向导编辑",
    ], 0.85),
    ("search_info", [
        "查询", "有没有", "是否具备", "资质", "业绩", "项目经理", "建造师", "证书", "注册资金",
    ], 0.8),
    ("draft_create", [
        "初版", "生成章节", "ai生成", "撰写章节", "章节初稿",
    ], 0.85),
    ("open_workspace", [
        "文档工作区", "打开编辑器", "双栏模式", "左边编辑",
    ], 0.7),
]


def get_feature_cards() -> list[dict]:
    return FEATURE_CARDS


def get_suggested_prompts() -> list[str]:
    return SUGGESTED_PROMPTS


def _score_intent(text: str) -> tuple[str, float]:
    q = text.strip().lower()
    best_intent = "general"
    best_score = 0.0
    for intent, keywords, weight in INTENT_PATTERNS:
        hits = sum(1 for k in keywords if k in q)
        if hits <= 0:
            continue
        score = weight * hits / max(len(keywords) * 0.25, 1)
        if score > best_score:
            best_score = score
            best_intent = intent
    return best_intent, best_score


async def _classify_intent(text: str, db: Session | None = None) -> str:
    intent, score = _score_intent(text)
    if score >= 0.45:
        return intent
    # LLM 兜底分类
    labels = [p[0] for p in INTENT_PATTERNS] + ["general"]
    prompt = (
        "将用户消息分类为以下意图之一，只返回意图英文名：\n"
        f"{', '.join(labels)}\n\n"
        f"用户消息：{text}\n\n"
        "只返回一个意图名，不要解释。"
    )
    raw = await ai.chat_completion([
        {"role": "system", "content": "你是意图分类器，只输出一个英文意图标签。"},
        {"role": "user", "content": prompt},
    ], db=db)
    label = (raw or "").strip().lower().replace(" ", "_")
    if label in labels:
        return label
    return intent if score > 0.2 else "general"


def _classify_intent_sync(text: str) -> str:
    intent, score = _score_intent(text)
    return intent if score >= 0.45 else "general"


def _company_context(db: Session) -> str:
    c = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    if not c:
        return ""
    parts = [
        f"企业全称：{c.full_name}",
        f"简称：{c.short_name}",
        f"法人：{c.legal_name}",
        f"注册资本：{c.registered_capital}",
        f"资质概况：{(c.qual_overview or '')[:500]}",
        f"典型项目：{(c.typical_projects or '')[:500]}",
    ]
    return "\n".join(p for p in parts if p.split("：", 1)[-1])


def _latest_project(db: Session) -> TenderProject | None:
    return db.query(TenderProject).order_by(TenderProject.updated_at.desc()).first()


async def _handle_create_project(db: Session, text: str) -> dict[str, Any]:
    tpl = (
        db.query(Template)
        .filter(Template.enabled.is_(True), Template.kind.in_(["template", "skeleton"]))
        .order_by(Template.id.asc())
        .first()
    )
    title = "新标书项目"
    m = re.search(r"[「『\"](.+?)[」』\"]", text)
    if m:
        title = m.group(1).strip()[:80] or title

    project = TenderProject(
        title=title,
        source_type="template",
        template_id=tpl.id if tpl else None,
        current_step=1,
        fields={},
        status="draft",
        updated_at=datetime.utcnow(),
    )
    db.add(project)
    db.flush()

    tpl_name = tpl.name if tpl else "默认模板"
    return {
        "answer": (
            f"已为您创建标书草稿「{title}」。\n\n"
            f"建议下一步：选择模板（当前默认：{tpl_name}），然后填写项目字段。"
            "更复杂的章节微调、资质插入请在向导中完成。"
        ),
        "mode": "action",
        "metadata": {
            "intent": "create_project",
            "project_id": project.id,
            "actions": [
                {"type": "link", "label": "选择模板", "url": f"/projects/{project.id}/step/1", "primary": True},
                {"type": "link", "label": "填写项目字段", "url": f"/projects/{project.id}/step/2"},
            ],
        },
    }


async def _handle_create_template(db: Session) -> dict[str, Any]:
    return {
        "answer": (
            "您可以将一份完整标书工程化为可复用模板。\n\n"
            "操作流程：\n"
            "1. 在「数据管理 → 模板」上传 DOCX\n"
            "2. 进入「模板工程化」工作台 → 智能识别\n"
            "3. 在可编辑页面手动调整：恢复原文 / 选中文本设为占位符\n"
            "4. 确认应用后，预览区查看高亮占位符"
        ),
        "mode": "action",
        "metadata": {
            "intent": "create_template",
            "actions": [
                {"type": "link", "label": "上传标书 DOCX", "url": "/admin/templates/new", "primary": True},
                {"type": "link", "label": "管理已有模板", "url": "/admin/templates"},
            ],
        },
    }


async def _handle_generate_document(db: Session, text: str, workspace: dict | None) -> dict[str, Any]:
    ws = workspace or {}
    if not ws.get("draft_object_key") and not ws.get("template_object_key"):
        return {
            "answer": (
                "请先在左侧工作区上传模板 DOCX，并在消息中说明编写要求。\n\n"
                "示例：「按模板生成标书，项目名称 XX，招标人 YY，工期 12 个月」"
            ),
            "mode": "action",
            "metadata": {
                "intent": "generate_document",
                "actions": [
                    {"type": "link", "label": "打开文档工作区", "url": "/chat", "primary": True},
                ],
            },
        }
    return {
        "answer": (
            "已收到生成请求。若左侧已上传模板，系统将使用 Aspose 引擎保持版式，"
            "并按您的编写要求填充占位符与 AI 章节。\n\n"
            "请确认左侧预览已更新；如需局部修改，可选中段落发送给我继续润色。"
        ),
        "mode": "action",
        "metadata": {
            "intent": "generate_document",
            "needs_workspace_generate": True,
            "requirements": text,
            "actions": [
                {"type": "link", "label": "查看文档预览", "url": "/chat", "primary": True},
            ],
        },
    }


async def _handle_edit_fragment(text: str, context: dict | None) -> dict[str, Any]:
    ctx = context or {}
    selected = ctx.get("selected_text") or ""
    if not selected:
        return {
            "answer": "请先在左侧文档中选中需要修改的文本，再发送修改指令（如「改为更正式的表述」）。",
            "mode": "action",
            "metadata": {
                "intent": "edit_fragment",
                "actions": [{"type": "link", "label": "打开文档工作区", "url": "/chat", "primary": True}],
            },
        }
    return {
        "answer": f"将对选中文本执行修改：\n「{selected[:120]}{'…' if len(selected) > 120 else ''}」\n\n正在调用 Aspose 引擎应用修订…",
        "mode": "action",
        "metadata": {
            "intent": "edit_fragment",
            "needs_workspace_edit": True,
            "instruction": text,
            "selected_text": selected,
            "paragraph_index": ctx.get("paragraph_index"),
        },
    }


async def _handle_open_workspace() -> dict[str, Any]:
    return {
        "answer": "已为您打开文档工作区。左侧可预览/编辑文档，右侧与我对话；支持上传模板、按格式生成标书、选中片段多轮修改。",
        "mode": "action",
        "metadata": {
            "intent": "open_workspace",
            "actions": [{"type": "link", "label": "进入工作区", "url": "/chat", "primary": True}],
        },
    }


async def _handle_edit_project(db: Session) -> dict[str, Any]:
    project = _latest_project(db)
    if not project:
        return {
            "answer": "当前没有进行中的标书项目。您可以先新建一份标书。",
            "mode": "action",
            "metadata": {
                "intent": "edit_project",
                "actions": [
                    {"type": "link", "label": "新建标书", "url": "/projects/new", "primary": True},
                ],
            },
        }
    step = project.current_step or 1
    return {
        "answer": (
            f"已找到最近编辑的标书「{project.title}」（当前第 {step} 步）。\n"
            "标书内容的精细调整（字段、AI 章节、资质、清单校验）请在六步向导中操作。"
        ),
        "mode": "action",
        "metadata": {
            "intent": "edit_project",
            "project_id": project.id,
            "actions": [
                {"type": "link", "label": "继续编辑标书", "url": f"/projects/{project.id}/step/{step}", "primary": True},
                {"type": "link", "label": "预览导出", "url": f"/projects/{project.id}/preview"},
            ],
        },
    }


async def _handle_draft_create(db: Session) -> dict[str, Any]:
    project = _latest_project(db)
    if not project:
        result = await _handle_create_project(db, "新建标书")
        project_id = result["metadata"]["project_id"]
        return {
            "answer": result["answer"] + "\n\n填写字段后，可在第 3 步使用 AI 生成章节初稿。",
            "mode": "action",
            "metadata": {
                "intent": "draft_create",
                "project_id": project_id,
                "actions": [
                    {"type": "link", "label": "填写字段", "url": f"/projects/{project_id}/step/2", "primary": True},
                    {"type": "link", "label": "AI 生成章节", "url": f"/projects/{project_id}/step/3"},
                ],
            },
        }
    return {
        "answer": (
            f"标书「{project.title}」可在向导第 3 步批量生成章节初稿。\n"
            "请确保第 2 步已填写项目名称、招标编号等关键字段，以获得更准确的 AI 输出。"
        ),
        "mode": "action",
        "metadata": {
            "intent": "draft_create",
            "project_id": project.id,
            "actions": [
                {"type": "link", "label": "前往 AI 生成", "url": f"/projects/{project.id}/step/3", "primary": True},
                {"type": "link", "label": "补充项目字段", "url": f"/projects/{project.id}/step/2"},
            ],
        },
    }


async def _handle_search_info(db: Session, text: str, history: list[dict], faq_items: list[dict]) -> dict[str, Any]:
    quals = db.query(Qualification).order_by(Qualification.sort_order.asc()).limit(30).all()
    qual_lines = [f"- {q.category}：{q.name}" for q in quals[:15]]
    fields = db.query(FieldDef).order_by(FieldDef.sort_order.asc()).limit(20).all()
    field_lines = [f"- {f.name}（{f.key}）" for f in fields[:10]]
    company = _company_context(db)

    context = (
        f"企业信息：\n{company}\n\n"
        f"资质摘录：\n" + ("\n".join(qual_lines) if qual_lines else "暂无") + "\n\n"
        f"常用字段：\n" + ("\n".join(field_lines) if field_lines else "暂无")
    )

    messages = [
        {"role": "system", "content": "你是企业投标信息检索助手。基于给定企业资料回答，无法确认时请说明需人工核实。"},
        *history[-6:],
        {"role": "user", "content": f"用户问题：{text}\n\n参考资料：\n{context}"},
    ]
    answer = await ai.chat_completion(messages, db=db)
    if not answer:
        faq_result = await ai.answer_faq(text, faq_items, db=db, history=history)
        return {
            "answer": faq_result.get("answer") or "",
            "mode": faq_result.get("mode") or "kb",
            "metadata": {
                "intent": "search_info",
                "actions": [
                    {"type": "link", "label": "查看资质库", "url": "/admin/qualifications"},
                    {"type": "link", "label": "企业档案", "url": "/admin/company"},
                ],
            },
        }

    return {
        "answer": answer.strip(),
        "mode": "ai",
        "metadata": {
            "intent": "search_info",
            "actions": [
                {"type": "link", "label": "查看资质库", "url": "/admin/qualifications"},
                {"type": "link", "label": "企业档案", "url": "/admin/company"},
            ],
        },
    }


async def process_chat_message(
    text: str,
    db: Session,
    history: list[dict] | None = None,
    faq_items: list[dict] | None = None,
    *,
    workspace: dict | None = None,
    context: dict | None = None,
) -> dict[str, Any]:
    intent = await _classify_intent(text, db=db)
    hist = history or []
    faqs = faq_items or []

    if intent == "generate_document":
        return await _handle_generate_document(db, text, workspace)
    if intent == "edit_fragment":
        return await _handle_edit_fragment(text, context)
    if intent == "open_workspace":
        return await _handle_open_workspace()
    if intent == "create_project":
        return await _handle_create_project(db, text)
    if intent == "create_template":
        return await _handle_create_template(db)
    if intent == "edit_project":
        return await _handle_edit_project(db)
    if intent == "draft_create":
        return await _handle_draft_create(db)
    if intent == "search_info":
        return await _handle_search_info(db, text, hist, faqs)

    faq_result = await ai.answer_faq(text, faqs, db=db, history=hist)
    return {
        "answer": faq_result.get("answer") or "",
        "mode": faq_result.get("mode") or "fallback",
        "source": faq_result.get("source") or "",
        "matched_question": faq_result.get("matched_question") or "",
        "metadata": {
            "intent": "general",
            "actions": [
                {"type": "link", "label": "文档工作区", "url": "/chat", "primary": True},
                {"type": "link", "label": "新建标书", "url": "/projects/new"},
            ],
        },
    }
