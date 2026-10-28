"""Chatbot 意图识别与任务路由。"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import CompanyProfile, FieldDef, Qualification, Template, TenderProject
from app.services import agent_flows, ai


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
        "url": "/chat",
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
        "id": "qual_folder_import",
        "title": "资质文件夹落库",
        "description": "指定本机文件夹，自动识别资质并写入企业档案",
        "icon": "📁",
        "url": "/chat",
        "intent": "import_qual_folder",
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
    "告诉我你是谁，你能干什么",
    "当前一共有多少个标书模板？",
    "最近一周创建了哪些标书？",
    "公司的全称是什么",
    "帮我写一份标书",
    "如何使用这个系统？",
    "联网查一下铁路投标保证金常见要求",
]

INTENT_PATTERNS: list[tuple[str, list[str], float]] = [
    ("web_search", [
        "联网", "网上查", "网上看看", "网上搜索", "搜索一下", "查一下最新",
        "公开资料", "查资料", "上网查", "中标公告",
    ], 2.0),
    ("generate_document", [
        "按模板生成", "根据模板写", "严格按模板", "生成一份标书", "生成全新标书",
        "模板文档", "编写要求", "照模板格式", "按格式生成",
    ], 1.0),
    ("compose_full_bid", [
        "完整标书", "各章节", "全部章节", "撰写正文", "生成完整", "完整投标",
        "投标函", "技术方案", "商务标", "整本标书", "填满各章",
    ], 1.05),
    ("edit_fragment", [
        "修改选中", "修改这段", "改写这段", "润色", "替换为", "把这段", "选中内容",
    ], 0.95),
    ("create_project", [
        "新建标书", "创建标书", "开始做标书", "写一份标书", "新建项目", "创建项目",
        "一份标书", "新标书", "做标书", "帮我写标书", "写标书",
    ], 0.9),
    ("create_template", [
        "创建模板", "做模板", "标书转模板", "转成模板", "占位符", "模板化", "工程化",
        "创建为模板", "建为模板", "做成模板", "作为模板", "变为模板", "生成模板",
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
    ("insert_table", [
        "插入表格", "添加表格", "画表格", "建表格", "表格插入",
    ], 0.88),
    ("insert_image", [
        "插入图片", "添加图片", "放入图片", "插图",
    ], 0.88),
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


# 这些回合不是在填标书，不能附上「待填基础信息」卡片或 compose 进度脚注。
_NON_BID_INTENTS = frozenset({
    "web_search",
    "general",
    "meta",
    "teach",
    "side_question",
    "search_info",
    "query_company",
    "query_template_stats",
    "list_templates",
    "query_recent_projects",
    "search_project",
    "search_template",
    "project_memo",
    "fallback",
    "import_qual_folder",
    "bulk_replace",
})


def should_attach_bid_intake_chrome(
    text: str,
    meta: dict | None,
    context: dict | None,
) -> bool:
    """只有标书填写类回合才附带待填卡片和模板进度脚注。"""
    ctx = context or {}
    if ctx.get("web_search") is True:
        return False
    data = meta or {}
    intent = str(data.get("intent") or "")
    if intent in _NON_BID_INTENTS:
        return False
    web = data.get("web_search")
    if isinstance(web, dict) and (web.get("query") or web.get("error") or web.get("searched")):
        return False
    if data.get("sources"):
        return False
    from app.services.web_search import should_search

    if should_search(text or "", ctx):
        return False
    return True


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


async def _handle_create_project(db: Session, text: str, session=None) -> dict[str, Any]:
    if session is not None:
        return await agent_flows.start_project_create(db, session)
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


async def _handle_create_template(db: Session, session=None) -> dict[str, Any]:
    if session is not None:
        return await agent_flows.start_template_create(db, session)
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
                {"type": "link", "label": "管理已有模板", "url": "/admin/templates", "primary": True},
            ],
        },
    }


def _asks_to_fill_bound_template(text: str) -> bool:
    q = text or ""
    if any(token in q for token in ("填入", "写入模板", "填到模板", "填入标书", "将这些信息")):
        return True
    if "文档工作区" in q and any(token in q for token in ("打开", "查阅", "填", "模板")):
        return True
    if any(token in q for token in ("按模板生成", "根据模板写", "开始编写", "开始写标书")):
        return True
    return False


async def _handle_compose_full_bid(
    db: Session,
    text: str,
    workspace: dict | None,
    session=None,
) -> dict[str, Any]:
    from app.services.bid_full_compose import respond_full_bid_compose

    project = _latest_bound_project(db, workspace or {}, {})
    if project is None or not project.template_id:
        return {
            "answer": "请先绑定铁路投标模板并保存项目基础信息，再让我生成完整标书各章节。",
            "mode": "action",
            "metadata": {"intent": "compose_full_bid"},
        }
    return await respond_full_bid_compose(db, project, session, text)


async def _handle_generate_document(
    db: Session,
    text: str,
    workspace: dict | None,
    session=None,
) -> dict[str, Any]:
    ws = workspace or {}
    project = _latest_bound_project(db, ws, {})
    if project is not None and project.template_id:
        from app.services.creation_draft import respond_creation_handoff

        return await respond_creation_handoff(db, project, session, text)
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


def _parse_table_shape(text: str) -> tuple[int, int]:
    m = re.search(r"(\d+)\s*[x×*]\s*(\d+)", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+)\s*行", text)
    rows = int(m.group(1)) if m else 3
    m = re.search(r"(\d+)\s*列", text)
    cols = int(m.group(1)) if m else 3
    return rows, cols


async def _handle_insert_table(text: str, context: dict | None, workspace: dict | None) -> dict[str, Any]:
    from app.services.agent_capabilities import ANCHOR_MISSING, anchor_can_insert, resolve_document_anchor

    ws = workspace or {}
    if not ws.get("draft_object_key") and not ws.get("template_object_key"):
        return {
            "answer": "请先在左侧打开标书草稿，再选中插入位置，并说明表格行列数，例如「在选中位置插入 4x3 表格」。",
            "mode": "action",
            "metadata": {"intent": "insert_table"},
        }
    anchor = resolve_document_anchor(context)
    if not anchor_can_insert(anchor):
        return {
            "answer": ANCHOR_MISSING,
            "mode": "action",
            "metadata": {"intent": "insert_table", "anchor_missing": True},
        }
    rows, cols = _parse_table_shape(text)
    return {
        "answer": f"将在选中位置（第 {anchor['paragraph_index']} 段）插入 {rows}×{cols} 表格…",
        "mode": "action",
        "metadata": {
            "intent": "insert_table",
            "needs_workspace_insert_table": True,
            "paragraph_index": anchor["paragraph_index"],
            "block_id": anchor.get("block_id") or "",
            "selected_text": anchor.get("selected_text") or "",
            "rows": rows,
            "cols": cols,
        },
    }


async def _handle_insert_image(text: str, context: dict | None, workspace: dict | None) -> dict[str, Any]:
    ws = workspace or {}
    if not ws.get("draft_object_key") and not ws.get("template_object_key"):
        return {
            "answer": "请先上传或生成标书 DOCX，再发送「插入图片」并附上 png/jpg 材料（📎）。",
            "mode": "action",
            "metadata": {"intent": "insert_image"},
        }
    from app.services.agent_capabilities import ANCHOR_MISSING, anchor_can_insert, resolve_document_anchor

    ctx = context or {}
    if not ctx.get("attachment_object_key") and not ctx.get("image_attachment_id"):
        return {
            "answer": "请先通过 📎 上传图片，或说明使用最近上传的图片附件，再发送「在光标处插入图片」。",
            "mode": "action",
            "metadata": {"intent": "insert_image"},
        }
    anchor = resolve_document_anchor(ctx)
    if not anchor_can_insert(anchor):
        return {
            "answer": ANCHOR_MISSING,
            "mode": "action",
            "metadata": {"intent": "insert_image", "anchor_missing": True},
        }
    return {
        "answer": f"正在将图片插入选中位置（第 {anchor['paragraph_index']} 段）…",
        "mode": "action",
        "metadata": {
            "intent": "insert_image",
            "needs_workspace_insert_image": True,
            "paragraph_index": anchor["paragraph_index"],
            "block_id": anchor.get("block_id") or "",
            "selected_text": anchor.get("selected_text") or "",
            "attachment_object_key": ctx.get("attachment_object_key"),
        },
    }


async def _handle_edit_fragment(text: str, context: dict | None) -> dict[str, Any]:
    from app.services.agent_capabilities import ANCHOR_MISSING, resolve_document_anchor

    anchor = resolve_document_anchor({**(context or {}), "instruction": text})
    if not anchor.get("ok"):
        return {
            "answer": ANCHOR_MISSING,
            "mode": "action",
            "metadata": {
                "intent": "edit_fragment",
                "anchor_missing": True,
                "actions": [{"type": "link", "label": "打开文档工作区", "url": "/chat", "primary": True}],
            },
        }
    selected = anchor.get("selected_text") or ""
    preview = selected[:120] + ("…" if len(selected) > 120 else "")
    where = f"「{preview}」" if selected else f"第 {anchor.get('paragraph_index')} 段"
    meta = {
        "intent": "edit_fragment",
        "needs_workspace_edit": True,
        "instruction": text,
        "selected_text": selected,
        "block_id": anchor.get("block_id") or "",
    }
    if anchor.get("paragraph_index") is not None:
        meta["paragraph_index"] = anchor["paragraph_index"]
    return {
        "answer": f"将对选中位置执行修改：{where}\n\n正在调用 Aspose 引擎应用修订…",
        "mode": "action",
        "metadata": meta,
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
    from app.services.project_sessions import agent_chat_path

    continue_url = agent_chat_path(project.id) if step >= 3 else f"/projects/{project.id}/step/{step}"
    return {
        "answer": (
            f"已找到最近编辑的标书「{project.title}」（当前第 {step} 步）。\n"
            "后续编写、审查和导出请在 Agent 对话中继续。"
            if step >= 3 else
            f"已找到最近编辑的标书「{project.title}」（当前第 {step} 步）。\n"
            "请先在向导中完成起点选择和信息录入。"
        ),
        "mode": "action",
        "metadata": {
            "intent": "edit_project",
            "project_id": project.id,
            "actions": [
                {
                    "type": "link",
                    "label": "继续编辑标书",
                    "url": continue_url,
                    "primary": True,
                },
                {"type": "link", "label": "预览导出", "url": f"/projects/{project.id}/preview"},
            ],
        },
    }


async def _handle_draft_create(db: Session) -> dict[str, Any]:
    from app.services.project_sessions import agent_chat_path

    project = _latest_project(db)
    if not project:
        result = await _handle_create_project(db, "新建标书")
        project_id = result["metadata"]["project_id"]
        return {
            "answer": result["answer"] + "\n\n填写字段后，在 Agent 对话中继续生成章节初稿。",
            "mode": "action",
            "metadata": {
                "intent": "draft_create",
                "project_id": project_id,
                "actions": [
                    {"type": "link", "label": "填写字段", "url": f"/projects/{project_id}/step/2", "primary": True},
                    {"type": "link", "label": "打开 Agent 对话", "url": agent_chat_path(project_id)},
                ],
            },
        }
    return {
        "answer": (
            f"标书「{project.title}」的章节初稿在 Agent 对话中生成。\n"
            "请确保已填写项目名称、招标编号等关键字段，以获得更准确的 AI 输出。"
        ),
        "mode": "action",
        "metadata": {
            "intent": "draft_create",
            "project_id": project.id,
            "actions": [
                {"type": "link", "label": "打开 Agent 对话", "url": agent_chat_path(project.id), "primary": True},
                {"type": "link", "label": "补充项目字段", "url": f"/projects/{project.id}/step/2"},
            ],
        },
    }


async def _handle_search_info(
    db: Session,
    text: str,
    history: list[dict],
    faq_items: list[dict],
    *,
    workspace: dict | None = None,
    context: dict | None = None,
) -> dict[str, Any]:
    quals = db.query(Qualification).order_by(Qualification.sort_order.asc()).limit(30).all()
    qual_lines = [f"- {q.category}：{q.name}" for q in quals[:15]]
    fields = db.query(FieldDef).order_by(FieldDef.sort_order.asc()).limit(20).all()
    field_lines = [f"- {f.name}（{f.key}）" for f in fields[:10]]
    company = _company_context(db)

    ref_block = (
        f"企业信息：\n{company}\n\n"
        f"资质摘录：\n" + ("\n".join(qual_lines) if qual_lines else "暂无") + "\n\n"
        f"常用字段：\n" + ("\n".join(field_lines) if field_lines else "暂无")
    )

    from app.services import agent_runtime

    messages = [
        {"role": "system", "content": "你是企业投标信息检索助手。基于给定企业资料回答，无法确认时请说明需人工核实。"},
        *history[-6:],
        {"role": "user", "content": f"用户问题：{text}\n\n参考资料：\n{ref_block}"},
    ]
    messages = agent_runtime.augment_messages(
        messages, db, workspace=workspace, context=context,
    )
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


_CANCEL_WORDS = ("取消", "算了", "不用了", "先不", "退出")

_META_PATTERNS: list[str] = [
    r"你是谁",
    r"你是什么",
    r"你是哪位",
    r"你能干什么",
    r"你能做什么",
    r"你有什么功能",
    r"你会什么",
    r"介绍一下你自己",
    r"自我介绍",
    r"怎么用",
    r"如何使用",
    r"能帮我什么",
    r"^你好[吗呀!！。?？]*$",
    r"^hi$",
    r"^hello$",
    r"^help$",
]


def _is_meta_question(text: str) -> bool:
    q = text.strip().lower()
    if not q:
        return False
    return any(re.search(p, q, re.IGNORECASE) for p in _META_PATTERNS)


async def _handle_meta_question() -> dict[str, Any]:
    return {
        "answer": (
            "我是**标书智能体助手**，面向铁路、轨道交通等行业的投标文书编写。\n\n"
            "我可以帮你：\n"
            "1. **新建标书**：从模板或历史标书开始，走六步向导完成字段、AI 章节、资质与导出\n"
            "2. **文档 Agent**：上传模板 + 编写要求，按版式生成或修订标书\n"
            "3. **企业问答**：查询资质、业绩、人员等投标资料（基于企业档案与 FAQ）\n"
            "4. **模板工程化**：把完整标书转为可复用占位符模板\n"
            "5. **资质文件夹落库**：提供本机资质目录路径，扫描 pdf/docx/图片并写入资质库与企业档案（**务必人工核对**）\n"
            "6. **联网查资料**：说「联网查一下…」或打开输入框的「联网」，我会检索公开网页并附上标题和链接；离线时会说明，并改用本地企业/项目资料\n\n"
            "你可以直接说「帮我写一份标书」「联网查一下铁路投标保证金常见要求」或打开「文档工作区」上传 DOCX。"
        ),
        "mode": "meta",
        "metadata": {
            "intent": "meta",
            "actions": [
                {"type": "link", "label": "文档工作区", "url": "/chat", "primary": True},
                {"type": "link", "label": "新建标书", "url": "/projects/new"},
            ],
        },
    }


async def _handle_general_conversation(
    text: str,
    db: Session,
    history: list[dict] | None,
    faq_items: list[dict] | None,
    *,
    workspace: dict | None = None,
    context: dict | None = None,
    stream: bool = False,
    session=None,
    on_token=None,
    on_tool=None,
) -> dict[str, Any]:
    from app.services import agent_runtime

    messages = agent_runtime.build_general_messages(
        text,
        faq_items or [],
        history,
        db,
        workspace=workspace,
        context=context,
    )
    if session is not None:
        from app.services import agent_tool_loop

        try:
            loop_result = await agent_tool_loop.run_tool_loop(
                db=db,
                session=session,
                messages=messages,
                workspace=workspace,
                context=context,
                on_token=on_token,
                on_tool=on_tool,
            )
            if loop_result and (loop_result.get("answer") or "").strip():
                meta = {
                    "intent": "general",
                    "tool_loop": True,
                    "actions": [
                        {"type": "link", "label": "文档工作区", "url": "/chat", "primary": True},
                    ],
                }
                extra = loop_result.get("metadata") or {}
                meta.update(extra)
                return {
                    "answer": loop_result["answer"].strip(),
                    "mode": "web_search" if extra.get("sources") else "ai",
                    "metadata": meta,
                }
        except Exception:
            if stream or on_token:
                raise
    meta = {
        "intent": "general",
        "actions": [
            {"type": "link", "label": "文档工作区", "url": "/chat", "primary": True},
            {"type": "link", "label": "新建标书", "url": "/projects/new"},
        ],
    }
    if stream:
        return {"stream_messages": messages, "mode": "ai", "metadata": meta}
    answer = await ai.chat_completion(messages, db=db)
    if not answer:
        return {
            "answer": "暂未匹配到明确答案。可以补充项目信息，或在文档工作区继续。",
            "mode": "fallback",
            "metadata": meta,
        }
    return {"answer": answer.strip(), "mode": "ai", "metadata": meta}


async def _answer_readonly_side_question(
    text: str,
    db: Session,
    history: list[dict] | None,
    faq_items: list[dict] | None,
    *,
    workspace: dict | None,
    context: dict | None,
    session,
) -> dict[str, Any]:
    """流程卡片还在时回答只读问题，不清除 pending_action。"""
    from app.services.agent_capabilities import progress_reply
    from app.services.web_search import explicit_fetch_url, run_web_research, should_search

    q = (text or "").strip()
    meta = {"intent": "side_question", "readonly": True, "flow_continued": True}
    if re.search(r"(进度|到哪了|进行到哪|现在哪一步|流程到哪)", q):
        project = _latest_bound_project(db, workspace, context)
        return {
            "answer": progress_reply(getattr(session, "workspace", None) or workspace, project),
            "mode": "action",
            "metadata": meta,
        }
    if should_search(q, context) or explicit_fetch_url(q):
        found = await run_web_research(q, db, history, workspace=workspace, context=context)
        found_meta = dict(found.get("metadata") or {})
        found_meta.update(meta)
        found["metadata"] = found_meta
        return found
    if re.search(r"(读(一下)?文件|看看文件|打开文件|文件内容)", q):
        path = ""
        ctx = context or {}
        path = str(ctx.get("workspace_file") or ctx.get("selected_workspace_file") or "").strip()
        matched = re.search(r"([^\s「」\"'，。；]+\.[A-Za-z0-9]{1,8})", q)
        if matched:
            path = matched.group(1).replace("\\", "/")
        if not path:
            return {"answer": "请说明要读的相对路径，例如「读一下 技术方案.txt」。", "mode": "action", "metadata": meta}
        try:
            from app.services import agent_tools

            data = agent_tools.read_workspace_file(db, session, path)
        except Exception as exc:
            return {"answer": f"没有读到该文件：{exc}", "mode": "action", "metadata": meta}
        content = data.get("content") or ""
        if data.get("binary"):
            content = f"（二进制文件，{data.get('size_bytes') or 0} 字节）"
        return {
            "answer": f"已读取 `{data.get('path') or path}`：\n\n{(content or '文件为空')[:2000]}",
            "mode": "action",
            "metadata": {**meta, "tool_trace": [{"tool": "read_workspace_file", "ok": True}]},
        }
    if re.search(r"(预览状态|预览好了)", q):
        from app.services.agent_tool_loop import _execute_tool

        status = await _execute_tool(db, session, "get_preview_status", {}, default_project_id=None, context=context)
        oo = status.get("onlyoffice") or {}
        return {
            "answer": (
                f"预览状态：{'已有文档' if status.get('has_document') else '还没有文档'}，"
                f"版本 v{status.get('version') or 0}。"
                f"OnlyOffice：{oo.get('message') or '未连接'}。"
            ),
            "mode": "action",
            "metadata": {**meta, "tool_trace": [{"tool": "get_preview_status", "ok": True}], "preview_status": status},
        }

    return {
        "answer": _lookup_readonly_facts(db, q, workspace, context),
        "mode": "query",
        "metadata": meta,
    }


def _lookup_readonly_facts(db: Session | None, question: str, workspace: dict | None, context: dict | None) -> str:
    """按问题去查人员、资质、业绩或企业档案，而不是一律回公司全称。"""
    from app.services.agent_query_tools import get_company_summary

    q = question or ""
    summary = get_company_summary(db) if db is not None else {"found": False}
    quals = []
    if db is not None:
        quals = db.query(Qualification).order_by(Qualification.sort_order.asc()).all()
    project = _latest_bound_project(db, workspace, context) if db is not None else None
    if re.search(r"人员|项目经理|建造师|法定代表人", q):
        people = [
            item for item in quals
            if re.search(r"人员|项目经理|建造师|岗位", f"{item.category} {item.name} {item.keywords}")
        ]
        lines = []
        if summary.get("legal_name"):
            lines.append(f"法定代表人：{summary.get('legal_name')}")
        manager = ""
        if project is not None:
            manager = str((project.fields or {}).get("project_manager") or "")
        if manager:
            lines.append(f"项目经理：{manager}")
        for item in people[:12]:
            lines.append(f"{item.category}：{item.name}")
        if lines:
            return "人员查询结果：\n" + "\n".join(f"- {line}" for line in lines)
        return "资质库里还没有人员记录。可以到数据管理补充项目经理、建造师等人员资质。"
    if re.search(r"资质|证书", q):
        if quals:
            return "资质查询结果：\n" + "\n".join(f"- {item.category}：{item.name}" for item in quals[:12])
        return "资质库还是空的。"
    if re.search(r"业绩|项目", q) and summary.get("typical_projects"):
        return f"业绩：{summary.get('typical_projects')}"
    if summary.get("found"):
        bits = [f"公司全称：{summary.get('full_name') or '未填写'}"]
        if summary.get("legal_name"):
            bits.append(f"法定代表人：{summary.get('legal_name')}")
        if summary.get("qual_overview"):
            bits.append(f"资质概况：{summary.get('qual_overview')}")
        return "\n".join(bits)
    return "系统中尚未录入企业档案。"


def _latest_bound_project(db: Session, workspace: dict | None, context: dict | None):
    from app.services.agent_capabilities import bound_project

    if db is None:
        return None
    return bound_project(db, workspace, context)


def _capability_loop_intent(text: str, context: dict | None) -> str | None:
    ctx = context or {}
    if ctx.get("web_search"):
        return "web_search"
    from app.services.web_search import explicit_fetch_url, should_search

    if should_search(text, ctx) or explicit_fetch_url(text):
        return "web_search"
    if re.search(r"对照招标|符合招标|偏离招标|检查招标|对照一下招标", text or ""):
        return "check_tender"
    intent, score = _score_intent(text or "")
    if intent in ("edit_fragment", "insert_table", "insert_image", "web_search") and score >= 0.45:
        return intent
    return None


async def _run_capability_tool_loop(
    text: str,
    db: Session,
    history: list[dict] | None,
    faq_items: list[dict] | None,
    *,
    workspace: dict | None,
    context: dict | None,
    session,
    on_token=None,
    on_tool=None,
) -> dict[str, Any] | None:
    """改写、插表、插图、招标对照、联网都先进入工具环，而不是只在自由对话里进。"""
    intent = _capability_loop_intent(text, context)
    if not intent or session is None:
        return None
    force = {
        "edit_fragment": "edit_document_anchor",
        "insert_table": "insert_table",
        "insert_image": "insert_image",
        "web_search": "web_search",
        "check_tender": "check_against_tender",
    }[intent]
    from app.services import agent_runtime, agent_tool_loop

    ctx = dict(context or {})
    ctx["instruction"] = text
    if intent == "insert_table":
        rows, cols = _parse_table_shape(text)
        ctx["rows"] = rows
        ctx["cols"] = cols
    messages = agent_runtime.build_general_messages(
        text, faq_items or [], history, db, workspace=workspace, context=ctx,
    )
    hint = f"当前要完成的动作是 {intent}。请调用工具 {force}，不要只口头答应。"
    if messages and messages[0].get("role") == "system":
        messages[0] = {"role": "system", "content": (messages[0].get("content") or "") + "\n\n" + hint}
    result = await agent_tool_loop.run_tool_loop(
        db=db,
        session=session,
        messages=messages,
        workspace=workspace,
        context=ctx,
        on_token=on_token,
        on_tool=on_tool,
        force_tool=force,
    )
    if not result or not (result.get("answer") or "").strip():
        return None
    trace = (result.get("metadata") or {}).get("tool_trace") or []
    if not any(item.get("tool") == force for item in trace):
        return None
    meta = {"intent": intent, "tool_loop": True}
    meta.update(result.get("metadata") or {})
    return {"answer": result["answer"].strip(), "mode": "ai", "metadata": meta}


def _open_session_docx(session) -> bytes | None:
    if session is None:
        return None
    ws = getattr(session, "workspace", None) or {}
    key = ws.get("draft_object_key") or ws.get("template_object_key")
    if not key:
        return None
    try:
        from app.services import storage

        return storage.download_bytes(key)
    except Exception:
        return None


def _store_fixed_docx(db: Session, session, fixed: dict) -> None:
    blob = fixed.pop("docx_bytes", None)
    if not isinstance(blob, (bytes, bytearray)) or session is None:
        fixed.pop("docx_bytes", None)
        return
    try:
        from datetime import datetime

        from app.services import storage

        key = f"chat/{session.id}/{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_review.docx"
        storage.upload_bytes(
            key, bytes(blob),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        ws = dict(getattr(session, "workspace", None) or {})
        ws["draft_object_key"] = key
        ws["version"] = int(ws.get("version") or 0) + 1
        session.workspace = ws
    except Exception:
        return


async def process_chat_message(
    text: str,
    db: Session,
    history: list[dict] | None = None,
    faq_items: list[dict] | None = None,
    *,
    workspace: dict | None = None,
    context: dict | None = None,
    session=None,
    stream: bool = False,
    on_token=None,
    on_tool=None,
) -> dict[str, Any]:
    from app.services.agent_capabilities import (
        bound_project,
        extract_decision,
        fix_review_issue,
        memo_prompt_block,
        mutating_flow_reply,
        progress_reply,
        remember_decision,
        side_question_kind,
        unresolved_issues,
        wants_single_issue_fix,
    )

    project = bound_project(db, workspace, context) if db is not None else None
    memo = None
    if project is not None and extract_decision(text):
        memo = remember_decision(project, text)
        if memo is not None:
            db.commit()

    if wants_single_issue_fix(text) and project is not None:
        review = (project.checklist_result or {}).get("doc_review") or {}
        issue_id = str((context or {}).get("review_issue_id") or "").strip()
        if not issue_id:
            open_issues = unresolved_issues(review)
            if len(open_issues) == 1:
                issue_id = str(open_issues[0].get("id") or "")
            elif len(open_issues) > 1:
                return {
                    "answer": "有多条审查问题。请点选其中一条，或在消息里带上要改的那一条。",
                    "mode": "action",
                    "metadata": {"intent": "fix_review_issue", "review_issues": open_issues},
                }
        if issue_id:
            fixed = await fix_review_issue(
                project, issue_id, docx_bytes=_open_session_docx(session), db=db,
            )
            _store_fixed_docx(db, session, fixed)
            db.commit()
            if session is not None and fixed.get("highlight_texts") is not None:
                ws_fix = dict(getattr(session, "workspace", None) or {})
                if fixed["highlight_texts"]:
                    ws_fix["review_highlight_texts"] = fixed["highlight_texts"]
                else:
                    ws_fix.pop("review_highlight_texts", None)
                session.workspace = ws_fix
                db.commit()
            return {
                "answer": fixed.get("answer") or fixed.get("error") or "未能修改这一条。",
                "mode": "action",
                "metadata": {
                    "intent": "fix_review_issue",
                    "review_issue_id": issue_id,
                    "highlight_texts": fixed.get("highlight_texts") or [],
                    "rereview": fixed.get("rereview"),
                    "workspace_updated": True,
                },
            }

    raw_decision = (text or "").strip()
    decision_text = extract_decision(text)
    decision_only = bool(
        memo is not None
        and decision_text
        and (raw_decision[:240] == decision_text or raw_decision.startswith(("记住", "决定", "备忘")))
    )
    if decision_only:
        kept = ""
        if session is not None and isinstance((workspace or {}).get("pending_action"), dict):
            kept = "当前卡片流程仍在进行，只读问题可以继续问。"
        return {
            "answer": f"已写入项目备忘：{memo['text']}\n\n{memo_prompt_block(project.fields) if project else ''}\n{kept}".strip(),
            "mode": "action",
            "metadata": {"intent": "project_memo", "memo": memo, "project_id": project.id if project else None},
        }

    if session is not None and (workspace or {}).get("project_id"):
        from app.services.project_export_flow import try_handle_export_flow

        export_hit = await try_handle_export_flow(
            text, db, session, workspace,
        )
        if export_hit is not None:
            return export_hit

    # 流程进行中：取消和修订仍优先；只读旁路可以回答，破坏流程的写操作要确认或取消。
    if session is not None:
        pa = (workspace or {}).get("pending_action")
        if isinstance(pa, dict) and pa.get("flow"):
            if any(w in text for w in _CANCEL_WORDS):
                return agent_flows.cancel_flow(db, session)
            kind = side_question_kind(text, context)
            if kind == "readonly":
                return await _answer_readonly_side_question(
                    text, db, history, faq_items, workspace=workspace, context=context, session=session,
                )
            if kind == "mutating":
                return {
                    "answer": mutating_flow_reply(),
                    "mode": "action",
                    "metadata": {"intent": "flow_pending", "blocked_write": True},
                }
            if pa.get("stage") == "revise_document":
                if any(w in text for w in ("完成", "结束修订", "好了", "可以了")):
                    return agent_flows.finish_revision(db, session)
                if text.strip():
                    return await agent_flows.handle_revision_text(db, session, text.strip())
            hint = agent_flows.pending_hint(session)
            if hint:
                return hint

    if project is not None and project.template_id and _asks_to_fill_bound_template(text):
        from app.services.creation_draft import respond_creation_handoff

        return await respond_creation_handoff(db, project, session, text)

    from app.services.agent_qual_folder import detect_local_folder_import

    folder_path, folder_score = detect_local_folder_import(text)
    if folder_path and folder_score >= 0.85 and session is not None:
        return await agent_flows.start_qual_folder_import(db, session, folder_path)

    looped = await _run_capability_tool_loop(
        text, db, history, faq_items,
        workspace=workspace, context=context, session=session,
        on_token=on_token, on_tool=on_tool,
    )
    if looped is not None:
        return looped

    from app.services.web_search import explicit_fetch_url, run_web_research, should_search

    if should_search(text, context) or explicit_fetch_url(text):
        return await run_web_research(
            text,
            db,
            history,
            workspace=workspace,
            context=context,
        )

    from app.services import agent_semantic

    semantic_result = await agent_semantic.process_with_semantic_router(
        text,
        db,
        history,
        faq_items,
        workspace=workspace,
        context=context,
        session=session,
    )
    if semantic_result is not None:
        return semantic_result

    if _is_meta_question(text):
        return await _handle_meta_question()

    intent = await _classify_intent(text, db=db)
    hist = history or []
    faqs = faq_items or []

    if intent == "compose_full_bid":
        return await _handle_compose_full_bid(db, text, workspace, session=session)
    if intent == "generate_document":
        return await _handle_generate_document(db, text, workspace, session=session)
    if intent == "edit_fragment":
        return await _handle_edit_fragment(text, context)
    if intent == "insert_table":
        return await _handle_insert_table(text, context, workspace)
    if intent == "insert_image":
        return await _handle_insert_image(text, context, workspace)
    if intent == "open_workspace":
        return await _handle_open_workspace()
    if intent == "create_project":
        return await _handle_create_project(db, text, session=session)
    if intent == "create_template":
        return await _handle_create_template(db, session=session)
    if intent == "edit_project":
        return await _handle_edit_project(db)
    if intent == "draft_create":
        return await _handle_draft_create(db)
    if intent == "web_search":
        from app.services.web_search import run_web_research

        return await run_web_research(
            text, db, hist, workspace=workspace, context=context,
        )
    if intent == "search_info":
        return await _handle_search_info(
            db, text, hist, faqs, workspace=workspace, context=context,
        )

    return await _handle_general_conversation(
        text,
        db,
        hist,
        faqs,
        workspace=workspace,
        context=context,
        stream=stream,
        session=session,
        on_token=on_token,
        on_tool=on_tool,
    )
