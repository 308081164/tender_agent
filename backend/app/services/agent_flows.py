"""Agent 中台流程编排：多轮状态机 + 卡片协议。

流程通过 ChatSession.workspace["pending_action"] 持久化：
- template_create.confirm_mapping：等待用户确认占位符映射
- project_create.select_template：等待用户点选模板
- project_create.collect_fields：等待用户填写关键字段

卡片协议（assistant 消息 metadata.cards）：
- template_picker / mapping_confirm / field_collect / template_info / project_info / confirm
- 每张卡有 id、type、title、state（active|confirmed|cancelled|done）、payload
- 前端通过 POST /chat/sessions/{id}/actions 回调推进流程
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import ChatSession, CompanyProfile
from app.services import agent_tools, document_agent, storage

FLOW_TEMPLATE_CREATE = "template_create"
FLOW_PROJECT_CREATE = "project_create"


def _template_supports_compose(db: Session, template_id: int) -> bool:
    from app.models import Template
    from app.services.doc_engine.manifest import get_manifest

    tpl = db.query(Template).filter(Template.id == template_id).first()
    if not tpl:
        return False
    manifest = get_manifest(tpl.placeholders or {})
    if not manifest:
        return False
    blocks = manifest.get("blocks") or []
    return any(b.get("type") in ("ai_section", "table_slot") for b in blocks)


def _card_id() -> str:
    return uuid.uuid4().hex[:12]


def _pending(session: ChatSession) -> dict[str, Any] | None:
    ws = getattr(session, "workspace", None) or {}
    pa = ws.get("pending_action")
    return pa if isinstance(pa, dict) and pa.get("flow") else None


def _set_pending(session: ChatSession, pending: dict[str, Any] | None) -> None:
    ws = dict(getattr(session, "workspace", None) or {})
    if pending:
        ws["pending_action"] = pending
    else:
        ws.pop("pending_action", None)
    session.workspace = ws


def _update_workspace(session: ChatSession, **changes: Any) -> None:
    ws = dict(getattr(session, "workspace", None) or {})
    ws.update(changes)
    session.workspace = ws


def _company_context(db: Session) -> str:
    c = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
    if not c:
        return ""
    return "\n".join(p for p in [c.full_name, c.intro, c.qual_overview] if p)


def _result(answer: str, cards: list[dict] | None = None,
            actions: list[dict] | None = None, **meta: Any) -> dict[str, Any]:
    metadata: dict[str, Any] = {"actions": actions or [], **meta}
    if cards:
        metadata["cards"] = cards
    return {"answer": answer, "mode": "action", "metadata": metadata}


# ---------------------------------------------------------------- 流程入口

async def start_template_create(db: Session, session: ChatSession) -> dict[str, Any]:
    """上传 DOCX 后启动模板创建：建草稿 + LLM 识别 + 映射确认卡。"""
    ws = getattr(session, "workspace", None) or {}
    if not (ws.get("template_object_key") or ws.get("draft_object_key")):
        return _result(
            "请先在左侧工作区上传一份完整的标书 DOCX，我将为您识别可复用字段并创建模板。",
            actions=[{"type": "link", "label": "打开文档工作区", "url": "/chat", "primary": True}],
            intent="create_template",
        )
    template = agent_tools.create_template_from_workspace(db, session.workspace)
    detection = await agent_tools.detect_template_placeholders(db, template.id)
    candidates = detection.get("candidates") or []
    existing = detection.get("existing_placeholders") or []

    if not candidates and not existing:
        agent_tools.discard_template_draft(db, template.id)
        return _result(
            "已分析文档，但未识别到适合模板化的字段。"
            "您可以在「数据管理 → 模板」中手动工程化，或换一份包含项目名称、招标人、金额等字段的标书重试。",
            actions=[{"type": "link", "label": "前往模板管理", "url": "/admin/templates", "primary": True}],
            intent="create_template",
        )

    mappings = [
        {
            "key": c.get("key"),
            "field_name": c.get("field_name") or c.get("key"),
            "original_text": c.get("original_text"),
            "confidence": c.get("confidence") or 0.6,
            "reason": c.get("reason") or "",
            "approved": float(c.get("confidence") or 0) >= 0.5,
        }
        for c in candidates
    ]
    _set_pending(session, {
        "flow": FLOW_TEMPLATE_CREATE,
        "stage": "confirm_mapping",
        "template_id": template.id,
    })
    return _result(
        f"已基于「{template.name}」创建模板草稿，AI 识别出 {len(mappings)} 个可模板化字段"
        + (f"（文档已有 {len(existing)} 个占位符）。" if existing else "。")
        + "\n请确认下方映射：取消勾选不需要的项，确认后我将生成正式模板。",
        cards=[{
            "id": _card_id(),
            "type": "mapping_confirm",
            "title": "确认占位符映射",
            "state": "active",
            "payload": {
                "template_id": template.id,
                "template_name": template.name,
                "mappings": mappings,
                "existing_placeholders": existing,
                "confirm_action": "confirm_mapping",
                "cancel_action": "cancel_flow",
            },
        }],
        intent="create_template",
    )


async def start_project_create(db: Session, session: ChatSession) -> dict[str, Any]:
    """编写标书入口：返回模板筛选卡。"""
    templates = agent_tools.list_selectable_templates(db)
    if not templates:
        return _result(
            "当前还没有可用的工程化模板。您可以先上传一份完整标书，我会帮您创建模板；"
            "或前往「数据管理 → 模板」手动上传。",
            cards=[{
                "id": _card_id(),
                "type": "confirm",
                "title": "先创建模板？",
                "state": "active",
                "payload": {
                    "message": "上传一份完整标书 DOCX，我将自动识别字段并创建可复用模板。",
                    "confirm_label": "上传并创建模板",
                    "cancel_label": "暂不",
                    "confirm_action": "goto_upload",
                    "cancel_action": "cancel_flow",
                },
            }],
            actions=[{"type": "link", "label": "手动管理模板", "url": "/admin/templates"}],
            intent="create_project",
        )
    _set_pending(session, {"flow": FLOW_PROJECT_CREATE, "stage": "select_template"})
    return _result(
        f"好的，请先选择标书模板（共 {len(templates)} 个可用）。选择后我会收集关键信息并生成初稿。",
        cards=[{
            "id": _card_id(),
            "type": "template_picker",
            "title": "选择标书模板",
            "state": "active",
            "payload": {
                "templates": templates,
                "select_action": "select_template",
                "cancel_action": "cancel_flow",
            },
        }],
        intent="create_project",
    )


def pending_hint(session: ChatSession) -> dict[str, Any] | None:
    """流程进行中用户发来普通消息时的引导。"""
    pa = _pending(session)
    if not pa:
        return None
    hints = {
        (FLOW_TEMPLATE_CREATE, "confirm_mapping"): "模板创建进行中：请在上方卡片确认占位符映射，或发送「取消」退出。",
        (FLOW_PROJECT_CREATE, "select_template"): "编写标书进行中：请在上方卡片选择模板，或发送「取消」退出。",
        (FLOW_PROJECT_CREATE, "collect_fields"): "编写标书进行中：请在上方卡片填写关键信息并确认，或发送「取消」退出。",
        (FLOW_PROJECT_CREATE, "collect_requirements"): "编写标书进行中：请补充编写要求后确认生成，或发送「取消」退出。",
        (FLOW_PROJECT_CREATE, "revise_document"): "标书已生成：可在上方卡片提交修订指令，或发送「完成」结束。",
    }
    text = hints.get((pa.get("flow"), pa.get("stage")), "当前有进行中的任务，请使用上方卡片继续，或发送「取消」退出。")
    return _result(text, intent="flow_pending")


def cancel_flow(db: Session, session: ChatSession) -> dict[str, Any]:
    pa = _pending(session)
    if pa and pa.get("flow") == FLOW_TEMPLATE_CREATE and pa.get("template_id"):
        agent_tools.discard_template_draft(db, int(pa["template_id"]))
    _set_pending(session, None)
    return _result("已取消当前任务。您可以随时上传文档创建模板，或告诉我「帮我写标书」重新开始。", intent="cancel")


# ---------------------------------------------------------------- 动作回调

async def handle_action(
    db: Session,
    session: ChatSession,
    action: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """卡片按钮回调入口。返回 (user_label, assistant_result, workspace_updated)。"""
    pa = _pending(session)

    if action == "cancel_flow":
        return "取消", cancel_flow(db, session), False

    if action == "dismiss_card":
        return "仅作为文档使用", _result(
            "好的，该文档仅作为当前工作区文档使用。您可以说明编写要求生成标书，或选中段落让我修改。",
            intent="dismiss",
        ), False

    if action == "goto_upload":
        return "上传并创建模板", _result(
            "请点击左侧工作区的上传按钮选择标书 DOCX，上传完成后我会询问是否创建模板。",
            intent="goto_upload",
        ), False

    if action == "start_template_create":
        result = await start_template_create(db, session)
        return "将此文档创建为模板", result, True

    if action == "select_template":
        return await _on_select_template(db, session, pa, payload)

    if action == "confirm_fields":
        return await _on_confirm_fields(db, session, pa, payload)

    if action == "confirm_requirements":
        return await _on_confirm_requirements(db, session, pa, payload)

    if action == "submit_revision":
        return await _on_submit_revision(db, session, pa, payload)

    if action == "finish_revision":
        return await _on_finish_revision(db, session, pa)

    if action == "confirm_mapping":
        return await _on_confirm_mapping(db, session, pa, payload)

    return "", _result("未知操作，请重试。", intent="error"), False


async def _on_select_template(
    db: Session, session: ChatSession, pa: dict | None, payload: dict
) -> tuple[str, dict, bool]:
    if not pa or pa.get("flow") != FLOW_PROJECT_CREATE:
        return "", _result("该选择已失效，请重新告诉我「帮我写标书」。", intent="error"), False
    template_id = int(payload.get("template_id") or 0)
    chosen = next(
        (t for t in agent_tools.list_selectable_templates(db) if t["id"] == template_id),
        None,
    )
    if not chosen:
        return "", _result("所选模板不可用，请重新选择。", intent="error"), False

    fields = agent_tools.required_fields_for_template(db)
    _set_pending(session, {
        "flow": FLOW_PROJECT_CREATE,
        "stage": "collect_fields",
        "template_id": template_id,
        "template_name": chosen["name"],
    })
    return f"选择模板「{chosen['name']}」", _result(
        f"已选择模板「{chosen['name']}」。请补充以下关键信息（带 * 必填），确认后我将生成标书初稿。",
        cards=[{
            "id": _card_id(),
            "type": "field_collect",
            "title": "填写关键信息",
            "state": "active",
            "payload": {
                "template_id": template_id,
                "template_name": chosen["name"],
                "fields": fields,
                "confirm_action": "confirm_fields",
                "cancel_action": "cancel_flow",
            },
        }],
        intent="create_project",
    ), False


async def _on_confirm_fields(
    db: Session, session: ChatSession, pa: dict | None, payload: dict
) -> tuple[str, dict, bool]:
    if not pa or pa.get("flow") != FLOW_PROJECT_CREATE or pa.get("stage") != "collect_fields":
        return "", _result("该表单已失效，请重新告诉我「帮我写标书」。", intent="error"), False
    template_id = int(pa.get("template_id") or 0)
    fields = {str(k): str(v) for k, v in (payload.get("fields") or {}).items() if str(v).strip()}
    if not fields.get("project_name"):
        return "", _result("项目名称不能为空，请补充后再次确认。", intent="error"), False

    project = agent_tools.create_project_with_template(
        db, template_id, fields.get("project_name", ""), fields
    )

    if _template_supports_compose(db, template_id):
        _set_pending(session, {
            "flow": FLOW_PROJECT_CREATE,
            "stage": "collect_requirements",
            "template_id": template_id,
            "template_name": pa.get("template_name") or "",
            "project_id": project.id,
            "fields": fields,
        })
        return "确认关键信息", _result(
            f"标书「{project.title}」已创建。该模板支持智能创作，请补充编写要求（章节重点、风格、约束等），我将分块生成并审阅。",
            cards=[{
                "id": _card_id(),
                "type": "requirements_collect",
                "title": "编写要求",
                "state": "active",
                "payload": {
                    "project_id": project.id,
                    "template_name": pa.get("template_name") or "",
                    "confirm_action": "confirm_requirements",
                    "cancel_action": "cancel_flow",
                    "placeholder": "例如：突出铁路信号系统维保经验；技术方案强调夜间作业安全；报价说明需与清单一致…",
                },
            }],
            intent="create_project",
            project_id=project.id,
        ), False

    _set_pending(session, None)
    ws_note, workspace_updated, review_summary = await _generate_project_draft(
        db, session, project, template_id, fields, requirements="；".join(f"{k}={v}" for k, v in fields.items()),
    )
    return "确认并生成标书", _result(
        f"标书「{project.title}」已创建。{ws_note}".strip(),
        cards=[{
            "id": _card_id(),
            "type": "project_info",
            "title": "标书已创建",
            "state": "done",
            "payload": {
                "project_id": project.id,
                "title": project.title,
                "template_name": pa.get("template_name") or "",
                "field_count": len(fields),
                "review_summary": review_summary,
            },
        }],
        actions=[
            {"type": "link", "label": "进入向导精细完善", "url": f"/projects/{project.id}/step/3", "primary": True},
            {"type": "link", "label": "预览与导出", "url": f"/projects/{project.id}/step/6"},
        ],
        intent="create_project",
        project_id=project.id,
        workspace_updated=workspace_updated,
    ), workspace_updated


async def _generate_project_draft(
    db: Session,
    session: ChatSession,
    project,
    template_id: int,
    fields: dict[str, str],
    requirements: str,
) -> tuple[str, bool, dict | None]:
    """生成初稿并可选执行 compose + 审阅摘要。"""
    from app.models import Template

    ws_note = ""
    workspace_updated = False
    review_summary = None
    tpl = db.query(Template).filter(Template.id == template_id).first()
    if not tpl or not tpl.object_key:
        return ws_note, workspace_updated, review_summary
    try:
        doc_bytes = storage.download_bytes(tpl.object_key)
        if _template_supports_compose(db, template_id) and requirements.strip():
            from app.models import TenderProject
            from app.services.doc_engine.composition import build_composition_plan, generate_block_contents
            from app.services.doc_engine.engine import render_project_document, review_project_document
            from app.services.doc_engine.manifest import get_manifest
            from app.services.doc_engine.parser import parse_template_manifest

            p = db.query(TenderProject).filter(TenderProject.id == project.id).first()
            manifest = get_manifest(tpl.placeholders) or parse_template_manifest(doc_bytes)
            plan = await build_composition_plan(
                manifest, fields, requirements, _company_context(db), db=db,
            )
            contents, table_rows = await generate_block_contents(
                plan, fields, requirements, _company_context(db), db=db,
            )
            chapters = dict(p.chapters or {})
            for k, v in contents.items():
                if k and v and not k.startswith("field.") and not k.startswith("ai."):
                    chapters[k] = {"content": v, "source": "ai", "engine": "doc_engine_v2"}
            p.chapters = chapters
            fields = dict(fields)
            fields["_writing_requirements"] = requirements
            for bind, rows in (table_rows or {}).items():
                fields[bind] = rows
            p.fields = fields
            db.commit()
            new_bytes, gen_meta = await render_project_document(
                doc_bytes,
                tpl.placeholders,
                fields,
                chapters,
                requirements=requirements,
                company_context=_company_context(db),
                db=db,
                mode=manifest.get("mode") or "create",
            )
            review = await review_project_document(
                new_bytes, tpl.placeholders, fields, None,
                ["project_name", "tenderer"], db=db,
            )
            review_summary = {
                "status": review.get("status"),
                "can_export": review.get("can_export"),
                "issue_count": len(review.get("issues") or []),
                "warning_count": len(review.get("warnings") or []),
                "issues": (review.get("issues") or [])[:12],
                "warnings": (review.get("warnings") or [])[:8],
            }
            gen_meta = {**gen_meta, "composition": True, "review": review_summary}
        else:
            new_bytes, gen_meta = await document_agent.generate_document_from_template(
                doc_bytes, requirements, db=db, company_context=_company_context(db),
            )
        import datetime as _dt
        new_key = f"chat/{session.id}/{_dt.datetime.utcnow().strftime('%Y%m%d%H%M%S')}_generated.docx"
        storage.upload_bytes(
            new_key, new_bytes,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        ws = dict(getattr(session, "workspace", None) or {})
        ws.update({
            "draft_object_key": new_key,
            "filename": f"{project.title}.docx",
            "version": int(ws.get("version") or 0) + 1,
            "last_action": "generate",
            "generation_meta": gen_meta,
        })
        session.workspace = ws
        workspace_updated = True
        keys = gen_meta.get("generated_keys") or gen_meta.get("composition_plan", {}).get("items") or []
        ws_note = f"\n\n已生成初稿（处理 {len(keys)} 个块/字段），请在左侧预览查看。"
        if review_summary:
            ws_note += f"\n文档审阅：{review_summary.get('status', 'unknown')}，"
            ws_note += "可导出" if review_summary.get("can_export") else "建议进入向导第 5 步完善"
    except Exception as exc:
        ws_note = f"\n\n初稿生成未完成（{exc}），可进入向导第 3 步重新生成。"
    return ws_note, workspace_updated, review_summary


async def _on_confirm_requirements(
    db: Session, session: ChatSession, pa: dict | None, payload: dict
) -> tuple[str, dict, bool]:
    if not pa or pa.get("flow") != FLOW_PROJECT_CREATE or pa.get("stage") != "collect_requirements":
        return "", _result("该步骤已失效，请重新告诉我「帮我写标书」。", intent="error"), False
    project_id = int(pa.get("project_id") or 0)
    template_id = int(pa.get("template_id") or 0)
    fields = dict(pa.get("fields") or {})
    requirements = str(payload.get("requirements") or "").strip()
    if not requirements:
        return "", _result("请填写编写要求后再确认生成。", intent="error"), False

    from app.models import TenderProject
    project = db.query(TenderProject).filter(TenderProject.id == project_id).first()
    if not project:
        return "", _result("项目不存在，请重新开始。", intent="error"), False

    ws_note, workspace_updated, review_summary = await _generate_project_draft(
        db, session, project, template_id, fields, requirements,
    )
    _set_pending(session, {
        "flow": FLOW_PROJECT_CREATE,
        "stage": "revise_document",
        "project_id": project.id,
        "template_id": template_id,
        "template_name": pa.get("template_name") or "",
    })
    return "确认编写要求并生成", _result(
        f"标书「{project.title}」智能创作完成。{ws_note}\n\n可继续提交修订指令，或点击「完成修订」。".strip(),
        cards=[
            {
                "id": _card_id(),
                "type": "doc_review",
                "title": "文档审阅摘要",
                "state": "done",
                "payload": review_summary or {"status": "unknown", "can_export": False, "issue_count": 0},
            },
            {
                "id": _card_id(),
                "type": "revision_collect",
                "title": "多轮修订",
                "state": "active",
                "payload": {
                    "project_id": project.id,
                    "submit_action": "submit_revision",
                    "finish_action": "finish_revision",
                    "placeholder": "例如：将技术方案压缩到 300 字；补充夜间作业安全措施…",
                },
            },
            {
                "id": _card_id(),
                "type": "project_info",
                "title": "标书已创建",
                "state": "done",
                "payload": {
                    "project_id": project.id,
                    "title": project.title,
                    "template_name": pa.get("template_name") or "",
                    "field_count": len(fields),
                    "review_summary": review_summary,
                },
            },
        ],
        actions=[
            {"type": "link", "label": "进入向导精细完善", "url": f"/projects/{project.id}/step/3", "primary": True},
            {"type": "link", "label": "预览与导出", "url": f"/projects/{project.id}/step/6"},
        ],
        intent="create_project",
        project_id=project.id,
        workspace_updated=workspace_updated,
    ), workspace_updated


async def handle_revision_text(
    db: Session, session: ChatSession, instruction: str,
) -> dict[str, Any]:
    """对话文本直接触发修订（revise_document 阶段）。"""
    pa = _pending(session)
    if not pa or pa.get("stage") != "revise_document":
        return _result("当前不在修订阶段。", intent="error")
    _label, result, _ = await _on_submit_revision(
        db, session, pa, {"instruction": instruction},
    )
    return result


async def finish_revision(db: Session, session: ChatSession) -> dict[str, Any]:
    _label, result, _ = await _on_finish_revision(db, session, _pending(session))
    return result


async def _on_submit_revision(
    db: Session, session: ChatSession, pa: dict | None, payload: dict,
) -> tuple[str, dict, bool]:
    if not pa or pa.get("flow") != FLOW_PROJECT_CREATE or pa.get("stage") != "revise_document":
        return "", _result("修订会话已失效。", intent="error"), False
    instruction = str(payload.get("instruction") or "").strip()
    if not instruction:
        return "", _result("请输入修订指令。", intent="error"), False
    ws = dict(getattr(session, "workspace", None) or {})
    key = ws.get("draft_object_key")
    if not key:
        return "", _result("工作区没有可修订的文档。", intent="error"), False
    try:
        doc_bytes = storage.download_bytes(key)
        new_bytes, revised, meta = await document_agent.edit_document_fragment(
            doc_bytes, instruction, db=db, company_context=_company_context(db),
        )
        import datetime as _dt
        new_key = f"chat/{session.id}/{_dt.datetime.utcnow().strftime('%Y%m%d%H%M%S')}_revised.docx"
        storage.upload_bytes(
            new_key, new_bytes,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        ws.update({
            "draft_object_key": new_key,
            "version": int(ws.get("version") or 0) + 1,
            "last_action": "revise",
            "last_revision": {"instruction": instruction, **meta},
        })
        session.workspace = ws
        return f"修订：{instruction[:40]}", _result(
            f"已根据指令完成修订。\n\n预览片段：\n{revised[:400]}{'…' if len(revised) > 400 else ''}",
            cards=[{
                "id": _card_id(),
                "type": "revision_collect",
                "title": "继续修订",
                "state": "active",
                "payload": {
                    "project_id": pa.get("project_id"),
                    "submit_action": "submit_revision",
                    "finish_action": "finish_revision",
                    "placeholder": "继续输入下一条修订指令…",
                },
            }],
            intent="revise_document",
            workspace_updated=True,
        ), True
    except Exception as exc:
        return "", _result(f"修订失败：{exc}", intent="error"), False


async def _on_finish_revision(
    db: Session, session: ChatSession, pa: dict | None,
) -> tuple[str, dict, bool]:
    _set_pending(session, None)
    project_id = int((pa or {}).get("project_id") or 0)
    return "完成修订", _result(
        "修订流程已结束。您可以继续导出，或进入向导精细完善。",
        actions=[
            {"type": "link", "label": "进入向导", "url": f"/projects/{project_id}/step/3", "primary": True},
        ] if project_id else [],
        intent="revise_done",
    ), False


async def _on_confirm_mapping(
    db: Session, session: ChatSession, pa: dict | None, payload: dict
) -> tuple[str, dict, bool]:
    if not pa or pa.get("flow") != FLOW_TEMPLATE_CREATE:
        return "", _result("该确认已失效，请重新上传文档并创建模板。", intent="error"), False
    template_id = int(pa.get("template_id") or 0)
    mappings = payload.get("mappings") or []
    applied = agent_tools.apply_template_placeholder_mappings(db, template_id, mappings)
    _set_pending(session, None)

    # 左侧工作区切换为工程化后的模板预览（占位符以 {{key}} 展示）
    if applied.get("object_key"):
        _update_workspace(
            session,
            draft_object_key=applied["object_key"],
            filename=f"{applied['template']['name']}.docx",
            last_action="template_engineered",
        )

    t = applied["template"]
    return "确认应用映射", _result(
        f"模板「{t['name']}」已创建完成并启用：应用 {applied['applied_count']} 处映射，"
        f"共 {t['placeholder_count']} 个占位符。左侧已更新为模板预览。",
        cards=[{
            "id": _card_id(),
            "type": "template_info",
            "title": "模板创建完成",
            "state": "done",
            "payload": {
                "template_id": t["id"],
                "name": t["name"],
                "placeholder_count": t["placeholder_count"],
                "applied_count": applied["applied_count"],
                "placeholders": applied.get("placeholders") or [],
            },
        }],
        actions=[
            {"type": "link", "label": "用此模板写标书", "url": "/chat", "primary": True},
            {"type": "link", "label": "模板管理", "url": "/admin/templates"},
        ],
        intent="create_template",
        template_id=t["id"],
        workspace_updated=True,
    ), True
