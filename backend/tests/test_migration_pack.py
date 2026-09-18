"""迁移包导出/导入与资质识别测试。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.database import Base, SessionLocal, engine
from app.models import CompanyProfile, FieldDef, Qualification, Template
from app.services.migration_pack import export_pack, import_pack
from app.services.qual_extract import _rule_based_extract


def _setup_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    db.add(CompanyProfile(id=1, full_name="测试企业", short_name="测试"))
    db.add(FieldDef(name="项目名称", key="project_name", field_type="文本"))
    db.add(Template(name="自定义模板", object_key="templates/custom.docx", placeholders={"list": []}))
    db.add(Qualification(
        category="企业资质包",
        name="营业执照",
        issuer="市场监管局",
        file_type="pdf",
        object_key="qualifications/企业资质包/执照.pdf",
        keywords="营业执照",
    ))
    db.commit()
    return db


def test_export_import_roundtrip():
    db = _setup_db()
    try:
        blob = export_pack(db)
        assert len(blob) > 100
        db.query(Qualification).delete()
        db.query(Template).delete()
        db.query(FieldDef).delete()
        db.query(CompanyProfile).delete()
        db.commit()
        result = import_pack(db, blob, force=True)
        assert result["ok"] is True
        assert db.query(FieldDef).count() == 1
        assert db.query(Template).count() == 1
        assert db.query(Qualification).count() == 1
        company = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
        assert company.full_name == "测试企业"
    finally:
        db.close()


def test_rule_based_qual_extract():
    text = "营业执照 颁发单位：济南市市场监督管理局 有效期至 2028-12-31"
    result = _rule_based_extract(text, "营业执照.pdf", "pdf")
    assert result["name"] == "营业执照"
    assert "市场" in result["issuer"]
    assert result["valid_to"] == "2028-12-31"


if __name__ == "__main__":
    test_export_import_roundtrip()
    test_rule_based_qual_extract()
    print("ok")
