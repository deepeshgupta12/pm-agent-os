from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db.models import (
    ActionItem,
    Artifact,
    ArtifactReview,
    Run,
    RunLog,
    User,
    Workspace,
)
from app.schemas.core import RunCreateIn

# Reuse existing run creation route (sync execution)
from app.api.runs import create_run as create_run_route


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _latest_artifact_for_run(db: Session, run_id: uuid.UUID) -> Optional[Artifact]:
    return (
        db.execute(
            select(Artifact)
            .where(Artifact.run_id == run_id)
            .order_by(Artifact.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


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
    return str(r.state) if r else None


def _log_run(db: Session, run_id: uuid.UUID, level: str, message: str, meta: Dict[str, Any]) -> None:
    try:
        db.add(
            RunLog(
                run_id=run_id,
                level=level,
                message=message,
                meta=meta or {},
            )
        )
        db.commit()
    except Exception:
        db.rollback()


# -----------------------------
# decision_log_create executor
# -----------------------------
def _build_decision_log_input(action: ActionItem) -> Dict[str, Any]:
    """
    Converts action.payload_json into a RunCreateIn.input_payload for agent_id="product_ops",
    which maps to artifact_type="decision_log".
    """
    pj = action.payload_json or {}
    if not isinstance(pj, dict):
        pj = {}

    decision_title = str(pj.get("decision_title") or action.title or "Decision").strip()
    context = str(pj.get("context") or "").strip()
    constraints = str(pj.get("constraints") or "").strip()

    # Everything else goes into context/details
    details = dict(pj)
    details.pop("decision_title", None)
    details.pop("context", None)
    details.pop("constraints", None)

    goal = f"Create a decision log entry: {decision_title}"

    input_payload: Dict[str, Any] = {
        "goal": goal,
        "context": (
            (context + "\n\n" if context else "")
            + "Decision details (from ActionItem.payload_json):\n"
            + str(details)
        ).strip(),
        "constraints": constraints,
        "_action": {
            "action_id": str(action.id),
            "action_type": action.type,
            "workspace_id": str(action.workspace_id),
        },
    }
    return input_payload


def _execute_decision_log_create(
    *,
    db: Session,
    ws: Workspace,
    user: User,
    action: ActionItem,
) -> Tuple[Optional[str], Optional[str]]:
    agent_id = "product_ops"
    input_payload = _build_decision_log_input(action)

    run_out = create_run_route(
        workspace_id=str(ws.id),
        payload=RunCreateIn(agent_id=agent_id, input_payload=input_payload, retrieval=None),
        db=db,
        user=user,
    )
    created_run_id = str(run_out.id)

    run_uuid = uuid.UUID(created_run_id)
    art = _latest_artifact_for_run(db, run_uuid)
    created_artifact_id = str(art.id) if art else None

    pj = action.payload_json or {}
    if not isinstance(pj, dict):
        pj = {}

    pj["created_run_id"] = created_run_id
    if created_artifact_id:
        pj["created_artifact_id"] = created_artifact_id
    pj["executed_at"] = _utcnow().isoformat()

    action.payload_json = pj
    db.add(action)
    db.commit()

    if art:
        _log_run(
            db,
            run_id=art.run_id,
            level="info",
            message="Action executor: decision_log_create completed",
            meta={"action_id": str(action.id), "created_artifact_id": created_artifact_id},
        )

    return created_run_id, created_artifact_id


# -----------------------------
# artifact_publish executor
# -----------------------------
def _execute_artifact_publish(
    *,
    db: Session,
    ws: Workspace,
    user: User,
    action: ActionItem,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Finalizes an artifact (status=final) after an approved ActionItem(type=artifact_publish).

    Expected action.payload_json shape (from /artifacts/{id}/request-publish):
    {
      "artifact_id": "<uuid>",
      "run_id": "<uuid>",
      "logical_key": "...",
      "version": <int>,
      "comment": <str|null>
    }
    """
    pj = action.payload_json or {}
    if not isinstance(pj, dict):
        pj = {}

    artifact_id_str = str(pj.get("artifact_id") or "").strip()
    run_id_str = str(pj.get("run_id") or "").strip()
    logical_key = str(pj.get("logical_key") or "").strip()
    version = pj.get("version")

    if not artifact_id_str or not run_id_str:
        raise HTTPException(status_code=400, detail="action.payload_json missing artifact_id/run_id")

    try:
        artifact_uuid = uuid.UUID(artifact_id_str)
        run_uuid = uuid.UUID(run_id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="action.payload_json artifact_id/run_id must be UUIDs")

    art = db.get(Artifact, artifact_uuid)
    if not art:
        raise HTTPException(status_code=404, detail="Artifact not found")

    run = db.get(Run, run_uuid)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # workspace safety check
    if str(run.workspace_id) != str(ws.id):
        raise HTTPException(status_code=403, detail="Artifact does not belong to this workspace")

    if str(art.run_id) != str(run.id):
        raise HTTPException(status_code=409, detail="Artifact/run mismatch (artifact not linked to run_id)")

    # Already final is idempotent (just record it)
    if art.status == "final":
        pj["published_artifact_id"] = str(art.id)
        pj["published_run_id"] = str(run.id)
        pj["published_at"] = _utcnow().isoformat()
        pj["executor_note"] = "Artifact already final; executor treated as success."
        action.payload_json = pj
        db.add(action)
        db.commit()
        return str(run.id), str(art.id)

    # Must be in_review
    if art.status != "in_review":
        raise HTTPException(status_code=409, detail="Artifact must be in_review to publish")

    # Must be latest version for that logical_key within the run
    # (We trust payload logical_key/version but still enforce DB truth)
    lk = logical_key or art.logical_key
    max_ver = (
        db.execute(
            select(func.max(Artifact.version)).where(
                Artifact.run_id == run.id,
                Artifact.logical_key == lk,
            )
        )
        .scalar_one_or_none()
    )
    if not max_ver or int(art.version) != int(max_ver):
        raise HTTPException(status_code=409, detail="Only latest artifact version can be published")

    # Must have latest review approved
    state = _latest_review_state(db, art.id)
    if state != "approved":
        raise HTTPException(status_code=409, detail="Artifact must be approved (latest review) before publish")

    # Finalize
    prev_status = art.status
    art.status = "final"
    db.add(art)
    db.commit()
    db.refresh(art)

    # Audit back onto action payload
    pj["published_run_id"] = str(run.id)
    pj["published_artifact_id"] = str(art.id)
    pj["published_at"] = _utcnow().isoformat()
    pj["published_prev_status"] = prev_status
    if version is not None:
        pj["requested_version"] = int(version)
    pj["executor_note"] = "Published via Action Center approval."
    action.payload_json = pj
    db.add(action)
    db.commit()

    _log_run(
        db,
        run_id=run.id,
        level="info",
        message="Action executor: artifact_publish completed (artifact finalized)",
        meta={"action_id": str(action.id), "artifact_id": str(art.id), "logical_key": lk, "version": int(art.version)},
    )

    return str(run.id), str(art.id)


# -----------------------------
# Dispatcher
# -----------------------------
def execute_action_if_applicable(
    *,
    db: Session,
    ws: Workspace,
    user: User,
    action: ActionItem,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Executes side-effects for approved actions.

    Returns (created_run_id, created_artifact_id) as strings.
    For artifact_publish: (run_id, artifact_id)
    For decision_log_create: (created_run_id, created_artifact_id)
    """
    # Only execute once (idempotency)
    pj = action.payload_json or {}
    if isinstance(pj, dict):
        if action.type == "artifact_publish" and (pj.get("published_artifact_id") or pj.get("published_run_id")):
            return str(pj.get("published_run_id") or ""), str(pj.get("published_artifact_id") or "")
        if action.type == "decision_log_create" and (pj.get("created_run_id") or pj.get("created_artifact_id")):
            return str(pj.get("created_run_id") or ""), str(pj.get("created_artifact_id") or "")

    if action.status != "approved":
        return None, None

    atype = (action.type or "").strip()

    if atype == "decision_log_create":
        return _execute_decision_log_create(db=db, ws=ws, user=user, action=action)

    if atype == "artifact_publish":
        return _execute_artifact_publish(db=db, ws=ws, user=user, action=action)

    return None, None