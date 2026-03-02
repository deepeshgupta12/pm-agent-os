from __future__ import annotations

import os
import uuid
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text as sql_text
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.main import app

# IMPORTANT:
# These tests assume Postgres is running at settings.DATABASE_URL.
# We hard-reset all tables via TRUNCATE CASCADE before each test.


@pytest.fixture(scope="session")
def engine():
    # allow override for CI if desired
    db_url = os.getenv("DATABASE_URL", settings.DATABASE_URL)
    return create_engine(db_url)


@pytest.fixture(scope="session")
def SessionLocal(engine):
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _truncate_all_tables(db) -> None:
    """
    Hard reset DB between tests.

    NOTE: This will delete ALL rows from the app tables.
    Safe for local dev, not for shared DBs.
    """
    # Order doesn’t matter with CASCADE as long as we include all major roots.
    # Include retrieval + core OS tables.
    tables = [
        # approvals / artifacts / runs
        "artifact_reviews",
        "artifacts",
        "run_status_events",
        "run_logs",
        "evidence",
        "runs",
        # pipelines (if present)
        "pipeline_steps",
        "pipeline_runs",
        "pipeline_templates",
        # workspaces / memberships
        "workspace_members",
        "workspaces",
        # users/auth
        "refresh_tokens",
        "users",
        # retrieval store
        "embeddings",
        "chunks",
        "documents",
        "sources",
        # connectors + jobs
        "ingestion_jobs",
        "connectors",
    ]

    # Some deployments may not have all tables (depending on migrations).
    # We try each TRUNCATE individually and ignore missing tables.
    for t in tables:
        try:
            db.execute(sql_text(f"TRUNCATE TABLE {t} RESTART IDENTITY CASCADE"))
        except Exception:
            db.rollback()
            # ignore if table doesn't exist in this schema
            continue
    db.commit()


@pytest.fixture()
def db(SessionLocal):
    db = SessionLocal()
    try:
        _truncate_all_tables(db)
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(db) -> Generator[TestClient, None, None]:
    # TestClient uses the real app; db fixture already reset tables.
    with TestClient(app) as c:
        yield c


# --------------------------
# Small DB helpers for tests
# --------------------------
def create_user(db, *, email: str, password_hash: str):
    # Import here to avoid import cycles at module import time
    from app.db.models import User

    u = User(email=email.lower().strip(), password_hash=password_hash)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def create_workspace(db, *, name: str, owner_user_id):
    from app.db.models import Workspace

    ws = Workspace(name=name, owner_user_id=owner_user_id)
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


def add_member(db, *, workspace_id, user_id, role: str):
    from app.db.models import WorkspaceMember

    m = WorkspaceMember(workspace_id=workspace_id, user_id=user_id, role=role)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def create_run_and_artifact(db, *, workspace_id, agent_id: str, created_by_user_id, artifact_type="prd"):
    from app.db.models import Run, Artifact

    r = Run(
        workspace_id=workspace_id,
        agent_id=agent_id,
        created_by_user_id=created_by_user_id,
        status="completed",
        input_payload={"goal": "test", "context": "x"},
        output_summary="test",
    )
    db.add(r)
    db.commit()
    db.refresh(r)

    a = Artifact(
        run_id=r.id,
        type=artifact_type,
        title="Test Artifact",
        content_md="# Test\n\nHello",
        logical_key=artifact_type,
        version=1,
        status="draft",
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return r, a