from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_access, require_workspace_role_min
from app.db.session import get_db
from app.db.models import Workspace, WorkspaceMember, User, GovernanceEvent
from app.schemas.core import WorkspaceCreateIn, WorkspaceOut
from app.schemas.workspaces import WorkspaceMemberInviteIn, WorkspaceMemberOut, WorkspaceRoleOut
from app.schemas.workspaces import TemplateAdminOut, TemplateAdminUpdateIn
from app.schemas.core import ApprovalsPolicyOut, ApprovalsPolicyUpdateIn
from app.schemas.workspaces import (
    WorkspacePolicyOut,
    WorkspacePolicyUpdateIn,
    WorkspaceRBACOut,
    WorkspaceRBACUpdateIn,
)
from app.schemas.governance import GovernanceEffectiveOut, GovernanceEventsOut, GovernanceEventOut
from app.core.governance import load_policy, load_rbac, safe_audit

router = APIRouter(prefix="/workspaces", tags=["workspaces"])

VALID_ROLES = {"admin", "member", "viewer"}


@router.post("", response_model=WorkspaceOut)
def create_workspace(payload: WorkspaceCreateIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    ws = Workspace(name=payload.name.strip(), owner_user_id=user.id)
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return WorkspaceOut(id=str(ws.id), name=ws.name, owner_user_id=str(ws.owner_user_id))


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(db: Session = Depends(get_db), user: User = Depends(require_user)):
    q = (
        select(Workspace)
        .outerjoin(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(or_(Workspace.owner_user_id == user.id, WorkspaceMember.user_id == user.id))
        .order_by(Workspace.created_at.desc())
        .distinct()
    )
    rows = db.execute(q).scalars().all()
    return [WorkspaceOut(id=str(w.id), name=w.name, owner_user_id=str(w.owner_user_id)) for w in rows]


@router.get("/{workspace_id}", response_model=WorkspaceOut)
def get_workspace(workspace_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    ws, _role = require_workspace_access(workspace_id, db, user)
    return WorkspaceOut(id=str(ws.id), name=ws.name, owner_user_id=str(ws.owner_user_id))


@router.get("/{workspace_id}/my-role", response_model=WorkspaceRoleOut)
def get_my_role(workspace_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    ws, role = require_workspace_access(workspace_id, db, user)
    return WorkspaceRoleOut(workspace_id=str(ws.id), role=role)


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberOut])
def list_members(workspace_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    ws, _ = require_workspace_access(workspace_id, db, user)

    owner = db.get(User, ws.owner_user_id)
    out: list[WorkspaceMemberOut] = []
    if owner:
        out.append(WorkspaceMemberOut(user_id=str(owner.id), email=owner.email, role="admin"))

    rows = db.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == ws.id)
        .order_by(User.email.asc())
    ).all()

    for wm, u in rows:
        if u.id == ws.owner_user_id:
            continue
        out.append(WorkspaceMemberOut(user_id=str(u.id), email=u.email, role=wm.role))

    return out


@router.post("/{workspace_id}/members", response_model=WorkspaceMemberOut)
def invite_member(
    workspace_id: str,
    payload: WorkspaceMemberInviteIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "admin", db, user)

    role = (payload.role or "member").strip().lower()
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")

    email = payload.email.strip().lower()
    target_user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=400, detail="User with that email does not exist")

    if target_user.id == ws.owner_user_id:
        raise HTTPException(status_code=400, detail="Owner is already an admin")

    existing = db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws.id,
            WorkspaceMember.user_id == target_user.id,
        )
    ).scalar_one_or_none()

    if existing:
        existing.role = role
        db.add(existing)
        db.commit()
        return WorkspaceMemberOut(user_id=str(target_user.id), email=target_user.email, role=existing.role)

    wm = WorkspaceMember(workspace_id=ws.id, user_id=target_user.id, role=role)
    db.add(wm)
    db.commit()

    return WorkspaceMemberOut(user_id=str(target_user.id), email=target_user.email, role=role)


@router.patch("/{workspace_id}/members/{member_user_id}", response_model=WorkspaceMemberOut)
def update_member_role(
    workspace_id: str,
    member_user_id: str,
    payload: WorkspaceMemberInviteIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "admin", db, user)

    role = (payload.role or "member").strip().lower()
    if role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")

    target = db.get(User, member_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Member not found")

    if target.id == ws.owner_user_id:
        raise HTTPException(status_code=400, detail="Cannot change owner role")

    wm = db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws.id,
            WorkspaceMember.user_id == target.id,
        )
    ).scalar_one_or_none()

    if not wm:
        raise HTTPException(status_code=404, detail="Member not found")

    wm.role = role
    db.add(wm)
    db.commit()

    return WorkspaceMemberOut(user_id=str(target.id), email=target.email, role=wm.role)


@router.delete("/{workspace_id}/members/{member_user_id}")
def remove_member(
    workspace_id: str,
    member_user_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _ = require_workspace_role_min(workspace_id, "admin", db, user)

    if str(ws.owner_user_id) == member_user_id:
        raise HTTPException(status_code=400, detail="Cannot remove owner")

    wm = db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws.id,
            WorkspaceMember.user_id == member_user_id,
        )
    ).scalar_one_or_none()

    if not wm:
        raise HTTPException(status_code=404, detail="Member not found")

    db.delete(wm)
    db.commit()

    return {"ok": True}


@router.get("/{workspace_id}/template-admin", response_model=TemplateAdminOut)
def get_template_admin(workspace_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    ws, _role = require_workspace_access(workspace_id, db, user)
    return TemplateAdminOut(workspace_id=str(ws.id), template_admin_json=ws.template_admin_json or {})


@router.put("/{workspace_id}/template-admin", response_model=TemplateAdminOut)
def update_template_admin(
    workspace_id: str,
    payload: TemplateAdminUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "admin", db, user)
    ws.template_admin_json = payload.template_admin_json or {}
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return TemplateAdminOut(workspace_id=str(ws.id), template_admin_json=ws.template_admin_json or {})


@router.get("/{workspace_id}/approvals-policy", response_model=ApprovalsPolicyOut)
def get_approvals_policy(workspace_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    ws, _role = require_workspace_access(workspace_id, db, user)
    return ApprovalsPolicyOut(workspace_id=str(ws.id), approvals_json=ws.approvals_json or {})


@router.put("/{workspace_id}/approvals-policy", response_model=ApprovalsPolicyOut)
def update_approvals_policy(
    workspace_id: str,
    payload: ApprovalsPolicyUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "admin", db, user)
    ws.approvals_json = payload.approvals_json or {}
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ApprovalsPolicyOut(workspace_id=str(ws.id), approvals_json=ws.approvals_json or {})


# -------------------------
# V3 Governance: Policy + RBAC
# -------------------------
@router.get("/{workspace_id}/policy", response_model=WorkspacePolicyOut)
def get_policy(workspace_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    ws, _role = require_workspace_access(workspace_id, db, user)
    return WorkspacePolicyOut(workspace_id=str(ws.id), policy_json=ws.policy_json or {})


@router.put("/{workspace_id}/policy", response_model=WorkspacePolicyOut)
def update_policy(
    workspace_id: str,
    payload: WorkspacePolicyUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "admin", db, user)

    before = ws.policy_json or {}
    after = payload.policy_json or {}

    ws.policy_json = after
    db.add(ws)
    db.commit()
    db.refresh(ws)

    safe_audit(
        db,
        ws=ws,
        user=user,
        action="policy.update",
        decision="allow",
        reason="Workspace policy updated",
        meta={"before": before, "after": after},
    )

    return WorkspacePolicyOut(workspace_id=str(ws.id), policy_json=ws.policy_json or {})


@router.get("/{workspace_id}/rbac", response_model=WorkspaceRBACOut)
def get_rbac(workspace_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    ws, _role = require_workspace_access(workspace_id, db, user)
    return WorkspaceRBACOut(workspace_id=str(ws.id), rbac_json=ws.rbac_json or {})


@router.put("/{workspace_id}/rbac", response_model=WorkspaceRBACOut)
def update_rbac(
    workspace_id: str,
    payload: WorkspaceRBACUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "admin", db, user)

    before = ws.rbac_json or {}
    after = payload.rbac_json or {}

    ws.rbac_json = after
    db.add(ws)
    db.commit()
    db.refresh(ws)

    safe_audit(
        db,
        ws=ws,
        user=user,
        action="rbac.update",
        decision="allow",
        reason="Workspace RBAC updated",
        meta={"before": before, "after": after},
    )

    return WorkspaceRBACOut(workspace_id=str(ws.id), rbac_json=ws.rbac_json or {})


# -------------------------
# Step 0.4: Effective governance + audit events
# -------------------------
@router.get("/{workspace_id}/governance", response_model=GovernanceEffectiveOut)
def get_governance_effective(workspace_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    ws, _role = require_workspace_access(workspace_id, db, user)  # viewer+ can read
    return GovernanceEffectiveOut(
        workspace_id=str(ws.id),
        policy_effective=load_policy(ws),
        rbac_effective=load_rbac(ws),
    )


@router.get("/{workspace_id}/governance/events", response_model=GovernanceEventsOut)
def list_governance_events(
    workspace_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)  # viewer+ can read

    lim = int(limit)
    rows = (
        db.execute(
            select(GovernanceEvent)
            .where(GovernanceEvent.workspace_id == ws.id)
            .order_by(GovernanceEvent.created_at.desc())
            .limit(lim)
        )
        .scalars()
        .all()
    )

    items: list[GovernanceEventOut] = []
    for e in rows:
        created_at = e.created_at.isoformat().replace("+00:00", "Z")
        items.append(
            GovernanceEventOut(
                id=str(e.id),
                workspace_id=str(e.workspace_id),
                user_id=str(e.user_id) if e.user_id else None,
                action=e.action,
                decision=e.decision,
                reason=e.reason or "",
                meta=e.meta or {},
                created_at=created_at,
            )
        )

    return GovernanceEventsOut(workspace_id=str(ws.id), items=items)