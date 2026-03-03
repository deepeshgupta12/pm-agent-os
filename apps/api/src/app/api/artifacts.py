from __future__ import annotations

import difflib
import uuid
from typing import Optional, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session

import re
from app.db.models import WorkspaceMember, ArtifactComment, ArtifactCommentMention
from app.schemas.core import ArtifactAssignIn, ArtifactCommentCreateIn, ArtifactCommentOut, ArtifactCommentMentionOut
from app.api.deps import require_user, require_workspace_access, require_workspace_role_min
from app.db.session import get_db
from app.db.models import (
    Run,
    Artifact,
    ArtifactReview,
    RunLog,
    User,
    Workspace,
    ActionItem,
)
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

# ----------------------------
# Helpers
# ----------------------------

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
        assigned_to_user_id=str(a.assigned_to_user_id) if getattr(a, "assigned_to_user_id", None) else None,
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


def _get_publish_policy_required_approvals(ws: Workspace) -> int:
    """
    Reads workspace.approvals_json shape:
    {
      "rules": {
        "artifact_publish": { "approvals_required": 2, ... }
      }
    }
    Defaults to 1 if absent/invalid.
    """
    try:
        pol = ws.approvals_json or {}
        if not isinstance(pol, dict):
            return 1
        rules = pol.get("rules") or {}
        if not isinstance(rules, dict):
            return 1
        rule = rules.get("artifact_publish") or {}
        if not isinstance(rule, dict):
            return 1
        n = int(rule.get("approvals_required") or 1)
        return max(1, n)
    except Exception:
        return 1


def _publish_is_approval_gated(ws: Workspace) -> bool:
    """
    If workspace has an explicit rule for artifact_publish, treat it as gated.
    """
    try:
        pol = ws.approvals_json or {}
        if not isinstance(pol, dict):
            return False
        rules = pol.get("rules") or {}
        if not isinstance(rules, dict):
            return False
        return "artifact_publish" in rules
    except Exception:
        return False

MENTION_EMAIL_RE = re.compile(r"@([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})")

def _workspace_id_for_artifact(db: Session, art: Artifact) -> str:
    run = db.get(Run, art.run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return str(run.workspace_id)

def _is_user_in_workspace(db: Session, workspace_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    # owner implicit membership OR workspace_members row
    ws = db.get(Workspace, workspace_id)
    if not ws:
        return False
    if ws.owner_user_id == user_id:
        return True
    row = db.execute(
        select(WorkspaceMember.id).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    ).scalar_one_or_none()
    return row is not None


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


# ---- Commit 2: Request publish (creates ActionItem) ----
class ArtifactRequestPublishIn(BaseModel):
    title: Optional[str] = Field(default=None, max_length=240)
    comment: Optional[str] = Field(default=None, max_length=5000)


class ArtifactPublishActionOut(BaseModel):
    ok: bool = True
    action_id: str
    workspace_id: str
    status: str


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
        select(func.max(Artifact.version)).where(
            Artifact.run_id == run.id,
            Artifact.logical_key == payload.logical_key,
        )
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


@router.get("/runs/{run_id}/artifacts/latest", response_model=ArtifactOut)
def get_latest_artifact_for_run(
    run_id: str,
    logical_key: str = Query(..., min_length=1, max_length=64),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # viewer+ ok
    _ensure_run_read_access(db, run, user)

    max_ver = db.execute(
        select(func.max(Artifact.version)).where(Artifact.run_id == run.id, Artifact.logical_key == logical_key)
    ).scalar_one_or_none()

    if not max_ver:
        raise HTTPException(status_code=404, detail="No artifact found for that logical_key")

    art = db.execute(
        select(Artifact).where(
            Artifact.run_id == run.id,
            Artifact.logical_key == logical_key,
            Artifact.version == int(max_ver),
        )
    ).scalar_one_or_none()

    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    return _to_out(art)


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

    _log_run_event(
        db,
        str(run.id),
        "info",
        "Artifact version created",
        {"artifact_id": str(new_art.id), "version": new_art.version},
    )

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
# Approvals v1 (auditable artifact_reviews)
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

    _log_run_event(
        db,
        str(run.id),
        "info",
        "Artifact submitted for review",
        {"artifact_id": str(art.id), "review_id": str(review.id)},
    )

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


# -------------------------
# Request publish -> creates ActionItem("artifact_publish")
# -------------------------
@router.post("/artifacts/{artifact_id}/request-publish", response_model=ArtifactPublishActionOut)
def request_publish_artifact(
    artifact_id: str,
    payload: ArtifactRequestPublishIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    run = _ensure_artifact_write_access(db, art, user)  # member+ only

    ws = db.get(Workspace, run.workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # must be in_review before publish request
    if art.status != "in_review":
        raise HTTPException(status_code=409, detail="Submit for review first (artifact must be in_review).")

    # if already final, no need
    if art.status == "final":
        raise HTTPException(status_code=409, detail="Artifact is already final")

    approvals_required = _get_publish_policy_required_approvals(ws)

    title = payload.title.strip() if payload.title else f"Publish artifact: {art.title}"
    a = ActionItem(
        workspace_id=ws.id,
        created_by_user_id=user.id,
        assigned_to_user_id=None,
        decided_by_user_id=None,
        type="artifact_publish",
        status="queued",
        title=title,
        payload_json={
            "artifact_id": str(art.id),
            "run_id": str(run.id),
            "logical_key": art.logical_key,
            "version": int(art.version),
            "comment": (payload.comment or None),
        },
        target_ref=f"artifact:{art.id}",
        decision_comment=None,
        decided_at=None,
        approvals_required=int(approvals_required or 1),
    )
    db.add(a)
    db.commit()
    db.refresh(a)

    _log_run_event(
        db,
        str(run.id),
        "info",
        "Publish requested (action created)",
        {"artifact_id": str(art.id), "action_id": str(a.id), "approvals_required": a.approvals_required},
    )

    return ArtifactPublishActionOut(ok=True, action_id=str(a.id), workspace_id=str(ws.id), status=a.status)

# -------------------------
# List comments, create comment (mentions), assign artifact
# -------------------------
@router.get("/artifacts/{artifact_id}/comments", response_model=list[ArtifactCommentOut])
def list_artifact_comments(
    artifact_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    run = _ensure_artifact_read_access(db, art, user)
    ws = db.get(Workspace, run.workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    rows = (
        db.execute(
            select(ArtifactComment)
            .where(ArtifactComment.artifact_id == art.id)
            .order_by(ArtifactComment.created_at.desc())
        )
        .scalars()
        .all()
    )

    out: list[ArtifactCommentOut] = []
    for c in rows:
        author = db.get(User, c.author_user_id)
        mention_rows = (
            db.execute(
                select(ArtifactCommentMention).where(ArtifactCommentMention.comment_id == c.id)
            )
            .scalars()
            .all()
        )
        mentions = [
            ArtifactCommentMentionOut(
                mentioned_user_id=str(m.mentioned_user_id),
                mentioned_email=m.mentioned_email,
            )
            for m in mention_rows
        ]
        out.append(
            ArtifactCommentOut(
                id=str(c.id),
                artifact_id=str(c.artifact_id),
                author_user_id=str(c.author_user_id),
                author_email=(author.email if author else ""),
                body=c.body,
                created_at=c.created_at,
                mentions=mentions,
            )
        )
    return out


@router.post("/artifacts/{artifact_id}/comments", response_model=ArtifactCommentOut)
def create_artifact_comment(
    artifact_id: str,
    payload: ArtifactCommentCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    # member+ only
    run = _ensure_artifact_write_access(db, art, user)
    ws = db.get(Workspace, run.workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="Comment body cannot be empty")

    c = ArtifactComment(
        artifact_id=art.id,
        author_user_id=user.id,
        body=body,
    )
    db.add(c)
    db.commit()
    db.refresh(c)

    # Mentions: only store mentions that map to existing users in this workspace
    found_emails = sorted(set([m.group(1).strip().lower() for m in MENTION_EMAIL_RE.finditer(body)]))
    mention_out: list[ArtifactCommentMentionOut] = []

    if found_emails:
        # Find users by email
        users = (
            db.execute(select(User).where(User.email.in_(found_emails)))
            .scalars()
            .all()
        )
        by_email = {u.email.lower(): u for u in users}

        for email in found_emails:
            u = by_email.get(email)
            if not u:
                continue
            # must be in workspace
            if not _is_user_in_workspace(db, ws.id, u.id):
                continue

            m = ArtifactCommentMention(
                comment_id=c.id,
                mentioned_user_id=u.id,
                mentioned_email=email,
            )
            db.add(m)
            mention_out.append(
                ArtifactCommentMentionOut(
                    mentioned_user_id=str(u.id),
                    mentioned_email=email,
                )
            )

        db.commit()

    _log_run_event(
        db,
        str(run.id),
        "info",
        "Artifact comment added",
        {"artifact_id": str(art.id), "comment_id": str(c.id), "mentions": found_emails},
    )

    return ArtifactCommentOut(
        id=str(c.id),
        artifact_id=str(c.artifact_id),
        author_user_id=str(c.author_user_id),
        author_email=user.email,
        body=c.body,
        created_at=c.created_at,
        mentions=mention_out,
    )


@router.patch("/artifacts/{artifact_id}/assign", response_model=ArtifactOut)
def assign_artifact(
    artifact_id: str,
    payload: ArtifactAssignIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    # member+ only
    run = _ensure_artifact_write_access(db, art, user)
    ws = db.get(Workspace, run.workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # no assignment change allowed when final/in_review? (we’ll allow assignment in_review; block only final)
    if art.status == "final":
        raise HTTPException(status_code=409, detail="Artifact is final; cannot change assignment")

    assigned_uuid: Optional[uuid.UUID] = None
    if payload.assigned_to_user_id:
        try:
            assigned_uuid = uuid.UUID(payload.assigned_to_user_id)
        except Exception:
            raise HTTPException(status_code=400, detail="assigned_to_user_id must be a UUID")

        # must be a user in this workspace (or owner)
        if not _is_user_in_workspace(db, ws.id, assigned_uuid):
            raise HTTPException(status_code=400, detail="User is not a member of this workspace")

    art.assigned_to_user_id = assigned_uuid
    db.add(art)
    db.commit()
    db.refresh(art)

    _log_run_event(
        db,
        str(run.id),
        "info",
        "Artifact assigned",
        {"artifact_id": str(art.id), "assigned_to_user_id": str(assigned_uuid) if assigned_uuid else None},
    )

    return _to_out(art)


# -------------------------
# Legacy: Direct publish endpoint
# -------------------------
@router.post("/artifacts/{artifact_id}/publish", response_model=ArtifactOut)
def publish_artifact(artifact_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """
    V1 legacy publish. In V2 Commit 2 we gate publish via Action Center.

    Rule:
    - If workspace has approvals policy for artifact_publish, direct publish is blocked.
    - Otherwise, legacy behavior remains.
    """
    art = db.get(Artifact, artifact_id)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    run = _ensure_artifact_write_access(db, art, user)

    ws = db.get(Workspace, run.workspace_id)
    if ws and _publish_is_approval_gated(ws):
        raise HTTPException(
            status_code=409,
            detail="Publish is approval-gated. Use /artifacts/{id}/request-publish and approve via Action Center.",
        )

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