from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional, List

from sqlalchemy import DateTime, ForeignKey, String, Text, Integer, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # relationships
    workspaces: Mapped[List["Workspace"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship(back_populates="workspaces")
    runs: Mapped[List["Run"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")


class AgentDefinition(Base):
    """
    Represents an agent 'capability' (one of the 16).
    Seeded into DB for visibility + future customization.
    """
    __tablename__ = "agent_definitions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g., "prd"
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="v0")

    # JSON schema-like definitions for future. For V0, store minimal.
    input_schema: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output_artifact_types: Mapped[List[str]] = mapped_column(JSONB, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    runs: Mapped[List["Run"]] = relationship(back_populates="agent")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_definitions.id"), nullable=False, index=True)

    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")  # created|running|completed|failed
    input_payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    output_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="runs")
    agent: Mapped["AgentDefinition"] = relationship(back_populates="runs")

    artifacts: Mapped[List["Artifact"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    evidence_items: Mapped[List["Evidence"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id"), nullable=False, index=True)

    type: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g., "prd"
    title: Mapped[str] = mapped_column(String(240), nullable=False, default="Untitled")

    # Markdown content for V0
    content_md: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Versioning model: each row is one version; group by logical_key
    logical_key: Mapped[str] = mapped_column(String(64), nullable=False)  # stable key within a run, e.g., "prd"
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")  # draft|final

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    run: Mapped["Run"] = relationship(back_populates="artifacts")


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id"), nullable=False, index=True)

    # V0 minimal: evidence tied to a run; later we can tie to artifact + citations.
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # metric|snippet|link
    source_name: Mapped[str] = mapped_column(String(120), nullable=False, default="manual")
    source_ref: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # url/id
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    meta: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    run: Mapped["Run"] = relationship(back_populates="evidence_items")