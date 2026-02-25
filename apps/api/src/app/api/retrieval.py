from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, text as sql_text
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_access, require_workspace_role_min
from app.core.chunker import chunk_text
from app.core.config import settings
from app.core.embeddings import embed_texts
from app.core.retrieval_search import hybrid_retrieve
from app.db.session import get_db
from app.db.models import User
from app.db.retrieval_models import Source, Document, Chunk, Embedding
from app.schemas.retrieval import IngestResult, EmbedResult, RetrieveResponse, DocumentOut

router = APIRouter(tags=["retrieval"])


# -------------------------
# V0 Docs: simple ingestion models
# -------------------------
class DocIngestIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1)
    external_id: Optional[str] = Field(default=None, max_length=256)


class SourceCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class SourceOut(BaseModel):
    id: str
    workspace_id: str
    type: str
    name: str
    config: dict


def _get_or_create_source(db: Session, workspace_id: uuid.UUID, stype: str, default_name: str) -> Source:
    s = db.execute(select(Source).where(Source.workspace_id == workspace_id, Source.type == stype)).scalar_one_or_none()
    if s:
        return s
    s = Source(workspace_id=workspace_id, type=stype, name=default_name, config={})
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _doc_out(doc: Document) -> DocumentOut:
    return DocumentOut(
        id=str(doc.id),
        workspace_id=str(doc.workspace_id),
        source_id=str(doc.source_id),
        title=doc.title,
        external_id=doc.external_id,
        meta=doc.meta or {},
    )


# -------------------------
# Sources: Docs + Manual
# -------------------------
@router.get("/workspaces/{workspace_id}/sources", response_model=list[SourceOut])
def list_sources(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    # viewer+ ok
    ws, _role = require_workspace_access(workspace_id, db, user)

    rows = (
        db.execute(select(Source).where(Source.workspace_id == ws.id).order_by(Source.created_at.desc()))
        .scalars()
        .all()
    )
    return [
        SourceOut(
            id=str(s.id),
            workspace_id=str(s.workspace_id),
            type=s.type,
            name=s.name,
            config=s.config or {},
        )
        for s in rows
    ]


@router.post("/workspaces/{workspace_id}/sources/docs", response_model=SourceOut)
def create_or_get_docs_source(
    workspace_id: str,
    payload: SourceCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    # member+ only (write)
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)

    s = _get_or_create_source(db, ws.id, "docs", payload.name.strip() or "Docs")
    # Update name if previously default and user wants custom
    if payload.name.strip() and s.name != payload.name.strip():
        s.name = payload.name.strip()
        db.add(s)
        db.commit()
        db.refresh(s)

    return SourceOut(
        id=str(s.id),
        workspace_id=str(s.workspace_id),
        type=s.type,
        name=s.name,
        config=s.config or {},
    )


# -------------------------
# V0 Docs ingestion (read-only connector replacement)
# -------------------------
@router.post("/workspaces/{workspace_id}/documents/docs", response_model=IngestResult)
def ingest_docs_text(
    workspace_id: str,
    payload: DocIngestIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    # member+ only
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)

    src = _get_or_create_source(db, ws.id, "docs", "Docs")

    doc = Document(
        workspace_id=ws.id,
        source_id=src.id,
        external_id=payload.external_id,
        title=payload.title,
        raw_text=payload.text,
        meta={"format": "text", "connector": "docs_v0_manual"},
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    parts = chunk_text(
        payload.text,
        chunk_size=settings.CHUNK_SIZE_CHARS,
        overlap=settings.CHUNK_OVERLAP_CHARS,
    )

    chunks: List[Chunk] = []
    for i, (start, end, txt) in enumerate(parts):
        chunks.append(
            Chunk(
                document_id=doc.id,
                chunk_index=i,
                text=txt,
                meta={"start": start, "end": end},
            )
        )

    if chunks:
        db.add_all(chunks)
        db.commit()

    return IngestResult(
        document=_doc_out(doc),
        chunks_created=len(chunks),
    )


@router.get("/workspaces/{workspace_id}/documents", response_model=list[DocumentOut])
def list_documents(
    workspace_id: str,
    source_type: Optional[str] = Query(default=None, description="Filter by source type (docs/manual/github/...)"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    # viewer+ ok
    ws, _role = require_workspace_access(workspace_id, db, user)

    q = select(Document).where(Document.workspace_id == ws.id)

    if source_type:
        # join on sources for type filter
        q = q.join(Source, Source.id == Document.source_id).where(Source.type == source_type)

    q = q.order_by(Document.created_at.desc())
    docs = db.execute(q).scalars().all()
    return [_doc_out(d) for d in docs]


# -------------------------
# Embeddings (optional in V0, already present)
# -------------------------
@router.post("/documents/{document_id}/embed", response_model=EmbedResult)
def embed_document_chunks(
    document_id: str,
    force: bool = Query(default=False, description="If true, re-embed even if embeddings exist."),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # member+ (write)
    require_workspace_role_min(str(doc.workspace_id), "member", db, user)

    chunks = (
        db.execute(select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.chunk_index.asc()))
        .scalars()
        .all()
    )
    if not chunks:
        raise HTTPException(status_code=400, detail="No chunks to embed")

    chunk_ids = [c.id for c in chunks]

    # Repair/backfill: jsonb -> text -> vector
    db.execute(
        sql_text(
            """
            UPDATE embeddings
            SET embedding_vec = (embedding::text)::vector
            WHERE model = :model
              AND chunk_id = ANY(:chunk_ids)
              AND embedding_vec IS NULL
              AND embedding IS NOT NULL
            """
        ),
        {"model": settings.EMBEDDINGS_MODEL, "chunk_ids": chunk_ids},
    )
    db.commit()

    if force:
        todo = chunks
    else:
        existing_chunk_ids = set(
            db.execute(
                select(Embedding.chunk_id).where(
                    Embedding.model == settings.EMBEDDINGS_MODEL,
                    Embedding.chunk_id.in_(chunk_ids),
                )
            )
            .scalars()
            .all()
        )
        todo = [c for c in chunks if c.id not in existing_chunk_ids]

    if not todo:
        return EmbedResult(document_id=str(doc.id), model=settings.EMBEDDINGS_MODEL, chunks_embedded=0)

    texts = [c.text for c in todo]
    vectors = embed_texts(texts)

    embedded_count = 0
    for c, vec in zip(todo, vectors):
        emb = Embedding(chunk_id=c.id, model=settings.EMBEDDINGS_MODEL, embedding=vec)
        db.add(emb)
        db.commit()
        db.refresh(emb)

        db.execute(
            sql_text("UPDATE embeddings SET embedding_vec = CAST(:v AS vector) WHERE id = :id"),
            {"v": vec, "id": str(emb.id)},
        )
        db.commit()
        embedded_count += 1

    return EmbedResult(document_id=str(doc.id), model=settings.EMBEDDINGS_MODEL, chunks_embedded=embedded_count)


# -------------------------
# Retrieval (viewer+)
# -------------------------
@router.get("/workspaces/{workspace_id}/retrieve", response_model=RetrieveResponse)
def retrieve(
    workspace_id: str,
    q: str = Query(min_length=1, max_length=500),
    k: int = Query(default=8, ge=1, le=50),
    alpha: float = Query(default=0.65, ge=0.0, le=1.0),
    source_types: Optional[str] = Query(default=None, description="Comma-separated source types, e.g. docs,manual"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    # viewer+ ok
    ws, _role = require_workspace_access(workspace_id, db, user)

    # Parse optional filter
    allowed_types: list[str] = []
    if source_types:
        allowed_types = [t.strip() for t in source_types.split(",") if t.strip()]

    # Call hybrid_retrieve WITHOUT source_types (since core function doesn't support it yet)
    items = hybrid_retrieve(db, workspace_id=workspace_id, q=q, k=k, alpha=alpha)

    # V0: API-layer filtering by source type (no change to retrieval core)
    if allowed_types:
        allowed_source_ids = set(
            str(x)
            for x in db.execute(
                select(Source.id).where(Source.workspace_id == ws.id, Source.type.in_(allowed_types))
            )
            .scalars()
            .all()
        )
        items = [it for it in items if str(it.get("source_id", "")) in allowed_source_ids]

    return RetrieveResponse(ok=True, q=q, k=k, alpha=alpha, items=items)