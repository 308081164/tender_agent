"""项目 context API 与敏感字段规则。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.database import Base, SessionLocal, engine
from app.models import FieldDef, Template, TenderProject
from app.services.field_verify import is_verify_field
from app.services.project_context import build_field_checklist, build_project_context


def _fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def test_is_verify_field_matches_desensitized():
    db = _fresh_db()
    fd = FieldDef(
        name="测试报价",
        key="custom_bid",
        field_type="文本",
        module="报价",
        desensitized=True,
    )
    db.add(fd)
    db.commit()
    assert is_verify_field(fd) is True
    db.close()


def test_project_context_field_checklist():
    db = _fresh_db()
    tpl = Template(
        name="测试模板",
        object_key="templates/test.docx",
        placeholders={"list": ["a", "b"]},
        template_code="common",
        kind="template",
        enabled=True,
    )
    db.add(tpl)
    db.flush()
    p = TenderProject(
        title="测试项目",
        template_id=tpl.id,
        fields={"project_name": "演示项目"},
        current_step=2,
    )
    db.add(p)
    db.commit()

    ctx = build_project_context(db, p.id)
    assert ctx["template"]["mode"] in ("replace", "compose")
    assert ctx["field_checklist"]["filled"]
    assert any(f["key"] == "project_name" for f in ctx["field_checklist"]["filled"])

    cl = build_field_checklist(db, p)
    assert "missing_required" in cl
    assert "needs_verify" in cl
    db.close()


if __name__ == "__main__":
    test_is_verify_field_matches_desensitized()
    test_project_context_field_checklist()
    print("OK")
