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
    citation_enforcement_report,
    render_citation_compliance_md,
)
from app.core.retrieval_search import hybrid_retrieve
from app.db.session import get_db
from app.db.models import (
    Workspace,
    User,
    AgentDefinition,
    PipelineTemplate,
    PipelineRun,
    PipelineStep,
    Run,
    Artifact,
    Evidence,
    RunLog,
)
from app.schemas.pipelines import (
    PipelineTemplateIn,
    PipelineTemplateOut,
    PipelineTemplatesSeedOut,
    PipelineRunCreateIn,
    PipelineRunOut,
    PipelineStepOut,
    PipelineNextOut,
    PipelineExecuteAllOut,
)

router = APIRouter(tags=["pipelines"])

VALID_STEP_STATUS = {"created", "running", "completed", "failed"}
VALID_PIPELINE_STATUS = {"created", "running", "completed", "failed"}

# -------------------------
# Canonical templates (V1)
# -------------------------
CANONICAL_PIPELINES: List[Dict[str, Any]] = [
    {
        "key": "discovery_strategy_prd",
        "name": "Discovery → Strategy → PRD",
        "description": "End-to-end early phase flow: identify opportunities, pick direction, write PRD.",
        "definition_json": {
            "version": "v1",
            "auto_regenerate_with_evidence": True,
            "steps": [
                {"name": "Discovery", "agent_id": "discovery"},
                {"name": "Strategy & Roadmap", "agent_id": "strategy_roadmap"},
                {"name": "PRD", "agent_id": "prd"},
            ],
        },
    },
    {
        "key": "prd_ux_feasibility",
        "name": "PRD → UX → Feasibility",
        "description": "Turn PRD into UX flow spec, then validate feasibility and architecture.",
        "definition_json": {
            "version": "v1",
            "auto_regenerate_with_evidence": True,
            "steps": [
                {"name": "PRD", "agent_id": "prd"},
                {"name": "UX Flow", "agent_id": "ux_flow"},
                {"name": "Feasibility & Architecture", "agent_id": "feasibility_architecture"},
            ],
        },
    },
    {
        "key": "analytics_qa_launch",
        "name": "Analytics → QA → Launch",
        "description": "Operationalization flow: tracking + experiment plan → QA suite → launch plan/runbook.",
        "definition_json": {
            "version": "v1",
            "auto_regenerate_with_evidence": True,
            "steps": [
                {"name": "Analytics & Experiment", "agent_id": "analytics_experiment"},
                {"name": "QA & Test", "agent_id": "qa_test"},
                {"name": "Launch", "agent_id": "launch"},
            ],
        },
    },
    {
        "key": "launch_monitoring_stakeholder",
        "name": "Launch → Monitoring → Stakeholders",
        "description": "Post-release loop: launch → health monitoring → stakeholder update pack.",
        "definition_json": {
            "version": "v1",
            "auto_regenerate_with_evidence": True,
            "steps": [
                {"name": "Launch", "agent_id": "launch"},
                {"name": "Post-launch Monitoring", "agent_id": "post_launch_monitoring"},
                {"name": "Stakeholder Alignment", "agent_id": "stakeholder_alignment"},
            ],
        },
    },
]


# -------------------------
# Helpers
# -------------------------
def _ensure_workspace_access(db: Session, workspace_id: str, user: User) -> Workspace:
    ws, _role = require_workspace_access(workspace_id, db, user)
    return ws


def _template_to_out(t: PipelineTemplate) -> PipelineTemplateOut:
    return PipelineTemplateOut(
        id=str(t.id),
        workspace_id=str(t.workspace_id),
        name=t.name,
        description=t.description,
        definition_json=t.definition_json or {},
    )


def _prev_context_attached_map(db: Session, steps: List[PipelineStep]) -> Dict[str, bool]:
    run_ids = [s.run_id for s in steps if s.run_id is not None and s.step_index > 0]
    if not run_ids:
        return {}

    rows = (
        db.execute(
            select(Evidence.run_id)
            .where(
                Evidence.run_id.in_(run_ids),
                Evidence.source_name == "pipeline_prev_artifact",
            )
            .distinct()
        )
        .scalars()
        .all()
    )
    return {str(rid): True for rid in rows}


def _latest_artifact_map(db: Session, steps: List[PipelineStep]) -> Dict[str, Dict[str, Any]]:
    """
    One query to get latest artifact metadata for each run_id (if exists).
    Uses DISTINCT ON which is Postgres-specific.
    """
    run_ids = [s.run_id for s in steps if s.run_id is not None]
    if not run_ids:
        return {}

    q = (
        select(Artifact)
        .where(Artifact.run_id.in_(run_ids))
        .distinct(Artifact.run_id)
        .order_by(Artifact.run_id, Artifact.created_at.desc())
    )

    rows = db.execute(q).scalars().all()
    out: Dict[str, Dict[str, Any]] = {}
    for a in rows:
        out[str(a.run_id)] = {
            "latest_artifact_id": str(a.id),
            "latest_artifact_version": int(a.version),
            "latest_artifact_type": a.type,
            "latest_artifact_title": a.title,
        }
    return out


def _run_retrieval_meta_map(db: Session, steps: List[PipelineStep]) -> Dict[str, Dict[str, Any]]:
    """
    Fetch run.input_payload["_retrieval"] for each step.run_id in ONE query.
    Returns: { run_id_str: retrieval_dict_or_empty }
    """
    run_ids = [s.run_id for s in steps if s.run_id is not None]
    if not run_ids:
        return {}

    rows = db.execute(select(Run).where(Run.id.in_(run_ids))).scalars().all()

    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        ip = r.input_payload or {}
        meta = ip.get("_retrieval")
        if isinstance(meta, dict):
            out[str(r.id)] = meta
        else:
            out[str(r.id)] = {}
    return out


def _step_to_out(
    s: PipelineStep,
    prev_attached_map: Dict[str, bool],
    latest_art_map: Dict[str, Dict[str, Any]],
    run_retrieval_map: Dict[str, Dict[str, Any]],
) -> PipelineStepOut:
    run_id_str = str(s.run_id) if s.run_id else None

    prev_ctx = None
    auto_regenerated = None
    latest: Dict[str, Any] = {}

    if run_id_str:
        prev_ctx = bool(prev_attached_map.get(run_id_str, False))
        latest = latest_art_map.get(run_id_str, {}) or {}
        v = latest.get("latest_artifact_version")
        if isinstance(v, int):
            auto_regenerated = v >= 2

    retrieval_enabled = None
    retrieval_query = None
    retrieval_evidence_count = None
    retrieval_batch_id = None
    retrieval_batch_kind = None

    if run_id_str:
        rmeta = run_retrieval_map.get(run_id_str, {}) or {}
        if isinstance(rmeta, dict) and rmeta:
            retrieval_enabled = bool(rmeta.get("enabled"))
            q = rmeta.get("query")
            if isinstance(q, str):
                retrieval_query = q
            ec = rmeta.get("evidence_count")
            if isinstance(ec, int):
                retrieval_evidence_count = ec
            bid = rmeta.get("batch_id")
            if isinstance(bid, str):
                retrieval_batch_id = bid
            bk = rmeta.get("batch_kind")
            if isinstance(bk, str):
                retrieval_batch_kind = bk

    return PipelineStepOut(
        id=str(s.id),
        pipeline_run_id=str(s.pipeline_run_id),
        step_index=s.step_index,
        step_name=s.step_name,
        agent_id=s.agent_id,
        status=s.status,
        input_payload=s.input_payload or {},
        run_id=run_id_str,
        prev_context_attached=prev_ctx,
        auto_regenerated=auto_regenerated,
        latest_artifact_id=latest.get("latest_artifact_id"),
        latest_artifact_version=latest.get("latest_artifact_version"),
        latest_artifact_type=latest.get("latest_artifact_type"),
        latest_artifact_title=latest.get("latest_artifact_title"),
        retrieval_enabled=retrieval_enabled,
        retrieval_query=retrieval_query,
        retrieval_evidence_count=retrieval_evidence_count,
        retrieval_batch_id=retrieval_batch_id,
        retrieval_batch_kind=retrieval_batch_kind,
    )


def _run_to_out(db: Session, pr: PipelineRun, steps: List[PipelineStep]) -> PipelineRunOut:
    prev_map = _prev_context_attached_map(db, steps)
    latest_map = _latest_artifact_map(db, steps)
    retrieval_map = _run_retrieval_meta_map(db, steps)

    return PipelineRunOut(
        id=str(pr.id),
        workspace_id=str(pr.workspace_id),
        template_id=str(pr.template_id),
        created_by_user_id=str(pr.created_by_user_id),
        status=pr.status,
        current_step_index=pr.current_step_index,
        input_payload=pr.input_payload or {},
        steps=[_step_to_out(s, prev_map, latest_map, retrieval_map) for s in sorted(steps, key=lambda x: x.step_index)],
    )


def _validate_pipeline_definition(db: Session, steps_def: Any) -> None:
    if not isinstance(steps_def, list) or len(steps_def) == 0:
        raise HTTPException(status_code=400, detail="Template has no steps")

    for idx, sd in enumerate(steps_def):
        agent_id = (sd or {}).get("agent_id")
        if not agent_id:
            raise HTTPException(status_code=400, detail=f"Invalid step at index {idx}: missing agent_id")

        agent = db.get(AgentDefinition, agent_id)
        if not agent:
            raise HTTPException(status_code=400, detail=f"Invalid agent_id in pipeline step: {agent_id}")


def _seed_canonical_templates_for_workspace(db: Session, ws: Workspace) -> Tuple[List[PipelineTemplate], List[PipelineTemplate]]:
    existing = db.execute(select(PipelineTemplate).where(PipelineTemplate.workspace_id == ws.id)).scalars().all()
    by_name = {t.name.strip().lower(): t for t in existing}

    created: List[PipelineTemplate] = []
    existing_out: List[PipelineTemplate] = []

    for tpl in CANONICAL_PIPELINES:
        name = str(tpl["name"]).strip()
        key = name.lower()
        if key in by_name:
            existing_out.append(by_name[key])
            continue

        definition = tpl.get("definition_json") or {}
        steps_def = definition.get("steps") or []
        _validate_pipeline_definition(db, steps_def)

        t = PipelineTemplate(
            workspace_id=ws.id,
            name=name,
            description=str(tpl.get("description") or ""),
            definition_json=definition,
        )
        db.add(t)
        db.commit()
        db.refresh(t)
        created.append(t)

    return created, existing_out


def _latest_artifact_snapshot(db: Session, run_id: uuid.UUID) -> Optional[Dict[str, Any]]:
    a = (
        db.execute(select(Artifact).where(Artifact.run_id == run_id).order_by(Artifact.created_at.desc()).limit(1))
        .scalars()
        .first()
    )
    if not a:
        return None

    md = a.content_md or ""
    excerpt = md[:800].strip()

    return {
        "artifact_id": str(a.id),
        "type": a.type,
        "title": a.title,
        "version": a.version,
        "status": a.status,
        "content_md_excerpt": excerpt,
    }


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


def _no_evidence_md(agent_id: str, input_payload: Dict[str, Any], retrieval_meta: Dict[str, Any]) -> Tuple[str, str, str]:
    artifact_type = AGENT_TO_DEFAULT_ARTIFACT_TYPE.get(agent_id, "strategy_memo")
    title = f"{artifact_type.replace('_', ' ').title()} — Draft"

    goal = (input_payload.get("goal") or "").strip()
    context = (input_payload.get("context") or "").strip()
    constraints = (input_payload.get("constraints") or "").strip()

    md = f"""# {title}

## Summary
No evidence was found for the requested retrieval query, so this draft does **not** attempt to write a grounded artifact. It instead captures what we need to proceed.

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
1. Which exact doc(s) should be considered the source of truth for this step (title or link)?
2. Are those docs already ingested into this workspace? If yes, confirm the correct source_type.
3. Should retrieval broaden (higher k / overfetch / multiple source_types) or narrow (more precise query)?
4. Should rerank be enabled and do we need embeddings for recall?

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

    artifact_type2, title2, md2 = build_initial_artifact(agent_id=agent_id, input_payload=input_payload, evidence_text=ev_text)
    if len(evidence_items) > 0 and "## Unknowns / Assumptions" not in md2:
        md2 = md2.rstrip() + "\n\n## Unknowns / Assumptions\n- Evidence attached, but citation-grounded generation requires LLM mode.\n"
    return artifact_type2, title2, md2


def _auto_attach_prev_artifact_as_evidence(
    db: Session,
    new_run_id: uuid.UUID,
    pipeline_run_id: uuid.UUID,
    step_index: int,
    step_name: str,
    template_id: uuid.UUID,
    prev_run_id: Optional[str],
    prev_artifact: Dict[str, Any],
) -> None:
    artifact_id = str(prev_artifact.get("artifact_id") or "").strip()
    excerpt = (prev_artifact.get("content_md_excerpt") or "").strip()
    if not artifact_id or not excerpt:
        return

    safe_excerpt = excerpt[:2000].strip()

    ev = Evidence(
        run_id=new_run_id,
        kind="snippet",
        source_name="pipeline_prev_artifact",
        source_ref=f"artifact:{artifact_id}",
        excerpt=safe_excerpt,
        meta={
            "pipeline_run_id": str(pipeline_run_id),
            "template_id": str(template_id),
            "step_index": step_index,
            "step_name": step_name,
            "prev_run_id": prev_run_id,
            "prev_artifact_id": artifact_id,
            "prev_artifact_type": prev_artifact.get("type"),
            "prev_artifact_title": prev_artifact.get("title"),
            "prev_artifact_version": prev_artifact.get("version"),
            "prev_artifact_status": prev_artifact.get("status"),
        },
    )
    db.add(ev)
    db.commit()


def _default_step_retrieval_query(step_name: str, agent_id: str, input_payload: Dict[str, Any]) -> str:
    goal = str(input_payload.get("goal") or "").strip()
    context = str(input_payload.get("context") or "").strip()

    bits: List[str] = []
    if step_name:
        bits.append(step_name)
    if agent_id:
        bits.append(agent_id)
    if goal:
        bits.append(goal)
    if context:
        bits.append(context)

    q = " ".join([b for b in bits if b]).strip()
    if len(q) < 2:
        q = agent_id or step_name or "product requirements"
    return q[:500]


def _attach_retrieval_evidence_for_run(
    db: Session,
    *,
    run: Run,
    workspace_id: str,
    retrieval_cfg: Dict[str, Any],
) -> Tuple[List[Evidence], Dict[str, Any]]:
    q = str(retrieval_cfg.get("query") or "").strip()
    if not q:
        return [], {"enabled": False}

    k = int(retrieval_cfg.get("k") or 6)
    alpha = float(retrieval_cfg.get("alpha") if retrieval_cfg.get("alpha") is not None else 0.65)
    source_types = [s.strip() for s in (retrieval_cfg.get("source_types") or []) if s and str(s).strip()]
    timeframe = retrieval_cfg.get("timeframe") or {}

    min_score = float(retrieval_cfg.get("min_score", 0.15))
    overfetch_k = int(retrieval_cfg.get("overfetch_k", 3))
    rerank = bool(retrieval_cfg.get("rerank", False))

    start_ts, end_ts = _timeframe_to_bounds(timeframe)

    items = hybrid_retrieve(
        db,
        workspace_id=str(workspace_id),
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
            "batch_kind": "pipeline_step_retrieval",
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
                "enabled": True,
                "query": q,
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
            run_id=run.id,
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
        "evidence_count": len(ev_items),
        "batch_id": batch_id,
        "batch_kind": "pipeline_step_retrieval",
    }
    return ev_items, retrieval_meta


def _create_completed_run_with_artifact_and_step_retrieval(
    db: Session,
    ws: Workspace,
    user: User,
    *,
    agent_id: str,
    step_name: str,
    base_input_payload: Dict[str, Any],
    template_definition: Dict[str, Any],
    step_definition: Dict[str, Any],
) -> Run:
    agent = db.get(AgentDefinition, agent_id)
    if not agent:
        raise HTTPException(status_code=400, detail=f"Invalid agent_id: {agent_id}")

    r = Run(
        workspace_id=ws.id,
        agent_id=agent.id,
        created_by_user_id=user.id,
        status="created",
        input_payload=base_input_payload or {},
    )
    db.add(r)
    db.commit()
    db.refresh(r)

    r.status = "running"
    db.add(r)
    db.commit()
    db.refresh(r)

    tpl_retrieval = template_definition.get("retrieval") if isinstance(template_definition, dict) else None
    tpl_retrieval = tpl_retrieval if isinstance(tpl_retrieval, dict) else {}

    step_retrieval = (step_definition or {}).get("retrieval")
    step_retrieval = step_retrieval if isinstance(step_retrieval, dict) else {}

    sources_selected = base_input_payload.get("sources_selected") or []
    if not isinstance(sources_selected, list):
        sources_selected = []
    source_types = [str(s).strip() for s in sources_selected if str(s).strip()]
    if not source_types:
        source_types = ["docs"]

    timeframe = base_input_payload.get("timeframe") or {}
    if not isinstance(timeframe, dict):
        timeframe = {}

    enabled = bool(step_retrieval.get("enabled", tpl_retrieval.get("enabled", True)))

    q = str(step_retrieval.get("query") or "").strip()
    if not q:
        q = _default_step_retrieval_query(step_name=step_name, agent_id=agent_id, input_payload=base_input_payload)

    retrieval_cfg = {
        "enabled": enabled,
        "query": q,
        "k": int(step_retrieval.get("k", tpl_retrieval.get("k", 6))),
        "alpha": float(step_retrieval.get("alpha", tpl_retrieval.get("alpha", 0.0))),
        "source_types": step_retrieval.get("source_types", tpl_retrieval.get("source_types", source_types)),
        "timeframe": step_retrieval.get("timeframe", tpl_retrieval.get("timeframe", timeframe)),
        "min_score": float(step_retrieval.get("min_score", tpl_retrieval.get("min_score", 0.15))),
        "overfetch_k": int(step_retrieval.get("overfetch_k", tpl_retrieval.get("overfetch_k", 3))),
        "rerank": bool(step_retrieval.get("rerank", tpl_retrieval.get("rerank", True))),
    }

    ev_items: List[Evidence] = []
    retrieval_meta: Dict[str, Any] = {"enabled": False}

    if enabled and str(retrieval_cfg.get("query") or "").strip():
        ev_items, retrieval_meta = _attach_retrieval_evidence_for_run(
            db,
            run=r,
            workspace_id=str(ws.id),
            retrieval_cfg=retrieval_cfg,
        )

    ip = dict(r.input_payload or {})
    ip["_retrieval"] = retrieval_meta
    r.input_payload = ip
    db.add(r)
    db.commit()
    db.refresh(r)

    db.add(
        RunLog(
            run_id=r.id,
            level="info" if ev_items else "warn",
            message="Pipeline step pre-retrieval completed; evidence attached."
            if ev_items
            else "Pipeline step pre-retrieval executed; no evidence found.",
            meta=retrieval_meta,
        )
    )
    db.commit()

    if retrieval_meta.get("enabled") and len(ev_items) == 0:
        artifact_type, title, md = _no_evidence_md(r.agent_id, r.input_payload, retrieval_meta)
    else:
        artifact_type, title, md = _generate_md_with_evidence(
            agent_id=r.agent_id,
            input_payload=r.input_payload,
            evidence_items=ev_items,
        )

    # V1 enforcement for pipeline step run (only when evidence exists)
    try:
        rep = citation_enforcement_report(artifact_type=artifact_type, md=md, evidence_count=len(ev_items))
        if len(ev_items) > 0:
            md = md.rstrip() + "\n\n" + render_citation_compliance_md(rep) + "\n"
            db.add(
                RunLog(
                    run_id=r.id,
                    level="info" if rep.get("ok") else "warn",
                    message="Citation enforcement check",
                    meta=rep,
                )
            )
            db.commit()
    except Exception:
        pass

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

    try:
        if len(ev_items) > 0:
            rep2 = citation_enforcement_report(artifact_type=artifact_type, md=md, evidence_count=len(ev_items))
            if not rep2.get("ok"):
                r.output_summary += f" ⚠️ Citation check failed (confidence={float(rep2.get('confidence_score') or 0.0):.2f})."
    except Exception:
        pass

    db.add(r)
    db.commit()
    db.refresh(r)

    return r


def _regenerate_run_with_evidence_internal(db: Session, run_uuid: uuid.UUID) -> None:
    r = db.get(Run, run_uuid)
    if not r:
        return

    ev_items = (
        db.execute(select(Evidence).where(Evidence.run_id == r.id).order_by(Evidence.created_at.desc()))
        .scalars()
        .all()
    )
    if len(ev_items) == 0:
        return

    evidence_text = format_evidence_for_prompt(ev_items)
    evidence_dicts = [
        {"excerpt": e.excerpt, "source_ref": e.source_ref, "source_name": e.source_name, "meta": e.meta or {}}
        for e in ev_items
    ]
    citations_block, sources_section_md, normalized = build_citation_pack(evidence_dicts)

    artifact_type = AGENT_TO_DEFAULT_ARTIFACT_TYPE.get(r.agent_id, "strategy_memo")
    title = f"{artifact_type.replace('_', ' ').title()} — Draft"

    if settings.LLM_ENABLED and settings.OPENAI_API_KEY:
        from app.core.prompts import build_system_prompt, build_user_prompt
        from app.core.llm_client import llm_generate_markdown

        system_prompt = build_system_prompt()
        base_user_prompt = build_user_prompt(agent_id=r.agent_id, input_payload=r.input_payload, evidence_text=evidence_text)

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

        if len(ev_items) > 0 and not output_has_any_citations(md):
            md = (
                md.rstrip()
                + "\n\n"
                + "### ⚠️ Citation check\n"
                + "Evidence was available, but no citations like [1] were found. Please add inline citations.\n\n"
                + sources_section_md
                + "\n"
            )

        if len(ev_items) > 0 and not body_has_inline_citations(md):
            patch = build_inline_citation_patch(normalized)
            md = md.rstrip() + "\n\n" + patch + "\n"
    else:
        _, _, md = build_initial_artifact(agent_id=r.agent_id, input_payload=r.input_payload)
        if "## Unknowns / Assumptions" not in md:
            md = md.rstrip() + "\n\n## Unknowns / Assumptions\n- Evidence-based citations require LLM mode.\n"
        if "## Sources" not in md:
            md = md.rstrip() + "\n\n" + sources_section_md + "\n"
        if not body_has_inline_citations(md):
            md = md.rstrip() + "\n\n" + build_inline_citation_patch(normalized) + "\n"

    # V1 enforcement for internal regen
    try:
        rep = citation_enforcement_report(artifact_type=artifact_type, md=md, evidence_count=len(ev_items))
        md = md.rstrip() + "\n\n" + render_citation_compliance_md(rep) + "\n"
        db.add(
            RunLog(
                run_id=r.id,
                level="info" if rep.get("ok") else "warn",
                message="Citation enforcement check",
                meta=rep,
            )
        )
        db.commit()
    except Exception:
        pass

    max_ver = (
        db.execute(
            select(Artifact.version)
            .where(Artifact.run_id == r.id, Artifact.logical_key == artifact_type)
            .order_by(Artifact.version.desc())
            .limit(1)
        )
        .scalar_one_or_none()
    )
    next_ver = int(max_ver or 0) + 1

    new_art = Artifact(
        run_id=r.id,
        type=artifact_type,
        title=title,
        content_md=md,
        logical_key=artifact_type,
        version=next_ver,
        status="draft",
    )
    db.add(new_art)

    r.output_summary = f"Auto-regenerated via pipeline using {len(ev_items)} evidence item(s). Latest version: v{next_ver}."
    try:
        rep2 = citation_enforcement_report(artifact_type=artifact_type, md=md, evidence_count=len(ev_items))
        if not rep2.get("ok"):
            r.output_summary += f" ⚠️ Citation check failed (confidence={float(rep2.get('confidence_score') or 0.0):.2f})."
    except Exception:
        pass

    db.add(r)
    db.commit()


def _mark_step_failed(db: Session, pr: PipelineRun, step: PipelineStep, *, error: str) -> None:
    step.status = "failed"
    step.completed_at = datetime.now(timezone.utc)
    db.add(step)

    pr.status = "failed"
    db.add(pr)

    try:
        if step.run_id:
            db.add(
                RunLog(
                    run_id=step.run_id,
                    level="error",
                    message="Pipeline step failed",
                    meta={
                        "pipeline_run_id": str(pr.id),
                        "step_index": step.step_index,
                        "step_name": step.step_name,
                        "error": error,
                    },
                )
            )
    except Exception:
        pass

    db.commit()


def _execute_one_step(
    db: Session,
    ws: Workspace,
    user: User,
    pr: PipelineRun,
    steps: List[PipelineStep],
    step: PipelineStep,
    auto_regen: bool,
) -> str:
    step.status = "running"
    step.started_at = datetime.now(timezone.utc)
    db.add(step)
    db.commit()
    db.refresh(step)

    run_input: Dict[str, Any] = dict(pr.input_payload or {})
    run_input["_pipeline"] = {
        "pipeline_run_id": str(pr.id),
        "step_index": step.step_index,
        "step_name": step.step_name,
        "template_id": str(pr.template_id),
    }

    prev_run_id: Optional[str] = None
    prev_artifact: Optional[Dict[str, Any]] = None

    if step.step_index > 0:
        prev_step = steps[step.step_index - 1]
        prev_run_id = str(prev_step.run_id) if prev_step.run_id else None
        run_input["_pipeline"]["prev_run_id"] = prev_run_id

        if prev_step.run_id:
            snap = _latest_artifact_snapshot(db, prev_step.run_id)
            if snap:
                prev_artifact = snap
                run_input["_pipeline"]["prev_artifact"] = snap

    tpl = db.get(PipelineTemplate, pr.template_id)
    definition = (tpl.definition_json or {}) if tpl else {}
    steps_def = definition.get("steps") or []

    step_def: Dict[str, Any] = {}
    if isinstance(steps_def, list) and 0 <= step.step_index < len(steps_def):
        sd = steps_def[step.step_index]
        if isinstance(sd, dict):
            step_def = sd

    new_run = _create_completed_run_with_artifact_and_step_retrieval(
        db=db,
        ws=ws,
        user=user,
        agent_id=step.agent_id,
        step_name=step.step_name,
        base_input_payload=run_input,
        template_definition=definition if isinstance(definition, dict) else {},
        step_definition=step_def,
    )

    if prev_artifact is not None:
        _auto_attach_prev_artifact_as_evidence(
            db=db,
            new_run_id=new_run.id,
            pipeline_run_id=pr.id,
            step_index=step.step_index,
            step_name=step.step_name,
            template_id=pr.template_id,
            prev_run_id=prev_run_id,
            prev_artifact=prev_artifact,
        )

    if auto_regen and step.step_index > 0:
        _regenerate_run_with_evidence_internal(db=db, run_uuid=new_run.id)

    step.run_id = new_run.id
    step.status = "completed"
    step.completed_at = datetime.now(timezone.utc)
    db.add(step)
    db.commit()

    return str(new_run.id)


# -------------------------
# Routes
# -------------------------
@router.post("/workspaces/{workspace_id}/pipelines/templates/seed", response_model=PipelineTemplatesSeedOut)
def seed_pipeline_templates(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)
    created, existing = _seed_canonical_templates_for_workspace(db, ws)

    return PipelineTemplatesSeedOut(
        ok=True,
        workspace_id=str(ws.id),
        created_count=len(created),
        existing_count=len(existing),
        created_template_ids=[str(t.id) for t in created],
        existing_template_ids=[str(t.id) for t in existing],
    )


@router.post("/workspaces/{workspace_id}/pipelines/templates", response_model=PipelineTemplateOut)
def create_pipeline_template(
    workspace_id: str,
    payload: PipelineTemplateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)

    definition = payload.definition_json or {}
    steps_def = definition.get("steps") or []
    _validate_pipeline_definition(db, steps_def)

    t = PipelineTemplate(
        workspace_id=ws.id,
        name=payload.name,
        description=payload.description,
        definition_json=payload.definition_json or {},
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return _template_to_out(t)


@router.get("/workspaces/{workspace_id}/pipelines/templates", response_model=list[PipelineTemplateOut])
def list_pipeline_templates(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws = _ensure_workspace_access(db, workspace_id, user)
    items = (
        db.execute(
            select(PipelineTemplate)
            .where(PipelineTemplate.workspace_id == ws.id)
            .order_by(PipelineTemplate.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [_template_to_out(t) for t in items]


@router.post("/workspaces/{workspace_id}/pipelines/runs", response_model=PipelineRunOut)
def start_pipeline_run(
    workspace_id: str,
    payload: PipelineRunCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)

    template_uuid = uuid.UUID(payload.template_id)
    t = db.get(PipelineTemplate, template_uuid)
    if not t or t.workspace_id != ws.id:
        raise HTTPException(status_code=404, detail="Pipeline template not found")

    definition = t.definition_json or {}
    steps_def = definition.get("steps") or []
    _validate_pipeline_definition(db, steps_def)

    pr = PipelineRun(
        workspace_id=ws.id,
        template_id=t.id,
        created_by_user_id=user.id,
        status="created",
        current_step_index=0,
        input_payload=payload.input_payload or {},
    )
    db.add(pr)
    db.commit()
    db.refresh(pr)

    steps_rows: List[PipelineStep] = []
    for idx, sd in enumerate(steps_def):
        agent_id = (sd or {}).get("agent_id")
        name = (sd or {}).get("name") or agent_id or f"Step {idx+1}"
        if not agent_id:
            raise HTTPException(status_code=400, detail=f"Invalid step at index {idx}: missing agent_id")

        agent = db.get(AgentDefinition, agent_id)
        if not agent:
            raise HTTPException(status_code=400, detail=f"Invalid agent_id in pipeline step: {agent_id}")

        step_payload = {"agent_step": idx, "agent_id": agent_id, "pipeline_step_name": name}

        steps_rows.append(
            PipelineStep(
                pipeline_run_id=pr.id,
                step_index=idx,
                step_name=name,
                agent_id=agent_id,
                status="created",
                input_payload=step_payload,
                run_id=None,
            )
        )

    db.add_all(steps_rows)
    db.commit()

    pr.status = "running"
    db.add(pr)
    db.commit()
    db.refresh(pr)

    steps = db.execute(select(PipelineStep).where(PipelineStep.pipeline_run_id == pr.id)).scalars().all()
    return _run_to_out(db, pr, steps)


@router.get("/pipelines/runs/{pipeline_run_id}", response_model=PipelineRunOut)
def get_pipeline_run(
    pipeline_run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    pr_uuid = uuid.UUID(pipeline_run_id)
    pr = db.get(PipelineRun, pr_uuid)
    if not pr:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    require_workspace_access(str(pr.workspace_id), db, user)

    steps = db.execute(select(PipelineStep).where(PipelineStep.pipeline_run_id == pr.id)).scalars().all()
    return _run_to_out(db, pr, steps)


@router.post("/pipelines/runs/{pipeline_run_id}/next", response_model=PipelineNextOut)
def run_next_step(
    pipeline_run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    pr_uuid = uuid.UUID(pipeline_run_id)
    pr = db.get(PipelineRun, pr_uuid)
    if not pr:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    ws, _role = require_workspace_role_min(str(pr.workspace_id), "member", db, user)

    if (pr.status or "").lower() == "failed":
        steps = db.execute(select(PipelineStep).where(PipelineStep.pipeline_run_id == pr.id)).scalars().all()
        return PipelineNextOut(ok=False, pipeline_run=_run_to_out(db, pr, steps), created_run_id=None)

    tpl = db.get(PipelineTemplate, pr.template_id)
    definition = (tpl.definition_json or {}) if tpl else {}
    auto_regen = bool(definition.get("auto_regenerate_with_evidence", True))

    steps = (
        db.execute(
            select(PipelineStep)
            .where(PipelineStep.pipeline_run_id == pr.id)
            .order_by(PipelineStep.step_index.asc())
        )
        .scalars()
        .all()
    )
    if not steps:
        raise HTTPException(status_code=400, detail="Pipeline has no steps")

    if pr.current_step_index >= len(steps):
        pr.status = "completed"
        db.add(pr)
        db.commit()
        return PipelineNextOut(ok=True, pipeline_run=_run_to_out(db, pr, steps), created_run_id=None)

    step = steps[pr.current_step_index]

    if step.status == "completed":
        pr.current_step_index += 1
        db.add(pr)
        db.commit()
        steps = db.execute(select(PipelineStep).where(PipelineStep.pipeline_run_id == pr.id)).scalars().all()
        return PipelineNextOut(ok=True, pipeline_run=_run_to_out(db, pr, steps), created_run_id=None)

    if (pr.status or "").lower() == "created":
        pr.status = "running"
        db.add(pr)
        db.commit()

    try:
        created_run_id = _execute_one_step(db=db, ws=ws, user=user, pr=pr, steps=steps, step=step, auto_regen=auto_regen)
    except Exception as e:
        _mark_step_failed(db, pr, step, error=str(e))
        steps = db.execute(select(PipelineStep).where(PipelineStep.pipeline_run_id == pr.id)).scalars().all()
        return PipelineNextOut(ok=False, pipeline_run=_run_to_out(db, pr, steps), created_run_id=None)

    pr.current_step_index += 1
    if pr.current_step_index >= len(steps):
        pr.status = "completed"
        db.add(pr)
        db.commit()
        db.refresh(pr)

    steps = db.execute(select(PipelineStep).where(PipelineStep.pipeline_run_id == pr.id)).scalars().all()
    return PipelineNextOut(ok=True, pipeline_run=_run_to_out(db, pr, steps), created_run_id=created_run_id)


@router.post("/pipelines/runs/{pipeline_run_id}/execute-all", response_model=PipelineExecuteAllOut)
def execute_all_steps(
    pipeline_run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    pr_uuid = uuid.UUID(pipeline_run_id)
    pr = db.get(PipelineRun, pr_uuid)
    if not pr:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    ws, _role = require_workspace_role_min(str(pr.workspace_id), "member", db, user)

    if (pr.status or "").lower() == "failed":
        steps = db.execute(select(PipelineStep).where(PipelineStep.pipeline_run_id == pr.id)).scalars().all()
        return PipelineExecuteAllOut(ok=False, pipeline_run=_run_to_out(db, pr, steps), created_run_ids=[])

    tpl = db.get(PipelineTemplate, pr.template_id)
    definition = (tpl.definition_json or {}) if tpl else {}
    auto_regen = bool(definition.get("auto_regenerate_with_evidence", True))

    steps = (
        db.execute(
            select(PipelineStep)
            .where(PipelineStep.pipeline_run_id == pr.id)
            .order_by(PipelineStep.step_index.asc())
        )
        .scalars()
        .all()
    )
    if not steps:
        raise HTTPException(status_code=400, detail="Pipeline has no steps")

    created_run_ids: List[str] = []

    if (pr.status or "").lower() == "created":
        pr.status = "running"
        db.add(pr)
        db.commit()
        db.refresh(pr)

    ok = True

    while pr.current_step_index < len(steps):
        step = steps[pr.current_step_index]

        if step.status == "completed":
            pr.current_step_index += 1
            db.add(pr)
            db.commit()
            continue

        try:
            rid = _execute_one_step(db=db, ws=ws, user=user, pr=pr, steps=steps, step=step, auto_regen=auto_regen)
            created_run_ids.append(rid)
        except Exception as e:
            ok = False
            _mark_step_failed(db, pr, step, error=str(e))
            break

        steps = (
            db.execute(
                select(PipelineStep)
                .where(PipelineStep.pipeline_run_id == pr.id)
                .order_by(PipelineStep.step_index.asc())
            )
            .scalars()
            .all()
        )

        pr.current_step_index += 1
        db.add(pr)
        db.commit()
        db.refresh(pr)

    if ok and pr.current_step_index >= len(steps):
        pr.status = "completed"
        db.add(pr)
        db.commit()
        db.refresh(pr)

    steps = db.execute(select(PipelineStep).where(PipelineStep.pipeline_run_id == pr.id)).scalars().all()
    return PipelineExecuteAllOut(
        ok=ok,
        pipeline_run=_run_to_out(db, pr, steps),
        created_run_ids=created_run_ids,
    )


# -------------------------
# Alias routes (stable links)
# -------------------------
@router.get("/pipeline-runs/{pipeline_run_id}", response_model=PipelineRunOut)
def get_pipeline_run_alias(
    pipeline_run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    return get_pipeline_run(pipeline_run_id=pipeline_run_id, db=db, user=user)


@router.post("/pipeline-runs/{pipeline_run_id}/execute-next", response_model=PipelineNextOut)
def execute_next_alias(
    pipeline_run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    return run_next_step(pipeline_run_id=pipeline_run_id, db=db, user=user)


@router.post("/pipeline-runs/{pipeline_run_id}/execute-all", response_model=PipelineExecuteAllOut)
def execute_all_alias(
    pipeline_run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    return execute_all_steps(pipeline_run_id=pipeline_run_id, db=db, user=user)