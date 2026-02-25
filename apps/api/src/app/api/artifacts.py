from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_access, require_workspace_role_min
from app.db.session import get_db
from app.db.models import Run, Artifact, User
from app.schemas.core import ArtifactCreateIn, ArtifactOut, ArtifactUpdateIn, ArtifactNewVersionIn

router = APIRouter(tags=["artifacts"])

ALLOWED_STATUSES = {"draft", "in_review", "final"}


def _ensure_run_read_access(db: Session, run: Run, user: User) -> None:
    require_workspace_access(str(run.workspace_id), db, user)


def _ensure_run_write_access(db: Session, run: Run, user: User) -> None:
    require_workspace_role_min(str(run.workspace_id), "member", db, user)


def _ensure_artifact_read_access(db: Session, art: Artifact, user: User) -> Run:
    run = db.get(Run, art.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Artifact not found")
    _ensure_run_read_access(db, run, user)
    return run


def _ensure_artifact_write_access(db: Session, art: Artifact, user: User) -> Run:
    run = db.get(Run, art.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Artifact not found")
    _ensure_run_write_access(db, run, user)
    return run


def _to_out(a: Artifact) -> ArtifactOut:
    return ArtifactOut(
        id=str(a.id),
        run_id=str(a.run_id),
        type=a.type,
        title=a.title,
        content_md=a.content_md,
        logical_key=a.logical_key,
        version=a.version,
        status=a.status,
    )


@router.post("/runs/{run_id}/artifacts", response_model=ArtifactOut)
def create_artifact(run_id: str, payload: ArtifactCreateIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # member+ only
    _ensure_run_write_access(db, run, user)

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
    return _to_out(art)


@router.get("/runs/{run_id}/artifacts", response_model=list[ArtifactOut])
def list_artifacts(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # viewer+ ok
    _ensure_run_read_access(db, run, user)

    arts = (
        db.execute(select(Artifact).where(Artifact.run_id == run.id).order_by(Artifact.created_at.desc()))
        .scalars()
        .all()
    )
    return [_to_out(a) for a in arts]


@router.get("/artifacts/{artifact_id}", response_model=ArtifactOut)
def get_artifact(artifact_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    _ensure_artifact_read_access(db, art, user)
    return _to_out(art)


@router.put("/artifacts/{artifact_id}", response_model=ArtifactOut)
def update_artifact(artifact_id: str, payload: ArtifactUpdateIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    # member+ only
    _ensure_artifact_write_access(db, art, user)

    if art.status == "final":
        raise HTTPException(status_code=409, detail="Artifact is final and cannot be edited")

    if payload.status is not None and payload.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")

    if payload.title is not None:
        art.title = payload.title
    if payload.content_md is not None:
        art.content_md = payload.content_md
    if payload.status is not None:
        art.status = payload.status

    db.add(art)
    db.commit()
    db.refresh(art)
    return _to_out(art)


@router.post("/artifacts/{artifact_id}/versions", response_model=ArtifactOut)
def new_artifact_version(artifact_id: str, payload: ArtifactNewVersionIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    # member+ only
    _ensure_artifact_write_access(db, art, user)

    if art.status == "final":
        raise HTTPException(status_code=409, detail="Artifact is final; unpublish or create a new draft from prior version")

    if payload.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")

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
    return _to_out(new_art)


@router.post("/artifacts/{artifact_id}/publish", response_model=ArtifactOut)
def publish_artifact(artifact_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    # member+ only
    _ensure_artifact_write_access(db, art, user)

    max_ver = db.execute(
        select(func.max(Artifact.version)).where(Artifact.run_id == art.run_id, Artifact.logical_key == art.logical_key)
    ).scalar_one()
    if art.version != int(max_ver):
        raise HTTPException(status_code=409, detail="Only the latest version can be published. Create a new version first.")

    art.status = "final"
    db.add(art)
    db.commit()
    db.refresh(art)
    return _to_out(art)


@router.post("/artifacts/{artifact_id}/unpublish", response_model=ArtifactOut)
def unpublish_artifact(artifact_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    # member+ only
    _ensure_artifact_write_access(db, art, user)

    art.status = "draft"
    db.add(art)
    db.commit()
    db.refresh(art)
    return _to_out(art)