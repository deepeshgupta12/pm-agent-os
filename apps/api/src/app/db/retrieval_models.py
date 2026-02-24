from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional, List

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Source(Base):
    """
    A source is a logical connector or manual upload bucket within a workspace.
    Examples:
    - type=manual (user pasted markdown)
    - type=github (read-only sync)
    - type=jira (read-only sync)
    """
    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True
    )

    type: Mapped[str] = mapped_column(String(32), nullable=False)  # manual|github|jira|docs|support|analytics
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    config: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    documents: Mapped[List["Document"]] = relationship(back_populates="source", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False, index=True
    )

    external_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False, default="Untitled")

    raw_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    meta: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    source: Mapped["Source"] = relationship(back_populates="documents")
    chunks: Mapped[List["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True
    )

    chunk_index: Mapped[int] = mapped_column(nullable=False)  # 0..N per document
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    meta: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    document: Mapped["Document"] = relationship(back_populates="chunks")
    embeddings: Mapped[List["Embedding"]] = relationship(back_populates="chunk", cascade="all, delete-orphan")


class Embedding(Base):
    __tablename__ = "embeddings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chunks.id"), nullable=False, index=True
    )
    model: Mapped[str] = mapped_column(String(80), nullable=False)

    # Placeholder: the real vector column is created via migration as embedding_vec vector(1536).
    # Keeping this field avoids SQLAlchemy type dependency on pgvector for now.
    embedding: Mapped[Optional[List[float]]] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    chunk: Mapped["Chunk"] = relationship(back_populates="embeddings")