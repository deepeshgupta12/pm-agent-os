from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_access
from app.core.config import settings
from app.core.generator import AGENT_TO_DEFAULT_ARTIFACT_TYPE
from app.core.governance import (
    policy_allowed_source_types,
    policy_assert_allowed_sources,
    audit_policy_check,
    effective_governance_payload,
    rbac_assert,
    rbac_allowed_preview_roles,
    rbac_allowed_view_published_roles,
)
from app.core.prompts import build_system_prompt, build_user_prompt_custom
from app.db.session import get_db
from app.db.models import AgentBase, AgentVersion, User, Workspace
from app.schemas.agent_builder import (
    AgentBuilderMetaOut,
    CustomAgentPublishedOut,
    CustomAgentPreviewIn,
    CustomAgentPreviewOut,
)
from app.schemas.core import RetrievalConfigIn

router = APIRouter(tags=["agent_builder"])


# -------------------------
# Constants for Builder Meta
# -------------------------
_TIMEFRAME_PRESETS: List[str] = ["7d", "30d", "90d", "custom"]

_RETRIEVAL_KNOBS: Dict[str, Any] = {
    "defaults": {"k": 6, "alpha": 0.65, "min_score": 0.15, "overfetch_k": 3, "rerank": False},
    "bounds": {
        "k": {"min": 1, "max": 50},
        "alpha": {"min": 0.0, "max": 1.0},
        "min_score": {"min": 0.0, "max": 1.0},
        "overfetch_k": {"min": 1, "max": 10},
        "rerank": {"min": 0, "max": 1},
    },
}


def _artifact_type(definition_json: Dict[str, Any]) -> str:
    art = definition_json.get("artifact") or {}
    if not isinstance(art, dict):
        art = {}
    t = str(art.get("type") or "").strip()
    return t or "strategy_memo"


def _published_version_or_409(db: Session, base_id: uuid.UUID) -> AgentVersion:
    v = (
        db.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_base_id == base_id)
            .where(AgentVersion.status == "published")
            .order_by(AgentVersion.version.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if not v:
        raise HTTPException(status_code=409, detail="No published version exists for this agent base")
    return v


def _merge_retrieval_defaults(defn: Dict[str, Any], override: Optional[RetrievalConfigIn]) -> Dict[str, Any]:
    base = defn.get("retrieval") or {}
    if not isinstance(base, dict):
        base = {}

    out = dict(base)
    if override is None:
        return out

    out["enabled"] = bool(override.enabled)
    out["query"] = str(override.query or "")
    out["k"] = int(override.k)
    out["alpha"] = float(override.alpha)
    out["source_types"] = [str(x).strip().lower() for x in (override.source_types or []) if str(x).strip()]
    out["timeframe"] = override.timeframe or {}
    out["min_score"] = float(override.min_score)
    out["overfetch_k"] = int(override.overfetch_k)
    out["rerank"] = bool(override.rerank)
    return out


def _audit_policy(
    db: Session,
    *,
    ws: Workspace,
    user: User,
    action: str,
    requested: List[str],
    decision: str,
    reason: str,
) -> None:
    allowlist = policy_allowed_source_types(ws)
    audit_policy_check(
        db,
        ws=ws,
        user=user,
        action=action,
        requested_source_types=requested,
        allowlist=allowlist,
        decision=decision,
        reason=reason,
    )


def _enforce_policy_sources(db: Session, ws: Workspace, user: User, requested: Optional[List[str]], action: str) -> None:
    req = [str(x).strip().lower() for x in (requested or []) if str(x).strip()]
    try:
        policy_assert_allowed_sources(ws, req or None)
        _audit_policy(db, ws=ws, user=user, action=action, requested=req, decision="allow", reason="ok")
    except ValueError as e:
        _audit_policy(db, ws=ws, user=user, action=action, requested=req, decision="deny", reason=str(e))
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/workspaces/{workspace_id}/agent-builder/meta", response_model=AgentBuilderMetaOut)
def agent_builder_meta(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)

    allowed_source_types = policy_allowed_source_types(ws)

    # Artifact types = union of known defaults; UI can show these templates.
    artifact_types = sorted({v for v in (AGENT_TO_DEFAULT_ARTIFACT_TYPE or {}).values() if str(v).strip()})

    gov = effective_governance_payload(ws)

    return AgentBuilderMetaOut(
        workspace_id=str(ws.id),
        allowed_source_types=allowed_source_types,
        timeframe_presets=list(_TIMEFRAME_PRESETS),
        retrieval_knobs=dict(_RETRIEVAL_KNOBS),
        artifact_types=artifact_types,
        policy_effective=gov.get("policy_effective") or {},
        rbac_effective=gov.get("rbac_effective") or {},
    )


@router.get("/workspaces/{workspace_id}/agent-bases/{base_id}/published", response_model=CustomAgentPublishedOut)
def get_published_custom_agent(
    workspace_id: str,
    base_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)

    # Commit 5: RBAC enforcement (who can view published)
    try:
        rbac_assert(
            db,
            ws=ws,
            user=user,
            action="rbac.agent_builder.view_published",
            allowed_roles=rbac_allowed_view_published_roles(ws),
        )
    except ValueError:
        raise HTTPException(status_code=403, detail="Not allowed by RBAC.")

    try:
        bid = uuid.UUID(base_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Agent base not found")

    base = db.get(AgentBase, bid)
    if not base or str(base.workspace_id) != str(ws.id):
        raise HTTPException(status_code=404, detail="Agent base not found")

    vpub = _published_version_or_409(db, base.id)
    return CustomAgentPublishedOut(
        agent_base_id=str(base.id),
        published_version_id=str(vpub.id),
        published_version=int(vpub.version),
        status="published",
        definition_json=vpub.definition_json or {},
    )


@router.post("/workspaces/{workspace_id}/agent-bases/{base_id}/preview", response_model=CustomAgentPreviewOut)
def preview_custom_agent(
    workspace_id: str,
    base_id: str,
    payload: CustomAgentPreviewIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)

    # Commit 5: RBAC enforcement (who can preview)
    try:
        rbac_assert(
            db,
            ws=ws,
            user=user,
            action="rbac.agent_builder.preview",
            allowed_roles=rbac_allowed_preview_roles(ws),
        )
    except ValueError:
        raise HTTPException(status_code=403, detail="Not allowed by RBAC.")

    try:
        bid = uuid.UUID(base_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Agent base not found")

    base = db.get(AgentBase, bid)
    if not base or str(base.workspace_id) != str(ws.id):
        raise HTTPException(status_code=404, detail="Agent base not found")

    vpub = _published_version_or_409(db, base.id)
    defn = vpub.definition_json or {}

    # Resolve retrieval config (defaults + override)
    r = _merge_retrieval_defaults(defn, payload.retrieval)
    r_source_types = [str(x).strip().lower() for x in (r.get("source_types") or []) if str(x).strip()]

    # Enforce policy on source selection (preview should behave exactly like save/run)
    _enforce_policy_sources(
        db,
        ws,
        user,
        r_source_types or None,
        action="policy.allowlist.agent_builder.preview_definition",
    )

    artifact_type = _artifact_type(defn)

    # Build prompts (for UI preview). This does NOT execute the run.
    system_prompt = build_system_prompt()
    user_prompt = build_user_prompt_custom(
        definition_json=defn,
        input_payload=payload.input_payload or {},
        evidence_text="",  # preview does not retrieve (no side effects)
        artifact_type=artifact_type,
        citations_block="",  # preview does not fetch evidence pack
    )

    notes: List[str] = []
    if not (settings.LLM_ENABLED and settings.OPENAI_API_KEY):
        notes.append("LLM is disabled; preview shows prompts only. Execution will generate deterministic scaffold.")

    return CustomAgentPreviewOut(
        ok=True,
        agent_base_id=str(base.id),
        published_version=int(vpub.version),
        artifact_type=artifact_type,
        retrieval_resolved=r,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        llm_enabled=bool(settings.LLM_ENABLED and settings.OPENAI_API_KEY),
        notes=notes,
    )