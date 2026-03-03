from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from app.db.models import Workspace, User
from app.api.deps import get_workspace_role


# -------------------------
# Defaults (safe + permissive for V0/V3 scaffolding)
# -------------------------
DEFAULT_POLICY: Dict[str, Any] = {
    # High-level safety controls (placeholders; enforcement added in later steps)
    "retrieval": {
        # Example: allowed sources by type; empty => allow all
        "allowed_source_types": [],  # e.g. ["docs", "github"]
        # Example: retention policy for stored evidence/artifacts (not enforced yet)
        "retention_days": None,
        # Example: whether to block external links in generated artifacts (not enforced yet)
        "block_external_links": False,
    },
    "privacy": {
        # Example: PII masking modes (not enforced yet)
        "pii_masking": {"enabled": False, "mode": "none"},  # none|soft|strict
    },
}


DEFAULT_RBAC: Dict[str, Any] = {
    # V3 “advanced RBAC” (beyond owner/admin/member/viewer).
    # In Step 1 we’ll interpret this for agent building/publishing.
    "agent_builder": {
        "can_create_agent_base_roles": ["admin", "member"],
        "can_publish_agent_roles": ["admin"],
        "can_archive_agent_roles": ["admin"],
    },
    "connectors": {
        # Per connector type rules could live here later
        "can_create_connector_roles": ["admin"],
        "can_trigger_sync_roles": ["admin", "member"],
    },
}


ROLE_ORDER = {"viewer": 1, "member": 2, "admin": 3}


def _role_at_least(role: Optional[str], min_role: str) -> bool:
    if not role:
        return False
    return ROLE_ORDER.get(role, 0) >= ROLE_ORDER.get(min_role, 0)


# -------------------------
# Loaders (merge defaults with workspace overrides)
# -------------------------
def load_policy(ws: Workspace) -> Dict[str, Any]:
    pol = ws.policy_json or {}
    if not isinstance(pol, dict):
        pol = {}
    out = dict(DEFAULT_POLICY)

    # shallow merge for top-level keys
    for k, v in pol.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            merged = dict(out.get(k) or {})
            merged.update(v)
            out[k] = merged
        else:
            out[k] = v
    return out


def load_rbac(ws: Workspace) -> Dict[str, Any]:
    rb = ws.rbac_json or {}
    if not isinstance(rb, dict):
        rb = {}
    out = dict(DEFAULT_RBAC)

    for k, v in rb.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            merged = dict(out.get(k) or {})
            merged.update(v)
            out[k] = merged
        else:
            out[k] = v
    return out


# -------------------------
# Policy hooks (stubs to be enforced in later steps)
# -------------------------
def policy_allowed_source_types(ws: Workspace) -> List[str]:
    pol = load_policy(ws)
    retrieval = pol.get("retrieval") or {}
    allowed = retrieval.get("allowed_source_types") or []
    if not isinstance(allowed, list):
        return []
    return [str(x).strip().lower() for x in allowed if str(x).strip()]


def policy_assert_allowed_sources(
    ws: Workspace,
    requested_source_types: Optional[List[str]],
) -> None:
    """
    Step 0.2: stub — does NOT raise yet unless policy explicitly defines allowlist.
    Later: this becomes a hard enforcement.
    """
    allowlist = policy_allowed_source_types(ws)
    if not allowlist:
        return  # allow all

    req = [str(x).strip().lower() for x in (requested_source_types or []) if str(x).strip()]
    # If request empty but allowlist exists, still allow (means “use defaults”)
    if not req:
        return

    for t in req:
        if t not in allowlist:
            raise ValueError(f"Source type '{t}' is not allowed by workspace policy.")


def policy_apply_pii_masking(ws: Workspace, text: str) -> str:
    """
    Placeholder. In Step 2/3 we’ll implement masking depending on privacy policy.
    """
    pol = load_policy(ws)
    privacy = pol.get("privacy") or {}
    pii = privacy.get("pii_masking") or {}
    enabled = bool(pii.get("enabled"))
    if not enabled:
        return text
    # For now: no-op (we’ll implement later)
    return text


# -------------------------
# RBAC hooks (V3 advanced RBAC)
# -------------------------
def rbac_can_create_agent_base(db: Session, ws: Workspace, user: User) -> bool:
    rb = load_rbac(ws)
    rule = rb.get("agent_builder") or {}
    allowed_roles = rule.get("can_create_agent_base_roles") or ["admin", "member"]

    role = get_workspace_role(db, ws, user)
    return bool(role and role.lower() in [str(r).lower() for r in allowed_roles])


def rbac_can_publish_agent(db: Session, ws: Workspace, user: User) -> bool:
    rb = load_rbac(ws)
    rule = rb.get("agent_builder") or {}
    allowed_roles = rule.get("can_publish_agent_roles") or ["admin"]

    role = get_workspace_role(db, ws, user)
    return bool(role and role.lower() in [str(r).lower() for r in allowed_roles])


def rbac_can_archive_agent(db: Session, ws: Workspace, user: User) -> bool:
    rb = load_rbac(ws)
    rule = rb.get("agent_builder") or {}
    allowed_roles = rule.get("can_archive_agent_roles") or ["admin"]

    role = get_workspace_role(db, ws, user)
    return bool(role and role.lower() in [str(r).lower() for r in allowed_roles])