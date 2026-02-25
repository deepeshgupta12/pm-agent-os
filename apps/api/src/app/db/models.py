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

    workspaces: Mapped[List["Workspace"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    refresh_tokens: Mapped[List["RefreshToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")

    # RBAC: memberships
    workspace_memberships: Mapped[List["WorkspaceMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped["User"] = relationship(back_populates="workspaces")
    runs: Mapped[List["Run"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")

    # RBAC: members
    members: Mapped[List["WorkspaceMember"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )

    # Pipelines
    pipeline_templates: Mapped[List["PipelineTemplate"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    pipeline_runs: Mapped[List["PipelineRun"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # admin | member | viewer
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="member")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    workspace: Mapped["Workspace"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="workspace_memberships")


class AgentDefinition(Base):
    __tablename__ = "agent_definitions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="v0")

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

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_definitions.id"), nullable=False, index=True)

    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
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
    logs: Mapped[List["RunLog"]] = relationship(back_populates="run", cascade="all, delete-orphan")

    pipeline_steps: Mapped[List["PipelineStep"]] = relationship(back_populates="run")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id"), nullable=False, index=True)

    type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False, default="Untitled")
    content_md: Mapped[str] = mapped_column(Text, nullable=False, default="")

    logical_key: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # draft|in_review|final
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    run: Mapped["Run"] = relationship(back_populates="artifacts")

    # Approvals (auditable)
    reviews: Mapped[List["ArtifactReview"]] = relationship(
        back_populates="artifact", cascade="all, delete-orphan"
    )


class ArtifactReview(Base):
    """
    Auditable review record for a specific artifact version (artifact_id).
    Lifecycle:
      - requested: created with requested_by + requested_at (+ request_comment)
      - decided: approved/rejected with decided_by + decided_at (+ decision_comment)
    """
    __tablename__ = "artifact_reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    artifact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("artifacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # requested|approved|rejected
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="requested")

    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    request_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    decided_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    artifact: Mapped["Artifact"] = relationship(back_populates="reviews")


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id"), nullable=False, index=True)

    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_name: Mapped[str] = mapped_column(String(120), nullable=False, default="manual")
    source_ref: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    meta: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    run: Mapped["Run"] = relationship(back_populates="evidence_items")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class RunLog(Base):
    __tablename__ = "run_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    meta: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    run: Mapped["Run"] = relationship(back_populates="logs")


# ------------------------
# Pipelines (V1)
# ------------------------
class PipelineTemplate(Base):
    __tablename__ = "pipeline_templates"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    definition_json: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    workspace: Mapped["Workspace"] = relationship(back_populates="pipeline_templates")
    runs: Mapped[List["PipelineRun"]] = relationship(back_populates="template", cascade="all, delete-orphan")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    template_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pipeline_templates.id"), nullable=False, index=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    current_step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    workspace: Mapped["Workspace"] = relationship(back_populates="pipeline_runs")
    template: Mapped["PipelineTemplate"] = relationship(back_populates="runs")
    steps: Mapped[List["PipelineStep"]] = relationship(back_populates="pipeline_run", cascade="all, delete-orphan")


class PipelineStep(Base):
    __tablename__ = "pipeline_steps"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    pipeline_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pipeline_runs.id"), nullable=False, index=True)
    step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    step_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    input_payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    run_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id"), nullable=True, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    pipeline_run: Mapped["PipelineRun"] = relationship(back_populates="steps")
    run: Mapped[Optional["Run"]] = relationship(back_populates="pipeline_steps")