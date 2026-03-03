from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_access, require_workspace_role_min
from app.core.governance import rbac_can_create_agent_base, rbac_can_publish_agent
from app.db.session import get_db
from app.db.models import User, Workspace, AgentBase, AgentVersion

from app.schemas.agents_v2 import (
    AgentBaseCreateIn,
    AgentBaseOut,
    AgentVersionCreateIn,
    AgentVersionOut,
    AgentPublishOut,
)

router = APIRouter(tags=["agents_v2"])


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _base_out(x: AgentBase) -> AgentBaseOut:
    return AgentBaseOut(
        id=str(x.id),
        workspace_id=str(x.workspace_id),
        key=x.key,
        name=x.name,
        description=x.description or "",
        created_by_user_id=str(x.created_by_user_id) if x.created_by_user_id else None,
        created_at=_iso(x.created_at),
        updated_at=_iso(x.updated_at),
    )


def _ver_out(v: AgentVersion) -> AgentVersionOut:
    return AgentVersionOut(
        id=str(v.id),
        agent_base_id=str(v.agent_base_id),
        version=int(v.version),
        status=v.status,
        definition_json=v.definition_json or {},
        created_by_user_id=str(v.created_by_user_id) if v.created_by_user_id else None,
        created_at=_iso(v.created_at),
    )


def _get_ws_or_404(db: Session, workspace_id: str) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


def _get_base_or_404(db: Session, base_id: str) -> AgentBase:
    try:
        bid = uuid.UUID(base_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Agent base not found")

    b = db.get(AgentBase, bid)
    if not b:
        raise HTTPException(status_code=404, detail="Agent base not found")
    return b


def _get_version_or_404(db: Session, version_id: str) -> AgentVersion:
    try:
        vid = uuid.UUID(version_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Agent version not found")

    v = db.get(AgentVersion, vid)
    if not v:
        raise HTTPException(status_code=404, detail="Agent version not found")
    return v


# -------------------------
# AgentBases
# -------------------------
@router.get("/workspaces/{workspace_id}/agent-bases", response_model=list[AgentBaseOut])
def list_agent_bases(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)  # viewer+ read
    rows = (
        db.execute(
            select(AgentBase)
            .where(AgentBase.workspace_id == ws.id)
            .order_by(AgentBase.updated_at.desc())
        )
        .scalars()
        .all()
    )
    return [_base_out(x) for x in rows]


@router.post("/workspaces/{workspace_id}/agent-bases", response_model=AgentBaseOut)
def create_agent_base(
    workspace_id: str,
    payload: AgentBaseCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)  # member+ baseline
    # V3 advanced RBAC check (policy-driven)
    if not rbac_can_create_agent_base(db, ws, user):
        raise HTTPException(status_code=403, detail="Not allowed to create agent bases in this workspace")

    key = payload.key.strip()
    name = payload.name.strip()
    desc = (payload.description or "").strip()

    # enforce workspace unique key
    existing = db.execute(
        select(AgentBase).where(AgentBase.workspace_id == ws.id, AgentBase.key == key)
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Agent base key already exists in this workspace")

    b = AgentBase(
        workspace_id=ws.id,
        key=key,
        name=name,
        description=desc,
        created_by_user_id=user.id,
    )
    db.add(b)
    db.commit()
    db.refresh(b)
    return _base_out(b)


# -------------------------
# AgentVersions
# -------------------------
@router.get("/workspaces/{workspace_id}/agent-bases/{base_id}/versions", response_model=list[AgentVersionOut])
def list_agent_versions(
    workspace_id: str,
    base_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)  # viewer+
    b = _get_base_or_404(db, base_id)
    if str(b.workspace_id) != str(ws.id):
        raise HTTPException(status_code=404, detail="Agent base not found")

    rows = (
        db.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_base_id == b.id)
            .order_by(AgentVersion.version.desc())
        )
        .scalars()
        .all()
    )
    return [_ver_out(v) for v in rows]


@router.post("/workspaces/{workspace_id}/agent-bases/{base_id}/versions", response_model=AgentVersionOut)
def create_agent_version(
    workspace_id: str,
    base_id: str,
    payload: AgentVersionCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)
    b = _get_base_or_404(db, base_id)
    if str(b.workspace_id) != str(ws.id):
        raise HTTPException(status_code=404, detail="Agent base not found")

    # Determine next version number (monotonic per base)
    max_ver = (
        db.execute(select(func.max(AgentVersion.version)).where(AgentVersion.agent_base_id == b.id))
        .scalar_one_or_none()
    )
    next_ver = int(max_ver or 0) + 1

    v = AgentVersion(
        agent_base_id=b.id,
        version=next_ver,
        status="draft",
        definition_json=payload.definition_json or {},
        created_by_user_id=user.id,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return _ver_out(v)


@router.post("/workspaces/{workspace_id}/agent-versions/{version_id}/publish", response_model=AgentPublishOut)
def publish_agent_version(
    workspace_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)

    v = _get_version_or_404(db, version_id)
    b = db.get(AgentBase, v.agent_base_id)
    if not b:
        raise HTTPException(status_code=404, detail="Agent base not found")
    if str(b.workspace_id) != str(ws.id):
        raise HTTPException(status_code=404, detail="Agent version not found")

    # Advanced RBAC
    if not rbac_can_publish_agent(db, ws, user):
        raise HTTPException(status_code=403, detail="Not allowed to publish agent versions in this workspace")

    # Must be draft to publish
    if v.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft versions can be published")

    # publish: set this version -> published, archive any other published version(s) for same base
    db.execute(
        select(AgentVersion)
        .where(AgentVersion.agent_base_id == b.id, AgentVersion.status == "published")
    )

    # archive existing published versions
    existing_published = (
        db.execute(
            select(AgentVersion).where(
                AgentVersion.agent_base_id == b.id,
                AgentVersion.status == "published",
            )
        )
        .scalars()
        .all()
    )
    for old in existing_published:
        old.status = "archived"
        db.add(old)

    v.status = "published"
    db.add(v)
    db.commit()
    db.refresh(v)

    return AgentPublishOut(
        ok=True,
        agent_base_id=str(b.id),
        published_version_id=str(v.id),
        published_version=int(v.version),
    )