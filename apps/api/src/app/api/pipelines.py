from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.db.session import get_db
from app.db.models import (
    Workspace,
    User,
    AgentDefinition,
    PipelineTemplate,
    PipelineRun,
    PipelineStep,
    Run,
)
from app.schemas.pipelines import (
    PipelineTemplateIn,
    PipelineTemplateOut,
    PipelineRunCreateIn,
    PipelineRunOut,
    PipelineStepOut,
    PipelineNextOut,
)

router = APIRouter(tags=["pipelines"])


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


@router.post("/workspaces/{workspace_id}/pipelines/templates", response_model=PipelineTemplateOut)
def create_pipeline_template(
    workspace_id: str,
    payload: PipelineTemplateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws = _ensure_workspace_access(db, workspace_id, user)

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
        select(PipelineTemplate).where(PipelineTemplate.workspace_id == ws.id).order_by(PipelineTemplate.created_at.desc())
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
    if not isinstance(steps_def, list) or len(steps_def) == 0:
        raise HTTPException(status_code=400, detail="Template has no steps")

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

    # Create step rows
    steps_rows: List[PipelineStep] = []
    for idx, sd in enumerate(steps_def):
        agent_id = (sd or {}).get("agent_id")
        name = (sd or {}).get("name") or agent_id or f"Step {idx+1}"
        if not agent_id:
            raise HTTPException(status_code=400, detail=f"Invalid step at index {idx}: missing agent_id")

        # Validate agent exists
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

    steps = db.execute(select(PipelineStep).where(PipelineStep.pipeline_run_id == pr.id).order_by(PipelineStep.step_index.asc())).scalars().all()
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
        return PipelineNextOut(ok=True, pipeline_run=_run_to_out(pr, steps), created_run_id=None)

    # Create a normal Run for this step using existing model directly
    step.status = "running"
    step.started_at = datetime.utcnow()
    db.add(step)
    db.commit()
    db.refresh(step)

    # Build run input: carry pipeline input + previous step artifact ids if any
    run_input: Dict[str, Any] = dict(pr.input_payload or {})
    run_input["_pipeline"] = {
        "pipeline_run_id": str(pr.id),
        "step_index": step.step_index,
        "step_name": step.step_name,
        "template_id": str(pr.template_id),
    }

    # Link previous step run/artifact
    if step.step_index > 0:
        prev = steps[step.step_index - 1]
        run_input["_pipeline"]["prev_run_id"] = str(prev.run_id) if prev.run_id else None

    new_run = Run(
        workspace_id=ws.id,
        agent_id=step.agent_id,
        created_by_user_id=user.id,
        status="created",
        input_payload=run_input,
    )
    db.add(new_run)
    db.commit()
    db.refresh(new_run)

    # Mark step completed and link
    step.run_id = new_run.id
    step.status = "completed"
    step.completed_at = datetime.utcnow()
    db.add(step)

    pr.current_step_index += 1
    if pr.current_step_index >= len(steps):
        pr.status = "completed"
    db.add(pr)
    db.commit()
    db.refresh(pr)

    steps = db.execute(select(PipelineStep).where(PipelineStep.pipeline_run_id == pr.id)).scalars().all()
    return PipelineNextOut(ok=True, pipeline_run=_run_to_out(pr, steps), created_run_id=str(new_run.id))