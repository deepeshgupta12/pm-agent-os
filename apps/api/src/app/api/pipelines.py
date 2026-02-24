from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Tuple, Optional

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
    Artifact,
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
        "description": "Go from discovery insights to a strategy memo and a PRD.",
        "definition_json": {
            "version": "v1",
            "steps": [
                {"name": "Discovery", "agent_id": "discovery"},
                {"name": "Strategy", "agent_id": "strategy_memo"},
                {"name": "PRD", "agent_id": "prd"},
            ],
        },
    },
    {
        "key": "prd_ux_feasibility",
        "name": "PRD → UX → Feasibility",
        "description": "Turn a PRD into UX spec and feasibility/tech brief.",
        "definition_json": {
            "version": "v1",
            "steps": [
                {"name": "PRD", "agent_id": "prd"},
                {"name": "UX", "agent_id": "ux_spec"},
                {"name": "Feasibility", "agent_id": "tech_brief"},
            ],
        },
    },
    {
        "key": "analytics_qa_launch",
        "name": "Analytics → QA → Launch",
        "description": "Use analytics to plan QA coverage and produce a launch plan.",
        "definition_json": {
            "version": "v1",
            "steps": [
                {"name": "Analytics", "agent_id": "analytics_experiment"},
                {"name": "QA", "agent_id": "qa_suite"},
                {"name": "Launch", "agent_id": "launch_plan"},
            ],
        },
    },
    {
        "key": "launch_monitoring_stakeholder",
        "name": "Launch → Monitoring → Stakeholder",
        "description": "Post-launch workflow: monitoring report and stakeholder update.",
        "definition_json": {
            "version": "v1",
            "steps": [
                {"name": "Launch", "agent_id": "launch_plan"},
                {"name": "Monitoring", "agent_id": "health_report"},
                {"name": "Stakeholder", "agent_id": "stakeholder_update"},
            ],
        },
    },
]


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


def _seed_canonical_templates_for_workspace(db: Session, ws: Workspace) -> Tuple[List[PipelineTemplate], List[PipelineTemplate]]:
    existing = db.execute(
        select(PipelineTemplate).where(PipelineTemplate.workspace_id == ws.id)
    ).scalars().all()

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

    # Create step rows
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


def _latest_artifact_snapshot(db: Session, run_id: uuid.UUID, max_chars: int = 1400) -> Optional[Dict[str, Any]]:
    a = (
        db.execute(
            select(Artifact)
            .where(Artifact.run_id == run_id)
            .order_by(Artifact.version.desc(), Artifact.created_at.desc())
        )
        .scalars()
        .first()
    )
    if not a:
        return None

    md = (a.content_md or "").strip()
    excerpt = md[:max_chars]
    if len(md) > max_chars:
        excerpt += "\n\n…(truncated)…"

    return {
        "artifact_id": str(a.id),
        "type": a.type,
        "title": a.title,
        "version": int(a.version),
        "status": a.status,
        "content_md_excerpt": excerpt,
    }


def _ensure_pipeline_run_access(db: Session, pr: PipelineRun, user: User) -> Workspace:
    ws = db.get(Workspace, pr.workspace_id)
    if not ws or ws.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return ws


def _execute_one_step(db: Session, pr: PipelineRun, user: User) -> Tuple[PipelineRun, List[PipelineStep], Optional[str]]:
    ws = _ensure_pipeline_run_access(db, pr, user)

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
        db.refresh(pr)
        return pr, steps, None

    step = steps[pr.current_step_index]

    if step.status == "completed":
        pr.current_step_index += 1
        if pr.current_step_index >= len(steps):
            pr.status = "completed"
        db.add(pr)
        db.commit()
        db.refresh(pr)
        steps = db.execute(select(PipelineStep).where(PipelineStep.pipeline_run_id == pr.id)).scalars().all()
        return pr, steps, None

    step.status = "running"
    step.started_at = datetime.utcnow()
    db.add(step)
    db.commit()
    db.refresh(step)

    run_input: Dict[str, Any] = dict(pr.input_payload or {})
    run_input["_pipeline"] = {
        "pipeline_run_id": str(pr.id),
        "step_index": int(step.step_index),
        "step_name": step.step_name,
        "template_id": str(pr.template_id),
    }

    # carry forward prev run + latest artifact snapshot
    if step.step_index > 0:
        prev = steps[step.step_index - 1]
        run_input["_pipeline"]["prev_run_id"] = str(prev.run_id) if prev.run_id else None
        if prev.run_id:
            snap = _latest_artifact_snapshot(db, prev.run_id)
            if snap:
                run_input["_pipeline"]["prev_artifact"] = snap

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

    step.run_id = new_run.id
    step.status = "completed"
    step.completed_at = datetime.utcnow()
    db.add(step)

    pr.current_step_index += 1
    if pr.current_step_index >= len(steps):
        pr.status = "completed"
    else:
        pr.status = "running"

    db.add(pr)
    db.commit()
    db.refresh(pr)

    steps = db.execute(select(PipelineStep).where(PipelineStep.pipeline_run_id == pr.id)).scalars().all()
    return pr, steps, str(new_run.id)


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

    pr2, steps, created = _execute_one_step(db, pr, user)
    return PipelineNextOut(ok=True, pipeline_run=_run_to_out(pr2, steps), created_run_id=created)


@router.post("/pipelines/runs/{pipeline_run_id}/execute-all", response_model=PipelineExecuteAllOut)
def execute_all_remaining_steps(
    pipeline_run_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    pr_uuid = uuid.UUID(pipeline_run_id)
    pr = db.get(PipelineRun, pr_uuid)
    if not pr:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    _ensure_pipeline_run_access(db, pr, user)

    created_ids: List[str] = []
    safety = 0

    while True:
        safety += 1
        if safety > 50:
            raise HTTPException(status_code=500, detail="Safety stop: too many pipeline iterations")

        pr = db.get(PipelineRun, pr_uuid)
        if not pr:
            raise HTTPException(status_code=404, detail="Pipeline run not found")

        if (pr.status or "").lower() == "completed":
            steps = db.execute(select(PipelineStep).where(PipelineStep.pipeline_run_id == pr.id)).scalars().all()
            return PipelineExecuteAllOut(ok=True, pipeline_run=_run_to_out(pr, steps), created_run_ids=created_ids)

        pr2, steps, created = _execute_one_step(db, pr, user)
        if created:
            created_ids.append(created)

        if (pr2.status or "").lower() == "completed":
            return PipelineExecuteAllOut(ok=True, pipeline_run=_run_to_out(pr2, steps), created_run_ids=created_ids)