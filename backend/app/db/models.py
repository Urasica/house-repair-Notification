from datetime import date, datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class Identity:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)


class Created:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Identity, Created, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name="status"),
        CheckConstraint(
            "normalized_email = lower(btrim(normalized_email))", name="email_normalized"
        ),
    )
    normalized_email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default="ACTIVE")


class AuthSession(Identity, Base):
    __tablename__ = "auth_sessions"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Catalog(Base):
    __tablename__ = "catalogs"
    __table_args__ = (
        CheckConstraint("status IN ('DRAFT', 'PUBLISHED')", name="status"),
        CheckConstraint("status <> 'PUBLISHED' OR published_at IS NOT NULL", name="published_time"),
    )
    version: Mapped[str] = mapped_column(String(80), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), server_default="DRAFT")
    payload_json: Mapped[dict] = mapped_column(JSONB)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class KnowledgeSet(Identity, Base):
    __tablename__ = "knowledge_sets"
    __table_args__ = (
        CheckConstraint("status IN ('BUILDING', 'PUBLISHED', 'WITHDRAWN')", name="status"),
        CheckConstraint("embedding_dimensions = 1536", name="dimensions"),
        CheckConstraint("status <> 'PUBLISHED' OR published_at IS NOT NULL", name="published_time"),
    )
    catalog_version: Mapped[str] = mapped_column(ForeignKey("catalogs.version"))
    status: Mapped[str] = mapped_column(String(16), server_default="BUILDING")
    embedding_model: Mapped[str] = mapped_column(String(100))
    embedding_dimensions: Mapped[int] = mapped_column(Integer)
    manifest_json: Mapped[dict] = mapped_column(JSONB)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Consultation(Identity, Created, Base):
    __tablename__ = "consultations"
    __table_args__ = (
        CheckConstraint("(owner_user_id IS NULL) <> (guest_token_hash IS NULL)", name="one_owner"),
        CheckConstraint("revision >= 0", name="revision"),
        CheckConstraint("expires_at > created_at", name="expiry"),
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    guest_token_hash: Mapped[str | None] = mapped_column(String(64))
    catalog_version: Mapped[str] = mapped_column(ForeignKey("catalogs.version"))
    knowledge_set_id: Mapped[UUID | None] = mapped_column(ForeignKey("knowledge_sets.id"))
    revision: Mapped[int] = mapped_column(Integer, server_default="0")
    context_json: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class RequestRun(Identity, Created, Base):
    __tablename__ = "request_runs"
    __table_args__ = (
        UniqueConstraint("consultation_id", "request_id"),
        CheckConstraint("kind IN ('SURVEY', 'CHAT')", name="kind"),
        CheckConstraint("state IN ('PROCESSING', 'COMPLETED', 'FAILED', 'DELETED')", name="state"),
        CheckConstraint(
            "(state = 'PROCESSING' AND finished_at IS NULL AND response_json IS NULL)"
            " OR (state = 'COMPLETED' AND finished_at IS NOT NULL AND response_json IS NOT NULL)"
            " OR (state IN ('FAILED', 'DELETED')"
            " AND finished_at IS NOT NULL AND response_json IS NULL)",
            name="state_payload",
        ),
    )
    consultation_id: Mapped[UUID] = mapped_column(
        ForeignKey("consultations.id", ondelete="CASCADE")
    )
    request_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(String(16))
    request_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), server_default="PROCESSING")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_json: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))


class QuestionRecord(Identity, Created, Base):
    __tablename__ = "question_records"
    __table_args__ = (CheckConstraint("kind IN ('SURVEY', 'CHAT')", name="kind"),)
    consultation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("consultations.id", ondelete="SET NULL")
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    origin_key: Mapped[str] = mapped_column(String(160), unique=True)
    kind: Mapped[str] = mapped_column(String(16))
    catalog_version: Mapped[str] = mapped_column(String(80))
    answers_json: Mapped[dict] = mapped_column(JSONB)
    masked_question: Mapped[str | None] = mapped_column(Text)
    retrieval_meta_json: Mapped[dict] = mapped_column(JSONB)
    retained_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Result(Identity, Created, Base):
    __tablename__ = "results"
    __table_args__ = (
        Index("ix_results_owner_created_id", "owner_user_id", "created_at", "id"),
        Index("ix_results_retained_until", "retained_until"),
    )
    consultation_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("consultations.id", ondelete="SET NULL")
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    request_run_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("request_runs.id", ondelete="SET NULL")
    )
    question_record_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("question_records.id", ondelete="SET NULL")
    )
    input_snapshot_json: Mapped[dict] = mapped_column(JSONB)
    payload_json: Mapped[dict] = mapped_column(JSONB)
    retained_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Message(Identity, Created, Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("request_run_id", "role"),
        CheckConstraint("role IN ('USER', 'ASSISTANT')", name="role"),
    )
    consultation_id: Mapped[UUID] = mapped_column(
        ForeignKey("consultations.id", ondelete="CASCADE")
    )
    request_run_id: Mapped[UUID] = mapped_column(ForeignKey("request_runs.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    citations_json: Mapped[list] = mapped_column(JSONB)


class KnowledgeDocument(Identity, Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        Index("ix_knowledge_documents_set_status", "knowledge_set_id", "status"),
        Index("ix_knowledge_documents_source_key", "source_key"),
        CheckConstraint("kind IN ('LAW_CRITERIA', 'LH_OPERATION', 'SAFETY_SOURCE')", name="kind"),
        CheckConstraint("status IN ('DRAFT', 'APPROVED', 'WITHDRAWN')", name="status"),
        CheckConstraint(
            "status <> 'APPROVED' OR (reviewed_at IS NOT NULL AND review_until IS NOT NULL"
            " AND review_until > reviewed_at"
            " AND reviewer_key IS NOT NULL)",
            name="approved_review",
        ),
        CheckConstraint(
            "status <> 'WITHDRAWN' OR (withdrawn_at IS NOT NULL AND withdrawal_reason IS NOT NULL)",
            name="withdrawal",
        ),
    )
    knowledge_set_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_sets.id", ondelete="CASCADE")
    )
    source_key: Mapped[str] = mapped_column(String(160))
    version_label: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    normalized_text: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    scope_json: Mapped[dict] = mapped_column(JSONB)
    effective_date: Mapped[date | None] = mapped_column(Date)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewer_key: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), server_default="DRAFT")
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawal_reason: Mapped[str | None] = mapped_column(Text)


class KnowledgeChunk(Identity, Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "ordinal"),
        CheckConstraint("ordinal >= 0", name="ordinal"),
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    locator: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedded_content_hash: Mapped[str | None] = mapped_column(String(64))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    metadata_json: Mapped[dict] = mapped_column(JSONB)


class DeletionLog(Identity, Base):
    __tablename__ = "deletion_log"
    __table_args__ = (CheckConstraint("expires_at > deleted_at", name="expiry"),)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[UUID]
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
