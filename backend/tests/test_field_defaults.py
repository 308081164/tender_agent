"""字段默认值与企业档案预填回归测试。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from app.database import Base, SessionLocal, engine
from app.models import CompanyProfile, FieldDef
from app.services.field_defaults import (
    backfill_field_company_mappings,
    field_effective_default,
    fill_field_defaults,
)


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
        assert field_effective_default(fd, company) == "测试铁路公司"
    finally:
        db.close()


def test_field_effective_default_fallback_map_without_db_flags():
    db = _fresh_db()
    try:
        db.add(CompanyProfile(id=1, full_name="爱国建材有限公司", phone="18888888888"))
        db.commit()
        fd = FieldDef(
            key="phone",
            name="电话",
            field_type="文本",
            is_company_default=False,
            company_field="",
        )
        company = db.query(CompanyProfile).filter(CompanyProfile.id == 1).first()
        assert field_effective_default(fd, company) == "18888888888"
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

        filled = fill_field_defaults(db, {"project_name": "已有项目"})
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

        filled = fill_field_defaults(db, {"bidder_name": "用户手填"})
        assert filled["bidder_name"] == "用户手填"
    finally:
        db.close()


def test_fill_field_defaults_overwrites_stale_static_default():
    """旧库种子默认值（如 XX铁路工程有限公司）应被企业档案覆盖。"""
    db = _fresh_db()
    try:
        db.add(CompanyProfile(
            id=1,
            full_name="爱国建材有限公司",
            office_address="山东省济南市历城区工业北路33号",
            phone="18888888888",
            fax="ss1236675599",
            website="https://www.baidu.com",
            legal_name="张爱国",
        ))
        db.add(FieldDef(
            key="bidder_name", name="投标人", field_type="文本", sort_order=1,
            default_value="XX铁路工程有限公司",
            is_company_default=False, company_field="",
        ))
        db.add(FieldDef(
            key="address", name="地址", field_type="文本", sort_order=2,
            is_company_default=False, company_field="",
        ))
        db.add(FieldDef(
            key="phone", name="电话", field_type="文本", sort_order=3,
            is_company_default=False, company_field="",
        ))
        db.add(FieldDef(
            key="legal_name", name="法定代表人", field_type="文本", sort_order=4,
            is_company_default=False, company_field="",
        ))
        db.commit()

        filled = fill_field_defaults(db, {"bidder_name": "XX铁路工程有限公司"})
        assert filled["bidder_name"] == "爱国建材有限公司"
        assert filled["address"] == "山东省济南市历城区工业北路33号"
        assert filled["phone"] == "18888888888"
        assert filled["legal_name"] == "张爱国"
    finally:
        db.close()


def test_address_falls_back_to_register_address():
    db = _fresh_db()
    try:
        db.add(CompanyProfile(
            id=1,
            register_address="山东省济南市历城区工业北路33号",
            office_address="",
        ))
        db.add(FieldDef(
            key="address", name="地址", field_type="文本", sort_order=1,
            is_company_default=True, company_field="office_address",
        ))
        db.commit()

        filled = fill_field_defaults(db, {})
        assert filled["address"] == "山东省济南市历城区工业北路33号"
    finally:
        db.close()


def test_backfill_field_company_mappings():
    db = _fresh_db()
    try:
        db.add(FieldDef(key="bidder_name", name="投标人", field_type="文本"))
        db.add(FieldDef(key="phone", name="电话", field_type="文本"))
        db.add(FieldDef(key="project_name", name="项目名称", field_type="文本"))
        db.commit()

        n = backfill_field_company_mappings(db)
        assert n == 2

        bidder = db.query(FieldDef).filter(FieldDef.key == "bidder_name").first()
        phone = db.query(FieldDef).filter(FieldDef.key == "phone").first()
        project = db.query(FieldDef).filter(FieldDef.key == "project_name").first()
        assert bidder.is_company_default is True
        assert bidder.company_field == "full_name"
        assert phone.company_field == "phone"
        assert project.is_company_default is False
        assert project.company_field == ""
    finally:
        db.close()
