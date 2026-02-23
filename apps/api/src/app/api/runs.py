from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.db.session import get_db
from app.db.models import Workspace, Run, AgentDefinition, User
from app.schemas.core import RunCreateIn, RunOut, RunStatusUpdateIn

router = APIRouter(tags=["runs"])


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

    ws = db.get(Workspace, r.workspace_id)
    if not ws or ws.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Run not found")

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

    ws = db.get(Workspace, r.workspace_id)
    if not ws or ws.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Run not found")

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