from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
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
from app.db.models import User, RetrievalRequest, RetrievalRequestItem
from app.db.retrieval_models import Source, Document, Chunk, Embedding
from app.schemas.retrieval import (
    IngestResult,
    EmbedResult,
    RetrieveResponse,
    DocumentOut,
    RetrievalRequestOut,
    RetrievalRequestItemOut,
)

router = APIRouter(tags=["retrieval"])


# -------------------------
# V0 Docs: simple ingestion models (kept)
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


def _parse_source_types(source_types: Optional[str]) -> List[str]:
    if not source_types:
        return []
    return [t.strip().lower() for t in source_types.split(",") if t.strip()]


def _compute_timeframe(
    *,
    preset: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
) -> tuple[dict, Optional[datetime], Optional[datetime]]:
    """
    Returns (timeframe_json, start_ts, end_ts) in UTC.

    Supported:
      - preset: 7d | 30d | 90d
      - custom: start_date/end_date (YYYY-MM-DD)
    """
    now = datetime.now(timezone.utc)

    if preset:
        p = preset.strip().lower()
        if p not in {"7d", "30d", "90d"}:
            raise HTTPException(status_code=400, detail="Invalid timeframe_preset (use 7d,30d,90d or omit)")
        days = int(p.replace("d", ""))
        start_ts = now - timedelta(days=days)
        end_ts = now
        return {"preset": p}, start_ts, end_ts

    # custom
    if not start_date and not end_date:
        return {}, None, None

    def parse_ymd(s: str) -> datetime:
        try:
            dt = datetime.strptime(s, "%Y-%m-%d")
            return dt.replace(tzinfo=timezone.utc)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid date format (use YYYY-MM-DD)")

    start_ts = parse_ymd(start_date) if start_date else None
    end_ts = parse_ymd(end_date) if end_date else None

    # If end_date provided, make it end-of-day inclusive
    if end_ts is not None:
        end_ts = end_ts + timedelta(days=1) - timedelta(seconds=1)

    tf: dict = {"preset": "custom"}
    if start_date:
        tf["start_date"] = start_date
    if end_date:
        tf["end_date"] = end_date

    return tf, start_ts, end_ts


# -------------------------
# Sources: Docs + Manual
# -------------------------
@router.get("/workspaces/{workspace_id}/sources", response_model=list[SourceOut])
def list_sources(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
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
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)

    s = _get_or_create_source(db, ws.id, "docs", payload.name.strip() or "Docs")
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
# V0 docs ingestion (kept)
# -------------------------
@router.post("/workspaces/{workspace_id}/documents/docs", response_model=IngestResult)
def ingest_docs_text(
    workspace_id: str,
    payload: DocIngestIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
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
    ws, _role = require_workspace_access(workspace_id, db, user)

    q = select(Document).where(Document.workspace_id == ws.id)

    if source_type:
        q = q.join(Source, Source.id == Document.source_id).where(Source.type == source_type)

    q = q.order_by(Document.created_at.desc())
    docs = db.execute(q).scalars().all()
    return [_doc_out(d) for d in docs]


# -------------------------
# Embeddings (optional)
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

    require_workspace_role_min(str(doc.workspace_id), "member", db, user)

    chunks = (
        db.execute(select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.chunk_index.asc()))
        .scalars()
        .all()
    )
    if not chunks:
        raise HTTPException(status_code=400, detail="No chunks to embed")

    chunk_ids = [c.id for c in chunks]

    # Backfill embedding_vec if needed
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

    # If embeddings are not configured, fail clearly
    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY is missing for embeddings")

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
# Retrieval (viewer+): timeframe + source filtering IN hybrid search
# -------------------------
@router.get("/workspaces/{workspace_id}/retrieve", response_model=RetrieveResponse)
def retrieve(
    workspace_id: str,
    q: str = Query(min_length=1, max_length=500),
    k: int = Query(default=8, ge=1, le=50),
    alpha: float = Query(default=0.65, ge=0.0, le=1.0),
    source_types: Optional[str] = Query(default=None, description="Comma-separated source types, e.g. docs,manual"),
    timeframe_preset: Optional[str] = Query(default=None, description="7d|30d|90d"),
    start_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)

    stypes = _parse_source_types(source_types)
    timeframe_json, start_ts, end_ts = _compute_timeframe(
        preset=timeframe_preset,
        start_date=start_date,
        end_date=end_date,
    )

    # Run retrieval with filters inside core
    items = hybrid_retrieve(
        db,
        workspace_id=workspace_id,
        q=q,
        k=k,
        alpha=alpha,
        source_types=stypes or None,
        start_ts=start_ts,
        end_ts=end_ts,
    )

    # ---- V1 traceability: store retrieval request + items
    rr = RetrievalRequest(
        workspace_id=ws.id,
        created_by_user_id=user.id,
        q=q,
        k=int(k),
        alpha=float(alpha),
        source_types=source_types,
        timeframe=timeframe_json or {},
    )
    db.add(rr)
    db.commit()
    db.refresh(rr)

    for idx, it in enumerate(items, start=1):
        # These are string UUIDs already (from SQL), but handle safely
        def _u(v: Any) -> Optional[uuid.UUID]:
            try:
                return uuid.UUID(str(v)) if v else None
            except Exception:
                return None

        ri = RetrievalRequestItem(
            request_id=rr.id,
            rank=int(idx),
            chunk_id=_u(it.get("chunk_id")),
            document_id=_u(it.get("document_id")),
            source_id=_u(it.get("source_id")),
            snippet=str(it.get("snippet") or ""),
            meta=it.get("meta") or {},
            score_fts=float(it.get("score_fts") or 0.0),
            score_vec=float(it.get("score_vec") or 0.0),
            score_hybrid=float(it.get("score_hybrid") or 0.0),
        )
        db.add(ri)

    db.commit()
    return RetrieveResponse(ok=True, q=q, k=k, alpha=alpha, items=items)


# -------------------------
# V1: Retrieval trace APIs (viewer+)
# -------------------------
@router.get("/workspaces/{workspace_id}/retrieval-requests", response_model=list[RetrievalRequestOut])
def list_retrieval_requests(
    workspace_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)

    rows = (
        db.execute(
            select(RetrievalRequest)
            .where(RetrievalRequest.workspace_id == ws.id)
            .order_by(RetrievalRequest.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )

    out: list[RetrievalRequestOut] = []
    for r in rows:
        out.append(
            RetrievalRequestOut(
                id=str(r.id),
                workspace_id=str(r.workspace_id),
                created_by_user_id=str(r.created_by_user_id),
                q=r.q,
                k=int(r.k),
                alpha=float(r.alpha),
                source_types=r.source_types,
                timeframe=r.timeframe or {},
                created_at=r.created_at.isoformat().replace("+00:00", "Z"),
            )
        )
    return out


@router.get("/retrieval-requests/{request_id}", response_model=RetrievalRequestOut)
def get_retrieval_request(
    request_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    try:
        rid = uuid.UUID(request_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Retrieval request not found")

    rr = db.get(RetrievalRequest, rid)
    if not rr:
        raise HTTPException(status_code=404, detail="Retrieval request not found")

    require_workspace_access(str(rr.workspace_id), db, user)

    return RetrievalRequestOut(
        id=str(rr.id),
        workspace_id=str(rr.workspace_id),
        created_by_user_id=str(rr.created_by_user_id),
        q=rr.q,
        k=int(rr.k),
        alpha=float(rr.alpha),
        source_types=rr.source_types,
        timeframe=rr.timeframe or {},
        created_at=rr.created_at.isoformat().replace("+00:00", "Z"),
    )


@router.get("/retrieval-requests/{request_id}/items", response_model=list[RetrievalRequestItemOut])
def list_retrieval_request_items(
    request_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    try:
        rid = uuid.UUID(request_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Retrieval request not found")

    rr = db.get(RetrievalRequest, rid)
    if not rr:
        raise HTTPException(status_code=404, detail="Retrieval request not found")

    require_workspace_access(str(rr.workspace_id), db, user)

    rows = (
        db.execute(
            select(RetrievalRequestItem)
            .where(RetrievalRequestItem.request_id == rr.id)
            .order_by(RetrievalRequestItem.rank.asc())
        )
        .scalars()
        .all()
    )

    out: list[RetrievalRequestItemOut] = []
    for it in rows:
        out.append(
            RetrievalRequestItemOut(
                id=str(it.id),
                request_id=str(it.request_id),
                rank=int(it.rank),
                chunk_id=str(it.chunk_id) if it.chunk_id else None,
                document_id=str(it.document_id) if it.document_id else None,
                source_id=str(it.source_id) if it.source_id else None,
                snippet=it.snippet or "",
                meta=it.meta or {},
                score_fts=float(it.score_fts or 0.0),
                score_vec=float(it.score_vec or 0.0),
                score_hybrid=float(it.score_hybrid or 0.0),
                created_at=it.created_at.isoformat().replace("+00:00", "Z"),
            )
        )
    return out