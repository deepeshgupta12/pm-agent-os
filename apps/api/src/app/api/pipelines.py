from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.core.generator import build_initial_artifact, build_run_summary
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
    ws = db.get(Workspace, workspace_id)
    if not ws or ws.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


def _template_to_out(t: PipelineTemplate) -> PipelineTemplateOut:
    return PipelineTemplateOut(
        id=str(t.id),
        workspace_id=str(t.workspace_id),
        name=t.name,
        description=t.description,
        definition_json=t.definition_json or {},
    )


def _step_to_out(s: PipelineStep) -> PipelineStepOut:
    return PipelineStepOut(
        id=str(s.id),
        pipeline_run_id=str(s.pipeline_run_id),
        step_index=s.step_index,
        step_name=s.step_name,
        agent_id=s.agent_id,
        status=s.status,
        input_payload=s.input_payload or {},
        run_id=str(s.run_id) if s.run_id else None,
    )


def _run_to_out(pr: PipelineRun, steps: List[PipelineStep]) -> PipelineRunOut:
    return PipelineRunOut(
        id=str(pr.id),
        workspace_id=str(pr.workspace_id),
        template_id=str(pr.template_id),
        created_by_user_id=str(pr.created_by_user_id),
        status=pr.status,
        current_step_index=pr.current_step_index,
        input_payload=pr.input_payload or {},
        steps=[_step_to_out(s) for s in sorted(steps, key=lambda x: x.step_index)],
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


def _seed_canonical_templates_for_workspace(
    db: Session, ws: Workspace
) -> Tuple[List[PipelineTemplate], List[PipelineTemplate]]:
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
    """
    Returns a small snapshot of the latest artifact for a run.
    This is what we embed into _pipeline.prev_artifact.
    """
    a = (
        db.execute(
            select(Artifact)
            .where(Artifact.run_id == run_id)
            .order_by(Artifact.created_at.desc())
            .limit(1)
        )
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


def _create_completed_run_with_artifact(
    db: Session,
    ws: Workspace,
    user: User,
    agent_id: str,
    input_payload: Dict[str, Any],
) -> Run:
    """
    Mirrors runs.py:create_run behavior:
    - creates Run
    - marks running
    - generates initial artifact
    - marks completed + output_summary
    """
    agent = db.get(AgentDefinition, agent_id)
    if not agent:
        raise HTTPException(status_code=400, detail=f"Invalid agent_id: {agent_id}")

    r = Run(
        workspace_id=ws.id,
        agent_id=agent.id,
        created_by_user_id=user.id,
        status="created",
        input_payload=input_payload or {},
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

    return r


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
    """
    Step 17A:
    If _pipeline.prev_artifact exists, attach it as an Evidence row for the new run.
    """
    artifact_id = str(prev_artifact.get("artifact_id") or "").strip()
    excerpt = (prev_artifact.get("content_md_excerpt") or "").strip()

    if not artifact_id or not excerpt:
        return

    # Keep evidence excerpt reasonably sized for DB + prompts
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


def _execute_one_step(
    db: Session,
    ws: Workspace,
    user: User,
    pr: PipelineRun,
    steps: List[PipelineStep],
    step: PipelineStep,
) -> str:
    """
    Executes exactly one pipeline step by creating a completed Run + artifact.
    Step 17A: auto-add prev_artifact as evidence to the created run.
    Returns created run_id.
    """
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

    # Attach previous step context (run_id + latest artifact excerpt)
    if step.step_index > 0:
        prev_step = steps[step.step_index - 1]
        prev_run_id = str(prev_step.run_id) if prev_step.run_id else None
        run_input["_pipeline"]["prev_run_id"] = prev_run_id

        if prev_step.run_id:
            snap = _latest_artifact_snapshot(db, prev_step.run_id)
            if snap:
                prev_artifact = snap
                run_input["_pipeline"]["prev_artifact"] = snap

    # Create run + initial artifact (COMPLETED)
    new_run = _create_completed_run_with_artifact(
        db=db,
        ws=ws,
        user=user,
        agent_id=step.agent_id,
        input_payload=run_input,
    )

    # Step 17A: auto-evidence
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

    # Mark step completed and link
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
    ws = _ensure_workspace_access(db, workspace_id, user)
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
    ws = _ensure_workspace_access(db, workspace_id, user)

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
    items = db.execute(
        select(PipelineTemplate)
        .where(PipelineTemplate.workspace_id == ws.id)
        .order_by(PipelineTemplate.created_at.desc())
    ).scalars().all()
    return [_template_to_out(t) for t in items]


@router.post("/workspaces/{workspace_id}/pipelines/runs", response_model=PipelineRunOut)
def start_pipeline_run(
    workspace_id: str,
    payload: PipelineRunCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws = _ensure_workspace_access(db, workspace_id, user)

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

        step_payload = {
            "agent_step": idx,
            "agent_id": agent_id,
            "pipeline_step_name": name,
        }

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
    return _run_to_out(pr, steps)


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

    ws = db.get(Workspace, pr.workspace_id)
    if not ws or ws.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    steps = db.execute(select(PipelineStep).where(PipelineStep.pipeline_run_id == pr.id)).scalars().all()
    return _run_to_out(pr, steps)


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

    ws = db.get(Workspace, pr.workspace_id)
    if not ws or ws.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    steps = db.execute(
        select(PipelineStep)
        .where(PipelineStep.pipeline_run_id == pr.id)
        .order_by(PipelineStep.step_index.asc())
    ).scalars().all()
    if not steps:
        raise HTTPException(status_code=400, detail="Pipeline has no steps")

    if pr.current_step_index >= len(steps):
        pr.status = "completed"
        db.add(pr)
        db.commit()
        return PipelineNextOut(ok=True, pipeline_run=_run_to_out(pr, steps), created_run_id=None)

    step = steps[pr.current_step_index]

    if step.status == "completed":
        pr.current_step_index += 1
        db.add(pr)
        db.commit()
        steps = db.execute(select(PipelineStep).where(PipelineStep.pipeline_run_id == pr.id)).scalars().all()
        return PipelineNextOut(ok=True, pipeline_run=_run_to_out(pr, steps), created_run_id=None)

    created_run_id = _execute_one_step(db=db, ws=ws, user=user, pr=pr, steps=steps, step=step)

    pr.current_step_index += 1
    if pr.current_step_index >= len(steps):
        pr.status = "completed"
    db.add(pr)
    db.commit()
    db.refresh(pr)

    steps = db.execute(select(PipelineStep).where(PipelineStep.pipeline_run_id == pr.id)).scalars().all()
    return PipelineNextOut(ok=True, pipeline_run=_run_to_out(pr, steps), created_run_id=created_run_id)


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

    ws = db.get(Workspace, pr.workspace_id)
    if not ws or ws.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    steps = db.execute(
        select(PipelineStep)
        .where(PipelineStep.pipeline_run_id == pr.id)
        .order_by(PipelineStep.step_index.asc())
    ).scalars().all()
    if not steps:
        raise HTTPException(status_code=400, detail="Pipeline has no steps")

    created_run_ids: List[str] = []

    while pr.current_step_index < len(steps):
        step = steps[pr.current_step_index]

        if step.status == "completed":
            pr.current_step_index += 1
            continue

        rid = _execute_one_step(db=db, ws=ws, user=user, pr=pr, steps=steps, step=step)
        created_run_ids.append(rid)

        # Reload steps so prev_run_id and run_id are consistent for next iteration
        steps = db.execute(
            select(PipelineStep)
            .where(PipelineStep.pipeline_run_id == pr.id)
            .order_by(PipelineStep.step_index.asc())
        ).scalars().all()

        pr.current_step_index += 1

    pr.status = "completed"
    db.add(pr)
    db.commit()
    db.refresh(pr)

    steps = db.execute(select(PipelineStep).where(PipelineStep.pipeline_run_id == pr.id)).scalars().all()
    return PipelineExecuteAllOut(
        ok=True,
        pipeline_run=_run_to_out(pr, steps),
        created_run_ids=created_run_ids,
    )