from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.db.session import get_db
from app.db.models import Workspace, Run, Artifact, User
from app.schemas.core import ArtifactCreateIn, ArtifactOut, ArtifactUpdateIn, ArtifactNewVersionIn

router = APIRouter(tags=["artifacts"])


def _ensure_run_access(db: Session, run: Run, user: User) -> None:
    ws = db.get(Workspace, run.workspace_id)
    if not ws or ws.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Run not found")


@router.post("/runs/{run_id}/artifacts", response_model=ArtifactOut)
def create_artifact(run_id: str, payload: ArtifactCreateIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _ensure_run_access(db, run, user)

    # version = max version for logical_key + 1
    max_ver = db.execute(
        select(func.max(Artifact.version)).where(Artifact.run_id == run.id, Artifact.logical_key == payload.logical_key)
    ).scalar_one_or_none()
    next_ver = int(max_ver or 0) + 1

    art = Artifact(
        run_id=run.id,
        type=payload.type,
        title=payload.title,
        content_md=payload.content_md or "",
        logical_key=payload.logical_key,
        version=next_ver,
        status="draft",
    )
    db.add(art)
    db.commit()
    db.refresh(art)

    return ArtifactOut(
        id=str(art.id),
        run_id=str(art.run_id),
        type=art.type,
        title=art.title,
        content_md=art.content_md,
        logical_key=art.logical_key,
        version=art.version,
        status=art.status,
    )


@router.get("/runs/{run_id}/artifacts", response_model=list[ArtifactOut])
def list_artifacts(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    _ensure_run_access(db, run, user)

    arts = db.execute(select(Artifact).where(Artifact.run_id == run.id).order_by(Artifact.created_at.desc())).scalars().all()
    return [
        ArtifactOut(
            id=str(a.id),
            run_id=str(a.run_id),
            type=a.type,
            title=a.title,
            content_md=a.content_md,
            logical_key=a.logical_key,
            version=a.version,
            status=a.status,
        )
        for a in arts
    ]


@router.get("/artifacts/{artifact_id}", response_model=ArtifactOut)
def get_artifact(artifact_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    run = db.get(Run, art.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Artifact not found")
    _ensure_run_access(db, run, user)

    return ArtifactOut(
        id=str(art.id),
        run_id=str(art.run_id),
        type=art.type,
        title=art.title,
        content_md=art.content_md,
        logical_key=art.logical_key,
        version=art.version,
        status=art.status,
    )


@router.put("/artifacts/{artifact_id}", response_model=ArtifactOut)
def update_artifact(artifact_id: str, payload: ArtifactUpdateIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    run = db.get(Run, art.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Artifact not found")
    _ensure_run_access(db, run, user)

    if payload.title is not None:
        art.title = payload.title
    if payload.content_md is not None:
        art.content_md = payload.content_md
    if payload.status is not None:
        art.status = payload.status

    db.add(art)
    db.commit()
    db.refresh(art)

    return ArtifactOut(
        id=str(art.id),
        run_id=str(art.run_id),
        type=art.type,
        title=art.title,
        content_md=art.content_md,
        logical_key=art.logical_key,
        version=art.version,
        status=art.status,
    )


@router.post("/artifacts/{artifact_id}/versions", response_model=ArtifactOut)
def new_artifact_version(artifact_id: str, payload: ArtifactNewVersionIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    run = db.get(Run, art.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Artifact not found")
    _ensure_run_access(db, run, user)

    max_ver = db.execute(
        select(func.max(Artifact.version)).where(Artifact.run_id == art.run_id, Artifact.logical_key == art.logical_key)
    ).scalar_one_or_none()
    next_ver = int(max_ver or 0) + 1

    new_art = Artifact(
        run_id=art.run_id,
        type=art.type,
        title=(payload.title if payload.title is not None else art.title),
        content_md=payload.content_md,
        logical_key=art.logical_key,
        version=next_ver,
        status=payload.status,
    )
    db.add(new_art)
    db.commit()
    db.refresh(new_art)

    return ArtifactOut(
        id=str(new_art.id),
        run_id=str(new_art.run_id),
        type=new_art.type,
        title=new_art.title,
        content_md=new_art.content_md,
        logical_key=new_art.logical_key,
        version=new_art.version,
        status=new_art.status,
    )