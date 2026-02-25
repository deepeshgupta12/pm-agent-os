from __future__ import annotations

import uuid

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
from app.db.session import get_db
from app.db.models import Workspace, Run, AgentDefinition, Artifact, Evidence, User
from app.schemas.core import RunCreateIn, RunOut, RunStatusUpdateIn

router = APIRouter(tags=["runs"])


def _parse_uuid(id_str: str) -> uuid.UUID:
    try:
        return uuid.UUID(id_str)
    except Exception:
        raise HTTPException(status_code=404, detail="Run not found")


def _ensure_run_workspace_access(db: Session, run: Run, user: User) -> Workspace:
    # Viewer+ allowed for reads; existence is guarded by workspace access
    ws, _role = require_workspace_access(str(run.workspace_id), db, user)
    return ws


@router.post("/workspaces/{workspace_id}/runs", response_model=RunOut)
def create_run(
    workspace_id: str,
    payload: RunCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    # member+ only
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

    artifact_type, title, md = build_initial_artifact(agent_id=r.agent_id, input_payload=r.input_payload)

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
    # viewer+ read ok
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
    # member+ (write)
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


@router.post("/runs/{run_id}/regenerate", response_model=RunOut)
def regenerate_with_evidence(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """
    Regenerate draft for this run using attached evidence.

    member+ only (it creates a new artifact version)
    """
    run_uuid = _parse_uuid(run_id)
    r = db.get(Run, run_uuid)
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")

    require_workspace_role_min(str(r.workspace_id), "member", db, user)

    # Collect evidence
    ev_items = (
        db.execute(select(Evidence).where(Evidence.run_id == r.id).order_by(Evidence.created_at.desc()))
        .scalars()
        .all()
    )
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
        if len(ev_items) > 0 and "## Sources" not in md:
            md = md.rstrip() + "\n\n" + sources_section_md + "\n"
        if len(ev_items) > 0 and not body_has_inline_citations(md):
            md = md.rstrip() + "\n\n" + build_inline_citation_patch(normalized) + "\n"

    max_ver = db.execute(
        select(func.max(Artifact.version)).where(Artifact.run_id == r.id, Artifact.logical_key == artifact_type)
    ).scalar_one_or_none()
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

    r.output_summary = f"Regenerated draft with inline citations using {len(ev_items)} evidence item(s). Latest version: v{next_ver}."
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