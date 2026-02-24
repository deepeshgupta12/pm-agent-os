from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, text as sql_text
from sqlalchemy.orm import Session

from app.core.chunker import chunk_text
from app.core.config import settings
from app.core.embeddings import embed_texts
from app.db.retrieval_models import Source, Document, Chunk, Embedding


def get_or_create_source(db: Session, *, workspace_id: uuid.UUID, type: str, name: str, config: Dict[str, Any]) -> Source:
    s = db.execute(select(Source).where(Source.workspace_id == workspace_id, Source.type == type)).scalar_one_or_none()
    if s:
        # Update config/name (V1 simple overwrite)
        s.name = name
        s.config = config
        db.add(s)
        db.commit()
        db.refresh(s)
        return s

    s = Source(workspace_id=workspace_id, type=type, name=name, config=config)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def upsert_document(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    source_id: uuid.UUID,
    external_id: Optional[str],
    title: str,
    raw_text: str,
    meta: Dict[str, Any],
) -> Tuple[Document, bool]:
    """
    Returns (doc, created_new).
    Idempotency: if external_id exists for workspace+source, update existing.
    """
    doc: Optional[Document] = None
    if external_id:
        doc = db.execute(
            select(Document).where(
                Document.workspace_id == workspace_id,
                Document.source_id == source_id,
                Document.external_id == external_id,
            )
        ).scalar_one_or_none()

    if doc:
        doc.title = title
        doc.raw_text = raw_text
        doc.meta = meta
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc, False

    doc = Document(
        workspace_id=workspace_id,
        source_id=source_id,
        external_id=external_id,
        title=title,
        raw_text=raw_text,
        meta=meta,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc, True


def rebuild_chunks(db: Session, *, document_id: uuid.UUID, raw_text: str) -> int:
    """
    Rebuild chunks for a document (delete old chunks + embeddings, then re-chunk).
    """
    # Delete embeddings for chunks of this doc
    db.execute(
        sql_text(
            """
            DELETE FROM embeddings
            WHERE chunk_id IN (SELECT id FROM chunks WHERE document_id = :doc_id)
            """
        ),
        {"doc_id": str(document_id)},
    )
    # Delete chunks
    db.execute(sql_text("DELETE FROM chunks WHERE document_id = :doc_id"), {"doc_id": str(document_id)})
    db.commit()

    parts = chunk_text(
        raw_text,
        chunk_size=settings.CHUNK_SIZE_CHARS,
        overlap=settings.CHUNK_OVERLAP_CHARS,
    )
    chunks: List[Chunk] = []
    for i, (start, end, txt) in enumerate(parts):
        chunks.append(
            Chunk(
                document_id=document_id,
                chunk_index=i,
                text=txt,
                meta={"start": start, "end": end},
            )
        )
    if chunks:
        db.add_all(chunks)
        db.commit()

    return len(chunks)


def embed_document(db: Session, *, document_id: uuid.UUID) -> int:
    """
    Embed all chunks for a document that don't already have embeddings for the current model.
    Ensures embedding_vec is populated.
    """
    chunks = db.execute(select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index.asc())).scalars().all()
    if not chunks:
        return 0

    chunk_ids = [c.id for c in chunks]

    # Backfill vector for existing rows (jsonb -> text -> vector)
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

    existing_chunk_ids = set(
        db.execute(
            select(Embedding.chunk_id).where(
                Embedding.model == settings.EMBEDDINGS_MODEL,
                Embedding.chunk_id.in_(chunk_ids),
            )
        ).scalars().all()
    )
    todo = [c for c in chunks if c.id not in existing_chunk_ids]
    if not todo:
        return 0

    vectors = embed_texts([c.text for c in todo])

    embedded = 0
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
        embedded += 1

    return embedded