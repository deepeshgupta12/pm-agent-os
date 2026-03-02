from __future__ import annotations

import pytest

from app.core.security_passwords import hash_password
from tests.conftest import (
    create_user,
    create_workspace,
    add_member,
    create_run_and_artifact,
)

# These endpoints are assumed from your existing system:
#   GET /artifacts/{artifact_id}/export/pdf
#   GET /artifacts/{artifact_id}/export/docx
#
# If your export router uses different paths, share export.py and I’ll align.


def _login(client, email: str, password: str):
    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r


@pytest.mark.parametrize("export_kind", ["pdf", "docx"])
def test_export_allowed_for_viewer_in_same_workspace(client, db, export_kind):
    from app.db.models import AgentDefinition

    viewer_email = "viewer@test.com"
    viewer_pw = "Password123!"
    viewer = create_user(db, email=viewer_email, password_hash=hash_password(viewer_pw))

    ws = create_workspace(db, name="WS A", owner_user_id=viewer.id)

    agent = AgentDefinition(
        id="prd",
        name="PRD",
        description="x",
        version="1",
        input_schema={},
        output_artifact_types=["prd"],
        default_artifact_type="prd",
    )
    try:
        db.add(agent)
        db.commit()
    except Exception:
        db.rollback()

    run, art = create_run_and_artifact(
        db,
        workspace_id=ws.id,
        agent_id="prd",
        created_by_user_id=viewer.id,
        artifact_type="prd",
    )

    _login(client, viewer_email, viewer_pw)

    path = f"/artifacts/{art.id}/export/{export_kind}"
    resp = client.get(path)

    assert resp.status_code == 200, resp.text

    ctype = resp.headers.get("content-type", "")
    if export_kind == "pdf":
        assert "application/pdf" in ctype
    else:
        assert (
            "application/vnd.openxmlformats" in ctype
            or "application/octet-stream" in ctype
            or "application/msword" in ctype
        )


@pytest.mark.parametrize("export_kind", ["pdf", "docx"])
def test_export_denied_cross_workspace(client, db, export_kind):
    from app.db.models import AgentDefinition

    owner_a_email = "ownerA@test.com"
    owner_a_pw = "Password123!"
    owner_a = create_user(db, email=owner_a_email, password_hash=hash_password(owner_a_pw))
    ws_a = create_workspace(db, name="WS A", owner_user_id=owner_a.id)

    user_b_email = "userB@test.com"
    user_b_pw = "Password123!"
    user_b = create_user(db, email=user_b_email, password_hash=hash_password(user_b_pw))
    ws_b = create_workspace(db, name="WS B", owner_user_id=user_b.id)

    agent = AgentDefinition(
        id="prd",
        name="PRD",
        description="x",
        version="1",
        input_schema={},
        output_artifact_types=["prd"],
        default_artifact_type="prd",
    )
    try:
        db.add(agent)
        db.commit()
    except Exception:
        db.rollback()

    run_a, art_a = create_run_and_artifact(
        db,
        workspace_id=ws_a.id,
        agent_id="prd",
        created_by_user_id=owner_a.id,
        artifact_type="prd",
    )

    _login(client, user_b_email, user_b_pw)

    path = f"/artifacts/{art_a.id}/export/{export_kind}"
    resp = client.get(path)

    assert resp.status_code in (403, 404), resp.text