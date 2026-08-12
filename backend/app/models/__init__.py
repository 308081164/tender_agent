from datetime import datetime, date
from sqlalchemy import String, Text, Integer, DateTime, Date, Boolean, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class CompanyProfile(Base):
    """企业档案（单例 id=1）"""
    __tablename__ = "company_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(200), default="")
    short_name: Mapped[str] = mapped_column(String(100), default="")
    credit_code: Mapped[str] = mapped_column(String(50), default="")
    register_address: Mapped[str] = mapped_column(String(300), default="")
    office_address: Mapped[str] = mapped_column(String(300), default="")
    legal_name: Mapped[str] = mapped_column(String(100), default="")
    legal_gender: Mapped[str] = mapped_column(String(20), default="")
    legal_age: Mapped[str] = mapped_column(String(20), default="")
    legal_title: Mapped[str] = mapped_column(String(100), default="")
    legal_id_no: Mapped[str] = mapped_column(String(50), default="")
    registered_capital: Mapped[str] = mapped_column(String(100), default="")
    founded_date: Mapped[str] = mapped_column(String(50), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    fax: Mapped[str] = mapped_column(String(50), default="")
    email: Mapped[str] = mapped_column(String(100), default="")
    website: Mapped[str] = mapped_column(String(200), default="")
    postcode: Mapped[str] = mapped_column(String(20), default="")
    bank_name: Mapped[str] = mapped_column(String(200), default="")
    bank_account: Mapped[str] = mapped_column(String(100), default="")
    recent_revenue: Mapped[str] = mapped_column(Text, default="")
    related_companies: Mapped[str] = mapped_column(Text, default="无")
    intro: Mapped[str] = mapped_column(Text, default="")
    business_scope: Mapped[str] = mapped_column(Text, default="")
    qual_overview: Mapped[str] = mapped_column(Text, default="")
    typical_projects: Mapped[str] = mapped_column(Text, default="")
    ai_style_notes: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Template(Base):
    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    object_key: Mapped[str] = mapped_column(String(500))
    placeholders: Mapped[dict] = mapped_column(JSON, default=dict)
    template_code: Mapped[str] = mapped_column(String(50), default="common")  # tpl1|tpl3|common|history|tender_doc
    kind: Mapped[str] = mapped_column(String(50), default="template")  # template|history|tender_doc|skeleton
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    source_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)  # 历史标书原字段快照，用于智能替换
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Qualification(Base):
    __tablename__ = "qualifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    issuer: Mapped[str] = mapped_column(String(200), default="")
    file_type: Mapped[str] = mapped_column(String(50), default="docx")
    file_name: Mapped[str] = mapped_column(String(300), default="")
    object_key: Mapped[str] = mapped_column(String(500))
    keywords: Mapped[str] = mapped_column(String(500), default="")
    section_hint: Mapped[str] = mapped_column(String(200), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_long_term: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TenderProject(Base):
    __tablename__ = "tender_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), default="未命名标书")
    source_type: Mapped[str] = mapped_column(String(50), default="template")  # template | history
    template_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("templates.id"), nullable=True)
    current_step: Mapped[int] = mapped_column(Integer, default=1)
    fields: Mapped[dict] = mapped_column(JSON, default=dict)
    chapters: Mapped[dict] = mapped_column(JSON, default=dict)
    inserted_quals: Mapped[list] = mapped_column(JSON, default=list)
    checklist_result: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(50), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    snapshots: Mapped[list["ProjectSnapshot"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    exports: Mapped[list["ProjectExport"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ProjectExport(Base):
    __tablename__ = "project_exports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("tender_projects.id"))
    object_key: Mapped[str] = mapped_column(String(500))
    filename: Mapped[str] = mapped_column(String(300), default="tender.docx")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project: Mapped["TenderProject"] = relationship(back_populates="exports")


class ProjectSnapshot(Base):
    __tablename__ = "project_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("tender_projects.id"))
    step: Mapped[int] = mapped_column(Integer)
    step_name: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    project: Mapped["TenderProject"] = relationship(back_populates="snapshots")


class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    section: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(200))
    required: Mapped[str] = mapped_column(String(50), default="必含")
    chapter: Mapped[str] = mapped_column(String(100), default="")
    remark: Mapped[str] = mapped_column(String(200), default="")
    template_code: Mapped[str] = mapped_column(String(50), default="common")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class FAQItem(Base):
    __tablename__ = "faq_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(100))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(300), default="")
    template_code: Mapped[str] = mapped_column(String(50), default="common")


class FieldDef(Base):
    __tablename__ = "field_defs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100))
    key: Mapped[str] = mapped_column(String(100), unique=True)
    field_type: Mapped[str] = mapped_column(String(50), default="文本")
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    default_value: Mapped[str] = mapped_column(String(500), default="")
    options: Mapped[str] = mapped_column(Text, default="")
    module: Mapped[str] = mapped_column(String(100), default="")
    validation: Mapped[str] = mapped_column(String(200), default="")
    template_code: Mapped[str] = mapped_column(String(50), default="common")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_company_default: Mapped[bool] = mapped_column(Boolean, default=False)
    company_field: Mapped[str] = mapped_column(String(100), default="")
    desensitized: Mapped[bool] = mapped_column(Boolean, default=False)


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    deepseek_api_key: Mapped[str] = mapped_column(Text, default="")
    deepseek_base_url: Mapped[str] = mapped_column(String(300), default="https://api.deepseek.com")
    deepseek_model: Mapped[str] = mapped_column(String(100), default="deepseek-chat")
    qwen_api_key: Mapped[str] = mapped_column(Text, default="")
    qwen_base_url: Mapped[str] = mapped_column(
        String(300), default="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    qwen_model: Mapped[str] = mapped_column(String(100), default="qwen-plus")
    preferred_provider: Mapped[str] = mapped_column(String(50), default="auto")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), default="新对话")
    workspace: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan", order_by="ChatMessage.id"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(Integer, ForeignKey("chat_sessions.id"))
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(300), default="")
    matched_question: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["ChatSession"] = relationship(back_populates="messages")
