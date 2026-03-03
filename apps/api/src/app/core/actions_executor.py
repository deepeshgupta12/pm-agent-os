from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ActionItem, Artifact, Run, User, Workspace
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
    # Keep it clean
    details.pop("decision_title", None)
    details.pop("context", None)
    details.pop("constraints", None)

    goal = f"Create a decision log entry: {decision_title}"

    # Provide structured content for the deterministic scaffold / LLM prompt
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
    """
    # Only execute once
    pj = action.payload_json or {}
    if isinstance(pj, dict) and (pj.get("created_run_id") or pj.get("created_artifact_id")):
        return str(pj.get("created_run_id") or ""), str(pj.get("created_artifact_id") or "")

    if action.status != "approved":
        return None, None

    # Only handle decision_log_create for this commit
    if (action.type or "").strip() != "decision_log_create":
        return None, None

    # Build run payload
    agent_id = "product_ops"
    input_payload = _build_decision_log_input(action)

    # Create run (sync) using existing route
    run_out = create_run_route(
        workspace_id=str(ws.id),
        payload=RunCreateIn(agent_id=agent_id, input_payload=input_payload, retrieval=None),
        db=db,
        user=user,
    )

    created_run_id = str(run_out.id)

    # Fetch latest artifact for that run
    run_uuid = uuid.UUID(created_run_id)
    art = _latest_artifact_for_run(db, run_uuid)
    created_artifact_id = str(art.id) if art else None

    # Write back pointers onto ActionItem.payload_json for audit
    if not isinstance(pj, dict):
        pj = {}
    pj["created_run_id"] = created_run_id
    if created_artifact_id:
        pj["created_artifact_id"] = created_artifact_id
    pj["executed_at"] = _utcnow().isoformat()

    action.payload_json = pj
    db.add(action)
    db.commit()

    return created_run_id, created_artifact_id