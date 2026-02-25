from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_access, require_workspace_role_min
from app.db.session import get_db
from app.db.models import Workspace, WorkspaceMember, User
from app.schemas.core import WorkspaceCreateIn, WorkspaceOut
from app.schemas.workspaces import WorkspaceMemberInviteIn, WorkspaceMemberOut, WorkspaceRoleOut

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
    # owner OR member
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

    # Owner row (implicit admin)
    owner = db.get(User, ws.owner_user_id)
    out: list[WorkspaceMemberOut] = []
    if owner:
        out.append(WorkspaceMemberOut(user_id=str(owner.id), email=owner.email, role="admin"))

    # Explicit members
    rows = db.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == ws.id)
        .order_by(User.email.asc())
    ).all()

    for wm, u in rows:
        # skip owner if ever inserted mistakenly
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
        # idempotent: update role
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