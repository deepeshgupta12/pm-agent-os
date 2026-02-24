from __future__ import annotations

import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text as sql_text
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.core.chunker import chunk_text
from app.core.config import settings
from app.core.embeddings import embed_texts
from app.db.session import get_db
from app.db.models import Workspace, User
from app.db.retrieval_models import Source, Document, Chunk, Embedding
from app.schemas.retrieval import DocumentIn, IngestResult, EmbedResult

router = APIRouter(tags=["retrieval"])


def _ensure_workspace_access(db: Session, workspace_id: str, user: User) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if not ws or ws.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


def _get_or_create_manual_source(db: Session, workspace_id: uuid.UUID) -> Source:
    s = db.execute(
        select(Source).where(Source.workspace_id == workspace_id, Source.type == "manual")
    ).scalar_one_or_none()
    if s:
        return s
    s = Source(workspace_id=workspace_id, type="manual", name="Manual Uploads", config={})
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.post("/workspaces/{workspace_id}/documents/manual", response_model=IngestResult)
def ingest_manual_markdown(
    workspace_id: str,
    payload: DocumentIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws = _ensure_workspace_access(db, workspace_id, user)
    src = _get_or_create_manual_source(db, ws.id)

    doc = Document(
        workspace_id=ws.id,
        source_id=src.id,
        external_id=None,
        title=payload.title,
        raw_text=payload.markdown,
        meta={"format": "markdown"},
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    parts = chunk_text(
        payload.markdown,
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
        document={
            "id": str(doc.id),
            "workspace_id": str(doc.workspace_id),
            "source_id": str(doc.source_id),
            "title": doc.title,
            "external_id": doc.external_id,
            "meta": doc.meta,
        },
        chunks_created=len(chunks),
    )


@router.post("/documents/{document_id}/embed", response_model=EmbedResult)
def embed_document_chunks(
    document_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    ws = db.get(Workspace, doc.workspace_id)
    if not ws or ws.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Document not found")

    chunks = db.execute(select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.chunk_index.asc())).scalars().all()
    if not chunks:
        raise HTTPException(status_code=400, detail="No chunks to embed")

    # Find chunks that do NOT already have an embedding_vec for this model
    # We'll treat "has any embedding row with same model" as already embedded.
    existing_chunk_ids = set(
        db.execute(select(Embedding.chunk_id).where(Embedding.model == settings.EMBEDDINGS_MODEL)).scalars().all()
    )
    todo = [c for c in chunks if c.id not in existing_chunk_ids]
    if not todo:
        return EmbedResult(document_id=str(doc.id), model=settings.EMBEDDINGS_MODEL, chunks_embedded=0)

    texts = [c.text for c in todo]
    vectors = embed_texts(texts)

    # Insert embedding rows; set embedding_vec via raw SQL so we avoid python pgvector dependency.
    # We'll store json embedding too for debugging.
    embedded_count = 0
    for c, vec in zip(todo, vectors):
        emb = Embedding(chunk_id=c.id, model=settings.EMBEDDINGS_MODEL, embedding=vec)
        db.add(emb)
        db.commit()
        db.refresh(emb)

        # Update embedding_vec (vector type)
        db.execute(
            sql_text("UPDATE embeddings SET embedding_vec = :v::vector WHERE id = :id"),
            {"v": vec, "id": str(emb.id)},
        )
        db.commit()
        embedded_count += 1

    return EmbedResult(document_id=str(doc.id), model=settings.EMBEDDINGS_MODEL, chunks_embedded=embedded_count)