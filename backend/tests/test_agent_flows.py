"""Agent 中台流程全链路测试（mock LLM 与对象存储）。

运行方式：
    python -m pytest backend/tests/test_agent_flows.py
    或直接：python backend/tests/test_agent_flows.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import ChatSession, FieldDef, Template
from app.services import agent_flows, chat_assistant


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _new_session(db) -> ChatSession:
    s = ChatSession(title="测试对话", workspace={})
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _seed_template(db, name="铁路工程模板", enabled=True) -> Template:
    t = Template(
        name=name,
        description="测试",
        object_key="templates/test.docx",
        placeholders={"list": ["project_name"]},
        template_code="common",
        kind="template",
        enabled=enabled,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


def _seed_fields(db):
    db.add(FieldDef(key="project_name", name="项目名称", field_type="文本", required=True, sort_order=1))
    db.add(FieldDef(key="tenderer", name="招标人", field_type="文本", required=False, sort_order=2))
    db.commit()


FAKE_DETECTION = {
    "candidates": [
        {"key": "project_name", "field_name": "项目名称", "original_text": "某某铁路工程",
         "confidence": 0.92, "reason": "AI 识别", "source": "ai"},
        {"key": "tender_no", "field_name": "招标编号", "original_text": "ABC-2026-001",
         "confidence": 0.7, "reason": "规则匹配", "source": "rule"},
    ],
    "existing_placeholders": [],
    "paragraph_count": 10,
    "document_excerpt": "...",
}


def _storage_patches():
    return (
        patch("app.services.agent_tools.storage.download_bytes", return_value=b"docx-bytes"),
        patch("app.services.agent_tools.storage.upload_bytes", side_effect=lambda k, d, c: k),
        patch("app.services.agent_tools.storage.delete_object", return_value=None),
        patch("app.services.agent_tools.word.extract_placeholders", return_value=[]),
    )


def test_template_create_flow():
    async def run():
        db = _make_db()
        session = _new_session(db)
        session.workspace = {
            "template_object_key": "chat/1/doc.docx",
            "draft_object_key": "chat/1/doc.docx",
            "filename": "完整标书.docx",
        }
        db.commit()

        patches = _storage_patches() + (
            patch("app.services.agent_tools.template_detect.detect_placeholder_candidates",
                  return_value=FAKE_DETECTION),
            patch("app.services.agent_tools.template_detect.apply_placeholder_mappings",
                  return_value=(b"new-bytes", {"project_name": "某某铁路工程"}, ["project_name", "tender_no"])),
        )
        for p in patches:
            p.start()
        try:
            # 1. 启动流程：识别 + 映射确认卡
            result = await agent_flows.start_template_create(db, session)
            cards = result["metadata"]["cards"]
            assert cards and cards[0]["type"] == "mapping_confirm"
            assert cards[0]["state"] == "active"
            mappings = cards[0]["payload"]["mappings"]
            assert len(mappings) == 2
            pa = session.workspace.get("pending_action")
            assert pa and pa["flow"] == "template_create"
            tpl = db.query(Template).first()
            assert tpl is not None and tpl.enabled is False

            # 2. 确认映射：应用 + 启用 + 信息卡 + 工作区切换
            _label, result2, ws_updated = await agent_flows.handle_action(
                db, session, "confirm_mapping", {"mappings": mappings}
            )
            assert ws_updated is True
            card2 = result2["metadata"]["cards"][0]
            assert card2["type"] == "template_info"
            assert card2["payload"]["applied_count"] == 1
            assert card2["payload"]["placeholder_count"] == 2
            db.refresh(tpl)
            assert tpl.enabled is True
            assert session.workspace.get("pending_action") is None
            assert session.workspace["draft_object_key"].startswith("templates/")
        finally:
            for p in patches:
                p.stop()
    asyncio.run(run())


def test_template_create_cancel_discards_draft():
    async def run():
        db = _make_db()
        session = _new_session(db)
        session.workspace = {"template_object_key": "chat/1/doc.docx", "filename": "a.docx"}
        db.commit()
        patches = _storage_patches() + (
            patch("app.services.agent_tools.template_detect.detect_placeholder_candidates",
                  return_value=FAKE_DETECTION),
        )
        for p in patches:
            p.start()
        try:
            await agent_flows.start_template_create(db, session)
            assert db.query(Template).count() == 1
            _label, result, _ = await agent_flows.handle_action(db, session, "cancel_flow", {})
            assert "已取消" in result["answer"]
            assert db.query(Template).count() == 0
            assert session.workspace.get("pending_action") is None
        finally:
            for p in patches:
                p.stop()
    asyncio.run(run())


def test_template_create_requires_document():
    async def run():
        db = _make_db()
        session = _new_session(db)
        result = await agent_flows.start_template_create(db, session)
        assert "上传" in result["answer"]
        assert db.query(Template).count() == 0
    asyncio.run(run())


def test_project_create_flow():
    async def run():
        db = _make_db()
        _seed_fields(db)
        tpl = _seed_template(db)
        session = _new_session(db)

        # 1. 入口：模板筛选卡
        result = await agent_flows.start_project_create(db, session)
        card = result["metadata"]["cards"][0]
        assert card["type"] == "template_picker"
        assert card["payload"]["templates"][0]["id"] == tpl.id
        assert session.workspace["pending_action"]["stage"] == "select_template"

        # 2. 选择模板：字段收集卡
        label, result2, _ = await agent_flows.handle_action(
            db, session, "select_template", {"template_id": tpl.id}
        )
        assert tpl.name in label
        card2 = result2["metadata"]["cards"][0]
        assert card2["type"] == "field_collect"
        field_keys = [f["key"] for f in card2["payload"]["fields"]]
        assert "project_name" in field_keys
        assert session.workspace["pending_action"]["stage"] == "collect_fields"

        # 3. 缺少必填项 → 错误提示
        _l, err, _ = await agent_flows.handle_action(
            db, session, "confirm_fields", {"fields": {"tenderer": "某局"}}
        )
        assert "项目名称" in err["answer"]

        # 4. 确认字段：创建项目 + 生成初稿
        with patch("app.services.agent_flows.document_agent.generate_document_from_template",
                   return_value=(b"gen-bytes", {"generated_keys": ["project_name"]})), \
             patch("app.services.agent_flows.storage.download_bytes", return_value=b"tpl"), \
             patch("app.services.agent_flows.storage.upload_bytes", side_effect=lambda k, d, c: k):
            _l2, result3, ws_updated = await agent_flows.handle_action(
                db, session, "confirm_fields",
                {"fields": {"project_name": "京沪高铁维保标段", "tenderer": "上海局集团"}},
            )
        assert ws_updated is True
        card3 = result3["metadata"]["cards"][0]
        assert card3["type"] == "project_info"
        assert card3["payload"]["title"] == "京沪高铁维保标段"
        from app.models import TenderProject
        project = db.query(TenderProject).first()
        assert project is not None
        assert project.template_id == tpl.id
        assert project.fields["project_name"] == "京沪高铁维保标段"
        assert session.workspace.get("pending_action") is None
        assert session.workspace["draft_object_key"].endswith("_generated.docx")
    asyncio.run(run())


def test_pending_flow_intercepts_text():
    async def run():
        db = _make_db()
        _seed_template(db)
        session = _new_session(db)
        await agent_flows.start_project_create(db, session)
        db.commit()

        # 普通文本 → 流程引导提示（不重新分类意图）
        hint = await chat_assistant.process_chat_message(
            "今天天气怎么样", db, workspace=session.workspace, session=session,
        )
        assert hint["metadata"]["intent"] == "flow_pending"
        assert "卡片" in hint["answer"]

        # 取消 → 退出流程
        cancelled = await chat_assistant.process_chat_message(
            "取消", db, workspace=session.workspace, session=session,
        )
        assert cancelled["metadata"]["intent"] == "cancel"
        assert session.workspace.get("pending_action") is None
    asyncio.run(run())


def test_intent_routing_to_flows():
    async def run():
        db = _make_db()
        _seed_template(db)
        session = _new_session(db)
        result = await chat_assistant.process_chat_message(
            "帮我新建一份标书", db, workspace=session.workspace, session=session,
        )
        cards = result["metadata"].get("cards") or []
        assert cards and cards[0]["type"] == "template_picker"
    asyncio.run(run())


def test_required_fields_options_are_lists():
    """回归：FieldDef.options 为分号分隔字符串时，字段收集卡必须返回列表。"""
    from app.services import agent_tools
    db = _make_db()
    db.add(FieldDef(
        key="project_type", name="项目类型", field_type="下拉选项",
        required=True, sort_order=1, options="铁路工程;轨道交通；线路维护",
    ))
    db.commit()
    fields = agent_tools.required_fields_for_template(db)
    pt = next(f for f in fields if f["key"] == "project_type")
    assert isinstance(pt["options"], list)
    assert pt["options"] == ["铁路工程", "轨道交通", "线路维护"]


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(tests)} tests passed")
