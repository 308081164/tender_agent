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
    "ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS metadata JSON DEFAULT '{}'::json",
    "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS workspace JSON DEFAULT '{}'::json",
    "ALTER TABLE tender_projects ADD COLUMN IF NOT EXISTS workspace_dir VARCHAR(1000) DEFAULT ''",
    # DeepSeek V4 Pro 默认模型升级（保留用户自定义的其他模型名）
    "UPDATE system_settings SET deepseek_model = 'deepseek-v4-pro' "
    "WHERE deepseek_model IS NULL OR deepseek_model IN ('', 'deepseek-chat', 'deepseek-reasoner')",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS kimi_api_key TEXT DEFAULT ''",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS kimi_base_url VARCHAR(300) DEFAULT 'https://api.moonshot.cn/v1'",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS kimi_model VARCHAR(100) DEFAULT 'moonshot-v1-8k'",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS qwen_vl_model VARCHAR(100) DEFAULT 'qwen-vl-plus'",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS kimi_k3_model VARCHAR(100) DEFAULT 'kimi-k3'",
    "UPDATE system_settings SET kimi_k3_model = kimi_model "
    "WHERE (kimi_k3_model IS NULL OR kimi_k3_model = '') "
    "AND kimi_model IN ('kimi-k3', 'kimi-k2.6', 'kimi-k2-0905-preview')",
    "UPDATE system_settings SET kimi_model = 'moonshot-v1-8k' "
    "WHERE kimi_model IN ('kimi-k3', 'kimi-k2.6', 'kimi-k2-0905-preview')",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS web_search_provider VARCHAR(40) DEFAULT 'duckduckgo'",
    "ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS web_search_api_key TEXT DEFAULT ''",
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
    _backfill_field_company_mappings()


def _backfill_field_company_mappings():
    """为旧库 field_defs 补齐企业档案映射，使向导信息录入可自动预填。"""
    try:
        from app.database import SessionLocal
        from app.services.field_defaults import backfill_field_company_mappings

        db = SessionLocal()
        try:
            n = backfill_field_company_mappings(db)
            if n:
                print(f"[migrate] backfilled company mappings for {n} field_defs")
        finally:
            db.close()
    except Exception as e:
        print(f"[migrate] field company mapping backfill skip: {e}")
