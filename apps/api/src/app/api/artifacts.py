from __future__ import annotations

import difflib
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_access, require_workspace_role_min
from app.db.session import get_db
from app.db.models import Run, Artifact, ArtifactReview, RunLog, User
from app.schemas.core import (
    ArtifactCreateIn,
    ArtifactOut,
    ArtifactUpdateIn,
    ArtifactNewVersionIn,
    ArtifactReviewSubmitIn,
    ArtifactReviewDecisionIn,
    ArtifactReviewOut,
)

router = APIRouter(tags=["artifacts"])

ALLOWED_STATUSES = {"draft", "in_review", "final"}
REVIEW_STATES = {"requested", "approved", "rejected"}


def _ensure_run_read_access(db: Session, run: Run, user: User) -> None:
    require_workspace_access(str(run.workspace_id), db, user)


def _ensure_run_write_access(db: Session, run: Run, user: User) -> None:
    require_workspace_role_min(str(run.workspace_id), "member", db, user)


def _ensure_run_admin_access(db: Session, run: Run, user: User) -> None:
    require_workspace_role_min(str(run.workspace_id), "admin", db, user)


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


def _ensure_artifact_admin_access(db: Session, art: Artifact, user: User) -> Run:
    run = db.get(Run, art.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Artifact not found")
    _ensure_run_admin_access(db, run, user)
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


def _review_to_out(r: ArtifactReview) -> ArtifactReviewOut:
    return ArtifactReviewOut(
        id=str(r.id),
        artifact_id=str(r.artifact_id),
        state=r.state,
        requested_by_user_id=str(r.requested_by_user_id),
        requested_at=r.requested_at,
        request_comment=r.request_comment,
        decided_by_user_id=str(r.decided_by_user_id) if r.decided_by_user_id else None,
        decided_at=r.decided_at,
        decision_comment=r.decision_comment,
    )


def _log_run_event(db: Session, run_id: str, level: str, message: str, meta: dict) -> None:
    try:
        rl = RunLog(run_id=run_id, level=level, message=message, meta=meta or {})
        db.add(rl)
        db.commit()
    except Exception:
        db.rollback()


# ---- Diff schema (V0 basic) ----
class ArtifactDiffMeta(BaseModel):
    id: str
    run_id: str
    type: str
    title: str
    logical_key: str
    version: int
    status: str


class ArtifactDiffOut(BaseModel):
    a: ArtifactDiffMeta
    b: ArtifactDiffMeta
    unified_diff: str


@router.post("/runs/{run_id}/artifacts", response_model=ArtifactOut)
def create_artifact(
    run_id: str,
    payload: ArtifactCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
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

    _log_run_event(db, str(run.id), "info", "Artifact created", {"artifact_id": str(art.id), "version": art.version})

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
def update_artifact(
    artifact_id: str,
    payload: ArtifactUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    # member+ only
    run = _ensure_artifact_write_access(db, art, user)

    if art.status == "final":
        raise HTTPException(status_code=409, detail="Artifact is final and cannot be edited")

    # Approval lock: in_review is locked
    if art.status == "in_review":
        raise HTTPException(status_code=409, detail="Artifact is in review and cannot be edited")

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

    _log_run_event(db, str(run.id), "info", "Artifact updated", {"artifact_id": str(art.id), "version": art.version})

    return _to_out(art)


@router.post("/artifacts/{artifact_id}/versions", response_model=ArtifactOut)
def new_artifact_version(
    artifact_id: str,
    payload: ArtifactNewVersionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    # member+ only
    run = _ensure_artifact_write_access(db, art, user)

    if art.status == "final":
        raise HTTPException(status_code=409, detail="Artifact is final; unpublish or create a new draft from prior version")

    if art.status == "in_review":
        raise HTTPException(status_code=409, detail="Artifact is in review; reject/unpublish to edit or version")

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

    _log_run_event(db, str(run.id), "info", "Artifact version created", {"artifact_id": str(new_art.id), "version": new_art.version})

    return _to_out(new_art)


@router.post("/artifacts/{artifact_id}/unpublish", response_model=ArtifactOut)
def unpublish_artifact(artifact_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    run = _ensure_artifact_write_access(db, art, user)

    # member+ only
    art.status = "draft"
    db.add(art)
    db.commit()
    db.refresh(art)

    _log_run_event(db, str(run.id), "info", "Artifact unpublished", {"artifact_id": str(art.id), "status": art.status})

    return _to_out(art)


# -------------------------
# Approvals v1 (Option B): auditable artifact_reviews
# -------------------------
@router.get("/artifacts/{artifact_id}/reviews", response_model=list[ArtifactReviewOut])
def list_artifact_reviews(
    artifact_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")
    _ensure_artifact_read_access(db, art, user)

    rows = (
        db.execute(
            select(ArtifactReview)
            .where(ArtifactReview.artifact_id == art.id)
            .order_by(ArtifactReview.requested_at.desc())
        )
        .scalars()
        .all()
    )
    return [_review_to_out(r) for r in rows]


@router.post("/artifacts/{artifact_id}/submit-review", response_model=ArtifactReviewOut)
def submit_artifact_for_review(
    artifact_id: str,
    payload: ArtifactReviewSubmitIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    run = _ensure_artifact_write_access(db, art, user)

    if art.status == "final":
        raise HTTPException(status_code=409, detail="Artifact is final and cannot be reviewed")

    if art.status == "in_review":
        raise HTTPException(status_code=409, detail="Artifact is already in review")

    # Must be latest version for this logical_key to avoid approving stale versions
    max_ver = db.execute(
        select(func.max(Artifact.version)).where(Artifact.run_id == art.run_id, Artifact.logical_key == art.logical_key)
    ).scalar_one()
    if art.version != int(max_ver):
        raise HTTPException(status_code=409, detail="Only the latest version can be submitted for review")

    art.status = "in_review"
    db.add(art)
    db.commit()
    db.refresh(art)

    review = ArtifactReview(
        artifact_id=art.id,
        state="requested",
        requested_by_user_id=user.id,
        request_comment=(payload.comment or None),
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    _log_run_event(db, str(run.id), "info", "Artifact submitted for review", {"artifact_id": str(art.id), "review_id": str(review.id)})

    return _review_to_out(review)


def _get_latest_open_request(db: Session, artifact_id: uuid.UUID) -> Optional[ArtifactReview]:
    # latest "requested" that is not decided yet
    return (
        db.execute(
            select(ArtifactReview)
            .where(
                ArtifactReview.artifact_id == artifact_id,
                ArtifactReview.state == "requested",
                ArtifactReview.decided_at.is_(None),
            )
            .order_by(ArtifactReview.requested_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


@router.post("/artifacts/{artifact_id}/approve", response_model=ArtifactReviewOut)
def approve_artifact(
    artifact_id: str,
    payload: ArtifactReviewDecisionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    run = _ensure_artifact_admin_access(db, art, user)

    if art.status != "in_review":
        raise HTTPException(status_code=409, detail="Artifact is not in review")

    req = _get_latest_open_request(db, art.id)
    if not req:
        raise HTTPException(status_code=409, detail="No pending review request found")

    req.state = "approved"
    req.decided_by_user_id = user.id
    req.decided_at = func.now()
    req.decision_comment = (payload.comment or None)

    db.add(req)
    db.commit()
    db.refresh(req)

    _log_run_event(db, str(run.id), "info", "Artifact approved", {"artifact_id": str(art.id), "review_id": str(req.id)})

    return _review_to_out(req)


@router.post("/artifacts/{artifact_id}/reject", response_model=ArtifactReviewOut)
def reject_artifact(
    artifact_id: str,
    payload: ArtifactReviewDecisionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    run = _ensure_artifact_admin_access(db, art, user)

    if art.status != "in_review":
        raise HTTPException(status_code=409, detail="Artifact is not in review")

    req = _get_latest_open_request(db, art.id)
    if not req:
        raise HTTPException(status_code=409, detail="No pending review request found")

    req.state = "rejected"
    req.decided_by_user_id = user.id
    req.decided_at = func.now()
    req.decision_comment = (payload.comment or None)

    # unlock for editing
    art.status = "draft"
    db.add(art)
    db.add(req)
    db.commit()
    db.refresh(req)

    _log_run_event(db, str(run.id), "info", "Artifact rejected", {"artifact_id": str(art.id), "review_id": str(req.id)})

    return _review_to_out(req)


def _latest_review_state(db: Session, artifact_id: uuid.UUID) -> Optional[str]:
    r = (
        db.execute(
            select(ArtifactReview)
            .where(ArtifactReview.artifact_id == artifact_id)
            .order_by(ArtifactReview.requested_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    return r.state if r else None


@router.post("/artifacts/{artifact_id}/publish", response_model=ArtifactOut)
def publish_artifact(artifact_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    run = _ensure_artifact_write_access(db, art, user)

    # must be latest version for this logical_key
    max_ver = db.execute(
        select(func.max(Artifact.version)).where(Artifact.run_id == art.run_id, Artifact.logical_key == art.logical_key)
    ).scalar_one()
    if art.version != int(max_ver):
        raise HTTPException(status_code=409, detail="Only the latest version can be published. Create a new version first.")

    # Approval rule: must be in_review and latest review must be approved
    if art.status != "in_review":
        raise HTTPException(status_code=409, detail="Artifact must be in review before publishing (submit for review first).")

    state = _latest_review_state(db, art.id)
    if state != "approved":
        raise HTTPException(status_code=409, detail="Artifact must be approved before publishing.")

    art.status = "final"
    db.add(art)
    db.commit()
    db.refresh(art)

    _log_run_event(db, str(run.id), "info", "Artifact published (final)", {"artifact_id": str(art.id), "status": art.status})

    return _to_out(art)


# -------------------------
# V0: Basic artifact diff
# -------------------------
@router.get("/artifacts/{artifact_id}/diff", response_model=ArtifactDiffOut)
def diff_artifacts(
    artifact_id: str,
    other_id: str = Query(..., min_length=36, max_length=36),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """
    Basic unified diff between two artifact markdown bodies.

    RBAC:
      - viewer+ can read/diff
    """
    a = db.get(Artifact, artifact_id)
    if not a:
        raise HTTPException(status_code=404, detail="Artifact not found")

    b = db.get(Artifact, other_id)
    if not b:
        raise HTTPException(status_code=404, detail="Other artifact not found")

    _ensure_artifact_read_access(db, a, user)
    _ensure_artifact_read_access(db, b, user)

    a_lines = (a.content_md or "").splitlines(keepends=True)
    b_lines = (b.content_md or "").splitlines(keepends=True)

    diff_lines = difflib.unified_diff(
        a_lines,
        b_lines,
        fromfile=f"{a.logical_key}-v{a.version}",
        tofile=f"{b.logical_key}-v{b.version}",
        lineterm="",
    )

    unified = "\n".join(diff_lines).strip()

    def _meta(x: Artifact) -> ArtifactDiffMeta:
        return ArtifactDiffMeta(
            id=str(x.id),
            run_id=str(x.run_id),
            type=x.type,
            title=x.title,
            logical_key=x.logical_key,
            version=int(x.version),
            status=x.status,
        )

    return ArtifactDiffOut(a=_meta(a), b=_meta(b), unified_diff=unified)