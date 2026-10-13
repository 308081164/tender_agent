"""对话式导出意图与 field_verify 向导信任规则。"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

for _name in ("aspose", "aspose.words"):
    sys.modules.setdefault(_name, MagicMock())

from app.database import Base, SessionLocal, engine
from app.models import FieldDef, Template, TenderProject
from app.services.field_verify import (
    auto_confirm_wizard_verify_fields,
    trust_wizard_filled_verify_field,
    unconfirmed_sensitive_keys,
)
from app.services.project_context import build_field_checklist
from app.services.project_export_flow import detect_export_ack, detect_export_start


def _fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def test_detect_export_phrases():
    assert detect_export_start("可以了，请你帮我导出标书")
    assert detect_export_start("请导出 word")
    assert detect_export_ack("没问题了，可以导出")
    assert not detect_export_start("今天天气不错")


def test_wizard_trust_skips_needs_verify():
    db = _fresh_db()
    fd = FieldDef(
        name="投标报价",
        key="bid_amount",
        field_type="文本",
        module="报价",
        template_code="common",
    )
    db.add(fd)
    tpl = Template(
        name="T",
        object_key="t/x.docx",
        placeholders={"list": []},
        template_code="common",
        enabled=True,
    )
    db.add(tpl)
    db.flush()
    p = TenderProject(
        title="P",
        template_id=tpl.id,
        current_step=3,
        fields={"bid_amount": "100万", "project_name": "演示"},
    )
    db.add(p)
    db.commit()

    cl = build_field_checklist(db, p)
    verify_keys = [v["key"] for v in cl.get("needs_verify") or []]
    assert "bid_amount" not in verify_keys

    auto_confirm_wizard_verify_fields(db, p)
    db.refresh(p)
    pending = unconfirmed_sensitive_keys(p.fields, db, project=p)
    assert pending == []
    db.close()


def test_trust_helper_respects_reverify():
    db = _fresh_db()
    p = TenderProject(
        title="P",
        current_step=3,
        fields={"bid_amount": "1", "_field_reverify": ["bid_amount"]},
    )
    assert not trust_wizard_filled_verify_field(
        p, "bid_amount", confirmed={}, has_value=True,
    )
    db.close()


if __name__ == "__main__":
    test_detect_export_phrases()
    test_wizard_trust_skips_needs_verify()
    test_trust_helper_respects_reverify()
    print("OK")
