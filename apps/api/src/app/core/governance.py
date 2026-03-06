from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import GovernanceEvent, User, Workspace, WorkspaceMember


# -------------------------
# Deterministic effective governance defaults
# -------------------------
_DEFAULT_POLICY: Dict[str, Any] = {
    # V1 Policy Center: internal-only toggle
    "internal_only": False,
    "retrieval": {
        # empty => no allowlist enforcement
        "allowed_source_types": [],
        # None => do not enforce retention (yet)
        "retention_days": None,
        # v1 toggle used in UI/policy payloads
        "block_external_links": False,
    },
    "privacy": {
        "pii_masking": {
            "enabled": False,
            # none | write_time | export_time | both
            "mode": "none",
        }
    },
}

_DEFAULT_RBAC: Dict[str, Any] = {
    "agent_builder": {
        "can_create_agent_base_roles": ["admin", "member"],
        "can_publish_agent_roles": ["admin"],
        "can_archive_agent_roles": ["admin"],
        "can_preview_agent_roles": ["admin", "member"],
        "can_view_published_agent_roles": ["admin", "member", "viewer"],
        "can_run_agent_roles": ["admin", "member"],
    },
    "connectors": {
        # workspace-wide defaults
        "can_read_connectors_roles": ["admin", "member", "viewer"],
        "can_create_connector_roles": ["admin"],
        "can_update_connector_roles": ["admin"],
        "can_trigger_sync_roles": ["admin", "member"],
        # optional overrides
        "per_type": {},  # e.g. {"github": {"can_trigger_sync_roles": ["admin"]}}
        "per_connector": {},  # e.g. {"<connector_uuid>": {"can_trigger_sync_roles": ["admin"]}}
    },
    "action_center": {
        # workspace-wide defaults
        "can_list_actions_roles": ["admin", "member", "viewer"],
        "can_create_action_roles": ["admin", "member"],
        "can_review_action_roles": ["admin"],  # default: only admins review
        "can_cancel_action_roles": ["admin"],  # default: only admins cancel (you still allow creator cancel in route)
        "can_execute_action_roles": ["admin"],  # default: only admins execute side-effects
        # optional overrides by action type
        "per_type": {},  # e.g. {"decision_log_create": {"can_review_action_roles": ["admin","member"]}}
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


def normalize_policy_json(raw: Any) -> Dict[str, Any]:
    """
    Normalizes incoming policy JSON into a safe, deterministic shape.
    Keeps the surface area intentionally small for v1.

    Expected v1 shape:
    {
      "internal_only": <bool>,
      "retrieval": {
        "allowed_source_types": [..],
        "retention_days": <int|null>,
        "block_external_links": <bool>
      },
      "privacy": {
        "pii_masking": { "enabled": <bool>, "mode": "none" | "write_time" | "export_time" | "both" }
      }
    }
    """
    if not isinstance(raw, dict):
        raw = {}

    # IMPORTANT (Commit 10): preserve internal_only toggle
    internal_only = bool(raw.get("internal_only", False))

    retrieval = raw.get("retrieval")
    if not isinstance(retrieval, dict):
        retrieval = {}

    privacy = raw.get("privacy")
    if not isinstance(privacy, dict):
        privacy = {}

    pii = privacy.get("pii_masking")
    if not isinstance(pii, dict):
        pii = {}

    # allowed_source_types -> list[str] lowercase deduped
    ast = retrieval.get("allowed_source_types", [])
    if not isinstance(ast, list):
        ast = []
    clean_types: List[str] = []
    for x in ast:
        s = str(x).strip().lower()
        if s:
            clean_types.append(s)
    # stable de-dupe
    seen = set()
    allowed_source_types: List[str] = []
    for s in clean_types:
        if s in seen:
            continue
        seen.add(s)
        allowed_source_types.append(s)

    # retention_days -> int | None (must be positive if set)
    rd = retrieval.get("retention_days", None)
    retention_days: Optional[int] = None
    if rd is None or rd == "":
        retention_days = None
    else:
        try:
            rd_i = int(rd)
            if rd_i > 0:
                retention_days = rd_i
            else:
                retention_days = None
        except Exception:
            retention_days = None

    # block_external_links -> bool
    bel = retrieval.get("block_external_links", False)
    block_external_links = bool(bel)

    # pii_masking.enabled/mode (keep permissive, but deterministic)
    enabled = bool(pii.get("enabled", False))
    mode = str(pii.get("mode", "none") or "none").strip().lower() or "none"
    if mode not in {"none", "write_time", "export_time", "both"}:
        mode = "none"

    normalized: Dict[str, Any] = {
        "internal_only": internal_only,
        "retrieval": {
            "allowed_source_types": allowed_source_types,
            "retention_days": retention_days,
            "block_external_links": block_external_links,
        },
        "privacy": {
            "pii_masking": {
                "enabled": enabled,
                "mode": mode,
            }
        },
    }
    return normalized


def retention_cutoff_ts(ws: Workspace) -> Optional[datetime]:
    """
    Returns a UTC datetime cutoff based on policy.retrieval.retention_days.
    If retention_days is not set or invalid => None.

    Cutoff semantics:
    - delete items with created_at < cutoff
    """
    eff = load_policy(ws)
    retrieval = eff.get("retrieval", {})
    if not isinstance(retrieval, dict):
        return None

    rd = retrieval.get("retention_days")
    if rd is None or rd == "":
        return None

    try:
        days = int(rd)
    except Exception:
        return None

    if days <= 0:
        return None

    now = datetime.now(timezone.utc)
    return now - timedelta(days=days)


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


def policy_retention_days(ws: Workspace) -> Optional[int]:
    """
    Returns retention days if configured, else None.
    """
    eff = load_policy(ws)
    v = eff.get("retrieval", {}).get("retention_days", None)
    if v is None:
        return None
    try:
        n = int(v)
        if n <= 0:
            return None
        return n
    except Exception:
        return None


def policy_internal_only(ws: Workspace) -> bool:
    eff = load_policy(ws)
    return bool(eff.get("internal_only", False))


def policy_pii_masking_config(ws: Workspace) -> Dict[str, Any]:
    eff = load_policy(ws)
    cfg = eff.get("privacy", {}).get("pii_masking", {}) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    enabled = bool(cfg.get("enabled", False))
    mode = str(cfg.get("mode", "none") or "none").strip().lower()
    if mode not in {"none", "write_time", "export_time", "both"}:
        mode = "none"
    return {"enabled": enabled, "mode": mode}


_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[- ]?)?(?:\(?\d{3,5}\)?[- ]?)?\d{6,10}\b")
_LONG_NUM_RE = re.compile(r"\b\d{9,16}\b")


def _mask_pii_basic(text: str) -> str:
    if not text:
        return ""
    out = text
    out = _EMAIL_RE.sub("[REDACTED_EMAIL]", out)
    out = _PHONE_RE.sub("[REDACTED_PHONE]", out)
    out = _LONG_NUM_RE.sub("[REDACTED_ID]", out)
    return out


def policy_apply_pii_masking(ws: Workspace, text: str, *, phase: str) -> str:
    """
    phase: "write" | "export"
    mode mapping:
    - none => no masking
    - write_time => mask only at write
    - export_time => mask only at export
    - both => mask both
    """
    cfg = policy_pii_masking_config(ws)
    if not cfg.get("enabled"):
        return text or ""

    mode = str(cfg.get("mode") or "none").strip().lower()
    phase = str(phase or "").strip().lower()

    if mode == "none":
        return text or ""
    if mode == "write_time" and phase != "write":
        return text or ""
    if mode == "export_time" and phase != "export":
        return text or ""

    return _mask_pii_basic(text or "")


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


def audit_internal_only_check(
    db: Session,
    *,
    ws: Workspace,
    user: Optional[User],
    action: str,
    decision: str,
    reason: str,
) -> None:
    meta = {
        "kind": "policy_internal_only",
        "internal_only": policy_internal_only(ws),
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

    seen = set()
    uniq: List[str] = []
    for s in out:
        if s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    return uniq


def _rbac_get_dict(ws: Workspace, path: Tuple[str, ...]) -> Optional[Dict[str, Any]]:
    eff = load_rbac(ws)
    cur: Any = eff
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur if isinstance(cur, dict) else None


def _rbac_get_list(ws: Workspace, path: Tuple[str, ...], default: List[str]) -> List[str]:
    return _rbac_allowed_roles(ws, path, default)


def _normalize_uuid_str(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


# -------------------------
# Connectors RBAC helpers (with overrides)
# -------------------------
def rbac_allowed_connectors_read_roles(ws: Workspace) -> List[str]:
    return _rbac_get_list(ws, ("connectors", "can_read_connectors_roles"), ["admin", "member", "viewer"])


def rbac_allowed_connectors_create_roles(ws: Workspace) -> List[str]:
    return _rbac_get_list(ws, ("connectors", "can_create_connector_roles"), ["admin"])


def rbac_allowed_connectors_update_roles(ws: Workspace) -> List[str]:
    return _rbac_get_list(ws, ("connectors", "can_update_connector_roles"), ["admin"])


def rbac_allowed_connectors_trigger_sync_roles(
    ws: Workspace,
    *,
    connector_type: Optional[str] = None,
    connector_id: Optional[str] = None,
) -> List[str]:
    base = _rbac_get_list(ws, ("connectors", "can_trigger_sync_roles"), ["admin", "member"])

    ctype = (connector_type or "").strip().lower()
    if ctype:
        per_type = _rbac_get_dict(ws, ("connectors", "per_type")) or {}
        rule = per_type.get(ctype)
        if isinstance(rule, dict) and isinstance(rule.get("can_trigger_sync_roles"), list):
            return _rbac_allowed_roles(ws, ("connectors", "per_type", ctype, "can_trigger_sync_roles"), base)

    cid = _normalize_uuid_str(connector_id)
    if cid:
        per_conn = _rbac_get_dict(ws, ("connectors", "per_connector")) or {}
        rule = per_conn.get(cid)
        if isinstance(rule, dict) and isinstance(rule.get("can_trigger_sync_roles"), list):
            return _rbac_allowed_roles(ws, ("connectors", "per_connector", cid, "can_trigger_sync_roles"), base)

    return base


# -------------------------
# Action Center RBAC helpers (with per-type overrides)
# -------------------------
def rbac_allowed_action_center_list_roles(ws: Workspace) -> List[str]:
    return _rbac_get_list(ws, ("action_center", "can_list_actions_roles"), ["admin", "member", "viewer"])


def rbac_allowed_action_center_create_roles(ws: Workspace, *, action_type: Optional[str] = None) -> List[str]:
    base = _rbac_get_list(ws, ("action_center", "can_create_action_roles"), ["admin", "member"])
    at = (action_type or "").strip()
    if not at:
        return base
    per = _rbac_get_dict(ws, ("action_center", "per_type")) or {}
    rule = per.get(at)
    if isinstance(rule, dict) and isinstance(rule.get("can_create_action_roles"), list):
        return _rbac_allowed_roles(ws, ("action_center", "per_type", at, "can_create_action_roles"), base)
    return base


def rbac_allowed_action_center_review_roles(ws: Workspace, *, action_type: Optional[str] = None) -> List[str]:
    base = _rbac_get_list(ws, ("action_center", "can_review_action_roles"), ["admin"])
    at = (action_type or "").strip()
    if not at:
        return base
    per = _rbac_get_dict(ws, ("action_center", "per_type")) or {}
    rule = per.get(at)
    if isinstance(rule, dict) and isinstance(rule.get("can_review_action_roles"), list):
        return _rbac_allowed_roles(ws, ("action_center", "per_type", at, "can_review_action_roles"), base)
    return base


def rbac_allowed_action_center_cancel_roles(ws: Workspace, *, action_type: Optional[str] = None) -> List[str]:
    base = _rbac_get_list(ws, ("action_center", "can_cancel_action_roles"), ["admin"])
    at = (action_type or "").strip()
    if not at:
        return base
    per = _rbac_get_dict(ws, ("action_center", "per_type")) or {}
    rule = per.get(at)
    if isinstance(rule, dict) and isinstance(rule.get("can_cancel_action_roles"), list):
        return _rbac_allowed_roles(ws, ("action_center", "per_type", at, "can_cancel_action_roles"), base)
    return base


def rbac_allowed_action_center_execute_roles(ws: Workspace, *, action_type: Optional[str] = None) -> List[str]:
    base = _rbac_get_list(ws, ("action_center", "can_execute_action_roles"), ["admin"])
    at = (action_type or "").strip()
    if not at:
        return base
    per = _rbac_get_dict(ws, ("action_center", "per_type")) or {}
    rule = per.get(at)
    if isinstance(rule, dict) and isinstance(rule.get("can_execute_action_roles"), list):
        return _rbac_allowed_roles(ws, ("action_center", "per_type", at, "can_execute_action_roles"), base)
    return base


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
# RBAC public helpers
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


def rbac_allowed_preview_roles(ws: Workspace) -> List[str]:
    return _rbac_allowed_roles(ws, ("agent_builder", "can_preview_agent_roles"), ["admin", "member"])


def rbac_allowed_view_published_roles(ws: Workspace) -> List[str]:
    return _rbac_allowed_roles(ws, ("agent_builder", "can_view_published_agent_roles"), ["admin", "member", "viewer"])


def rbac_allowed_run_roles(ws: Workspace) -> List[str]:
    return _rbac_allowed_roles(ws, ("agent_builder", "can_run_agent_roles"), ["admin", "member"])


# -------------------------
# Policy enforcement helper for agent definitions
# -------------------------
def extract_definition_source_types(definition_json: Dict[str, Any]) -> List[str]:
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