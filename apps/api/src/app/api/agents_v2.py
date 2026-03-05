from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_access, require_workspace_role_min, get_workspace_role
from app.core.governance import audit_rbac_check, load_rbac
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


def _rbac_allowed_roles(ws: Workspace, path: Tuple[str, str], default: List[str]) -> List[str]:
    """
    Reads effective RBAC roles from Workspace.rbac_json merged with defaults.
    path example: ("agent_builder", "can_create_agent_base_roles")
    """
    eff = load_rbac(ws)
    cur: Any = eff
    for p in path:
        if not isinstance(cur, dict):
            cur = None
            break
        cur = cur.get(p)

    if not isinstance(cur, list) or not cur:
        cur = default

    out: List[str] = []
    for x in cur:
        s = str(x).strip().lower()
        if s:
            out.append(s)

    # stable de-dupe
    seen = set()
    uniq: List[str] = []
    for s in out:
        if s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    return uniq


def _enforce_rbac_with_audit(
    db: Session,
    *,
    ws: Workspace,
    user: User,
    action: str,
    allowed_roles: List[str],
) -> None:
    """
    Step 0.4 requirement:
    - hard-enforce RBAC
    - always audit allow/deny to governance_events
    """
    role = get_workspace_role(db, ws, user)
    role_l = (role or "").strip().lower()

    allowed = [str(r).strip().lower() for r in (allowed_roles or []) if str(r).strip()]
    ok = bool(role_l and role_l in allowed)

    if ok:
        audit_rbac_check(
            db,
            ws=ws,
            user=user,
            action=action,
            role=role,
            allowed_roles=allowed_roles,
            decision="allow",
            reason="ok",
        )
        return

    audit_rbac_check(
        db,
        ws=ws,
        user=user,
        action=action,
        role=role,
        allowed_roles=allowed_roles,
        decision="deny",
        reason="Not allowed by RBAC.",
    )
    raise HTTPException(status_code=403, detail="Not allowed by RBAC.")


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
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)  # baseline

    allowed_roles = _rbac_allowed_roles(ws, ("agent_builder", "can_create_agent_base_roles"), ["admin", "member"])
    _enforce_rbac_with_audit(
        db,
        ws=ws,
        user=user,
        action="rbac.agent_builder.create_agent_base",
        allowed_roles=allowed_roles,
    )

    key = payload.key.strip()
    name = payload.name.strip()
    desc = (payload.description or "").strip()

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

    # Version creation is allowed for member+ (no advanced RBAC gate yet)
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

    allowed_roles = _rbac_allowed_roles(ws, ("agent_builder", "can_publish_agent_roles"), ["admin"])
    _enforce_rbac_with_audit(
        db,
        ws=ws,
        user=user,
        action="rbac.agent_builder.publish_agent",
        allowed_roles=allowed_roles,
    )

    if v.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft versions can be published")

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