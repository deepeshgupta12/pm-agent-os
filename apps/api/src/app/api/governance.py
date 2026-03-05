from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_access
from app.core.governance import effective_governance_payload
from app.db.session import get_db
from app.db.models import GovernanceEvent, User

router = APIRouter(tags=["governance"])


class GovernanceEffectiveOut(BaseModel):
    workspace_id: str
    policy_effective: Dict[str, Any] = Field(default_factory=dict)
    rbac_effective: Dict[str, Any] = Field(default_factory=dict)


class GovernanceEventOut(BaseModel):
    id: str
    workspace_id: str
    user_id: Optional[str] = None
    action: str
    decision: str
    reason: str
    meta: Dict[str, Any] = Field(default_factory=dict)
    created_at: str


class GovernanceEventsOut(BaseModel):
    workspace_id: str
    items: List[GovernanceEventOut] = Field(default_factory=list)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@router.get("/workspaces/{workspace_id}/governance", response_model=GovernanceEffectiveOut)
def get_governance(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)

    payload = effective_governance_payload(ws)
    return GovernanceEffectiveOut(
        workspace_id=str(ws.id),
        policy_effective=payload.get("policy_effective") or {},
        rbac_effective=payload.get("rbac_effective") or {},
    )


@router.get("/workspaces/{workspace_id}/governance/events", response_model=GovernanceEventsOut)
def list_governance_events(
    workspace_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    decision: Optional[str] = Query(default=None, description="Optional filter: allow|deny"),
    action_prefix: Optional[str] = Query(default=None, description="Optional filter by action prefix"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)

    q = select(GovernanceEvent).where(GovernanceEvent.workspace_id == ws.id)

    if decision:
        d = decision.strip().lower()
        if d not in {"allow", "deny"}:
            raise HTTPException(status_code=400, detail="Invalid decision (allow|deny)")
        q = q.where(GovernanceEvent.decision == d)

    if action_prefix:
        pref = action_prefix.strip()
        if pref:
            q = q.where(GovernanceEvent.action.like(f"{pref}%"))

    q = q.order_by(GovernanceEvent.created_at.desc()).limit(int(limit))
    rows = db.execute(q).scalars().all()

    items: List[GovernanceEventOut] = []
    for e in rows:
        items.append(
            GovernanceEventOut(
                id=str(e.id),
                workspace_id=str(e.workspace_id),
                user_id=str(e.user_id) if e.user_id else None,
                action=e.action,
                decision=e.decision,
                reason=e.reason or "",
                meta=e.meta or {},
                created_at=_iso(e.created_at) or "",
            )
        )

    return GovernanceEventsOut(workspace_id=str(ws.id), items=items)