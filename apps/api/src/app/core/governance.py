from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import GovernanceEvent, User, Workspace, WorkspaceMember


# -------------------------
# Deterministic effective governance defaults
# -------------------------
_DEFAULT_POLICY: Dict[str, Any] = {
    "retrieval": {
        "allowed_source_types": [],  # empty => no allowlist enforcement
        "retention_days": None,
        "block_external_links": False,
    },
    "privacy": {
        "pii_masking": {
            "enabled": False,
            "mode": "none",
        }
    },
}

_DEFAULT_RBAC: Dict[str, Any] = {
    "agent_builder": {
        "can_create_agent_base_roles": ["admin", "member"],
        "can_publish_agent_roles": ["admin"],
        "can_archive_agent_roles": ["admin"],
        # NEW (Commit 5): runtime / visibility permissions
        "can_preview_agent_roles": ["admin", "member"],
        "can_view_published_agent_roles": ["admin", "member", "viewer"],
        "can_run_agent_roles": ["admin", "member"],
    },
    "connectors": {
        "can_create_connector_roles": ["admin"],
        "can_trigger_sync_roles": ["admin", "member"],
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Safe deep merge:
    - dict values merge recursively
    - other values replace
    """
    out: Dict[str, Any] = dict(base or {})
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)  # type: ignore[arg-type]
        else:
            out[k] = v
    return out


def load_policy(ws: Workspace) -> Dict[str, Any]:
    raw = ws.policy_json or {}
    if not isinstance(raw, dict):
        raw = {}
    return _deep_merge(_DEFAULT_POLICY, raw)


def load_rbac(ws: Workspace) -> Dict[str, Any]:
    raw = ws.rbac_json or {}
    if not isinstance(raw, dict):
        raw = {}
    return _deep_merge(_DEFAULT_RBAC, raw)


def effective_governance_payload(ws: Workspace) -> Dict[str, Any]:
    """
    Used by app.api.governance and Agent Builder meta.
    Deterministic, UI-friendly representation of effective governance.
    """
    return {
        "workspace_id": str(ws.id),
        "policy_effective": load_policy(ws),
        "rbac_effective": load_rbac(ws),
    }


# -------------------------
# Policy helpers
# -------------------------
def policy_allowed_source_types(ws: Workspace) -> List[str]:
    """
    Returns allowlist for source types if configured, else [] meaning "no allowlist".
    """
    eff = load_policy(ws)
    st = eff.get("retrieval", {}).get("allowed_source_types", [])
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


def policy_assert_allowed_sources(ws: Workspace, requested_source_types: Optional[List[str]]) -> None:
    """
    Enforces allowlist when configured.
    - If allowlist is empty => allow everything
    - If requested is None/[] => allow (means "no filter requested")
    - Else every requested type must be in allowlist
    Raises ValueError when disallowed.
    """
    allowlist = policy_allowed_source_types(ws)
    if not allowlist:
        return

    req = [str(x).strip().lower() for x in (requested_source_types or []) if str(x).strip()]
    if not req:
        return

    for st in req:
        if st not in allowlist:
            raise ValueError(f"Source type '{st}' is not allowed by workspace policy.")


def policy_apply_pii_masking(ws: Workspace, text: str) -> str:
    """
    Deterministic placeholder. Switch based on load_policy(ws)['privacy']['pii_masking'] later.
    """
    return text or ""


# -------------------------
# Audit logging (Step 0.4)
# -------------------------
def _mk_event(
    *,
    ws: Workspace,
    user: Optional[User],
    action: str,
    decision: str,
    reason: str,
    meta: Optional[Dict[str, Any]] = None,
) -> GovernanceEvent:
    return GovernanceEvent(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        user_id=user.id if user else None,
        action=str(action or "").strip()[:120],
        decision=str(decision or "").strip()[:16],
        reason=str(reason or ""),
        meta=meta or {},
        created_at=datetime.now(timezone.utc),
    )


def safe_audit(
    db: Session,
    *,
    ws: Workspace,
    user: Optional[User],
    action: str,
    decision: str,
    reason: str,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Primary helper used across API modules.
    Never breaks request flow if audit insert fails.
    """
    ev = _mk_event(ws=ws, user=user, action=action, decision=decision, reason=reason, meta=meta)
    try:
        db.add(ev)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass


def audit_policy_check(
    db: Session,
    *,
    ws: Workspace,
    user: Optional[User],
    action: str,
    requested_source_types: Optional[List[str]],
    allowlist: Optional[List[str]],
    decision: str,
    reason: str,
) -> None:
    meta = {
        "kind": "policy_check",
        "requested_source_types": [str(x).strip().lower() for x in (requested_source_types or []) if str(x).strip()],
        "allowlist": [str(x).strip().lower() for x in (allowlist or []) if str(x).strip()],
    }
    safe_audit(db, ws=ws, user=user, action=action, decision=decision, reason=reason, meta=meta)


def audit_rbac_check(
    db: Session,
    *,
    ws: Workspace,
    user: Optional[User],
    action: str,
    role: Optional[str],
    allowed_roles: Optional[List[str]],
    decision: str,
    reason: str,
) -> None:
    meta = {
        "kind": "rbac_check",
        "role": (role or "").strip().lower() or None,
        "allowed_roles": [str(x).strip().lower() for x in (allowed_roles or []) if str(x).strip()],
    }
    safe_audit(db, ws=ws, user=user, action=action, decision=decision, reason=reason, meta=meta)


# -------------------------
# RBAC: role resolution + allow checks
# -------------------------
def _normalize_role(role: Optional[str]) -> Optional[str]:
    if role is None:
        return None
    r = str(role).strip().lower()
    return r or None


def _get_user_workspace_role(db: Session, ws: Workspace, user: Optional[User]) -> Optional[str]:
    """
    Returns one of: admin|member|viewer or None if no access.
    Owner => admin.
    """
    if not user:
        return None

    try:
        if str(ws.owner_user_id) == str(user.id):
            return "admin"
    except Exception:
        pass

    wm = db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws.id,
            WorkspaceMember.user_id == user.id,
        )
    ).scalar_one_or_none()

    if not wm:
        return None

    return _normalize_role(getattr(wm, "role", None)) or "viewer"


def _rbac_allowed_roles(ws: Workspace, path: Tuple[str, ...], default: List[str]) -> List[str]:
    """
    Read allowed roles from effective RBAC at a given path.
    Example: ("connectors","can_trigger_sync_roles")
    """
    eff = load_rbac(ws)
    cur: Any = eff
    for p in path:
        if not isinstance(cur, dict):
            return default
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


def _is_role_allowed(role: Optional[str], allowed_roles: List[str]) -> bool:
    r = _normalize_role(role)
    if not r:
        return False
    return r in [a.strip().lower() for a in (allowed_roles or [])]


def rbac_assert(
    db: Session,
    *,
    ws: Workspace,
    user: Optional[User],
    action: str,
    allowed_roles: List[str],
) -> None:
    """
    Commit 5: single RBAC enforcement helper with auditing.
    - Resolves role deterministically
    - Audits allow/deny
    - Raises ValueError if denied (caller converts to HTTP 403)
    """
    role = _get_user_workspace_role(db, ws, user)
    ok = _is_role_allowed(role, allowed_roles)

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
    raise ValueError("Not allowed by RBAC.")


# -------------------------
# RBAC public helpers (existing + new)
# -------------------------
def rbac_can_create_connector(db: Session, ws: Workspace, user: Optional[User]) -> bool:
    role = _get_user_workspace_role(db, ws, user)
    allowed = _rbac_allowed_roles(ws, ("connectors", "can_create_connector_roles"), ["admin"])
    return _is_role_allowed(role, allowed)


def rbac_can_trigger_connector_sync(db: Session, ws: Workspace, user: Optional[User]) -> bool:
    role = _get_user_workspace_role(db, ws, user)
    allowed = _rbac_allowed_roles(ws, ("connectors", "can_trigger_sync_roles"), ["admin", "member"])
    return _is_role_allowed(role, allowed)


def rbac_can_create_agent_base(db: Session, ws: Workspace, user: Optional[User]) -> bool:
    role = _get_user_workspace_role(db, ws, user)
    allowed = _rbac_allowed_roles(ws, ("agent_builder", "can_create_agent_base_roles"), ["admin", "member"])
    return _is_role_allowed(role, allowed)


def rbac_can_publish_agent(db: Session, ws: Workspace, user: Optional[User]) -> bool:
    role = _get_user_workspace_role(db, ws, user)
    allowed = _rbac_allowed_roles(ws, ("agent_builder", "can_publish_agent_roles"), ["admin"])
    return _is_role_allowed(role, allowed)


def rbac_can_archive_agent(db: Session, ws: Workspace, user: Optional[User]) -> bool:
    role = _get_user_workspace_role(db, ws, user)
    allowed = _rbac_allowed_roles(ws, ("agent_builder", "can_archive_agent_roles"), ["admin"])
    return _is_role_allowed(role, allowed)


# NEW (Commit 5): agent-builder runtime permissions
def rbac_allowed_preview_roles(ws: Workspace) -> List[str]:
    return _rbac_allowed_roles(ws, ("agent_builder", "can_preview_agent_roles"), ["admin", "member"])


def rbac_allowed_view_published_roles(ws: Workspace) -> List[str]:
    return _rbac_allowed_roles(ws, ("agent_builder", "can_view_published_agent_roles"), ["admin", "member", "viewer"])


def rbac_allowed_run_roles(ws: Workspace) -> List[str]:
    return _rbac_allowed_roles(ws, ("agent_builder", "can_run_agent_roles"), ["admin", "member"])


# -------------------------
# Commit 5: Policy enforcement helper for definitions
# -------------------------
def extract_definition_source_types(definition_json: Dict[str, Any]) -> List[str]:
    """
    Canonical extraction: definition_json.retrieval.source_types => list[str]
    Stable de-dupe + normalization.
    """
    r = definition_json.get("retrieval") or {}
    if not isinstance(r, dict):
        return []
    st = r.get("source_types") or []
    if not isinstance(st, list):
        return []

    out: List[str] = []
    for x in st:
        s = str(x).strip().lower()
        if s:
            out.append(s)

    seen = set()
    uniq: List[str] = []
    for s in out:
        if s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    return uniq


def enforce_policy_for_definition(
    db: Session,
    *,
    ws: Workspace,
    user: Optional[User],
    definition_json: Dict[str, Any],
    action: str,
) -> None:
    """
    Commit 5: single policy enforcement path for agents_v2 save/publish.
    - Enforces allowlist (if configured)
    - Audits allow/deny
    - Raises ValueError when disallowed
    """
    requested = extract_definition_source_types(definition_json)
    allowlist = policy_allowed_source_types(ws)
    try:
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
        return
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
        raise