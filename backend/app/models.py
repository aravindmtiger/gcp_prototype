"""ORM models.

Every row that belongs to a user carries ``owner_email`` so queries can be scoped
per user (Row-level tenancy is enforced in the routers and services, never trusted
from the client).
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import get_settings


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Flow(Base):
    """A saved agentflow: a named, ordered list of nodes (see schemas.FlowDefinition)."""

    __tablename__ = "flows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    definition: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Run(Base):
    """One execution of a flow. Status: queued -> running -> succeeded | failed."""

    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    flow_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("flows.id", ondelete="CASCADE"), index=True
    )
    owner_email: Mapped[str] = mapped_column(String(320), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    input_message: Mapped[str] = mapped_column(Text)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentChunk(Base):
    """A chunk of ingested text with its embedding, searched by the retriever node."""

    __tablename__ = "document_chunks"
    __table_args__ = (Index("ix_document_chunks_owner_collection", "owner_email", "collection"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_email: Mapped[str] = mapped_column(String(320))
    collection: Mapped[str] = mapped_column(String(100))
    source: Mapped[str] = mapped_column(String(500))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(get_settings().embedding_dim))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeSource(Base):
    """A data source for the Knowledge Studio.

    ``kind="structured"``: a BigQuery or Cloud SQL table used by the SQL Executor tool.
    ``kind="unstructured"``: a Vertex AI RAG corpus used by the Knowledge Retriever tool.
    """

    __tablename__ = "knowledge_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text, default="")
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GuardrailTemplate(Base):
    """A Model Armor or Sensitive Data Protection template attached to agents."""

    __tablename__ = "guardrail_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str] = mapped_column(String(200))
    # Comma-separated: "model_armor", "sdp", or "model_armor,sdp" when both are on.
    provider: Mapped[str] = mapped_column(String(20))
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def providers(self) -> list[str]:
        return [p for p in self.provider.split(",") if p]


class AppUser(Base):
    """A signed-in person and their role. Admins are also listed in ADMIN_EMAILS."""

    __tablename__ = "app_users"

    email: Mapped[str] = mapped_column(String(320), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), default="platform_user")
    # Google's stable account ID (the token's sub claim), set on sign-in.
    google_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SpanRecord(Base):
    """One OpenTelemetry span received over OTLP. Owned by the user whose token sent it."""

    __tablename__ = "spans"
    __table_args__ = (UniqueConstraint("trace_id", "span_id", name="uq_span_trace_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_email: Mapped[str] = mapped_column(String(320), index=True)
    trace_id: Mapped[str] = mapped_column(String(32), index=True)
    span_id: Mapped[str] = mapped_column(String(16))
    parent_span_id: Mapped[str] = mapped_column(String(16), default="")
    name: Mapped[str] = mapped_column(String(300))
    service_name: Mapped[str] = mapped_column(String(200), default="")
    kind: Mapped[str] = mapped_column(String(40), default="")
    status_code: Mapped[str] = mapped_column(String(10), default="unset")
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[float] = mapped_column(Float)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class McpServer(Base):
    """An MCP server this platform connects to as a client, with its last-known tools."""

    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    endpoint_url: Mapped[str] = mapped_column(String(2000), default="")
    # none | google_id_token | bearer_token | api_key_header
    auth_type: Mapped[str] = mapped_column(String(20), default="none")
    # Holds header names and Secret Manager references only, never secret values.
    auth_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Tools discovered from the server on the last successful connect.
    tools: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    # draft | connected | error
    status: Mapped[str] = mapped_column(String(20), default="draft")
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentDraft(Base):
    """An agent built on the canvas. ``adk_source`` is the generated ADK agent code.

    Status: draft -> in_review -> approved | rejected; approved -> deployed (later step).
    """

    __tablename__ = "agent_drafts"
    # Agent names are unique across the platform: the name is the ADK package name.
    __table_args__ = (UniqueConstraint("name", name="uq_agent_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_email: Mapped[str] = mapped_column(String(320), index=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    workflow: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # The canvas graph (nodes with positions, edges) and the ADK graph compiled from it.
    architecture: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    adk_graph: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    adk_source: Mapped[str] = mapped_column(Text, default="")
    guardrail_template_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Deployment(Base):
    """A deployment of an approved agent. Status: queued -> running -> succeeded | failed."""

    __tablename__ = "deployments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_drafts.id", ondelete="CASCADE"), index=True
    )
    owner_email: Mapped[str] = mapped_column(String(320), index=True)
    target: Mapped[str] = mapped_column(String(20))
    session_backend: Mapped[str] = mapped_column(String(30))
    memory_backend: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    endpoint_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    agent_identity: Mapped[str | None] = mapped_column(String(320), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Approval(Base):
    """A review request for an agent. Status: pending -> approved | rejected."""

    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    agent_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_drafts.id", ondelete="CASCADE"), index=True
    )
    requested_by: Mapped[str] = mapped_column(String(320), index=True)
    approver_group: Mapped[str] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    decided_by: Mapped[str | None] = mapped_column(String(320), nullable=True)
    decision_comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
