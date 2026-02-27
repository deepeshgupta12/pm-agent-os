from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_access, require_workspace_role_min
from app.core.generator import build_initial_artifact, build_run_summary, AGENT_TO_DEFAULT_ARTIFACT_TYPE
from app.core.config import settings
from app.core.evidence_format import format_evidence_for_prompt
from app.core.citations import (
    build_citation_pack,
    output_has_any_citations,
    body_has_inline_citations,
    build_inline_citation_patch,
)
from app.core.retrieval_search import hybrid_retrieve
from app.db.session import get_db
from app.db.models import Workspace, Run, RunLog, AgentDefinition, Artifact, Evidence, User
from app.db.retrieval_models import Source
from app.schemas.core import RunCreateIn, RunOut, RunStatusUpdateIn

from app.schemas.core import (
    RunLogCreateIn,
    RunLogOut,
    RunTimelineEventOut,
)

router = APIRouter(tags=["runs"])


def _parse_uuid(id_str: str) -> uuid.UUID:
    try:
        return uuid.UUID(id_str)
    except Exception:
        raise HTTPException(status_code=404, detail="Run not found")


def _ensure_run_workspace_access(db: Session, run: Run, user: User) -> Workspace:
    ws, _role = require_workspace_access(str(run.workspace_id), db, user)
    return ws


def _call_hybrid_retrieve(
    db: Session,
    *,
    workspace_id: str,
    q: str,
    k: int,
    alpha: float,
    source_types: Optional[List[str]] = None,
    timeframe: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Compatibility shim:
    - If hybrid_retrieve supports source/timeframe args, pass them.
    - Otherwise fall back and filter in Python (like retrieval.py did earlier).
    """
    source_types = source_types or []
    timeframe = timeframe or {}

    try:
        # Newer signature (if you already added it)
        return hybrid_retrieve(
            db,
            workspace_id=workspace_id,
            q=q,
            k=k,
            alpha=alpha,
            source_types=source_types,
            timeframe=timeframe,
        )
    except TypeError:
        # Old signature, then filter manually
        items = hybrid_retrieve(db, workspace_id=workspace_id, q=q, k=k, alpha=alpha)

        if source_types:
            # map type->source_ids
            src_ids = set(
                str(x)
                for x in db.execute(
                    select(Source.id).where(Source.workspace_id == uuid.UUID(workspace_id), Source.type.in_(source_types))
                ).scalars().all()
            )
            items = [it for it in items if str(it.get("source_id", "")) in src_ids]

        # timeframe filtering (best-effort) - only if chunk/doc meta includes a timestamp
        # (Your retrieval core already supports timeframe, so for old core we keep it no-op.)
        return items


def _generate_md_with_evidence(
    *,
    agent_id: str,
    input_payload: Dict[str, Any],
    evidence_items: List[Evidence],
) -> Tuple[str, str, str]:
    """
    Returns (artifact_type, title, md) for initial artifact, grounded in evidence if LLM is on.
    """
    artifact_type = AGENT_TO_DEFAULT_ARTIFACT_TYPE.get(agent_id, "strategy_memo")
    title = f"{artifact_type.replace('_', ' ').title()} — Draft"

    ev_text = format_evidence_for_prompt(evidence_items)

    # If LLM on -> enforce citations using same rules as regenerate
    if settings.LLM_ENABLED and settings.OPENAI_API_KEY:
        from app.core.prompts import build_system_prompt, build_user_prompt
        from app.core.llm_client import llm_generate_markdown

        evidence_dicts = [
            {"excerpt": e.excerpt, "source_ref": e.source_ref, "source_name": e.source_name, "meta": e.meta or {}}
            for e in evidence_items
        ]
        citations_block, sources_section_md, normalized = build_citation_pack(evidence_dicts)

        system_prompt = build_system_prompt()
        base_user_prompt = build_user_prompt(agent_id=agent_id, input_payload=input_payload, evidence_text=ev_text)

        citation_rules = f"""
You MUST ground claims in the Evidence Pack below.

Citation rules:
- Any factual claim, decision, requirement, or number MUST include at least one inline citation like [1] or [2].
- Do NOT invent sources. Only cite from the Evidence Pack IDs.
- If evidence is insufficient for a claim, write it under "## Unknowns / Assumptions" instead of guessing.

Output requirements (MANDATORY):
1) Start with a clear H1 title.
2) Include a section "## Unknowns / Assumptions".
3) Include a section "## Sources" at the end with the exact [n] references.
"""

        evidence_pack = f"""
Evidence Pack (cite as [n]):

{citations_block}
""".strip()

        user_prompt = "\n\n".join([base_user_prompt.strip(), citation_rules.strip(), evidence_pack])

        md = llm_generate_markdown(system_prompt=system_prompt, user_prompt=user_prompt)

        if not md.lstrip().startswith("#"):
            md = f"# {title}\n\n" + md

        if "## Unknowns / Assumptions" not in md:
            md = md.rstrip() + "\n\n## Unknowns / Assumptions\n- None stated.\n"

        if "## Sources" not in md:
            md = md.rstrip() + "\n\n" + sources_section_md + "\n"

        if len(evidence_items) > 0 and not output_has_any_citations(md):
            md = (
                md.rstrip()
                + "\n\n"
                + "### ⚠️ Citation check\n"
                + "Evidence was available, but no citations like [1] were found. Please add inline citations.\n\n"
                + sources_section_md
                + "\n"
            )

        if len(evidence_items) > 0 and not body_has_inline_citations(md):
            patch = build_inline_citation_patch(normalized)
            md = md.rstrip() + "\n\n" + patch + "\n"

        return artifact_type, title, md

    # LLM off -> deterministic scaffold, plus note
    artifact_type2, title2, md2 = build_initial_artifact(agent_id=agent_id, input_payload=input_payload, evidence_text=ev_text)
    if len(evidence_items) > 0 and "## Unknowns / Assumptions" not in md2:
        md2 = md2.rstrip() + "\n\n## Unknowns / Assumptions\n- Evidence attached, but citation-grounded generation requires LLM mode.\n"
    return artifact_type2, title2, md2


@router.post("/workspaces/{workspace_id}/runs", response_model=RunOut)
def create_run(
    workspace_id: str,
    payload: RunCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)

    agent = db.get(AgentDefinition, payload.agent_id)
    if not agent:
        raise HTTPException(status_code=400, detail="Invalid agent_id")

    r = Run(
        workspace_id=ws.id,
        agent_id=agent.id,
        created_by_user_id=user.id,
        status="created",
        input_payload=payload.input_payload or {},
    )
    db.add(r)
    db.commit()
    db.refresh(r)

    r.status = "running"
    db.add(r)
    db.commit()
    db.refresh(r)

    # ----------------------------
    # True RAG: pre-retrieve & attach evidence
    # ----------------------------
    ev_items: List[Evidence] = []
    rcfg = payload.retrieval

    if rcfg and rcfg.enabled and (rcfg.query or "").strip():
        q = rcfg.query.strip()
        k = int(rcfg.k or 6)
        alpha = float(rcfg.alpha) if rcfg.alpha is not None else 0.65
        source_types = [s.strip() for s in (rcfg.source_types or []) if s.strip()]
        timeframe = rcfg.timeframe or {}

        items = _call_hybrid_retrieve(
            db,
            workspace_id=str(ws.id),
            q=q,
            k=k,
            alpha=alpha,
            source_types=source_types,
            timeframe=timeframe,
        )

        for rank, it in enumerate(items, start=1):
            source_ref = f"doc:{it.get('document_id')}#chunk:{it.get('chunk_id')}"
            meta = {
                "rank": rank,
                "score_hybrid": float(it.get("score_hybrid") or 0.0),
                "score_fts": float(it.get("score_fts") or 0.0),
                "score_vec": float(it.get("score_vec") or 0.0),
                "document_title": it.get("document_title", ""),
                "source_id": it.get("source_id", ""),
                "chunk_index": int(it.get("chunk_index") or 0),
                "retrieval": {
                    "q": q,
                    "k": k,
                    "alpha": alpha,
                    "source_types": source_types,
                    "timeframe": timeframe,
                },
            }

            ev = Evidence(
                run_id=r.id,
                kind="snippet",
                source_name="retrieval",
                source_ref=source_ref,
                excerpt=str(it.get("snippet") or ""),
                meta=meta,
            )
            db.add(ev)
            ev_items.append(ev)

        db.commit()
        for e in ev_items:
            db.refresh(e)

        # Also log retrieval action (auditable)
        db.add(
            RunLog(
                run_id=r.id,
                level="info",
                message="Pre-retrieval completed; evidence attached.",
                meta={
                    "query": q,
                    "k": k,
                    "alpha": alpha,
                    "source_types": source_types,
                    "timeframe": timeframe,
                    "evidence_count": len(ev_items),
                },
            )
        )
        db.commit()

    # ----------------------------
    # Generate artifact grounded in evidence
    # ----------------------------
    artifact_type, title, md = _generate_md_with_evidence(
        agent_id=r.agent_id,
        input_payload=r.input_payload,
        evidence_items=ev_items,
    )

    art = Artifact(
        run_id=r.id,
        type=artifact_type,
        title=title,
        content_md=md,
        logical_key=artifact_type,
        version=1,
        status="draft",
    )
    db.add(art)
    db.commit()

    r.status = "completed"
    r.output_summary = build_run_summary(agent_id=r.agent_id, artifact_type=artifact_type)
    if ev_items:
        r.output_summary += f" Evidence attached: {len(ev_items)} snippet(s)."
    db.add(r)
    db.commit()
    db.refresh(r)

    return RunOut(
        id=str(r.id),
        workspace_id=str(r.workspace_id),
        agent_id=r.agent_id,
        created_by_user_id=str(r.created_by_user_id),
        status=r.status,
        input_payload=r.input_payload,
        output_summary=r.output_summary,
    )


@router.get("/workspaces/{workspace_id}/runs", response_model=list[RunOut])
def list_runs(workspace_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    ws, _role = require_workspace_access(workspace_id, db, user)

    runs = (
        db.execute(select(Run).where(Run.workspace_id == ws.id).order_by(Run.created_at.desc()))
        .scalars()
        .all()
    )
    return [
        RunOut(
            id=str(r.id),
            workspace_id=str(r.workspace_id),
            agent_id=r.agent_id,
            created_by_user_id=str(r.created_by_user_id),
            status=r.status,
            input_payload=r.input_payload,
            output_summary=r.output_summary,
        )
        for r in runs
    ]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    r = db.get(Run, run_id)
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")

    _ensure_run_workspace_access(db, r, user)

    return RunOut(
        id=str(r.id),
        workspace_id=str(r.workspace_id),
        agent_id=r.agent_id,
        created_by_user_id=str(r.created_by_user_id),
        status=r.status,
        input_payload=r.input_payload,
        output_summary=r.output_summary,
    )


@router.post("/runs/{run_id}/status", response_model=RunOut)
def update_run_status(
    run_id: str,
    payload: RunStatusUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    run_uuid = _parse_uuid(run_id)
    r = db.get(Run, run_uuid)
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")

    require_workspace_role_min(str(r.workspace_id), "member", db, user)

    r.status = payload.status
    r.output_summary = payload.output_summary
    db.add(r)
    db.commit()
    db.refresh(r)

    return RunOut(
        id=str(r.id),
        workspace_id=str(r.workspace_id),
        agent_id=r.agent_id,
        created_by_user_id=str(r.created_by_user_id),
        status=r.status,
        input_payload=r.input_payload,
        output_summary=r.output_summary,
    )


def _to_log_out(l: RunLog) -> RunLogOut:
    return RunLogOut(
        id=str(l.id),
        run_id=str(l.run_id),
        level=l.level,
        message=l.message,
        meta=l.meta or {},
        created_at=l.created_at,
    )


@router.get("/runs/{run_id}/logs", response_model=list[RunLogOut])
def list_run_logs(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    r = db.get(Run, run_id)
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")

    _ensure_run_workspace_access(db, r, user)

    rows = (
        db.execute(select(RunLog).where(RunLog.run_id == r.id).order_by(RunLog.created_at.desc()))
        .scalars()
        .all()
    )
    return [_to_log_out(x) for x in rows]


@router.post("/runs/{run_id}/logs", response_model=RunLogOut)
def create_run_log(run_id: str, payload: RunLogCreateIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    run_uuid = _parse_uuid(run_id)
    r = db.get(Run, run_uuid)
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")

    require_workspace_role_min(str(r.workspace_id), "member", db, user)

    level = (payload.level or "info").strip().lower()
    if level not in {"info", "warn", "error", "debug"}:
        raise HTTPException(status_code=400, detail="Invalid log level")

    l = RunLog(
        run_id=r.id,
        level=level,
        message=payload.message,
        meta=payload.meta or {},
    )
    db.add(l)
    db.commit()
    db.refresh(l)
    return _to_log_out(l)


@router.get("/runs/{run_id}/timeline", response_model=list[RunTimelineEventOut])
def get_run_timeline(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    r = db.get(Run, run_id)
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")

    _ensure_run_workspace_access(db, r, user)

    events: list[RunTimelineEventOut] = []

    events.append(
        RunTimelineEventOut(
            ts=r.created_at,
            kind="run",
            label=f"Run created (agent={r.agent_id})",
            ref_id=str(r.id),
            meta={"status": r.status},
        )
    )

    if r.updated_at and r.updated_at != r.created_at:
        events.append(
            RunTimelineEventOut(
                ts=r.updated_at,
                kind="status",
                label=f"Run status now: {r.status}",
                ref_id=str(r.id),
                meta={"output_summary": r.output_summary or ""},
            )
        )

    arts = (
        db.execute(select(Artifact).where(Artifact.run_id == r.id).order_by(Artifact.created_at.desc()))
        .scalars()
        .all()
    )
    for a in arts:
        events.append(
            RunTimelineEventOut(
                ts=a.created_at,
                kind="artifact",
                label=f"Artifact created: {a.type} v{a.version} ({a.status}) — {a.title}",
                ref_id=str(a.id),
                meta={"logical_key": a.logical_key, "version": int(a.version), "status": a.status},
            )
        )

    evs = (
        db.execute(select(Evidence).where(Evidence.run_id == r.id).order_by(Evidence.created_at.desc()))
        .scalars()
        .all()
    )
    for e in evs:
        events.append(
            RunTimelineEventOut(
                ts=e.created_at,
                kind="evidence",
                label=f"Evidence attached: {e.kind} from {e.source_name}",
                ref_id=str(e.id),
                meta={"source_ref": e.source_ref, "meta": e.meta or {}},
            )
        )

    logs = (
        db.execute(select(RunLog).where(RunLog.run_id == r.id).order_by(RunLog.created_at.desc()))
        .scalars()
        .all()
    )
    for l in logs:
        events.append(
            RunTimelineEventOut(
                ts=l.created_at,
                kind="log",
                label=f"[{l.level}] {l.message}",
                ref_id=str(l.id),
                meta=l.meta or {},
            )
        )

    events.sort(key=lambda x: x.ts, reverse=True)
    return events

@router.get("/runs/{run_id}/rag-debug")
def rag_debug(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """
    Returns:
    - latest pre-retrieval log meta (query, k, alpha, source_types, timeframe, evidence_count)
    - all evidence items attached to this run (ordered newest first)
    """
    r = db.get(Run, run_id)
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")

    _ensure_run_workspace_access(db, r, user)

    # newest evidence first
    evs = (
        db.execute(select(Evidence).where(Evidence.run_id == r.id).order_by(Evidence.created_at.desc()))
        .scalars()
        .all()
    )

    # latest "Pre-retrieval..." log
    log = (
        db.execute(
            select(RunLog)
            .where(RunLog.run_id == r.id)
            .where(RunLog.message == "Pre-retrieval completed; evidence attached.")
            .order_by(RunLog.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )

    return {
        "ok": True,
        "run_id": str(r.id),
        "retrieval_log": (log.meta or {}) if log else None,
        "evidence": [
            {
                "id": str(e.id),
                "kind": e.kind,
                "source_name": e.source_name,
                "source_ref": e.source_ref,
                "excerpt": e.excerpt,
                "meta": e.meta or {},
                "created_at": e.created_at,
            }
            for e in evs
        ],
    }