from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_access, require_workspace_role_min
from app.core.retrieval_search import hybrid_retrieve
from app.db.session import get_db
from app.db.models import Run, Evidence, User
from app.schemas.core import EvidenceCreateIn, EvidenceOut

router = APIRouter(tags=["evidence"])


class AutoEvidenceIn(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    k: int = Field(default=6, ge=1, le=20)
    alpha: float = Field(default=0.65, ge=0.0, le=1.0)


def _parse_uuid(id_str: str) -> uuid.UUID:
    try:
        return uuid.UUID(id_str)
    except Exception:
        raise HTTPException(status_code=404, detail="Run not found")


def _get_run_or_404(db: Session, run_id: str) -> Run:
    run_uuid = _parse_uuid(run_id)
    run = db.get(Run, run_uuid)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/runs/{run_id}/evidence", response_model=EvidenceOut)
def add_evidence(
    run_id: str,
    payload: EvidenceCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    run = _get_run_or_404(db, run_id)

    # member+ only
    require_workspace_role_min(str(run.workspace_id), "member", db, user)

    ev = Evidence(
        run_id=run.id,
        kind=payload.kind,
        source_name=payload.source_name,
        source_ref=payload.source_ref,
        excerpt=payload.excerpt,
        meta=payload.meta,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)

    return EvidenceOut(
        id=str(ev.id),
        run_id=str(ev.run_id),
        kind=ev.kind,
        source_name=ev.source_name,
        source_ref=ev.source_ref,
        excerpt=ev.excerpt,
        meta=ev.meta,
    )


@router.get("/runs/{run_id}/evidence", response_model=list[EvidenceOut])
def list_evidence(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    run = _get_run_or_404(db, run_id)

    # viewer+ read ok
    require_workspace_access(str(run.workspace_id), db, user)

    items = (
        db.execute(select(Evidence).where(Evidence.run_id == run.id).order_by(Evidence.created_at.desc()))
        .scalars()
        .all()
    )
    return [
        EvidenceOut(
            id=str(e.id),
            run_id=str(e.run_id),
            kind=e.kind,
            source_name=e.source_name,
            source_ref=e.source_ref,
            excerpt=e.excerpt,
            meta=e.meta,
        )
        for e in items
    ]


@router.post("/runs/{run_id}/evidence/auto", response_model=list[EvidenceOut])
def auto_add_evidence(
    run_id: str,
    payload: AutoEvidenceIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    run = _get_run_or_404(db, run_id)

    # member+ only
    require_workspace_role_min(str(run.workspace_id), "member", db, user)

    items = hybrid_retrieve(
        db,
        workspace_id=str(run.workspace_id),
        q=payload.query,
        k=payload.k,
        alpha=payload.alpha,
    )
    if not items:
        return []

    created: list[Evidence] = []
    for rank, it in enumerate(items, start=1):
        source_ref = f"doc:{it['document_id']}#chunk:{it['chunk_id']}"

        meta = {
            "rank": rank,
            "score_hybrid": float(it.get("score_hybrid", 0.0)),
            "document_title": it.get("document_title", ""),
            "source_id": it.get("source_id", ""),
            "chunk_index": int(it.get("chunk_index", 0)),
        }

        ev = Evidence(
            run_id=run.id,
            kind="snippet",
            source_name="retrieval",
            source_ref=source_ref,
            excerpt=it.get("snippet", ""),
            meta=meta,
        )
        db.add(ev)
        created.append(ev)

    db.commit()
    for e in created:
        db.refresh(e)

    return [
        EvidenceOut(
            id=str(e.id),
            run_id=str(e.run_id),
            kind=e.kind,
            source_name=e.source_name,
            source_ref=e.source_ref,
            excerpt=e.excerpt,
            meta=e.meta,
        )
        for e in created
    ]