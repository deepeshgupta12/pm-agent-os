from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text as sql_text
from sqlalchemy.orm import Session

from app.api.deps import (
    require_user,
    require_workspace_access,
    require_workspace_role_min,
    get_workspace_role,
)
from app.core.github_client import GitHubClient, GitHubAPIError
from app.core.ingest_common import get_or_create_source, upsert_document, rebuild_chunks, embed_document
from app.core.google_client import GoogleClient, GoogleAPIError
from app.core.config import settings
from app.core.governance import (
    policy_assert_allowed_sources,
    policy_allowed_source_types,
    audit_policy_check,
    audit_rbac_check,
    policy_internal_only,
    audit_internal_only_check,
    rbac_assert,
    rbac_allowed_connectors_read_roles,
    rbac_allowed_connectors_create_roles,
    rbac_allowed_connectors_update_roles,
    rbac_allowed_connectors_trigger_sync_roles,
)
from app.db.session import get_db
from app.db.models import Connector, IngestionJob, User, Workspace
from app.db.retrieval_models import Document, Source
from app.schemas.connectors import (
    ConnectorCreateIn,
    ConnectorUpdateIn,
    ConnectorOut,
    DocsIngestionJobCreateIn,
    GitHubIngestionJobCreateIn,
    IngestionJobOut,
    GoogleDocsIngestionJobCreateIn,
)

router = APIRouter(tags=["connectors"])

VALID_TYPES = {"docs", "jira", "github", "slack", "support", "analytics"}
VALID_STATUSES = {"connected", "disconnected"}


# -------------------------
# Step 0.4: Policy + RBAC audit logging helpers
# -------------------------
def _enforce_policy_sources(
    db: Session,
    ws: Workspace,
    user: User,
    requested: Optional[List[str]],
    action: str,
) -> None:
    """
    Step 0.4:
    - Enforce workspace policy allowlist for source types.
    - Always log allow/deny decision into governance_events (never breaks request).
    - Convert ValueError -> HTTP 403.
    """
    allowlist = policy_allowed_source_types(ws)
    req = [str(x).strip().lower() for x in (requested or []) if str(x).strip()]

    try:
        policy_assert_allowed_sources(ws, req or None)
        audit_policy_check(
            db,
            ws=ws,
            user=user,
            action=action,
            requested_source_types=req,
            allowlist=allowlist,
            decision="allow",
            reason="ok",
        )
    except ValueError as e:
        audit_policy_check(
            db,
            ws=ws,
            user=user,
            action=action,
            requested_source_types=req,
            allowlist=allowlist,
            decision="deny",
            reason=str(e),
        )
        raise HTTPException(status_code=403, detail=str(e))


def _enforce_rbac(
    db: Session,
    ws: Workspace,
    user: User,
    *,
    allowed_roles: List[str],
    action: str,
) -> None:
    """
    Step 0.4:
    - Enforce advanced RBAC rule (allowed_roles) for a specific action.
    - Always log allow/deny into governance_events.
    """
    role = get_workspace_role(db, ws, user)
    allowed = [str(r).strip().lower() for r in (allowed_roles or []) if str(r).strip()]
    role_l = (role or "").strip().lower()

    ok = bool(role_l and role_l in allowed)

    if ok:
        audit_rbac_check(
            db,
            ws=ws,
            user=user,
            action=action,
            role=role,
            allowed_roles=allowed_roles,
            decision="allow",
            reason="ok",
        )
        return

    audit_rbac_check(
        db,
        ws=ws,
        user=user,
        action=action,
        role=role,
        allowed_roles=allowed_roles,
        decision="deny",
        reason="Not allowed by RBAC.",
    )
    raise HTTPException(status_code=403, detail="Not allowed by RBAC.")


def _enforce_internal_only(
    db: Session,
    ws: Workspace,
    user: User,
    *,
    action: str,
) -> None:
    """
    V1 Policy Center:
    - If workspace.policy.internal_only == True, block connector operations
    - Always audit allow/deny
    """
    if policy_internal_only(ws):
        audit_internal_only_check(
            db,
            ws=ws,
            user=user,
            action=action,
            decision="deny",
            reason="Workspace is internal-only; connectors are disabled.",
        )
        raise HTTPException(status_code=403, detail="Workspace is internal-only; connectors are disabled.")
    audit_internal_only_check(
        db,
        ws=ws,
        user=user,
        action=action,
        decision="allow",
        reason="ok",
    )


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_rfc3339(s: Optional[str]) -> Optional[datetime]:
    """
    Parse RFC3339 timestamps from Google APIs.
    Example: "2026-02-27T10:11:12.345Z"
    """
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _parse_github_ts(s: Optional[str]) -> Optional[datetime]:
    """
    Parse GitHub ISO 8601 timestamps.
    Example: "2026-02-27T10:11:12Z"
    """
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _to_out(c: Connector) -> ConnectorOut:
    return ConnectorOut(
        id=str(c.id),
        workspace_id=str(c.workspace_id),
        type=c.type,
        name=c.name,
        status=c.status,
        config=c.config or {},
        last_sync_at=_iso(c.last_sync_at),
        last_error=c.last_error,
    )


def _job_out(j: IngestionJob) -> IngestionJobOut:
    return IngestionJobOut(
        id=str(j.id),
        workspace_id=str(j.workspace_id),
        connector_id=str(j.connector_id) if j.connector_id else None,
        source_id=str(j.source_id) if j.source_id else None,
        kind=j.kind,
        status=j.status,
        timeframe=j.timeframe or {},
        params=j.params or {},
        stats=j.stats or {},
        started_at=_iso(j.started_at),
        finished_at=_iso(j.finished_at),
        created_by_user_id=str(j.created_by_user_id),
        created_at=_iso(j.created_at),
    )


def _embed_after_effective(v: Optional[bool]) -> bool:
    """
    V2.5: If embed_after is omitted (None) => default True.
    If explicitly false => respect.
    """
    return True if v is None else bool(v)


# -------------------------
# Connectors CRUD
# -------------------------
@router.get("/workspaces/{workspace_id}/connectors", response_model=list[ConnectorOut])
def list_connectors(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)  # viewer+ can read
    try:
        rbac_assert(
            db,
            ws=ws,
            user=user,
            action="rbac.connectors.read",
            allowed_roles=rbac_allowed_connectors_read_roles(ws),
        )
    except ValueError:
        raise HTTPException(status_code=403, detail="Not allowed by RBAC.")
    items = (
        db.execute(select(Connector).where(Connector.workspace_id == ws.id).order_by(Connector.created_at.desc()))
        .scalars()
        .all()
    )
    return [_to_out(c) for c in items]


@router.post("/workspaces/{workspace_id}/connectors", response_model=ConnectorOut)
def create_connector(
    workspace_id: str,
    payload: ConnectorCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "admin", db, user)  # admin config

    # V1 Policy: internal-only blocks connectors
    _enforce_internal_only(db, ws, user, action="policy.internal_only.connectors.create")

    try:
        rbac_assert(
            db,
            ws=ws,
            user=user,
            action="rbac.connectors.read",
            allowed_roles=rbac_allowed_connectors_read_roles(ws),
        )
    except ValueError:
        raise HTTPException(status_code=403, detail="Not allowed by RBAC.")

    ctype = payload.type.strip().lower()
    name = payload.name.strip()

    if ctype not in VALID_TYPES:
        raise HTTPException(status_code=400, detail="Invalid connector type")

    # Step 0.4 Policy enforcement + audit
    _enforce_policy_sources(db, ws, user, [ctype], "policy.allowlist.connectors.create")

    # idempotent by (workspace_id, type, name)
    existing = db.execute(
        select(Connector).where(Connector.workspace_id == ws.id, Connector.type == ctype, Connector.name == name)
    ).scalar_one_or_none()

    if existing:
        existing.config = payload.config or {}
        existing.status = "connected"
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return _to_out(existing)

    c = Connector(
        workspace_id=ws.id,
        type=ctype,
        name=name,
        status="connected",
        config=payload.config or {},
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _to_out(c)


@router.patch("/connectors/{connector_id}", response_model=ConnectorOut)
def update_connector(
    connector_id: str,
    payload: ConnectorUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    try:
        cid = uuid.UUID(connector_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Connector not found")

    c = db.get(Connector, cid)
    if not c:
        raise HTTPException(status_code=404, detail="Connector not found")

    ws, _role = require_workspace_role_min(str(c.workspace_id), "admin", db, user)
    try:
        rbac_assert(
            db,
            ws=ws,
            user=user,
            action="rbac.connectors.update",
            allowed_roles=rbac_allowed_connectors_update_roles(ws),
        )
    except ValueError:
        raise HTTPException(status_code=403, detail="Not allowed by RBAC.")

    # V1 Policy: internal-only blocks connectors
    _enforce_internal_only(db, ws, user, action="policy.internal_only.connectors.update")

    # Step 0.4 Policy audit: ensure the connector's type itself is allowed if allowlist exists.
    _enforce_policy_sources(db, ws, user, [str(c.type or "").strip().lower()], "policy.allowlist.connectors.update")

    if payload.name is not None:
        c.name = payload.name.strip()

    if payload.status is not None:
        st = payload.status.strip().lower()
        if st not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid status")
        c.status = st

    if payload.config is not None:
        c.config = payload.config

    db.add(c)
    db.commit()
    db.refresh(c)
    return _to_out(c)


@router.post("/connectors/{connector_id}/sync", response_model=ConnectorOut)
def trigger_sync(
    connector_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """
    Keeps old semantics: stamps last_sync_at for basic health checks.
    member+ can trigger; admin configures.

    Step 0.4: RBAC + policy enforcement + audit logging.
    V1: internal-only blocks connector operations.
    """
    try:
        cid = uuid.UUID(connector_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Connector not found")

    c = db.get(Connector, cid)
    if not c:
        raise HTTPException(status_code=404, detail="Connector not found")

    ws = db.get(Workspace, c.workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    require_workspace_role_min(str(ws.id), "member", db, user)

    allowed = rbac_allowed_connectors_trigger_sync_roles(
    ws,
    connector_type=str(c.type or "").strip().lower(),
    connector_id=str(c.id),
    )
    try:
        rbac_assert(
            db,
            ws=ws,
            user=user,
            action="rbac.connectors.trigger_sync",
            allowed_roles=allowed,
        )
    except ValueError:
        raise HTTPException(status_code=403, detail="Not allowed by RBAC.")

    # V1 Policy: internal-only blocks connectors
    _enforce_internal_only(db, ws, user, action="policy.internal_only.connectors.trigger_sync")

    # Step 0.4 RBAC enforcement + audit
    allowed_roles = (ws.rbac_json or {}).get("connectors", {}).get("can_trigger_sync_roles", ["admin", "member"])
    if not isinstance(allowed_roles, list) or not allowed_roles:
        allowed_roles = ["admin", "member"]
    _enforce_rbac(db, ws, user, allowed_roles=[str(x) for x in allowed_roles], action="rbac.connectors.trigger_sync")

    # Step 0.4 Policy enforcement + audit: connector type is implied source type
    _enforce_policy_sources(
        db,
        ws,
        user,
        [str(c.type or "").strip().lower()],
        "policy.allowlist.connectors.trigger_sync",
    )

    c.last_sync_at = datetime.now(timezone.utc)
    c.last_error = None
    db.add(c)
    db.commit()
    db.refresh(c)
    return _to_out(c)


# -------------------------
# Ingestion jobs listing
# -------------------------
@router.get("/workspaces/{workspace_id}/ingestion-jobs", response_model=list[IngestionJobOut])
def list_ingestion_jobs(
    workspace_id: str,
    limit: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_access(workspace_id, db, user)  # viewer+ read

    lim = max(1, min(int(limit), 200))
    rows = (
        db.execute(
            select(IngestionJob)
            .where(IngestionJob.workspace_id == ws.id)
            .order_by(IngestionJob.created_at.desc())
            .limit(lim)
        )
        .scalars()
        .all()
    )
    return [_job_out(j) for j in rows]


# -------------------------
# V1 Docs ingestion job + V2.5 embed_after default
# -------------------------
@router.post(
    "/workspaces/{workspace_id}/connectors/{connector_id}/ingestion-jobs/docs",
    response_model=IngestionJobOut,
)
def create_docs_ingestion_job(
    workspace_id: str,
    connector_id: str,
    payload: DocsIngestionJobCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)

    # V1 Policy: internal-only blocks connectors/ingestion
    _enforce_internal_only(db, ws, user, action="policy.internal_only.ingestion.docs")

    # Policy enforcement + audit
    _enforce_policy_sources(db, ws, user, ["docs"], "policy.allowlist.connectors.ingestion_jobs.docs")

    allowed = rbac_allowed_connectors_trigger_sync_roles(
        ws,
        connector_type="<docs>",
        connector_id=str(c.id),
    )
    try:
        rbac_assert(
            db,
            ws=ws,
            user=user,
            action="rbac.connectors.ingestion",
            allowed_roles=allowed,
        )
    except ValueError:
        raise HTTPException(status_code=403, detail="Not allowed by RBAC.")

    try:
        cid = uuid.UUID(connector_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Connector not found")

    c = db.get(Connector, cid)
    if not c or str(c.workspace_id) != str(ws.id) or c.type != "docs":
        raise HTTPException(status_code=404, detail="Connector not found")

    job = IngestionJob(
        workspace_id=ws.id,
        connector_id=c.id,
        kind="docs_sync",
        status="running",
        timeframe=payload.timeframe or {},
        params=payload.params or {},
        stats={},
        started_at=datetime.now(timezone.utc),
        created_by_user_id=user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Source row for docs
    src = get_or_create_source(
        db,
        workspace_id=ws.id,
        type="docs",
        name=c.name or "Docs",
        config={"connector_id": str(c.id), **(c.config or {})},
    )

    job.source_id = src.id
    db.add(job)
    db.commit()
    db.refresh(job)

    stats: Dict[str, Any] = {
        "docs_seen": 0,
        "docs_created": 0,
        "docs_updated": 0,
        "chunks_created": 0,
        "embedded_chunks": 0,
        "embed_after_effective": _embed_after_effective(payload.embed_after),
        "errors": 0,
        "error_samples": [],
    }

    embed_after = _embed_after_effective(payload.embed_after)

    try:
        for d in payload.docs or []:
            stats["docs_seen"] += 1
            ext_id = d.external_id if payload.upsert else None

            meta = {
                "kind": "doc",
                "external_id": d.external_id,
                "connector_id": str(c.id),
                "ingestion_job_id": str(job.id),
                "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                **(d.meta or {}),
            }

            # Manual docs payload has no canonical upstream timestamps; leave as None.
            doc, created = upsert_document(
                db,
                workspace_id=ws.id,
                source_id=src.id,
                external_id=ext_id,
                title=d.title,
                raw_text=d.text,
                meta=meta,
                source_created_at=None,
                source_updated_at=None,
            )
            stats["docs_created" if created else "docs_updated"] += 1
            stats["chunks_created"] += rebuild_chunks(db, document_id=doc.id, raw_text=doc.raw_text)

            if embed_after:
                stats["embedded_chunks"] += embed_document(db, document_id=doc.id)

        job.status = "success"
        job.last_error = None  # type: ignore[attr-defined]
    except Exception as e:
        stats["errors"] += 1
        stats["error_samples"].append(str(e))
        job.status = "failed"
    finally:
        job.stats = stats
        job.finished_at = datetime.now(timezone.utc)
        db.add(job)
        db.commit()
        db.refresh(job)

    return _job_out(job)


# -------------------------
# V1 GitHub real ingestion job + V2.5 embed_after default
# -------------------------
@router.post(
    "/workspaces/{workspace_id}/connectors/{connector_id}/ingestion-jobs/github",
    response_model=IngestionJobOut,
)
def create_github_ingestion_job(
    workspace_id: str,
    connector_id: str,
    payload: GitHubIngestionJobCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)

    # V1 Policy: internal-only blocks connectors/ingestion
    _enforce_internal_only(db, ws, user, action="policy.internal_only.ingestion.github")

    # Policy enforcement + audit
    _enforce_policy_sources(db, ws, user, ["github"], "policy.allowlist.connectors.ingestion_jobs.github")

    allowed = rbac_allowed_connectors_trigger_sync_roles(
        ws,
        connector_type="<github>",
        connector_id=str(c.id),
    )
    try:
        rbac_assert(
            db,
            ws=ws,
            user=user,
            action="rbac.connectors.ingestion",
            allowed_roles=allowed,
        )
    except ValueError:
        raise HTTPException(status_code=403, detail="Not allowed by RBAC.")

    try:
        cid = uuid.UUID(connector_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Connector not found")

    c = db.get(Connector, cid)
    if not c or str(c.workspace_id) != str(ws.id) or c.type != "github":
        raise HTTPException(status_code=404, detail="Connector not found")

    cfg = c.config or {}
    owner = cfg.get("owner")
    repo = cfg.get("repo")
    if not owner or not repo:
        raise HTTPException(status_code=400, detail="GitHub connector config missing owner/repo")

    prs_state = cfg.get("prs_state", "all")
    prs_per_page = int(cfg.get("prs_per_page", 30))
    max_pages = int(cfg.get("max_pages", 5))
    max_items = cfg.get("max_items")
    max_items = int(max_items) if max_items is not None else None
    releases_per_page = int(cfg.get("releases_per_page", 20))
    issues_state = cfg.get("issues_state", "all")
    issues_per_page = int(cfg.get("issues_per_page", 50))

    job = IngestionJob(
        workspace_id=ws.id,
        connector_id=c.id,
        kind="github_sync",
        status="running",
        timeframe=payload.timeframe or {},
        params=payload.params or {},
        stats={},
        started_at=datetime.now(timezone.utc),
        created_by_user_id=user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Source row for github
    src = get_or_create_source(
        db,
        workspace_id=ws.id,
        type="github",
        name=c.name or f"GitHub: {owner}/{repo}",
        config={"connector_id": str(c.id), **cfg},
    )

    job.source_id = src.id
    db.add(job)
    db.commit()
    db.refresh(job)

    embed_after = _embed_after_effective(payload.embed_after)

    stats: Dict[str, Any] = {
        "errors": 0,
        "error_samples": [],
        "documents_upserted": 0,
        "chunks_created": 0,
        "embedded_chunks": 0,
        "embed_after_effective": embed_after,
        "releases_seen": 0,
        "releases_created": 0,
        "releases_updated": 0,
        "prs_seen": 0,
        "prs_created": 0,
        "prs_updated": 0,
        "issues_seen": 0,
        "issues_created": 0,
        "issues_updated": 0,
    }

    client = GitHubClient()

    try:
        # Releases
        if payload.include_releases:
            releases, _dbg_rel = client.list_releases(
                owner,
                repo,
                per_page=releases_per_page,
                max_pages=max_pages,
                max_items=max_items,
            )
            for rel in releases:
                stats["releases_seen"] += 1

                rid = str(rel.get("id"))
                tag = rel.get("tag_name") or ""
                name = rel.get("name") or tag or "Release"
                body = rel.get("body") or ""
                url = rel.get("html_url") or ""

                title = f"[Release] {name}".strip()
                raw = f"# {title}\n\nTag: {tag}\n\nURL: {url}\n\n{body}".strip()

                # Canonical timestamps from GitHub
                src_created = _parse_github_ts(rel.get("published_at") or rel.get("created_at"))
                src_updated = _parse_github_ts(rel.get("updated_at") or rel.get("published_at"))

                meta = {
                    "kind": "release",
                    "external_id": f"release:{rid}",
                    "tag": tag,
                    "url": url,
                    "connector_id": str(c.id),
                    "ingestion_job_id": str(job.id),
                    "repo": f"{owner}/{repo}",
                    "github_created_at": rel.get("created_at"),
                    "github_updated_at": rel.get("updated_at"),
                    "github_published_at": rel.get("published_at"),
                    "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }

                doc, created = upsert_document(
                    db,
                    workspace_id=ws.id,
                    source_id=src.id,
                    external_id=meta["external_id"] if payload.upsert else None,
                    title=title,
                    raw_text=raw,
                    meta=meta,
                    source_created_at=src_created,
                    source_updated_at=src_updated,
                )
                stats["documents_upserted"] += 1
                stats["releases_created" if created else "releases_updated"] += 1

                stats["chunks_created"] += rebuild_chunks(db, document_id=doc.id, raw_text=doc.raw_text)
                if embed_after:
                    stats["embedded_chunks"] += embed_document(db, document_id=doc.id)

        # PRs
        if payload.include_prs:
            prs, _dbg_prs = client.list_pull_requests(
                owner,
                repo,
                state=prs_state,
                per_page=prs_per_page,
                max_pages=max_pages,
                max_items=max_items,
            )
            for pr in prs:
                stats["prs_seen"] += 1

                pid = str(pr.get("id"))
                number = pr.get("number")
                pr_title = pr.get("title") or f"PR #{number}"
                body = pr.get("body") or ""
                url = pr.get("html_url") or ""
                state = pr.get("state") or ""
                merged = pr.get("merged_at") is not None

                title = f"[PR] #{number} {pr_title}".strip()
                raw = f"# {title}\n\nState: {state}\nMerged: {merged}\n\nURL: {url}\n\n{body}".strip()

                # Canonical timestamps from GitHub
                src_created = _parse_github_ts(pr.get("created_at"))
                src_updated = _parse_github_ts(pr.get("updated_at"))

                meta = {
                    "kind": "pull_request",
                    "external_id": f"pr:{pid}",
                    "number": number,
                    "state": state,
                    "merged": merged,
                    "url": url,
                    "connector_id": str(c.id),
                    "ingestion_job_id": str(job.id),
                    "repo": f"{owner}/{repo}",
                    "github_created_at": pr.get("created_at"),
                    "github_updated_at": pr.get("updated_at"),
                    "github_merged_at": pr.get("merged_at"),
                    "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }

                doc, created = upsert_document(
                    db,
                    workspace_id=ws.id,
                    source_id=src.id,
                    external_id=meta["external_id"] if payload.upsert else None,
                    title=title,
                    raw_text=raw,
                    meta=meta,
                    source_created_at=src_created,
                    source_updated_at=src_updated,
                )
                stats["documents_upserted"] += 1
                stats["prs_created" if created else "prs_updated"] += 1

                stats["chunks_created"] += rebuild_chunks(db, document_id=doc.id, raw_text=doc.raw_text)
                if embed_after:
                    stats["embedded_chunks"] += embed_document(db, document_id=doc.id)

        # Issues (filter PRs out)
        if payload.include_issues:
            items, _dbg_issues = client.list_issues(
                owner,
                repo,
                state=issues_state,
                per_page=issues_per_page,
                max_pages=max_pages,
                max_items=max_items,
            )
            issues = [it for it in items if it.get("pull_request") is None]

            for issue in issues:
                stats["issues_seen"] += 1

                iid = str(issue.get("id"))
                number = issue.get("number")
                title_txt = issue.get("title") or f"Issue #{number}"
                body = issue.get("body") or ""
                url = issue.get("html_url") or ""
                state = issue.get("state") or ""
                labels = [l.get("name") for l in (issue.get("labels") or []) if isinstance(l, dict)]

                title = f"[Issue] #{number} {title_txt}".strip()
                raw = f"# {title}\n\nState: {state}\n\nLabels: {', '.join(labels)}\n\nURL: {url}\n\n{body}".strip()

                # Canonical timestamps from GitHub
                src_created = _parse_github_ts(issue.get("created_at"))
                src_updated = _parse_github_ts(issue.get("updated_at"))

                meta = {
                    "kind": "issue",
                    "external_id": f"issue:{iid}",
                    "number": number,
                    "state": state,
                    "labels": labels,
                    "url": url,
                    "connector_id": str(c.id),
                    "ingestion_job_id": str(job.id),
                    "repo": f"{owner}/{repo}",
                    "github_created_at": issue.get("created_at"),
                    "github_updated_at": issue.get("updated_at"),
                    "github_closed_at": issue.get("closed_at"),
                    "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }

                doc, created = upsert_document(
                    db,
                    workspace_id=ws.id,
                    source_id=src.id,
                    external_id=meta["external_id"] if payload.upsert else None,
                    title=title,
                    raw_text=raw,
                    meta=meta,
                    source_created_at=src_created,
                    source_updated_at=src_updated,
                )
                stats["documents_upserted"] += 1
                stats["issues_created" if created else "issues_updated"] += 1

                stats["chunks_created"] += rebuild_chunks(db, document_id=doc.id, raw_text=doc.raw_text)
                if embed_after:
                    stats["embedded_chunks"] += embed_document(db, document_id=doc.id)

        job.status = "success"
        c.last_sync_at = datetime.now(timezone.utc)
        c.last_error = None

    except GitHubAPIError as e:
        stats["errors"] += 1
        stats["error_samples"].append({"status": e.status_code, "message": str(e), "details": e.details})
        job.status = "failed"
        c.last_error = f"GitHubAPIError {e.status_code}: {str(e)}"
    except Exception as e:
        stats["errors"] += 1
        stats["error_samples"].append(str(e))
        job.status = "failed"
        c.last_error = str(e)
    finally:
        job.stats = stats
        job.finished_at = datetime.now(timezone.utc)
        db.add(job)
        db.add(c)
        db.commit()
        db.refresh(job)

    return _job_out(job)


# -------------------------
# V1 Google Docs ingestion job + V2.5 embed_after default
# -------------------------
@router.post(
    "/workspaces/{workspace_id}/connectors/{connector_id}/ingestion-jobs/gdocs",
    response_model=IngestionJobOut,
)
def create_google_docs_ingestion_job(
    workspace_id: str,
    connector_id: str,
    payload: GoogleDocsIngestionJobCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)

    # V1 Policy: internal-only blocks connectors/ingestion
    _enforce_internal_only(db, ws, user, action="policy.internal_only.ingestion.gdocs")

    # Policy enforcement + audit
    _enforce_policy_sources(db, ws, user, ["docs"], "policy.allowlist.connectors.ingestion_jobs.gdocs")

    allowed = rbac_allowed_connectors_trigger_sync_roles(
        ws,
        connector_type="<docs>",
        connector_id=str(c.id),
    )
    try:
        rbac_assert(
            db,
            ws=ws,
            user=user,
            action="rbac.connectors.ingestion",
            allowed_roles=allowed,
        )
    except ValueError:
        raise HTTPException(status_code=403, detail="Not allowed by RBAC.")

    try:
        cid = uuid.UUID(connector_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Connector not found")

    c = db.get(Connector, cid)
    if not c or str(c.workspace_id) != str(ws.id) or c.type != "docs":
        raise HTTPException(status_code=404, detail="Connector not found")

    cfg = c.config or {}
    folder_id = cfg.get("folder_id")
    if not folder_id:
        raise HTTPException(status_code=400, detail="Docs connector config missing folder_id")

    # OAuth creds can come from connector.config or env
    client_id = cfg.get("client_id")
    client_secret = cfg.get("client_secret")
    refresh_token = cfg.get("refresh_token")

    job = IngestionJob(
        workspace_id=ws.id,
        connector_id=c.id,
        kind="gdocs_sync",
        status="running",
        timeframe=payload.timeframe or {},
        params=payload.params or {},
        stats={},
        started_at=datetime.now(timezone.utc),
        created_by_user_id=user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Use retrieval Source type=docs (same bucket). Multiple docs sources allowed by name now.
    src = get_or_create_source(
        db,
        workspace_id=ws.id,
        type="docs",
        name=c.name or "Google Drive Docs",
        config={"provider": "google_drive", "connector_id": str(c.id), **cfg},
    )
    job.source_id = src.id
    db.add(job)
    db.commit()
    db.refresh(job)

    embed_after = _embed_after_effective(payload.embed_after)

    stats: Dict[str, Any] = {
        "errors": 0,
        "error_samples": [],
        "docs_seen": 0,
        "docs_created": 0,
        "docs_updated": 0,
        "documents_upserted": 0,
        "chunks_created": 0,
        "embedded_chunks": 0,
        "embed_after_effective": embed_after,
        "folder_id": folder_id,
        "google_docs_seen": 0,
        "docx_seen": 0,
        "docx_empty_text": 0,
    }

    try:
        client = GoogleClient(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
        )

        fetched = 0
        page_token: Optional[str] = None

        while True:
            files, dbg = client.list_docs_in_folder(
                folder_id=str(folder_id),
                page_size=int(payload.page_size),
                page_token=page_token,
                include_docx=True,
            )
            page_token = dbg.get("nextPageToken")

            for f in files:
                if fetched >= int(payload.max_docs):
                    page_token = None
                    break

                fetched += 1
                stats["docs_seen"] += 1

                file_id = f.get("id")
                title = f.get("name") or "Untitled"
                mime = f.get("mimeType") or ""
                if not file_id:
                    continue

                text = ""
                if mime == GoogleClient.GOOGLE_DOC_MIME:
                    stats["google_docs_seen"] += 1
                    text, _dbg2 = client.export_google_doc_text(file_id=str(file_id))
                    ext_id = f"gdoc:{file_id}" if payload.upsert else None
                    kind = "google_doc"
                elif mime == GoogleClient.DOCX_MIME:
                    stats["docx_seen"] += 1
                    blob, _dbg3 = client.download_file_bytes(file_id=str(file_id))
                    text = client.extract_text_from_docx_bytes(blob)
                    if not text.strip():
                        stats["docx_empty_text"] += 1
                    ext_id = f"docx:{file_id}" if payload.upsert else None
                    kind = "docx"
                else:
                    continue

                # Canonical upstream timestamps
                src_created = _parse_rfc3339(f.get("createdTime"))
                src_updated = _parse_rfc3339(f.get("modifiedTime"))

                meta = {
                    "provider": "google_drive",
                    "kind": kind,
                    "folder_id": folder_id,
                    "drive_file_id": file_id,
                    "mimeType": mime,
                    "webViewLink": f.get("webViewLink"),
                    "modifiedTime": f.get("modifiedTime"),
                    "createdTime": f.get("createdTime"),
                    "owners": f.get("owners"),
                    "connector_id": str(c.id),
                    "ingestion_job_id": str(job.id),
                    "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }

                doc, created = upsert_document(
                    db,
                    workspace_id=ws.id,
                    source_id=src.id,
                    external_id=ext_id,
                    title=title,
                    raw_text=text,
                    meta=meta,
                    source_created_at=src_created,
                    source_updated_at=src_updated,
                )
                stats["documents_upserted"] += 1
                stats["docs_created" if created else "docs_updated"] += 1

                stats["chunks_created"] += rebuild_chunks(db, document_id=doc.id, raw_text=doc.raw_text)

                if embed_after:
                    stats["embedded_chunks"] += embed_document(db, document_id=doc.id)

            if not page_token:
                break

        job.status = "success"
        c.last_sync_at = datetime.now(timezone.utc)
        c.last_error = None

    except GoogleAPIError as e:
        stats["errors"] += 1
        stats["error_samples"].append({"status": e.status_code, "message": str(e), "details": e.details})
        job.status = "failed"
        c.last_error = f"GoogleAPIError {e.status_code}: {str(e)}"
    except Exception as e:
        stats["errors"] += 1
        stats["error_samples"].append(str(e))
        job.status = "failed"
        c.last_error = str(e)
    finally:
        job.stats = stats
        job.finished_at = datetime.now(timezone.utc)
        db.add(job)
        db.add(c)
        db.commit()
        db.refresh(job)

    return _job_out(job)


# -------------------------
# V2.5: On-demand embeddings runner (no cron)
# -------------------------
@router.post("/workspaces/{workspace_id}/embeddings/run-once")
def embeddings_run_once(
    workspace_id: str,
    limit_docs: int = Query(default=25, ge=1, le=200, description="Max documents to embed in this run"),
    max_total_chunks: int = Query(default=2000, ge=1, le=20000, description="Hard cap on chunks embedded in this run"),
    source_type: Optional[str] = Query(default=None, description="Optional filter by source type (docs/github/manual/...)"),
    dry_run: bool = Query(default=False, description="If true, only report what would be embedded"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """
    Finds documents in the workspace whose chunks are missing embeddings for the current model and embeds them.
    No background system required; call manually after ingestion or on demand.

    Notes:
    - Requires OPENAI_API_KEY to actually embed (unless dry_run=true).
    - Uses ingest_common.embed_document for idempotent per-doc embedding.
    """
    ws, _role = require_workspace_role_min(workspace_id, "member", db, user)

    # V1 Policy: internal-only blocks connector-like retrieval/embedding operations
    _enforce_internal_only(db, ws, user, action="policy.internal_only.embeddings.run_once")

    if source_type:
        _enforce_policy_sources(
            db,
            ws,
            user,
            [source_type.strip().lower()],
            "policy.allowlist.connectors.embeddings.run_once",
        )

    lim = int(limit_docs)
    max_chunks = int(max_total_chunks)

    base_q = select(Document).where(Document.workspace_id == ws.id).order_by(Document.updated_at.desc())

    if source_type:
        st = source_type.strip().lower()
        base_q = base_q.join(Source, Source.id == Document.source_id).where(Source.type == st)

    docs = db.execute(base_q.limit(lim)).scalars().all()

    model = settings.EMBEDDINGS_MODEL

    considered = 0
    candidate_docs: list[dict] = []
    embedded_docs = 0
    embedded_chunks_total = 0
    skipped_no_missing = 0

    for d in docs:
        considered += 1

        missing_count = db.execute(
            sql_text(
                """
                SELECT count(*)
                FROM chunks c
                WHERE c.document_id = :doc_id
                AND NOT EXISTS (
                  SELECT 1
                  FROM embeddings e
                  WHERE e.chunk_id = c.id
                  AND e.model = :model
                )
                """
            ),
            {"doc_id": str(d.id), "model": model},
        ).scalar_one()

        missing_count = int(missing_count or 0)

        if missing_count <= 0:
            skipped_no_missing += 1
            continue

        candidate_docs.append(
            {
                "document_id": str(d.id),
                "title": d.title,
                "source_id": str(d.source_id),
                "missing_chunks": missing_count,
                "updated_at": d.updated_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        )

    if dry_run:
        return {
            "ok": True,
            "workspace_id": str(ws.id),
            "model": model,
            "dry_run": True,
            "limit_docs": lim,
            "max_total_chunks": max_chunks,
            "considered_docs": considered,
            "candidate_docs": candidate_docs,
            "skipped_no_missing": skipped_no_missing,
            "note": "No embeddings were created because dry_run=true.",
        }

    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY missing; cannot embed (or use dry_run=true).")

    for cd in candidate_docs:
        if embedded_chunks_total >= max_chunks:
            break

        doc_id = uuid.UUID(cd["document_id"])
        before = embedded_chunks_total
        newly = embed_document(db, document_id=doc_id)
        embedded_chunks_total += int(newly or 0)

        if newly > 0:
            embedded_docs += 1

        if embedded_chunks_total >= max_chunks:
            break

        if embedded_chunks_total - before > max_chunks:
            embedded_chunks_total = max_chunks
            break

    return {
        "ok": True,
        "workspace_id": str(ws.id),
        "model": model,
        "dry_run": False,
        "limit_docs": lim,
        "max_total_chunks": max_chunks,
        "considered_docs": considered,
        "candidate_docs": candidate_docs,
        "skipped_no_missing": skipped_no_missing,
        "embedded_docs": embedded_docs,
        "embedded_chunks": embedded_chunks_total,
    }