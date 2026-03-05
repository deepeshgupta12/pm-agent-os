from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_access, require_workspace_role_min
from app.core.config import settings
from app.core.governance import (
    policy_allowed_source_types,
    policy_assert_allowed_sources,
    policy_apply_pii_masking,
    audit_policy_check,
)
from app.core.retrieval_search import hybrid_retrieve
from app.core.evidence_format import format_evidence_for_prompt
from app.core.prompts import build_system_prompt, build_user_prompt_custom
from app.core.llm_client import llm_generate_markdown
from app.core.citations import (
    build_citation_pack,
    output_has_any_citations,
    body_has_inline_citations,
    build_inline_citation_patch,
    citation_enforcement_report,
    render_citation_compliance_md,
)

from app.db.session import get_db
from app.db.models import (
    Workspace,
    User,
    Run,
    RunLog,
    RunStatusEvent,
    Artifact,
    Evidence,
    AgentBase,
    AgentVersion,
    AgentDefinition,
)

from app.schemas.core import RunOut, RetrievalConfigIn
from app.schemas.agents_v2 import CustomAgentRunIn

router = APIRouter(tags=["custom_agent_runs"])


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _custom_agent_id(base_id: uuid.UUID) -> str:
    return f"custom:{str(base_id)}"


def _audit_policy(
    db: Session,
    *,
    ws: Workspace,
    user: User,
    action: str,
    requested_source_types: Optional[List[str]],
    decision: str,
    reason: str,
) -> None:
    allowlist = policy_allowed_source_types(ws)
    audit_policy_check(
        db,
        ws=ws,
        user=user,
        action=action,
        requested_source_types=requested_source_types or [],
        allowlist=allowlist,
        decision=decision,
        reason=reason,
    )


def _enforce_policy_sources(db: Session, ws: Workspace, user: User, requested: Optional[List[str]], action: str) -> None:
    try:
        policy_assert_allowed_sources(ws, requested)
        _audit_policy(db, ws=ws, user=user, action=action, requested_source_types=requested or [], decision="allow", reason="ok")
    except ValueError as e:
        _audit_policy(db, ws=ws, user=user, action=action, requested_source_types=requested or [], decision="deny", reason=str(e))
        raise HTTPException(status_code=403, detail=str(e))


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


def _artifact_type(definition_json: Dict[str, Any]) -> str:
    art = definition_json.get("artifact") or {}
    if not isinstance(art, dict):
        art = {}
    t = str(art.get("type") or "").strip()
    return t or "strategy_memo"


def _merge_retrieval_defaults(defn: Dict[str, Any], override: Optional[RetrievalConfigIn]) -> Dict[str, Any]:
    """
    defn.retrieval is the default.
    override (if provided) can overwrite query/k/alpha/source_types/timeframe/knobs.
    """
    base = defn.get("retrieval") or {}
    if not isinstance(base, dict):
        base = {}

    out = dict(base)

    if override is None:
        return out

    out["enabled"] = bool(override.enabled)
    if override.query is not None:
        out["query"] = str(override.query or "")
    out["k"] = int(override.k)
    out["alpha"] = float(override.alpha)
    out["source_types"] = [str(x).strip().lower() for x in (override.source_types or []) if str(x).strip()]
    out["timeframe"] = override.timeframe or {}
    out["min_score"] = float(override.min_score)
    out["overfetch_k"] = int(override.overfetch_k)
    out["rerank"] = bool(override.rerank)
    return out


def _timeframe_to_bounds(timeframe: Optional[Dict[str, Any]]) -> tuple[Optional[datetime], Optional[datetime]]:
    tf = timeframe or {}
    preset = (tf.get("preset") or "").strip().lower()
    now = datetime.now(timezone.utc)

    if preset in {"7d", "30d", "90d"}:
        days = int(preset.replace("d", ""))
        return now - timedelta(days=days), now

    if preset == "custom":
        start_date = tf.get("start_date")
        end_date = tf.get("end_date")

        def parse_ymd(s: str) -> datetime:
            dt = datetime.strptime(s, "%Y-%m-%d")
            return dt.replace(tzinfo=timezone.utc)

        start_ts = parse_ymd(start_date) if start_date else None
        end_ts = parse_ymd(end_date) if end_date else None
        if end_ts is not None:
            end_ts = end_ts + timedelta(days=1) - timedelta(seconds=1)
        return start_ts, end_ts

    return None, None


def _write_status_event(db: Session, *, run: Run, from_status: Optional[str], to_status: str, message: str, meta: Dict[str, Any]) -> None:
    ev = RunStatusEvent(
        run_id=run.id,
        from_status=from_status,
        to_status=to_status,
        message=message,
        meta=meta or {},
    )
    db.add(ev)
    db.commit()


def _set_run_status(db: Session, *, run: Run, to_status: str, message: str, meta: Dict[str, Any]) -> None:
    from_status = run.status
    run.status = to_status
    db.add(run)
    db.commit()
    db.refresh(run)
    _write_status_event(db, run=run, from_status=from_status, to_status=to_status, message=message, meta=meta or {})


@router.post("/workspaces/{workspace_id}/agent-bases/{base_id}/runs", response_model=RunOut)
def run_custom_agent(
    workspace_id: str,
    base_id: str,
    payload: CustomAgentRunIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)

    # base + published version
    try:
        bid = uuid.UUID(base_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Agent base not found")

    base = db.get(AgentBase, bid)
    if not base or str(base.workspace_id) != str(ws.id):
        raise HTTPException(status_code=404, detail="Agent base not found")

    vpub = _published_version_or_409(db, base.id)
    defn = vpub.definition_json or {}

    # Ensure AgentDefinition exists (defensive; publish should upsert, but don’t trust)
    agent_id = _custom_agent_id(base.id)
    ad = db.get(AgentDefinition, agent_id)
    if not ad:
        raise HTTPException(status_code=409, detail="Custom agent is not registered (publish it again)")

    # Resolve artifact type
    artifact_type = _artifact_type(defn)
    title = f"{artifact_type.replace('_', ' ').title()} — Draft"

    # Resolve retrieval config (defaults + optional override)
    r = _merge_retrieval_defaults(defn, payload.retrieval)
    r_enabled = bool(r.get("enabled", True))
    r_query = str(r.get("query") or "").strip()
    r_k = int(r.get("k") or 6)
    r_alpha = float(r.get("alpha") or 0.65)
    r_source_types = [str(x).strip().lower() for x in (r.get("source_types") or []) if str(x).strip()]
    r_timeframe = r.get("timeframe") or {}
    r_min_score = float(r.get("min_score") or 0.15)
    r_overfetch_k = int(r.get("overfetch_k") or 3)
    r_rerank = bool(r.get("rerank") or False)

    # Policy enforcement (and audit)
    _enforce_policy_sources(
        db,
        ws,
        user,
        r_source_types or None,
        action="policy.allowlist.runs.custom_agent_run.retrieval",
    )

    # Create run
    run = Run(
        workspace_id=ws.id,
        agent_id=agent_id,  # FK-safe
        created_by_user_id=user.id,
        status="created",
        input_payload=payload.input_payload or {},
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    _write_status_event(db, run=run, from_status=None, to_status="created", message="Run created", meta={"custom_agent_base_id": str(base.id)})
    _set_run_status(db, run=run, to_status="running", message="Run started", meta={"custom_agent_base_id": str(base.id)})

    ev_items: List[Evidence] = []
    retrieval_meta: Dict[str, Any] = {
        "enabled": bool(r_enabled),
        "query": r_query,
        "k": int(r_k),
        "alpha": float(r_alpha),
        "source_types": r_source_types,
        "timeframe": r_timeframe,
        "min_score": float(r_min_score),
        "overfetch_k": int(r_overfetch_k),
        "rerank": bool(r_rerank),
        "evidence_count": 0,
    }

    # Retrieval + attach evidence
    if r_enabled and r_query:
        start_ts, end_ts = _timeframe_to_bounds(r_timeframe)

        items = hybrid_retrieve(
            db,
            workspace_id=str(ws.id),
            q=r_query,
            k=r_k,
            alpha=r_alpha,
            source_types=r_source_types or None,
            start_ts=start_ts,
            end_ts=end_ts,
            min_score=r_min_score,
            overfetch_k=r_overfetch_k,
            rerank=r_rerank,
        )

        batch_id = str(uuid.uuid4())
        for rank, it in enumerate(items, start=1):
            source_ref = f"doc:{it.get('document_id')}#chunk:{it.get('chunk_id')}"
            meta = {
                "batch_id": batch_id,
                "batch_kind": "custom_agent_run",
                "rank": rank,
                "score_hybrid": float(it.get("score_hybrid") or 0.0),
                "score_fts": float(it.get("score_fts") or 0.0),
                "score_vec": float(it.get("score_vec") or 0.0),
                "score_rerank_bonus": it.get("score_rerank_bonus"),
                "score_final": it.get("score_final"),
                "document_title": it.get("document_title", ""),
                "source_id": it.get("source_id", ""),
                "chunk_index": int(it.get("chunk_index") or 0),
                "retrieval": {**retrieval_meta},
            }
            ev = Evidence(
                run_id=run.id,
                kind="snippet",
                source_name="retrieval",
                source_ref=source_ref,
                excerpt=policy_apply_pii_masking(ws, str(it.get("snippet") or "")),
                meta=meta,
            )
            db.add(ev)
            ev_items.append(ev)

        db.commit()
        for e in ev_items:
            db.refresh(e)

        retrieval_meta["evidence_count"] = len(ev_items)
        retrieval_meta["batch_id"] = batch_id

        ip = dict(run.input_payload or {})
        ip["_retrieval"] = retrieval_meta
        run.input_payload = ip
        db.add(run)
        db.commit()
        db.refresh(run)

        db.add(
            RunLog(
                run_id=run.id,
                level="info" if ev_items else "warn",
                message="Custom agent retrieval completed; evidence attached." if ev_items else "Custom agent retrieval completed; no evidence found.",
                meta=retrieval_meta,
            )
        )
        db.commit()

    # Generate markdown (LLM or deterministic)
    evidence_text = format_evidence_for_prompt(ev_items)
    md = ""
    if settings.LLM_ENABLED and settings.OPENAI_API_KEY:
        # Build evidence pack for citation grounding
        evidence_dicts = [
            {"excerpt": e.excerpt, "source_ref": e.source_ref, "source_name": e.source_name, "meta": e.meta or {}}
            for e in ev_items
        ]
        citations_block, sources_section_md, normalized = build_citation_pack(evidence_dicts)

        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt_custom(
            definition_json=defn,
            input_payload=payload.input_payload or {},
            evidence_text=evidence_text,
            artifact_type=artifact_type,
            citations_block=citations_block,
        )

        md = llm_generate_markdown(system_prompt=system_prompt, user_prompt=user_prompt)

        if not md.lstrip().startswith("#"):
            md = f"# {title}\n\n" + md

        if "## Sources" not in md and citations_block.strip():
            md = md.rstrip() + "\n\n" + sources_section_md + "\n"

        if len(ev_items) > 0 and not output_has_any_citations(md):
            md = (
                md.rstrip()
                + "\n\n### ⚠️ Citation check\n"
                + "Evidence was available, but no citations like [1] were found. Please add inline citations.\n\n"
                + sources_section_md
                + "\n"
            )

        if len(ev_items) > 0 and not body_has_inline_citations(md):
            patch = build_inline_citation_patch(normalized)
            md = md.rstrip() + "\n\n" + patch + "\n"
    else:
        # Deterministic scaffold
        md = f"""# {title}

## Summary
Deterministic draft scaffold (LLM disabled).

## Goal
{(payload.input_payload or {}).get('goal') or '- (not provided)'}

## Context
{(payload.input_payload or {}).get('context') or '- (not provided)'}

## Constraints
{(payload.input_payload or {}).get('constraints') or '- (not provided)'}

## Notes
- This custom agent run used published version: {int(vpub.version)}
- Evidence attached: {len(ev_items)}

## Next Actions
- Enable LLM mode for grounded drafting OR expand evidence corpus.
"""

    # Citation compliance report (only when evidence exists)
    try:
        rep = citation_enforcement_report(artifact_type=artifact_type, md=md, evidence_count=len(ev_items))
        if len(ev_items) > 0:
            md = md.rstrip() + "\n\n" + render_citation_compliance_md(rep) + "\n"
            db.add(
                RunLog(
                    run_id=run.id,
                    level="info" if rep.get("ok") else "warn",
                    message="Citation enforcement check",
                    meta=rep,
                )
            )
            db.commit()
    except Exception:
        pass

    # Create artifact
    art = Artifact(
        run_id=run.id,
        type=artifact_type,
        title=title,
        content_md=md,
        logical_key=artifact_type,
        version=1,
        status="draft",
    )
    db.add(art)
    db.commit()

    # finalize run
    run.output_summary = f"Custom agent run completed. Generated artifact: {artifact_type}. Evidence: {len(ev_items)} snippet(s)."
    db.add(run)
    db.commit()
    db.refresh(run)

    _set_run_status(
        db,
        run=run,
        to_status="completed",
        message="Run completed",
        meta={"artifact_type": artifact_type, "evidence_count": len(ev_items), "custom_agent_base_id": str(base.id)},
    )

    return RunOut(
        id=str(run.id),
        workspace_id=str(run.workspace_id),
        agent_id=str(run.agent_id),
        created_by_user_id=str(run.created_by_user_id),
        status=run.status,
        input_payload=run.input_payload,
        output_summary=run.output_summary,
    )