"""compose_policy 单元测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services.doc_engine.compose_policy import (
    should_generate_ai_narrative,
    should_infer_ai_section_block,
    title_is_structured_letter,
    title_prefers_table_fill,
)

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = (
    ROOT
    / "docs/标书智能体参考资料-和远智能-20260729/02-word标书模板/1-标准投标word模板/铁路工程投标模板2-空白.docx"
)


@pytest.mark.skipif(not TEMPLATE.is_file(), reason="customer template missing")
def test_railway_template_skips_bid_letter_and_cert_narrative():
    data = TEMPLATE.read_bytes()
    assert title_is_structured_letter("竞标函")
    assert not should_generate_ai_narrative("竞标函", data)
    assert not should_infer_ai_section_block("许可和认证", data)
    assert title_prefers_table_fill("许可和认证基本情况表")


def test_generic_ai_sections_still_allowed():
    assert should_generate_ai_narrative("技术方案")
    assert should_generate_ai_narrative("售后服务方案")
