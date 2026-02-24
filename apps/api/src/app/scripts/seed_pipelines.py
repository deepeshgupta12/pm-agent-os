from __future__ import annotations

import argparse
import uuid

from sqlalchemy import select

from app.db.session import engine
from app.db.models import Workspace, AgentDefinition, PipelineTemplate
from app.api.pipelines import CANONICAL_PIPELINES  # reuse single source of truth


def _validate_agents_exist(workspace_id: uuid.UUID) -> None:
    # workspace_id is not needed for agent validation since agents are global,
    # but it keeps signature symmetric for future.
    needed = set()
    for tpl in CANONICAL_PIPELINES:
        steps = (tpl.get("definition_json") or {}).get("steps") or []
        for s in steps:
            aid = (s or {}).get("agent_id")
            if aid:
                needed.add(aid)

    with engine.begin() as conn:
        existing = set(conn.execute(select(AgentDefinition.id)).scalars().all())
    missing = sorted([a for a in needed if a not in existing])
    if missing:
        raise RuntimeError(f"Missing AgentDefinition rows for: {missing}. Run seed_agents first.")


def seed_for_workspace(workspace_id: uuid.UUID) -> tuple[int, int]:
    """
    Idempotent seed. Creates canonical templates if not already present by (workspace_id + name).
    Returns (created_count, existing_count).
    """
    with engine.begin() as conn:
        ws = conn.execute(select(Workspace).where(Workspace.id == workspace_id)).scalar_one_or_none()
        if not ws:
            raise RuntimeError(f"Workspace not found: {workspace_id}")

        existing = conn.execute(
            select(PipelineTemplate).where(PipelineTemplate.workspace_id == workspace_id)
        ).scalars().all()
        by_name = {t.name.strip().lower(): t for t in existing}

        created = 0
        existing_count = 0

        for tpl in CANONICAL_PIPELINES:
            name = str(tpl["name"]).strip()
            key = name.lower()
            if key in by_name:
                existing_count += 1
                continue

            t = PipelineTemplate(
                id=uuid.uuid4(),
                workspace_id=workspace_id,
                name=name,
                description=str(tpl.get("description") or ""),
                definition_json=tpl.get("definition_json") or {},
            )
            conn.add(t)
            created += 1

        return created, existing_count


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace_id", required=True, help="Workspace UUID to seed canonical pipeline templates into")
    args = ap.parse_args()

    ws_id = uuid.UUID(args.workspace_id)
    _validate_agents_exist(ws_id)

    created, existing = seed_for_workspace(ws_id)
    print(f"Seed complete. created={created} existing={existing}")


if __name__ == "__main__":
    main()