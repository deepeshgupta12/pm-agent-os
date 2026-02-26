from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_access, require_workspace_role_min
from app.core.chunker import chunk_text
from app.core.config import settings
from app.core.embeddings import embed_texts
from app.db.session import get_db
from app.db.models import Connector, IngestionJob, User
from app.db.retrieval_models import Source, Document, Chunk, Embedding
from app.schemas.connectors import (
    ConnectorCreateIn,
    ConnectorUpdateIn,
    ConnectorOut,
    DocsIngestionJobCreateIn,
    IngestionJobOut,
)

router = APIRouter(tags=["connectors"])


def _iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_out(c: Connector) -> ConnectorOut:
    return ConnectorOut(
        id=str(c.id),
        workspace_id=str(c.workspace_id),
        type=c.type,
        name=c.name,
        status=c.status,
        config=c.config or {},
        last_sync_at=_iso(c.last_sync_at),
        last_error=c.last_error,
    )


def _job_out(j: IngestionJob) -> IngestionJobOut:
    return IngestionJobOut(
        id=str(j.id),
        workspace_id=str(j.workspace_id),
        connector_id=str(j.connector_id) if j.connector_id else None,
        source_id=str(j.source_id) if j.source_id else None,
        kind=j.kind,
        status=j.status,
        timeframe=j.timeframe or {},
        params=j.params or {},
        stats=j.stats or {},
        started_at=_iso(j.started_at),
        finished_at=_iso(j.finished_at),
        created_by_user_id=str(j.created_by_user_id),
        created_at=_iso(j.created_at),
    )


def _get_or_create_source_for_connector(db: Session, workspace_id: uuid.UUID, connector: Connector) -> Source:
    # One retrieval source per connector (workspace + type + name)
    s = db.execute(
        select(Source).where(
            Source.workspace_id == workspace_id,
            Source.type == connector.type,
            Source.name == connector.name,
        )
    ).scalar_one_or_none()

    if s:
        # ensure connector_id is stamped in config
        cfg = s.config or {}
        if cfg.get("connector_id") != str(connector.id):
            cfg["connector_id"] = str(connector.id)
            s.config = cfg
            db.add(s)
            db.commit()
            db.refresh(s)
        return s

    s = Source(
        workspace_id=workspace_id,
        type=connector.type,
        name=connector.name,
        config={"connector_id": str(connector.id)},
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _upsert_document_and_chunks(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    source: Source,
    job_id: uuid.UUID,
    connector: Connector,
    external_id: str,
    title: str,
    text: str,
    extra_meta: dict,
    upsert: bool,
) -> tuple[Document, int, bool]:
    """
    Returns: (doc, chunks_created, was_updated)
    Identity: (workspace_id, source_id, external_id)
    Behavior: If upsert and exists -> replace raw_text, title, meta and re-chunk (delete prior chunks).
    """
    existing: Document | None = None
    if upsert and external_id:
        existing = db.execute(
            select(Document).where(
                Document.workspace_id == workspace_id,
                Document.source_id == source.id,
                Document.external_id == external_id,
            )
        ).scalar_one_or_none()

    now = datetime.now(timezone.utc)

    provenance = {
        "connector": {"id": str(connector.id), "type": connector.type, "name": connector.name},
        "ingestion_job_id": str(job_id),
        "external_id": external_id,
        "fetched_at": now.isoformat().replace("+00:00", "Z"),
    }

    if existing:
        # delete old chunks (embeddings cascade via relationship in retrieval_models)
        for ch in list(existing.chunks):
            db.delete(ch)
        db.flush()

        meta = existing.meta or {}
        meta.update(extra_meta or {})
        meta["provenance"] = provenance
        meta["format"] = "text"
        meta["connector"] = connector.type

        existing.title = title
        existing.raw_text = text
        existing.meta = meta
        db.add(existing)
        db.commit()
        db.refresh(existing)
        doc = existing
        was_updated = True
    else:
        meta = {}
        meta.update(extra_meta or {})
        meta["provenance"] = provenance
        meta["format"] = "text"
        meta["connector"] = connector.type

        doc = Document(
            workspace_id=workspace_id,
            source_id=source.id,
            external_id=external_id,
            title=title,
            raw_text=text,
            meta=meta,
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        was_updated = False

    # chunk
    parts = chunk_text(
        text,
        chunk_size=settings.CHUNK_SIZE_CHARS,
        overlap=settings.CHUNK_OVERLAP_CHARS,
    )

    chunks_created = 0
    chunks: list[Chunk] = []
    for i, (start, end, txt) in enumerate(parts):
        ch_meta = {"start": start, "end": end, "ingestion_job_id": str(job_id), "external_id": external_id}
        chunks.append(
            Chunk(
                document_id=doc.id,
                chunk_index=i,
                text=txt,
                meta=ch_meta,
            )
        )

    if chunks:
        db.add_all(chunks)
        db.commit()
        chunks_created = len(chunks)

    return doc, chunks_created, was_updated


def _embed_chunks_for_document(db: Session, doc: Document) -> int:
    chunks = (
        db.execute(select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.chunk_index.asc()))
        .scalars()
        .all()
    )
    if not chunks:
        return 0

    # embed everything in one go (simple V1)
    vectors = embed_texts([c.text for c in chunks])

    embedded = 0
    for c, vec in zip(chunks, vectors):
        emb = Embedding(chunk_id=c.id, model=settings.EMBEDDINGS_MODEL, embedding=vec)
        db.add(emb)
        db.commit()
        db.refresh(emb)

        # backfill vector column; embeddings table has embedding_vec created by migration
        db.execute(
            select(1).execution_options(autocommit=True)  # harmless noop, keeps pattern consistent
        )
        db.execute(
            # raw SQL update is used elsewhere; keep consistent
            # cast text -> vector handled by DB
            # note: Embedding model doesn't expose embedding_vec in SQLAlchemy
            # we update it directly here
            sa_text("UPDATE embeddings SET embedding_vec = CAST(:v AS vector) WHERE id = :id"),
            {"v": vec, "id": str(emb.id)},
        )
        db.commit()
        embedded += 1

    return embedded


# NOTE: use SQLAlchemy text safely without adding new dependency imports at top
from sqlalchemy import text as sa_text  # noqa: E402


@router.get("/workspaces/{workspace_id}/connectors", response_model=list[ConnectorOut])
def list_connectors(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)
    items = (
        db.execute(select(Connector).where(Connector.workspace_id == ws.id).order_by(Connector.created_at.desc()))
        .scalars()
        .all()
    )
    return [_to_out(c) for c in items]


@router.post("/workspaces/{workspace_id}/connectors", response_model=ConnectorOut)
def create_connector(
    workspace_id: str,
    payload: ConnectorCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "admin", db, user)

    ctype = payload.type.strip().lower()
    name = payload.name.strip()

    if ctype not in {"docs", "jira", "github", "slack", "support", "analytics"}:
        raise HTTPException(status_code=400, detail="Invalid connector type")

    existing = db.execute(
        select(Connector).where(Connector.workspace_id == ws.id, Connector.type == ctype, Connector.name == name)
    ).scalar_one_or_none()

    if existing:
        existing.config = payload.config or {}
        existing.status = "connected"
        existing.updated_at = datetime.now(timezone.utc)
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return _to_out(existing)

    c = Connector(
        workspace_id=ws.id,
        type=ctype,
        name=name,
        status="connected",
        config=payload.config or {},
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _to_out(c)


@router.patch("/connectors/{connector_id}", response_model=ConnectorOut)
def update_connector(
    connector_id: str,
    payload: ConnectorUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    c = db.get(Connector, uuid.UUID(connector_id))
    if not c:
        raise HTTPException(status_code=404, detail="Connector not found")

    require_workspace_role_min(str(c.workspace_id), "admin", db, user)

    if payload.name is not None:
        c.name = payload.name.strip()

    if payload.status is not None:
        c.status = payload.status.strip().lower()

    if payload.config is not None:
        c.config = payload.config

    db.add(c)
    db.commit()
    db.refresh(c)
    return _to_out(c)


@router.post("/connectors/{connector_id}/sync", response_model=ConnectorOut)
def trigger_sync(
    connector_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    c = db.get(Connector, uuid.UUID(connector_id))
    if not c:
        raise HTTPException(status_code=404, detail="Connector not found")

    require_workspace_role_min(str(c.workspace_id), "member", db, user)

    c.last_sync_at = datetime.now(timezone.utc)
    c.last_error = None
    db.add(c)
    db.commit()
    db.refresh(c)
    return _to_out(c)


# -------------------------
# V1 Step 2: REAL ingestion job (sync execution)
# -------------------------
@router.post("/workspaces/{workspace_id}/connectors/{connector_id}/ingestion-jobs/docs", response_model=IngestionJobOut)
def run_docs_ingestion_job(
    workspace_id: str,
    connector_id: str,
    payload: DocsIngestionJobCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    # member+ can ingest
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)

    c = db.get(Connector, uuid.UUID(connector_id))
    if not c or str(c.workspace_id) != str(ws.id):
        raise HTTPException(status_code=404, detail="Connector not found")

    if c.type != "docs":
        raise HTTPException(status_code=400, detail="Connector type must be docs")

    src = _get_or_create_source_for_connector(db, ws.id, c)

    job = IngestionJob(
        workspace_id=ws.id,
        connector_id=c.id,
        source_id=src.id,
        kind="docs_sync",
        status="queued",
        timeframe=payload.timeframe or {},
        params=payload.params or {},
        stats={
            "docs_seen": len(payload.docs or []),
            "docs_created": 0,
            "docs_updated": 0,
            "chunks_created": 0,
            "embedded_chunks": 0,
            "errors": 0,
            "error_samples": [],
        },
        created_by_user_id=user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # execute synchronously for V1
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    db.add(job)
    db.commit()
    db.refresh(job)

    stats = job.stats or {}
    try:
        embedded_total = 0
        for d in payload.docs or []:
            doc, chunks_created, was_updated = _upsert_document_and_chunks(
                db,
                workspace_id=ws.id,
                source=src,
                job_id=job.id,
                connector=c,
                external_id=d.external_id,
                title=d.title,
                text=d.text,
                extra_meta=d.meta or {},
                upsert=payload.upsert,
            )

            stats["chunks_created"] = int(stats.get("chunks_created", 0)) + int(chunks_created)
            if was_updated:
                stats["docs_updated"] = int(stats.get("docs_updated", 0)) + 1
            else:
                stats["docs_created"] = int(stats.get("docs_created", 0)) + 1

            if payload.embed_after:
                # embed all chunks for this doc (simple V1)
                # NOTE: embedding requires OPENAI_API_KEY set
                vectors = embed_texts([c2.text for c2 in doc.chunks])
                for ch, vec in zip(doc.chunks, vectors):
                    emb = Embedding(chunk_id=ch.id, model=settings.EMBEDDINGS_MODEL, embedding=vec)
                    db.add(emb)
                    db.commit()
                    db.refresh(emb)

                    db.execute(sa_text("UPDATE embeddings SET embedding_vec = CAST(:v AS vector) WHERE id = :id"),
                               {"v": vec, "id": str(emb.id)})
                    db.commit()
                    embedded_total += 1

        stats["embedded_chunks"] = int(stats.get("embedded_chunks", 0)) + int(embedded_total)
        job.stats = stats
        job.status = "success"
        job.finished_at = datetime.now(timezone.utc)

        # stamp connector last_sync_at too
        c.last_sync_at = datetime.now(timezone.utc)
        c.last_error = None

        db.add(job)
        db.add(c)
        db.commit()
        db.refresh(job)
        return _job_out(job)

    except Exception as e:
        stats["errors"] = int(stats.get("errors", 0)) + 1
        samples = list(stats.get("error_samples", []))[:10]
        samples.append({"error": str(e)})
        stats["error_samples"] = samples

        job.stats = stats
        job.status = "failed"
        job.finished_at = datetime.now(timezone.utc)

        c.last_error = str(e)

        db.add(job)
        db.add(c)
        db.commit()
        db.refresh(job)
        raise