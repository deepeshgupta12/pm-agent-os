from __future__ import annotations

import argparse
import uuid
from typing import Any, Dict, List, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.db.models import AgentDefinition, PipelineTemplate


# ---------
# Canonical pipelines (V1)
# NOTE: agent_id must exist in AgentDefinition.id (seed_agents.py)
# ---------
CANONICAL_PIPELINES: List[Dict[str, Any]] = [
    {
        "name": "Discovery → Strategy → PRD",
        "description": "End-to-end early phase flow: identify opportunities, pick direction, write PRD.",
        "steps": [
            {"name": "Discovery", "agent_id": "discovery"},
            {"name": "Strategy & Roadmap", "agent_id": "strategy_roadmap"},
            {"name": "PRD", "agent_id": "prd"},
        ],
    },
    {
        "name": "PRD → UX → Feasibility",
        "description": "Turn PRD into UX flow spec, then validate feasibility and architecture.",
        "steps": [
            {"name": "PRD", "agent_id": "prd"},
            {"name": "UX Flow", "agent_id": "ux_flow"},
            {"name": "Feasibility & Architecture", "agent_id": "feasibility_architecture"},
        ],
    },
    {
        "name": "Analytics → QA → Launch",
        "description": "Operationalization flow: tracking + experiment plan → QA suite → launch plan/runbook.",
        "steps": [
            {"name": "Analytics & Experiment", "agent_id": "analytics_experiment"},
            {"name": "QA & Test", "agent_id": "qa_test"},
            {"name": "Launch", "agent_id": "launch"},
        ],
    },
    {
        "name": "Launch → Monitoring → Stakeholders",
        "description": "Post-release loop: launch → health monitoring → stakeholder update pack.",
        "steps": [
            {"name": "Launch", "agent_id": "launch"},
            {"name": "Post-launch Monitoring", "agent_id": "post_launch_monitoring"},
            {"name": "Stakeholder Alignment", "agent_id": "stakeholder_alignment"},
        ],
    },
]


def _validate_agents_exist(db: Session) -> None:
    needed = sorted({s["agent_id"] for p in CANONICAL_PIPELINES for s in p["steps"]})
    existing = {a.id for a in db.execute(select(AgentDefinition)).scalars().all()}
    missing = [a for a in needed if a not in existing]
    if missing:
        raise RuntimeError(
            f"Missing AgentDefinition rows for: {missing}. "
            f"Run: PYTHONPATH=src python -m app.scripts.seed_agents"
        )


def seed(workspace_id: uuid.UUID) -> Tuple[int, int]:
    """
    Upsert canonical pipeline templates for a workspace.
    Returns: (created_count, updated_count)
    """
    db: Session = SessionLocal()
    try:
        _validate_agents_exist(db)

        existing_by_name: Dict[str, PipelineTemplate] = {
            t.name: t
            for t in db.execute(
                select(PipelineTemplate).where(PipelineTemplate.workspace_id == workspace_id)
            ).scalars().all()
        }

        created = 0
        updated = 0

        for p in CANONICAL_PIPELINES:
            definition_json = {
                "version": "v1",
                "steps": [{"name": s["name"], "agent_id": s["agent_id"]} for s in p["steps"]],
            }

            if p["name"] in existing_by_name:
                t = existing_by_name[p["name"]]
                # Update in-place (id stable)
                t.description = p["description"]
                t.definition_json = definition_json
                db.add(t)
                updated += 1
            else:
                t = PipelineTemplate(
                    id=uuid.uuid4(),
                    workspace_id=workspace_id,
                    name=p["name"],
                    description=p["description"],
                    definition_json=definition_json,
                )
                db.add(t)
                created += 1

        db.commit()
        return created, updated
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace_id", required=True, help="Workspace UUID to seed templates into")
    args = parser.parse_args()

    ws_id = uuid.UUID(args.workspace_id)
    created, updated = seed(ws_id)
    print(f"Seed pipelines complete. Created={created}, Updated={updated}")


if __name__ == "__main__":
    main()