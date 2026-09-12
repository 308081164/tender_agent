"""Agent 语义路由与系统查询工具测试。"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

for _name in ("aspose", "aspose.words"):
    sys.modules.setdefault(_name, MagicMock())

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import CompanyProfile, Template, TenderProject
from app.services.agent_query_tools import (
    count_templates,
    get_company_summary,
    list_recent_projects,
    parse_bulk_replace,
    search_projects,
)
from app.services.agent_semantic import _keyword_route, route_intent


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    db.add(CompanyProfile(id=1, full_name="和远智能科技股份有限公司", short_name="和远智能"))
    db.add(Template(name="铁路模板1", object_key="t/1.docx", kind="template", enabled=True))
    db.add(Template(name="历史标书样例", object_key="t/2.docx", kind="history", enabled=True))
    p = TenderProject(
        title="地铁12号线电气火灾监控",
        status="draft",
        current_step=2,
        fields={"project_name": "地铁12号线"},
        created_at=datetime.utcnow() - timedelta(days=2),
        updated_at=datetime.utcnow(),
    )
    db.add(p)
    db.commit()
    return db


def test_keyword_route_meta_and_stats():
    intent, _, score = _keyword_route("告诉我你是谁，你能干什么")
    assert intent == "meta" and score > 0.9
    intent2, _, score2 = _keyword_route("当前一共有多少个标书模板")
    assert intent2 == "query_template_stats" and score2 > 0.8


def test_query_tools():
    db = _db()
    company = get_company_summary(db)
    assert "和远智能" in company["full_name"]
    stats = count_templates(db)
    assert stats["total"] == 2
    recent = list_recent_projects(db, days=7)
    assert len(recent) == 1
    found = search_projects(db, "地铁12号线")
    assert found and found[0]["title"].startswith("地铁")


def test_parse_bulk_replace():
    assert parse_bulk_replace("把ABC全部替换成XYZ") == ("ABC", "XYZ")


async def _test_route_company():
    db = _db()
    intent, _, conf = await route_intent("公司的全称是什么", db, [], {})
    assert intent == "query_company" and conf >= 0.5


def test_route_company():
    import asyncio
    asyncio.run(_test_route_company())


if __name__ == "__main__":
    test_keyword_route_meta_and_stats()
    test_query_tools()
    test_parse_bulk_replace()
    test_route_company()
    print("PASS all agent semantic tests")
