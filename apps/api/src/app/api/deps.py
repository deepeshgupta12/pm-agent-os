from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_user_from_cookie
from app.db.models import User, Workspace, WorkspaceMember

ROLE_ORDER = {"viewer": 1, "member": 2, "admin": 3}


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user_from_cookie(db, request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def get_workspace_role(db: Session, ws: Workspace, user: User) -> str | None:
    # Owner is always admin
    if ws.owner_user_id == user.id:
        return "admin"

    role = db.execute(
        select(WorkspaceMember.role).where(
            WorkspaceMember.workspace_id == ws.id,
            WorkspaceMember.user_id == user.id,
        )
    ).scalar_one_or_none()

    return str(role) if role else None


def require_workspace_access(workspace_id: str, db: Session, user: User) -> tuple[Workspace, str]:
    ws = db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    role = get_workspace_role(db, ws, user)
    if not role:
        # hide existence if no access
        raise HTTPException(status_code=404, detail="Workspace not found")

    return ws, role


def require_workspace_role_min(workspace_id: str, min_role: str, db: Session, user: User) -> tuple[Workspace, str]:
    ws, role = require_workspace_access(workspace_id, db, user)

    if ROLE_ORDER.get(role, 0) < ROLE_ORDER.get(min_role, 0):
        raise HTTPException(status_code=403, detail="Forbidden")

    return ws, role