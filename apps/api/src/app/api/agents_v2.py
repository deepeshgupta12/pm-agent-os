from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.api.deps import (
    require_user,
    require_workspace_access,
    require_workspace_role_min,
    get_workspace_role,
)
from app.core.governance import (
    audit_rbac_check,
    audit_policy_check,
    load_rbac,
    policy_allowed_source_types,
    policy_assert_allowed_sources,
)
from app.db.session import get_db
from app.db.models import User, Workspace, AgentBase, AgentVersion

from app.schemas.agents_v2 import (
    AgentBaseCreateIn,
    AgentBaseUpdateIn,
    AgentBaseOut,
    AgentVersionCreateIn,
    AgentVersionUpdateIn,
    AgentVersionOut,
    AgentPublishOut,
    AgentArchiveOut,
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
    Hard-enforce RBAC and always audit allow/deny to governance_events.
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


def _extract_source_types_from_definition(defn: Dict[str, Any]) -> List[str]:
    """
    Reads definition_json.retrieval.source_types (if present) and returns normalized list.
    """
    try:
        retrieval = defn.get("retrieval") or {}
        if not isinstance(retrieval, dict):
            return []
        st = retrieval.get("source_types") or []
        if not isinstance(st, list):
            return []
        out: List[str] = []
        for x in st:
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
    except Exception:
        return []


def _enforce_policy_sources_from_definition_with_audit(
    db: Session,
    *,
    ws: Workspace,
    user: User,
    definition_json: Dict[str, Any],
    action: str,
) -> None:
    """
    Enforces workspace policy allowlist for any retrieval.source_types embedded in agent definition_json.
    Always audits allow/deny to governance_events.
    """
    requested = _extract_source_types_from_definition(definition_json)
    allowlist = policy_allowed_source_types(ws)

    try:
        # policy_assert_allowed_sources treats empty allowlist => allow all
        # requested empty => ok
        policy_assert_allowed_sources(ws, requested or None)

        audit_policy_check(
            db,
            ws=ws,
            user=user,
            action=action,
            requested_source_types=requested,
            allowlist=allowlist,
            decision="allow",
            reason="ok",
        )
    except ValueError as e:
        audit_policy_check(
            db,
            ws=ws,
            user=user,
            action=action,
            requested_source_types=requested,
            allowlist=allowlist,
            decision="deny",
            reason=str(e),
        )
        raise HTTPException(status_code=403, detail=str(e))


# -------------------------
# AgentBases
# -------------------------
@router.get("/workspaces/{workspace_id}/agent-bases", response_model=list[AgentBaseOut])
def list_agent_bases(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)  # viewer+
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


@router.get("/workspaces/{workspace_id}/agent-bases/{base_id}", response_model=AgentBaseOut)
def get_agent_base(
    workspace_id: str,
    base_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)  # viewer+
    b = _get_base_or_404(db, base_id)
    if str(b.workspace_id) != str(ws.id):
        raise HTTPException(status_code=404, detail="Agent base not found")
    return _base_out(b)


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

    existing = (
        db.execute(select(AgentBase).where(AgentBase.workspace_id == ws.id, AgentBase.key == key))
        .scalar_one_or_none()
    )
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


@router.patch("/workspaces/{workspace_id}/agent-bases/{base_id}", response_model=AgentBaseOut)
def update_agent_base(
    workspace_id: str,
    base_id: str,
    payload: AgentBaseUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)  # member+

    b = _get_base_or_404(db, base_id)
    if str(b.workspace_id) != str(ws.id):
        raise HTTPException(status_code=404, detail="Agent base not found")

    # Step 1 v1: allow member+ to edit, but still optionally gate via same "create" roles
    allowed_roles = _rbac_allowed_roles(ws, ("agent_builder", "can_create_agent_base_roles"), ["admin", "member"])
    _enforce_rbac_with_audit(
        db,
        ws=ws,
        user=user,
        action="rbac.agent_builder.edit_agent_base",
        allowed_roles=allowed_roles,
    )

    if payload.key is not None:
        new_key = payload.key.strip()
        if new_key and new_key != b.key:
            exists2 = (
                db.execute(select(AgentBase).where(AgentBase.workspace_id == ws.id, AgentBase.key == new_key))
                .scalar_one_or_none()
            )
            if exists2:
                raise HTTPException(status_code=409, detail="Agent base key already exists in this workspace")
            b.key = new_key

    if payload.name is not None:
        b.name = payload.name.strip()

    if payload.description is not None:
        b.description = (payload.description or "").strip()

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


@router.get("/workspaces/{workspace_id}/agent-versions/{version_id}", response_model=AgentVersionOut)
def get_agent_version(
    workspace_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)  # viewer+

    v = _get_version_or_404(db, version_id)
    b = db.get(AgentBase, v.agent_base_id)
    if not b or str(b.workspace_id) != str(ws.id):
        raise HTTPException(status_code=404, detail="Agent version not found")
    return _ver_out(v)


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

    definition_json = payload.definition_json or {}
    if not isinstance(definition_json, dict):
        raise HTTPException(status_code=400, detail="definition_json must be an object")

    # Step 1: enforce policy allowlist on definition_json retrieval source_types
    _enforce_policy_sources_from_definition_with_audit(
        db,
        ws=ws,
        user=user,
        definition_json=definition_json,
        action="policy.allowlist.agent_builder.save_definition",
    )

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
        definition_json=definition_json,
        created_by_user_id=user.id,
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return _ver_out(v)


@router.patch("/workspaces/{workspace_id}/agent-versions/{version_id}", response_model=AgentVersionOut)
def update_agent_version(
    workspace_id: str,
    version_id: str,
    payload: AgentVersionUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)

    v = _get_version_or_404(db, version_id)
    b = db.get(AgentBase, v.agent_base_id)
    if not b or str(b.workspace_id) != str(ws.id):
        raise HTTPException(status_code=404, detail="Agent version not found")

    if v.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft versions can be edited")

    # Step 1 v1: allow member+ to edit, but gate via same roles as create base
    allowed_roles = _rbac_allowed_roles(ws, ("agent_builder", "can_create_agent_base_roles"), ["admin", "member"])
    _enforce_rbac_with_audit(
        db,
        ws=ws,
        user=user,
        action="rbac.agent_builder.edit_agent_version",
        allowed_roles=allowed_roles,
    )

    if payload.definition_json is not None:
        if not isinstance(payload.definition_json, dict):
            raise HTTPException(status_code=400, detail="definition_json must be an object")

        # enforce policy allowlist on any retrieval defaults inside the definition
        _enforce_policy_sources_from_definition_with_audit(
            db,
            ws=ws,
            user=user,
            definition_json=payload.definition_json,
            action="policy.allowlist.agent_builder.save_definition",
        )

        v.definition_json = payload.definition_json

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

    # Before publish, re-validate definition_json against policy allowlist
    _enforce_policy_sources_from_definition_with_audit(
        db,
        ws=ws,
        user=user,
        definition_json=v.definition_json or {},
        action="policy.allowlist.agent_builder.publish_definition",
    )

    # publish: archive existing published versions for base
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


@router.post("/workspaces/{workspace_id}/agent-versions/{version_id}/archive", response_model=AgentArchiveOut)
def archive_agent_version(
    workspace_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)

    v = _get_version_or_404(db, version_id)
    b = db.get(AgentBase, v.agent_base_id)
    if not b or str(b.workspace_id) != str(ws.id):
        raise HTTPException(status_code=404, detail="Agent version not found")

    allowed_roles = _rbac_allowed_roles(ws, ("agent_builder", "can_archive_agent_roles"), ["admin"])
    _enforce_rbac_with_audit(
        db,
        ws=ws,
        user=user,
        action="rbac.agent_builder.archive_agent",
        allowed_roles=allowed_roles,
    )

    if v.status == "archived":
        return AgentArchiveOut(ok=True, agent_version_id=str(v.id), status="archived")

    # v1: allow archiving draft or published
    v.status = "archived"
    db.add(v)
    db.commit()
    db.refresh(v)

    return AgentArchiveOut(ok=True, agent_version_id=str(v.id), status="archived")