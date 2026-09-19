"""字段默认值与企业档案预填回归测试。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.database import Base, SessionLocal, engine
from app.models import CompanyProfile, FieldDef
from app.routers.api import _fill_field_defaults, _field_effective_default


def _fresh_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def test_field_effective_default_prefers_company():
    db = _fresh_db()
    try:
        db.add(CompanyProfile(id=1, full_name="测试铁路公司", phone="010-12345678"))
        db.commit()
        fd = FieldDef(
            key="bidder_name",
            name="投标人",
            field_type="文本",
            is_company_default=True,
            company_field="full_name",
            default_value="旧默认值",
        )
        company = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
        assert _field_effective_default(fd, company) == "测试铁路公司"
    finally:
        db.close()


def test_fill_field_defaults_merges_company_and_static():
    db = _fresh_db()
    try:
        db.add(CompanyProfile(id=1, full_name="XX铁路工程有限公司", office_address="北京市朝阳区"))
        db.add(FieldDef(
            key="bidder_name", name="投标人", field_type="文本", sort_order=1,
            is_company_default=True, company_field="full_name",
        ))
        db.add(FieldDef(
            key="address", name="地址", field_type="文本", sort_order=2,
            is_company_default=True, company_field="office_address",
        ))
        db.add(FieldDef(
            key="duration", name="工期", field_type="文本", sort_order=3,
            default_value="365日历天",
        ))
        db.commit()

        filled = _fill_field_defaults(db, {"project_name": "已有项目"})
        assert filled["project_name"] == "已有项目"
        assert filled["bidder_name"] == "XX铁路工程有限公司"
        assert filled["address"] == "北京市朝阳区"
        assert filled["duration"] == "365日历天"
    finally:
        db.close()


def test_fill_field_defaults_does_not_overwrite_existing():
    db = _fresh_db()
    try:
        db.add(CompanyProfile(id=1, full_name="企业档案名"))
        db.add(FieldDef(
            key="bidder_name", name="投标人", field_type="文本", sort_order=1,
            is_company_default=True, company_field="full_name",
        ))
        db.commit()

        filled = _fill_field_defaults(db, {"bidder_name": "用户手填"})
        assert filled["bidder_name"] == "用户手填"
    finally:
        db.close()
