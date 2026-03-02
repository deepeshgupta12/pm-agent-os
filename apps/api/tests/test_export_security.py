from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.security_passwords import hash_password


def _login(client, email: str, password: str):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r


def _create_user(db, *, email: str, password: str):
    from app.db.models import User

    u = User(email=email.strip().lower(), password_hash=hash_password(password))
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _create_workspace(db, *, name: str, owner_user_id):
    from app.db.models import Workspace

    ws = Workspace(name=name, owner_user_id=owner_user_id)
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


def _ensure_agent_exists(db, agent_id: str = "prd"):
    from app.db.models import AgentDefinition

    existing = db.get(AgentDefinition, agent_id)
    if existing:
        return existing

    a = AgentDefinition(
        id=agent_id,
        name=agent_id.upper(),
        description="test",
        version="1",
        input_schema={},
        output_artifact_types=[agent_id],
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _create_run_and_artifact(db, *, workspace_id, agent_id: str, created_by_user_id, artifact_type="prd"):
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


@pytest.mark.parametrize("export_kind", ["pdf", "docx"])
def test_export_allowed_for_viewer_in_same_workspace(client, db, export_kind):
    # Owner is admin implicitly, and export is viewer+ per export.py
    email = "owner@test.com"
    pw = "Password123!"
    user = _create_user(db, email=email, password=pw)

    ws = _create_workspace(db, name="WS A", owner_user_id=user.id)

    _ensure_agent_exists(db, "prd")
    _run, art = _create_run_and_artifact(
        db,
        workspace_id=ws.id,
        agent_id="prd",
        created_by_user_id=user.id,
        artifact_type="prd",
    )

    _login(client, email, pw)

    resp = client.get(f"/artifacts/{art.id}/export/{export_kind}")
    assert resp.status_code == 200, resp.text

    ctype = resp.headers.get("content-type", "")
    if export_kind == "pdf":
        assert "application/pdf" in ctype
    else:
        assert "application/vnd.openxmlformats-officedocument.wordprocessingml.document" in ctype


@pytest.mark.parametrize("export_kind", ["pdf", "docx"])
def test_export_denied_cross_workspace(client, db, export_kind):
    # Workspace A owner creates artifact
    email_a = "ownerA@test.com"
    pw_a = "Password123!"
    owner_a = _create_user(db, email=email_a, password=pw_a)
    ws_a = _create_workspace(db, name="WS A", owner_user_id=owner_a.id)

    # Workspace B user tries to export artifact from A
    email_b = "ownerB@test.com"
    pw_b = "Password123!"
    owner_b = _create_user(db, email=email_b, password=pw_b)
    _ws_b = _create_workspace(db, name="WS B", owner_user_id=owner_b.id)

    _ensure_agent_exists(db, "prd")
    _run_a, art_a = _create_run_and_artifact(
        db,
        workspace_id=ws_a.id,
        agent_id="prd",
        created_by_user_id=owner_a.id,
        artifact_type="prd",
    )

    _login(client, email_b, pw_b)

    resp = client.get(f"/artifacts/{art_a.id}/export/{export_kind}")

    # Your RBAC uses require_workspace_access which hides existence → 404 expected.
    # If it ever returns 403, allow it too.
    assert resp.status_code in (403, 404), resp.text