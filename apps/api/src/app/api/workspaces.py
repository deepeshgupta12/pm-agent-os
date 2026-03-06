from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_, delete
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_access, require_workspace_role_min
from app.db.session import get_db
from app.db.models import (
    Workspace,
    WorkspaceMember,
    User,
    Evidence,
    RunLog,
)
from app.schemas.core import WorkspaceCreateIn, WorkspaceOut
from app.schemas.workspaces import WorkspaceMemberInviteIn, WorkspaceMemberOut, WorkspaceRoleOut
from app.schemas.workspaces import TemplateAdminOut, TemplateAdminUpdateIn
from app.schemas.core import ApprovalsPolicyOut, ApprovalsPolicyUpdateIn
from app.schemas.workspaces import (
    WorkspacePolicyOut,
    WorkspacePolicyUpdateIn,
    WorkspaceRBACOut,
    WorkspaceRBACUpdateIn,
    WorkspacePolicyPurgeOut,
)
from app.core.governance import safe_audit, normalize_policy_json, retention_cutoff_ts

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
# V3 Governance: Policy + RBAC (store + audit)
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
    after_in = payload.policy_json or {}

    after = normalize_policy_json(after_in)

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


@router.post("/{workspace_id}/policy/purge", response_model=WorkspacePolicyPurgeOut)
def purge_by_retention_policy(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """
    Policy Center v1:
    Manual purge endpoint driven by policy.retrieval.retention_days.

    Deletes:
    - evidence.created_at older than cutoff
    - run_logs.created_at older than cutoff

    (Artifacts are NOT deleted in v1.)
    """
    ws, _role = require_workspace_role_min(workspace_id, "admin", db, user)

    cutoff = retention_cutoff_ts(ws)
    if cutoff is None:
        raise HTTPException(status_code=400, detail="retention_days is not set in policy; nothing to purge")

    # count + delete evidence by workspace via run join
    # NOTE: Evidence has run_id; Run has workspace_id, but we avoid importing Run model here to keep file small.
    # We'll delete via subquery in SQLAlchemy ORM by selecting run_ids.
    # Minimal approach: fetch run ids then delete.
    run_ids = db.execute(
        select(Evidence.run_id)
        .distinct()
    ).scalars().all()

    # Safer: delete by created_at first, then rely on FK cascade? Evidence is keyed by run_id not workspace.
    # We'll do explicit deletes filtered by run.workspace_id in raw SQL style using session.execute(text).
    # However, to keep dependencies minimal, we delete by created_at only AND rely on per-workspace DB separation? Not true.
    # So we must scope properly.
    # We will scope by checking each evidence's run->workspace via EXISTS using ORM select on Run table.
    from app.db.models import Run  # local import to avoid circulars

    ev_q = (
        select(Evidence.id)
        .join(Run, Run.id == Evidence.run_id)
        .where(Run.workspace_id == ws.id)
        .where(Evidence.created_at < cutoff)
    )
    ev_ids = db.execute(ev_q).scalars().all()
    deleted_evidence = 0
    if ev_ids:
        db.execute(delete(Evidence).where(Evidence.id.in_(ev_ids)))
        db.commit()
        deleted_evidence = len(ev_ids)

    log_q = (
        select(RunLog.id)
        .join(Run, Run.id == RunLog.run_id)
        .where(Run.workspace_id == ws.id)
        .where(RunLog.created_at < cutoff)
    )
    log_ids = db.execute(log_q).scalars().all()
    deleted_logs = 0
    if log_ids:
        db.execute(delete(RunLog).where(RunLog.id.in_(log_ids)))
        db.commit()
        deleted_logs = len(log_ids)

    safe_audit(
        db,
        ws=ws,
        user=user,
        action="policy.retention.purge",
        decision="allow",
        reason="Retention purge executed",
        meta={
            "cutoff": cutoff.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "deleted_evidence": deleted_evidence,
            "deleted_logs": deleted_logs,
        },
    )

    return WorkspacePolicyPurgeOut(
        ok=True,
        workspace_id=str(ws.id),
        cutoff=cutoff.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        deleted_evidence=deleted_evidence,
        deleted_logs=deleted_logs,
    )


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