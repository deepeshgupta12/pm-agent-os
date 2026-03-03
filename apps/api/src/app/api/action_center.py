from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_access, require_workspace_role_min
from app.db.session import get_db
from app.db.models import ActionItem, Workspace, User

from app.schemas.core import (
    ActionItemCreateIn,
    ActionItemAssignIn,
    ActionItemDecisionIn,
    ActionItemOut,
)

router = APIRouter(tags=["action_center"])

VALID_STATUSES = {"queued", "approved", "rejected", "cancelled"}

def _to_out(a: ActionItem) -> ActionItemOut:
    return ActionItemOut(
        id=str(a.id),
        workspace_id=str(a.workspace_id),
        created_by_user_id=str(a.created_by_user_id),
        assigned_to_user_id=str(a.assigned_to_user_id) if a.assigned_to_user_id else None,
        decided_by_user_id=str(a.decided_by_user_id) if a.decided_by_user_id else None,
        type=a.type,
        status=a.status,
        title=a.title,
        payload_json=a.payload_json or {},
        target_ref=a.target_ref,
        decision_comment=a.decision_comment,
        decided_at=a.decided_at,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )

def _parse_uuid(id_str: str, *, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(id_str)
    except Exception:
        raise HTTPException(status_code=404, detail=f"{label} not found")

@router.get("/workspaces/{workspace_id}/actions", response_model=list[ActionItemOut])
def list_actions(
    workspace_id: str,
    status: Optional[str] = Query(default=None, description="Filter by status"),
    type: Optional[str] = Query(default=None, description="Filter by type"),
    assigned_to_me: bool = Query(default=False, description="If true, only items assigned to current user"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)

    q = select(ActionItem).where(ActionItem.workspace_id == ws.id)

    if status:
        s = status.strip().lower()
        if s not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status filter")
        q = q.where(ActionItem.status == s)

    if type:
        q = q.where(ActionItem.type == type.strip())

    if assigned_to_me:
        q = q.where(ActionItem.assigned_to_user_id == user.id)

    q = q.order_by(ActionItem.created_at.desc())
    items = db.execute(q).scalars().all()
    return [_to_out(x) for x in items]

@router.post("/workspaces/{workspace_id}/actions", response_model=ActionItemOut)
def create_action(
    workspace_id: str,
    payload: ActionItemCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)

    assigned_id = None
    if payload.assigned_to_user_id:
        try:
            assigned_id = uuid.UUID(payload.assigned_to_user_id)
        except Exception:
            raise HTTPException(status_code=400, detail="assigned_to_user_id must be a UUID")

    a = ActionItem(
        workspace_id=ws.id,
        created_by_user_id=user.id,
        assigned_to_user_id=assigned_id,
        decided_by_user_id=None,
        type=payload.type.strip(),
        status="queued",
        title=payload.title.strip(),
        payload_json=payload.payload_json or {},
        target_ref=(payload.target_ref.strip() if payload.target_ref else None),
        decision_comment=None,
        decided_at=None,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return _to_out(a)

@router.get("/actions/{action_id}", response_model=ActionItemOut)
def get_action(
    action_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    aid = _parse_uuid(action_id, label="Action item")
    a = db.get(ActionItem, aid)
    if not a:
        raise HTTPException(status_code=404, detail="Action item not found")

    # viewer+ ok if can access workspace
    require_workspace_access(str(a.workspace_id), db, user)
    return _to_out(a)

@router.patch("/actions/{action_id}/assign", response_model=ActionItemOut)
def assign_action(
    action_id: str,
    payload: ActionItemAssignIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    aid = _parse_uuid(action_id, label="Action item")
    a = db.get(ActionItem, aid)
    if not a:
        raise HTTPException(status_code=404, detail="Action item not found")

    require_workspace_role_min(str(a.workspace_id), "member", db, user)

    assigned_id = None
    if payload.assigned_to_user_id:
        try:
            assigned_id = uuid.UUID(payload.assigned_to_user_id)
        except Exception:
            raise HTTPException(status_code=400, detail="assigned_to_user_id must be a UUID")

    a.assigned_to_user_id = assigned_id
    db.add(a)
    db.commit()
    db.refresh(a)
    return _to_out(a)

@router.post("/actions/{action_id}/decide", response_model=ActionItemOut)
def decide_action(
    action_id: str,
    payload: ActionItemDecisionIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    aid = _parse_uuid(action_id, label="Action item")
    a = db.get(ActionItem, aid)
    if not a:
        raise HTTPException(status_code=404, detail="Action item not found")

    # For Step 1: admin-only decisions
    require_workspace_role_min(str(a.workspace_id), "admin", db, user)

    if a.status not in {"queued"}:
        raise HTTPException(status_code=409, detail="Action item is already decided")

    decision = payload.decision.strip().lower()
    if decision not in {"approved", "rejected", "cancelled"}:
        raise HTTPException(status_code=400, detail="Invalid decision")

    a.status = decision
    a.decided_by_user_id = user.id
    a.decision_comment = payload.comment
    a.decided_at = datetime.now(timezone.utc)

    db.add(a)
    db.commit()
    db.refresh(a)
    return _to_out(a)