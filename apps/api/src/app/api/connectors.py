from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_access, require_workspace_role_min
from app.db.session import get_db
from app.db.models import Connector, User
from app.schemas.connectors import ConnectorCreateIn, ConnectorUpdateIn, ConnectorOut

router = APIRouter(tags=["connectors"])


def _to_out(c: Connector) -> ConnectorOut:
    return ConnectorOut(
        id=str(c.id),
        workspace_id=str(c.workspace_id),
        type=c.type,
        name=c.name,
        status=c.status,
        config=c.config or {},
        last_sync_at=c.last_sync_at.isoformat().replace("+00:00", "Z") if c.last_sync_at else None,
        last_error=c.last_error,
    )


@router.get("/workspaces/{workspace_id}/connectors", response_model=list[ConnectorOut])
def list_connectors(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    # viewer+ can read
    ws, _role = require_workspace_access(workspace_id, db, user)
    items = (
        db.execute(select(Connector).where(Connector.workspace_id == ws.id).order_by(Connector.created_at.desc()))
        .scalars()
        .all()
    )
    return [_to_out(c) for c in items]


@router.post("/workspaces/{workspace_id}/connectors", response_model=ConnectorOut)
def create_connector(
    workspace_id: str,
    payload: ConnectorCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    # admin only (managing connectors)
    ws, _role = require_workspace_role_min(workspace_id, "admin", db, user)

    ctype = payload.type.strip().lower()
    name = payload.name.strip()

    if ctype not in {"docs", "jira", "github", "slack", "support", "analytics"}:
        raise HTTPException(status_code=400, detail="Invalid connector type")

    # idempotent by (workspace_id, type, name)
    existing = db.execute(
        select(Connector).where(Connector.workspace_id == ws.id, Connector.type == ctype, Connector.name == name)
    ).scalar_one_or_none()

    if existing:
        # update config on re-create
        existing.config = payload.config or {}
        existing.status = "connected"
        existing.updated_at = datetime.now(timezone.utc)
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return _to_out(existing)

    c = Connector(
        workspace_id=ws.id,
        type=ctype,
        name=name,
        status="connected",
        config=payload.config or {},
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _to_out(c)


@router.patch("/connectors/{connector_id}", response_model=ConnectorOut)
def update_connector(
    connector_id: str,
    payload: ConnectorUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    c = db.get(Connector, uuid.UUID(connector_id))
    if not c:
        raise HTTPException(status_code=404, detail="Connector not found")

    # admin only
    require_workspace_role_min(str(c.workspace_id), "admin", db, user)

    if payload.name is not None:
        c.name = payload.name.strip()

    if payload.status is not None:
        c.status = payload.status.strip().lower()

    if payload.config is not None:
        c.config = payload.config

    db.add(c)
    db.commit()
    db.refresh(c)
    return _to_out(c)


@router.post("/connectors/{connector_id}/sync", response_model=ConnectorOut)
def trigger_sync(
    connector_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """
    V1 will implement real sync jobs. For Step 1, this is a stub that stamps last_sync_at.
    member+ can trigger, admin owns configuration.
    """
    c = db.get(Connector, uuid.UUID(connector_id))
    if not c:
        raise HTTPException(status_code=404, detail="Connector not found")

    require_workspace_role_min(str(c.workspace_id), "member", db, user)

    c.last_sync_at = datetime.now(timezone.utc)
    c.last_error = None
    db.add(c)
    db.commit()
    db.refresh(c)
    return _to_out(c)