from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
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
from app.db.models import (
    Workspace,
    Run,
    RunLog,
    AgentDefinition,
    Artifact,
    Evidence,
    User,
    RunStatusEvent,
)
from app.schemas.core import (
    RunCreateIn,
    RunOut,
    RunStatusUpdateIn,
    RunLogCreateIn,
    RunLogOut,
    RunTimelineEventOut,
    RunRegenerateWithRetrievalIn,
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


def _write_status_event(
    db: Session,
    *,
    run: Run,
    from_status: Optional[str],
    to_status: str,
    message: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> RunStatusEvent:
    ev = RunStatusEvent(
        run_id=run.id,
        from_status=from_status,
        to_status=to_status,
        message=message,
        meta=meta or {},
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


def _set_run_status(
    db: Session,
    *,
    run: Run,
    to_status: str,
    message: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    from_status = run.status
    run.status = to_status
    db.add(run)
    db.commit()
    db.refresh(run)

    _write_status_event(
        db,
        run=run,
        from_status=from_status,
        to_status=to_status,
        message=message,
        meta=meta or {},
    )


def _timeframe_to_bounds(timeframe: Optional[Dict[str, Any]]) -> tuple[Optional[datetime], Optional[datetime]]:
    """
    Accepts retrieval.timeframe JSON and returns (start_ts,end_ts) in UTC.

    Supported:
      - {"preset":"7d"|"30d"|"90d"}
      - {"preset":"custom","start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD"}
    """
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


def _no_evidence_md(agent_id: str, input_payload: Dict[str, Any], retrieval_meta: Dict[str, Any]) -> Tuple[str, str, str]:
    artifact_type = AGENT_TO_DEFAULT_ARTIFACT_TYPE.get(agent_id, "strategy_memo")
    title = f"{artifact_type.replace('_', ' ').title()} — Draft"

    goal = (input_payload.get("goal") or "").strip()
    context = (input_payload.get("context") or "").strip()
    constraints = (input_payload.get("constraints") or "").strip()

    md = f"""# {title}

## Summary
No evidence was found for the requested retrieval query, so this draft does **not** attempt to write a grounded PRD/spec. It instead captures what we need to proceed.

## Goal
{goal or "- (not provided)"}

## Context
{context or "- (not provided)"}

## Constraints
{constraints or "- (not provided)"}

## Retrieval Attempt
- Query: `{retrieval_meta.get("query")}`
- k: `{retrieval_meta.get("k")}`
- alpha: `{retrieval_meta.get("alpha")}`
- source_types: `{retrieval_meta.get("source_types")}`
- timeframe: `{retrieval_meta.get("timeframe")}`
- min_score: `{retrieval_meta.get("min_score")}`
- overfetch_k: `{retrieval_meta.get("overfetch_k")}`
- rerank: `{retrieval_meta.get("rerank")}`
- evidence_count: `0`

## What this means
- We cannot ground requirements/claims without evidence.
- Next step is to ingest/sync the right documents OR change the query/source filters.

## Open Questions (required to proceed)
1. Which exact doc(s) should be considered the source of truth for this run (title or link)?
2. Are those docs already ingested into this workspace? If yes, confirm the correct source_type (docs/github/manual).
3. Should retrieval broaden (higher k / overfetch / multiple source_types) or narrow (more precise query)?
4. Should rerank be enabled (rerank=true) and do we need embeddings (embed_after=true) for recall?

## Next Actions
- Ingest/sync the missing documents into the workspace
- Re-run retrieval with an updated query and confirm evidence_count > 0
- Then regenerate the artifact grounded in evidence
"""
    return artifact_type, title, md


def _generate_md_with_evidence(
    *,
    agent_id: str,
    input_payload: Dict[str, Any],
    evidence_items: List[Evidence],
) -> Tuple[str, str, str]:
    artifact_type = AGENT_TO_DEFAULT_ARTIFACT_TYPE.get(agent_id, "strategy_memo")
    title = f"{artifact_type.replace('_', ' ').title()} — Draft"

    ev_text = format_evidence_for_prompt(evidence_items)

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

        citation_rules = """
You MUST ground claims in the Evidence Pack below.

Citation rules:
- Any factual claim, decision, requirement, or number MUST include at least one inline citation like [1] or [2].
- Do NOT invent sources. Only cite from the Evidence Pack IDs.
- If evidence is insufficient for a claim, write it under "## Unknowns / Assumptions" instead of guessing.

Output requirements (MANDATORY):
1) Start with a clear H1 title.
2) Include a section "## Unknowns / Assumptions".
3) Include a section "## Sources" at the end with the exact [n] references.
""".strip()

        evidence_pack = f"""
Evidence Pack (cite as [n]):

{citations_block}
""".strip()

        user_prompt = "\n\n".join([base_user_prompt.strip(), citation_rules, evidence_pack])

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

    artifact_type2, title2, md2 = build_initial_artifact(
        agent_id=agent_id, input_payload=input_payload, evidence_text=ev_text
    )
    if len(evidence_items) > 0 and "## Unknowns / Assumptions" not in md2:
        md2 = md2.rstrip() + "\n\n## Unknowns / Assumptions\n- Evidence attached, but citation-grounded generation requires LLM mode.\n"
    return artifact_type2, title2, md2


def _latest_artifact_for_run(db: Session, run_id: uuid.UUID) -> Optional[Artifact]:
    return (
        db.execute(select(Artifact).where(Artifact.run_id == run_id).order_by(Artifact.created_at.desc()).limit(1))
        .scalars()
        .first()
    )


def _next_version_for_logical_key(db: Session, run_id: uuid.UUID, logical_key: str) -> int:
    max_ver = (
        db.execute(
            select(Artifact.version)
            .where(Artifact.run_id == run_id, Artifact.logical_key == logical_key)
            .order_by(Artifact.version.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    return int(max_ver or 0) + 1


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

    _write_status_event(db, run=r, from_status=None, to_status="created", message="Run created", meta={})
    _set_run_status(db, run=r, to_status="running", message="Run started", meta={})

    ev_items: List[Evidence] = []
    rcfg = payload.retrieval
    retrieval_meta: Optional[Dict[str, Any]] = None

    if rcfg and rcfg.enabled and (rcfg.query or "").strip():
        q = rcfg.query.strip()
        k = int(rcfg.k or 6)
        alpha = float(rcfg.alpha) if rcfg.alpha is not None else 0.65
        source_types = [s.strip() for s in (rcfg.source_types or []) if s.strip()]
        timeframe = rcfg.timeframe or {}

        min_score = float(getattr(rcfg, "min_score", 0.15))
        overfetch_k = int(getattr(rcfg, "overfetch_k", 3))
        rerank = bool(getattr(rcfg, "rerank", False))

        start_ts, end_ts = _timeframe_to_bounds(timeframe)

        retrieval_meta = {
            "enabled": True,
            "query": q,
            "k": k,
            "alpha": alpha,
            "source_types": source_types,
            "timeframe": timeframe,
            "min_score": min_score,
            "overfetch_k": overfetch_k,
            "rerank": rerank,
        }

        items = hybrid_retrieve(
            db,
            workspace_id=str(ws.id),
            q=q,
            k=k,
            alpha=alpha,
            source_types=source_types or None,
            start_ts=start_ts,
            end_ts=end_ts,
            min_score=min_score,
            overfetch_k=overfetch_k,
            rerank=rerank,
        )

        batch_id = str(uuid.uuid4())

        for rank, it in enumerate(items, start=1):
            source_ref = f"doc:{it.get('document_id')}#chunk:{it.get('chunk_id')}"
            meta = {
                "batch_id": batch_id,
                "batch_kind": "create_run",
                "rank": rank,
                "score_hybrid": float(it.get("score_hybrid") or 0.0),
                "score_fts": float(it.get("score_fts") or 0.0),
                "score_vec": float(it.get("score_vec") or 0.0),
                "score_rerank_bonus": it.get("score_rerank_bonus"),
                "score_final": it.get("score_final"),
                "document_title": it.get("document_title", ""),
                "source_id": it.get("source_id", ""),
                "chunk_index": int(it.get("chunk_index") or 0),
                "retrieval": {
                    "q": q,
                    "k": k,
                    "alpha": alpha,
                    "source_types": source_types,
                    "timeframe": timeframe,
                    "min_score": min_score,
                    "overfetch_k": overfetch_k,
                    "rerank": rerank,
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

        retrieval_meta["evidence_count"] = len(ev_items)
        retrieval_meta["batch_id"] = batch_id

        ip = dict(r.input_payload or {})
        ip["_retrieval"] = retrieval_meta
        r.input_payload = ip
        db.add(r)
        db.commit()
        db.refresh(r)

        db.add(
            RunLog(
                run_id=r.id,
                level="info",
                message="Pre-retrieval completed; evidence attached.",
                meta={
                    **retrieval_meta,
                    "evidence_count": len(ev_items),
                },
            )
        )
        db.commit()

    if retrieval_meta and retrieval_meta.get("enabled") and len(ev_items) == 0:
        artifact_type, title, md = _no_evidence_md(r.agent_id, r.input_payload, retrieval_meta)
        db.add(
            RunLog(
                run_id=r.id,
                level="warn",
                message="No evidence found for retrieval query; returned questions-only draft.",
                meta={"retrieval": retrieval_meta},
            )
        )
        db.commit()
    else:
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

    r.output_summary = build_run_summary(agent_id=r.agent_id, artifact_type=artifact_type)
    if ev_items:
        r.output_summary += f" Evidence attached: {len(ev_items)} snippet(s)."
    db.add(r)
    db.commit()
    db.refresh(r)

    _set_run_status(
        db,
        run=r,
        to_status="completed",
        message="Run completed",
        meta={"artifact_type": artifact_type, "evidence_count": len(ev_items)},
    )

    return RunOut(
        id=str(r.id),
        workspace_id=str(r.workspace_id),
        agent_id=r.agent_id,
        created_by_user_id=str(r.created_by_user_id),
        status=r.status,
        input_payload=r.input_payload,
        output_summary=r.output_summary,
    )


# -------------------------
# V2.2: Regenerate with retrieval
# -------------------------
@router.post("/runs/{run_id}/regenerate-with-retrieval", response_model=RunOut)
def regenerate_with_retrieval(
    run_id: str,
    payload: RunRegenerateWithRetrievalIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    run_uuid = _parse_uuid(run_id)
    r = db.get(Run, run_uuid)
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")

    require_workspace_role_min(str(r.workspace_id), "member", db, user)

    # Determine base artifact key/type/versioning from latest artifact
    latest = _latest_artifact_for_run(db, r.id)
    if not latest:
        raise HTTPException(status_code=400, detail="No artifacts exist for this run yet")

    logical_key = latest.logical_key or latest.type
    artifact_type = latest.type
    next_ver = _next_version_for_logical_key(db, r.id, logical_key)

    # Use run input payload as-is, but persist new retrieval config into _retrieval
    rcfg = payload.retrieval
    if not rcfg.enabled or not (rcfg.query or "").strip():
        raise HTTPException(status_code=400, detail="retrieval.enabled=true and retrieval.query required")

    q = rcfg.query.strip()
    k = int(rcfg.k or 6)
    alpha = float(rcfg.alpha) if rcfg.alpha is not None else 0.65
    source_types = [s.strip() for s in (rcfg.source_types or []) if s.strip()]
    timeframe = rcfg.timeframe or {}

    min_score = float(getattr(rcfg, "min_score", 0.15))
    overfetch_k = int(getattr(rcfg, "overfetch_k", 3))
    rerank = bool(getattr(rcfg, "rerank", False))

    start_ts, end_ts = _timeframe_to_bounds(timeframe)

    retrieval_meta: Dict[str, Any] = {
        "enabled": True,
        "query": q,
        "k": k,
        "alpha": alpha,
        "source_types": source_types,
        "timeframe": timeframe,
        "min_score": min_score,
        "overfetch_k": overfetch_k,
        "rerank": rerank,
    }

    # Retrieve
    items = hybrid_retrieve(
        db,
        workspace_id=str(r.workspace_id),
        q=q,
        k=k,
        alpha=alpha,
        source_types=source_types or None,
        start_ts=start_ts,
        end_ts=end_ts,
        min_score=min_score,
        overfetch_k=overfetch_k,
        rerank=rerank,
    )

    batch_id = str(uuid.uuid4())
    ev_items: List[Evidence] = []

    for rank, it in enumerate(items, start=1):
        source_ref = f"doc:{it.get('document_id')}#chunk:{it.get('chunk_id')}"
        meta = {
            "batch_id": batch_id,
            "batch_kind": "regenerate_with_retrieval",
            "rank": rank,
            "score_hybrid": float(it.get("score_hybrid") or 0.0),
            "score_fts": float(it.get("score_fts") or 0.0),
            "score_vec": float(it.get("score_vec") or 0.0),
            "score_rerank_bonus": it.get("score_rerank_bonus"),
            "score_final": it.get("score_final"),
            "document_title": it.get("document_title", ""),
            "source_id": it.get("source_id", ""),
            "chunk_index": int(it.get("chunk_index") or 0),
            "retrieval": {
                **retrieval_meta,
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

    retrieval_meta["evidence_count"] = len(ev_items)
    retrieval_meta["batch_id"] = batch_id

    # Persist latest retrieval config onto run (for UI)
    ip = dict(r.input_payload or {})
    ip["_retrieval"] = retrieval_meta
    r.input_payload = ip
    db.add(r)
    db.commit()
    db.refresh(r)

    # Audit logs + status event (completed -> completed)
    db.add(
        RunLog(
            run_id=r.id,
            level="info" if ev_items else "warn",
            message="Regenerate-with-retrieval executed; evidence attached." if ev_items else "Regenerate-with-retrieval executed; no evidence found.",
            meta=retrieval_meta,
        )
    )
    db.commit()

    _write_status_event(
        db,
        run=r,
        from_status=r.status,
        to_status=r.status,
        message="Regenerate with retrieval",
        meta={"artifact_type": artifact_type, "logical_key": logical_key, "new_version": next_ver, **retrieval_meta},
    )

    # Generate new artifact
    if len(ev_items) == 0:
        _atype, _title, md = _no_evidence_md(r.agent_id, r.input_payload, retrieval_meta)
        title = latest.title or f"{artifact_type.replace('_', ' ').title()} — Draft"
    else:
        _atype, _title, md = _generate_md_with_evidence(
            agent_id=r.agent_id,
            input_payload=r.input_payload,
            evidence_items=ev_items,
        )
        title = latest.title or _title

    new_art = Artifact(
        run_id=r.id,
        type=artifact_type,
        title=title,
        content_md=md,
        logical_key=logical_key,
        version=next_ver,
        status="draft",
    )
    db.add(new_art)
    db.commit()

    # Update summary (keep run status as-is)
    r.output_summary = build_run_summary(agent_id=r.agent_id, artifact_type=artifact_type)
    r.output_summary += f" Regenerated v{next_ver}."
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

    runs = db.execute(select(Run).where(Run.workspace_id == ws.id).order_by(Run.created_at.desc())).scalars().all()
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

    from_status = r.status
    r.status = payload.status
    r.output_summary = payload.output_summary
    db.add(r)
    db.commit()
    db.refresh(r)

    _write_status_event(
        db,
        run=r,
        from_status=from_status,
        to_status=r.status,
        message="Status updated via API",
        meta={"output_summary": r.output_summary or ""},
    )

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

    rows = db.execute(select(RunLog).where(RunLog.run_id == r.id).order_by(RunLog.created_at.desc())).scalars().all()
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

    l = RunLog(run_id=r.id, level=level, message=payload.message, meta=payload.meta or {})
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

    status_events = (
        db.execute(select(RunStatusEvent).where(RunStatusEvent.run_id == r.id).order_by(RunStatusEvent.created_at.desc()))
        .scalars()
        .all()
    )
    for se in status_events:
        from_s = se.from_status or ""
        to_s = se.to_status or ""
        label = f"Status: {from_s} -> {to_s}".strip()
        if se.message:
            label = f"{label} — {se.message}"
        events.append(
            RunTimelineEventOut(
                ts=se.created_at,
                kind="status",
                label=label,
                ref_id=str(se.id),
                meta=se.meta or {},
            )
        )

    arts = db.execute(select(Artifact).where(Artifact.run_id == r.id).order_by(Artifact.created_at.desc())).scalars().all()
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

    evs = db.execute(select(Evidence).where(Evidence.run_id == r.id).order_by(Evidence.created_at.desc())).scalars().all()
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

    logs = db.execute(select(RunLog).where(RunLog.run_id == r.id).order_by(RunLog.created_at.desc())).scalars().all()
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
    r = db.get(Run, run_id)
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")

    _ensure_run_workspace_access(db, r, user)

    evs = db.execute(select(Evidence).where(Evidence.run_id == r.id).order_by(Evidence.created_at.desc())).scalars().all()

    log = (
        db.execute(
            select(RunLog)
            .where(RunLog.run_id == r.id)
            .where(RunLog.message.in_(
                [
                    "Pre-retrieval completed; evidence attached.",
                    "Regenerate-with-retrieval executed; evidence attached.",
                    "Regenerate-with-retrieval executed; no evidence found.",
                ]
            ))
            .order_by(RunLog.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )

    retrieval_cfg = None
    try:
        retrieval_cfg = (r.input_payload or {}).get("_retrieval")
    except Exception:
        retrieval_cfg = None

    return {
        "ok": True,
        "run_id": str(r.id),
        "retrieval_config": retrieval_cfg,
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