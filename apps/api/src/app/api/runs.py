from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.core.generator import build_initial_artifact, build_run_summary, AGENT_TO_DEFAULT_ARTIFACT_TYPE
from app.core.config import settings
from app.core.evidence_format import format_evidence_for_prompt
from app.db.session import get_db
from app.db.models import Workspace, Run, AgentDefinition, Artifact, Evidence, User

from app.schemas.core import RunCreateIn, RunOut, RunStatusUpdateIn

router = APIRouter(tags=["runs"])


def _parse_uuid(id_str: str) -> uuid.UUID:
    try:
        return uuid.UUID(id_str)
    except Exception:
        raise HTTPException(status_code=404, detail="Run not found")


def _ensure_run_access(db: Session, run: Run, user: User) -> None:
    ws = db.get(Workspace, run.workspace_id)
    if not ws or ws.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Run not found")


@router.post("/workspaces/{workspace_id}/runs", response_model=RunOut)
def create_run(workspace_id: str, payload: RunCreateIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    ws = db.get(Workspace, workspace_id)
    if not ws or ws.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Workspace not found")

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

    # Usually no evidence exists at create time, but keep hook
    ev_items = db.execute(select(Evidence).where(Evidence.run_id == r.id).order_by(Evidence.created_at.desc())).scalars().all()
    evidence_text = format_evidence_for_prompt(ev_items)

    # build_initial_artifact will use evidence if enabled via prompts (Step 4C)
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
    ws = db.get(Workspace, workspace_id)
    if not ws or ws.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Workspace not found")

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

    _ensure_run_access(db, r, user)

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
def update_run_status(run_id: str, payload: RunStatusUpdateIn, db: Session = Depends(get_db), user: User = Depends(require_user)):
    r = db.get(Run, run_id)
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")

    _ensure_run_access(db, r, user)

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
    Regenerate the default artifact type for this run using currently attached evidence.
    Creates a new artifact version row.
    """
    run_uuid = _parse_uuid(run_id)
    r = db.get(Run, run_uuid)
    if not r:
        raise HTTPException(status_code=404, detail="Run not found")

    _ensure_run_access(db, r, user)

    # Collect evidence
    ev_items = db.execute(select(Evidence).where(Evidence.run_id == r.id).order_by(Evidence.created_at.desc())).scalars().all()
    evidence_text = format_evidence_for_prompt(ev_items)

    # Determine default artifact type from agent mapping
    artifact_type = AGENT_TO_DEFAULT_ARTIFACT_TYPE.get(r.agent_id, "strategy_memo")
    title = f"{artifact_type.replace('_', ' ').title()} — Draft"

    # Generate markdown (LLM if enabled, else deterministic)
    if settings.LLM_ENABLED and settings.OPENAI_API_KEY:
        from app.core.prompts import build_system_prompt, build_user_prompt
        from app.core.llm_client import llm_generate_markdown

        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(agent_id=r.agent_id, input_payload=r.input_payload, evidence_text=evidence_text)
        md = llm_generate_markdown(system_prompt=system_prompt, user_prompt=user_prompt)
        if not md.lstrip().startswith("#"):
            md = f"# {title}\n\n" + md
    else:
        # fallback
        _, _, md = build_initial_artifact(agent_id=r.agent_id, input_payload=r.input_payload)

    # Next version
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

    r.output_summary = f"Regenerated draft using {len(ev_items)} evidence item(s). Latest version: v{next_ver}."
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