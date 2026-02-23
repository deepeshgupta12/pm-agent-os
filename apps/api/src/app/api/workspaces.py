from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.db.session import get_db
from app.db.models import Workspace, User
from app.schemas.core import WorkspaceCreateIn, WorkspaceOut

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceOut)
def create_workspace(payload: WorkspaceCreateIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    ws = Workspace(name=payload.name.strip(), owner_user_id=user.id)
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return WorkspaceOut(id=str(ws.id), name=ws.name, owner_user_id=str(ws.owner_user_id))


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(db: Session = Depends(get_db), user: User = Depends(require_user)):
    rows = db.execute(select(Workspace).where(Workspace.owner_user_id == user.id).order_by(Workspace.created_at.desc())).scalars().all()
    return [WorkspaceOut(id=str(w.id), name=w.name, owner_user_id=str(w.owner_user_id)) for w in rows]


@router.get("/{workspace_id}", response_model=WorkspaceOut)
def get_workspace(workspace_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    ws = db.get(Workspace, workspace_id)
    if not ws or ws.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return WorkspaceOut(id=str(ws.id), name=ws.name, owner_user_id=str(ws.owner_user_id))