from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.db.session import get_db
from app.db.models import Workspace, Run, Evidence, User
from app.schemas.core import EvidenceCreateIn, EvidenceOut

router = APIRouter(tags=["evidence"])


def _parse_uuid(id_str: str) -> uuid.UUID:
    try:
        return uuid.UUID(id_str)
    except Exception:
        raise HTTPException(status_code=404, detail="Run not found")


def _ensure_run_access(db: Session, run: Run, user: User) -> None:
    ws = db.get(Workspace, run.workspace_id)
    if not ws or ws.owner_user_id != user.id:
        # don't leak existence
        raise HTTPException(status_code=404, detail="Run not found")


@router.post("/runs/{run_id}/evidence", response_model=EvidenceOut)
def add_evidence(run_id: str, payload: EvidenceCreateIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    run_uuid = _parse_uuid(run_id)

    run = db.get(Run, run_uuid)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _ensure_run_access(db, run, user)

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
    run_uuid = _parse_uuid(run_id)

    run = db.get(Run, run_uuid)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _ensure_run_access(db, run, user)

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