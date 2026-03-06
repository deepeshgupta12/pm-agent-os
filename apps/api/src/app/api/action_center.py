from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.api.deps import (
    require_user,
    require_workspace_access,
    require_workspace_role_min,
    get_workspace_role,
)
from app.core.actions_executor import execute_action_if_applicable
from app.db.session import get_db
from app.db.models import ActionItem, Workspace, User, ActionItemDecision

from app.schemas.core import (
    ActionItemCreateIn,
    ActionItemAssignIn,
    ActionItemDecisionIn,
    ActionItemCancelIn,
    ActionItemOut,
    ActionItemDecisionOut,
)

from app.core.governance import (
    rbac_assert,
    rbac_allowed_action_center_list_roles,
    rbac_allowed_action_center_create_roles,
    rbac_allowed_action_center_review_roles,
    rbac_allowed_action_center_cancel_roles,
    rbac_allowed_action_center_execute_roles,
)

router = APIRouter(tags=["action_center"])

VALID_STATUSES = {"queued", "approved", "rejected", "cancelled"}

# ---------------------------
# Policy helpers
# ---------------------------

DEFAULT_POLICY: Dict[str, Any] = {
    # per action type: required approvals + allowed roles
    "rules": {
        # default examples
        "decision_log_create": {
            "approvals_required": 1,
            "reviewer_roles": ["admin"],
            "creator_roles": ["member", "admin"],
        },
        "artifact_publish": {
            "approvals_required": 1,
            "reviewer_roles": ["admin"],
            "creator_roles": ["member", "admin"],
        },
    }
}

ROLE_ORDER = {"viewer": 1, "member": 2, "admin": 3}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_uuid(id_str: str, *, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(id_str)
    except Exception:
        raise HTTPException(status_code=404, detail=f"{label} not found")


def _load_policy(ws: Workspace) -> Dict[str, Any]:
    # workspace.approvals_json overrides defaults; merge shallow
    pol = (ws.approvals_json or {}) if hasattr(ws, "approvals_json") else {}
    if not isinstance(pol, dict):
        pol = {}
    base = dict(DEFAULT_POLICY)
    rules = dict(base.get("rules") or {})
    if isinstance(pol.get("rules"), dict):
        rules.update(pol["rules"])
    base["rules"] = rules
    return base


def _policy_for_action(ws: Workspace, action_type: str) -> Dict[str, Any]:
    pol = _load_policy(ws)
    rules = pol.get("rules") or {}
    rule = rules.get(action_type) or {}
    if not isinstance(rule, dict):
        rule = {}

    approvals_required = int(rule.get("approvals_required") or 1)

    reviewer_roles = rule.get("reviewer_roles") or ["admin"]
    creator_roles = rule.get("creator_roles") or ["member", "admin"]

    reviewer_user_ids = rule.get("reviewer_user_ids") or []  # optional allow-list

    # normalize
    reviewer_roles_norm = [str(r).lower() for r in reviewer_roles]
    creator_roles_norm = [str(r).lower() for r in creator_roles]

    allow_users = [str(x) for x in reviewer_user_ids if str(x).strip()]

    # If explicit allow-list exists, we treat it as "required reviewers".
    # Snapshot approvals_required = len(allow_users) (min 1).
    if allow_users:
        approvals_required = max(1, len(allow_users))

    return {
        "approvals_required": max(1, approvals_required),
        "reviewer_roles": reviewer_roles_norm,
        "creator_roles": creator_roles_norm,
        "reviewer_user_ids": allow_users,
    }


def _is_creator_allowed(ws: Workspace, user: User, db: Session, rule: Dict[str, Any]) -> bool:
    role = get_workspace_role(db, ws, user)
    if not role:
        return False
    role = role.lower()
    allowed_roles: List[str] = rule.get("creator_roles") or ["member", "admin"]
    return role in allowed_roles


def _is_reviewer_allowed(ws: Workspace, user: User, db: Session, rule: Dict[str, Any]) -> bool:
    role = get_workspace_role(db, ws, user)
    if not role:
        return False
    role = role.lower()

    allow_users: List[str] = rule.get("reviewer_user_ids") or []
    if allow_users:
        return str(user.id) in allow_users

    allowed_roles: List[str] = rule.get("reviewer_roles") or ["admin"]
    return role in allowed_roles


def _decision_counts(db: Session, action_id: uuid.UUID) -> Tuple[int, int]:
    approved = (
        db.execute(
            select(func.count(ActionItemDecision.id)).where(
                ActionItemDecision.action_id == action_id,
                ActionItemDecision.decision == "approved",
            )
        ).scalar_one()
        or 0
    )
    rejected = (
        db.execute(
            select(func.count(ActionItemDecision.id)).where(
                ActionItemDecision.action_id == action_id,
                ActionItemDecision.decision == "rejected",
            )
        ).scalar_one()
        or 0
    )
    return int(approved), int(rejected)


def _my_decision(db: Session, action_id: uuid.UUID, user_id: uuid.UUID) -> Optional[str]:
    row = db.execute(
        select(ActionItemDecision.decision).where(
            ActionItemDecision.action_id == action_id,
            ActionItemDecision.reviewer_user_id == user_id,
        )
    ).scalar_one_or_none()
    return str(row) if row else None


def _recompute_status(a: ActionItem, approved: int, rejected: int) -> str:
    if a.status == "cancelled":
        return "cancelled"
    if rejected > 0:
        return "rejected"
    if approved >= int(getattr(a, "approvals_required", 1) or 1):
        return "approved"
    return "queued"


def _to_out(a: ActionItem, *, db: Session, user: User) -> ActionItemOut:
    approved, rejected = _decision_counts(db, a.id)
    mine = _my_decision(db, a.id, user.id)

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
        approvals_required=int(getattr(a, "approvals_required", 1) or 1),
        approvals_approved_count=approved,
        approvals_rejected_count=rejected,
        my_decision=mine,
    )


def _decisions_to_out(rows: List[ActionItemDecision]) -> List[ActionItemDecisionOut]:
    out: List[ActionItemDecisionOut] = []
    for d in rows:
        out.append(
            ActionItemDecisionOut(
                reviewer_user_id=str(d.reviewer_user_id),
                decision=d.decision,
                comment=d.comment,
                decided_at=d.decided_at,
            )
        )
    return out

def _rbac_or_403(db: Session, *, ws: Workspace, user: User, action: str, allowed_roles: List[str]) -> None:
    try:
        rbac_assert(db, ws=ws, user=user, action=action, allowed_roles=allowed_roles)
    except ValueError:
        raise HTTPException(status_code=403, detail="Not allowed by RBAC.")


# ---------------------------
# Routes
# ---------------------------

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

    _rbac_or_403(
        db,
        ws=ws,
        user=user,
        action="rbac.action_center.list",
        allowed_roles=rbac_allowed_action_center_list_roles(ws),
    )

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
    return [_to_out(x, db=db, user=user) for x in items]


@router.post("/workspaces/{workspace_id}/actions", response_model=ActionItemOut)
def create_action(
    workspace_id: str,
    payload: ActionItemCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)

    # ✅ define action_type BEFORE RBAC usage
    action_type = (payload.type or "").strip()

    _rbac_or_403(
        db,
        ws=ws,
        user=user,
        action="rbac.action_center.create",
        allowed_roles=rbac_allowed_action_center_create_roles(ws, action_type=action_type),
    )

    rule = _policy_for_action(ws, action_type)

    # creator permission enforcement (approvals policy)
    if not _is_creator_allowed(ws, user, db, rule):
        raise HTTPException(status_code=403, detail="Not allowed to create this action type")

    assigned_id = None
    if payload.assigned_to_user_id:
        try:
            assigned_id = uuid.UUID(payload.assigned_to_user_id)
        except Exception:
            raise HTTPException(status_code=400, detail="assigned_to_user_id must be a UUID")

    approvals_required = int(rule.get("approvals_required") or 1)

    a = ActionItem(
        workspace_id=ws.id,
        created_by_user_id=user.id,
        assigned_to_user_id=assigned_id,
        decided_by_user_id=None,
        type=action_type,
        status="queued",
        title=payload.title.strip(),
        payload_json=payload.payload_json or {},
        target_ref=(payload.target_ref.strip() if payload.target_ref else None),
        decision_comment=None,
        decided_at=None,
        approvals_required=approvals_required,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return _to_out(a, db=db, user=user)


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

    require_workspace_access(str(a.workspace_id), db, user)
    return _to_out(a, db=db, user=user)


@router.get("/actions/{action_id}/decisions", response_model=list[ActionItemDecisionOut])
def list_action_decisions(
    action_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    aid = _parse_uuid(action_id, label="Action item")
    a = db.get(ActionItem, aid)
    if not a:
        raise HTTPException(status_code=404, detail="Action item not found")

    require_workspace_access(str(a.workspace_id), db, user)

    rows = (
        db.execute(
            select(ActionItemDecision)
            .where(ActionItemDecision.action_id == a.id)
            .order_by(ActionItemDecision.decided_at.asc())
        )
        .scalars()
        .all()
    )
    return _decisions_to_out(rows)


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
    return _to_out(a, db=db, user=user)


@router.post("/actions/{action_id}/cancel", response_model=ActionItemOut)
def cancel_action(
    action_id: str,
    payload: ActionItemCancelIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    aid = _parse_uuid(action_id, label="Action item")
    a = db.get(ActionItem, aid)
    if not a:
        raise HTTPException(status_code=404, detail="Action item not found")

    ws, role = require_workspace_access(str(a.workspace_id), db, user)

    _rbac_or_403(
        db,
        ws=ws,
        user=user,
        action="rbac.action_center.cancel",
        allowed_roles=rbac_allowed_action_center_cancel_roles(ws, action_type=a.type),
    )

    # Only queued actions can be cancelled
    if a.status != "queued":
        raise HTTPException(status_code=409, detail="Only queued actions can be cancelled")

    # Cancel permissions: admin OR creator
    is_admin = (role or "").lower() == "admin"
    is_creator = a.created_by_user_id == user.id
    if not (is_admin or is_creator):
        raise HTTPException(status_code=403, detail="Not allowed to cancel this action")

    a.status = "cancelled"
    a.decided_by_user_id = user.id
    a.decision_comment = payload.comment
    a.decided_at = _utcnow()

    db.add(a)
    db.commit()
    db.refresh(a)
    return _to_out(a, db=db, user=user)


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

    ws, _ = require_workspace_access(str(a.workspace_id), db, user)
    rule = _policy_for_action(ws, a.type)

    _rbac_or_403(
        db,
        ws=ws,
        user=user,
        action="rbac.action_center.review",
        allowed_roles=rbac_allowed_action_center_review_roles(ws, action_type=a.type),
    )

    if a.status != "queued":
        raise HTTPException(status_code=409, detail="Action item is already decided")

    # reviewer eligibility
    if not _is_reviewer_allowed(ws, user, db, rule):
        raise HTTPException(status_code=403, detail="Not allowed to review this action type")

    decision = payload.decision.strip().lower()
    if decision not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Invalid decision (must be approved|rejected)")

    # one decision per reviewer
    existing = db.execute(
        select(ActionItemDecision).where(
            ActionItemDecision.action_id == a.id,
            ActionItemDecision.reviewer_user_id == user.id,
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="You have already decided on this action")

    d = ActionItemDecision(
        action_id=a.id,
        reviewer_user_id=user.id,
        decision=decision,
        comment=payload.comment,
        decided_at=_utcnow(),
    )
    db.add(d)
    db.commit()

    approved, rejected = _decision_counts(db, a.id)
    new_status = _recompute_status(a, approved, rejected)

    if new_status != a.status:
        a.status = new_status
        if new_status in {"approved", "rejected"}:
            a.decided_by_user_id = user.id
            a.decision_comment = payload.comment
            a.decided_at = _utcnow()
        db.add(a)
        db.commit()
        db.refresh(a)

        # If approved, run executor (A: create NEW Run+Artifact)
        if new_status == "approved":
            try:
                _rbac_or_403(
                    db,
                    ws=ws,
                    user=user,
                    action="rbac.action_center.execute",
                    allowed_roles=rbac_allowed_action_center_execute_roles(ws, action_type=a.type),
                )
                execute_action_if_applicable(db=db, ws=ws, user=user, action=a)
                db.refresh(a)
            except Exception as e:
                # Keep action approved, but store error in payload for audit
                pj = a.payload_json or {}
                if not isinstance(pj, dict):
                    pj = {}
                pj["executor_error"] = str(e)
                pj["executor_error_at"] = _utcnow().isoformat()
                a.payload_json = pj
                db.add(a)
                db.commit()
                db.refresh(a)

    return _to_out(a, db=db, user=user)