"""table_compose 确定性填表。"""
from __future__ import annotations

import pytest

from app.services.doc_engine.table_compose import (
    _seed_performance_rows,
    generate_table_rows_for_slot,
    table_slot_skip_llm,
)


def test_performance_rows_exclude_current_bid():
    fields = {
        "project_name": "新城智慧交通维保系统投标",
        "tender_no": "XCZHJT-2026-1027-A",
    }
    columns = ["序号", "项目名称", "谈判编号", "合同金额"]
    rows = _seed_performance_rows(columns, fields)
    assert len(rows) >= 2
    blob = str(rows)
    assert "XCZHJT-2026-1027-A" not in blob
    assert "新城智慧交通维保系统投标" not in blob


def test_quote_slot_skips_llm():
    slot = {"title": "竞标物资报价表", "bind": "table_5_rows", "columns": ["序号", "谈判编号", "报价"]}
    assert table_slot_skip_llm(slot)


@pytest.mark.asyncio
async def test_generate_quote_rows_from_fields():
    slot = {
        "title": "竞标物资报价表",
        "bind": "table_5_rows",
        "columns": ["谈判编号", "竞标人", "报价"],
    }
    fields = {
        "tender_no": "XCZHJT-2026-1027-A",
        "bidder_name": "华远智通科技有限公司",
        "bid_amount_lower": "9800000.00",
        "bid_amount_upper": "人民币玖佰捌拾万元整",
    }
    rows = await generate_table_rows_for_slot(slot, fields, "req", db=None)
    assert rows
    assert rows[0]["谈判编号"] == "XCZHJT-2026-1027-A"
    assert "华远智通" in rows[0]["竞标人"]
