from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.core.generator import AGENT_TO_DEFAULT_ARTIFACT_TYPE
from app.db.session import get_db
from app.db.models import AgentDefinition, User
from app.schemas.core import AgentOut

router = APIRouter(prefix="/agents", tags=["agents"])


def _default_type(agent_id: str) -> str:
    return AGENT_TO_DEFAULT_ARTIFACT_TYPE.get(agent_id, "strategy_memo")


@router.get("", response_model=list[AgentOut])
def list_agents(db: Session = Depends(get_db), user: User = Depends(require_user)):
    agents = db.execute(select(AgentDefinition).order_by(AgentDefinition.id.asc())).scalars().all()
    return [
        AgentOut(
            id=a.id,
            name=a.name,
            description=a.description,
            version=a.version,
            input_schema=a.input_schema,
            output_artifact_types=a.output_artifact_types,
            default_artifact_type=_default_type(a.id),
        )
        for a in agents
    ]


@router.get("/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    a = db.get(AgentDefinition, agent_id)
    if not a:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentOut(
        id=a.id,
        name=a.name,
        description=a.description,
        version=a.version,
        input_schema=a.input_schema,
        output_artifact_types=a.output_artifact_types,
        default_artifact_type=_default_type(a.id),
    )