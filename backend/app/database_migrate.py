"""轻量 schema 迁移：为已有库补齐新列/新表。"""
from __future__ import annotations

from sqlalchemy import text

from app.database import engine, Base


ALTERS = [
    "ALTER TABLE templates ADD COLUMN IF NOT EXISTS template_code VARCHAR(50) DEFAULT 'common'",
    "ALTER TABLE templates ADD COLUMN IF NOT EXISTS kind VARCHAR(50) DEFAULT 'template'",
    "ALTER TABLE templates ADD COLUMN IF NOT EXISTS enabled BOOLEAN DEFAULT TRUE",
    "ALTER TABLE templates ADD COLUMN IF NOT EXISTS source_snapshot JSON DEFAULT '{}'::json",
    "ALTER TABLE qualifications ADD COLUMN IF NOT EXISTS file_name VARCHAR(300) DEFAULT ''",
    "ALTER TABLE qualifications ADD COLUMN IF NOT EXISTS section_hint VARCHAR(200) DEFAULT ''",
    "ALTER TABLE qualifications ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0",
    "ALTER TABLE checklist_items ADD COLUMN IF NOT EXISTS template_code VARCHAR(50) DEFAULT 'common'",
    "ALTER TABLE checklist_items ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0",
    "ALTER TABLE faq_items ADD COLUMN IF NOT EXISTS template_code VARCHAR(50) DEFAULT 'common'",
    "ALTER TABLE field_defs ADD COLUMN IF NOT EXISTS template_code VARCHAR(50) DEFAULT 'common'",
    "ALTER TABLE field_defs ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0",
    "ALTER TABLE field_defs ADD COLUMN IF NOT EXISTS is_company_default BOOLEAN DEFAULT FALSE",
    "ALTER TABLE field_defs ADD COLUMN IF NOT EXISTS company_field VARCHAR(100) DEFAULT ''",
    "ALTER TABLE field_defs ADD COLUMN IF NOT EXISTS desensitized BOOLEAN DEFAULT FALSE",
    "ALTER TABLE field_defs ALTER COLUMN default_value TYPE VARCHAR(500)",
]


def ensure_schema():
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        for sql in ALTERS:
            try:
                conn.execute(text(sql))
            except Exception as e:
                # 兼容非 PG 或已存在
                print(f"[migrate] skip: {e}")
