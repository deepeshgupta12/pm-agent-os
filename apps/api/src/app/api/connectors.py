from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import require_user, require_workspace_access, require_workspace_role_min
from app.core.github_client import GitHubClient, GitHubAPIError
from app.core.ingest_common import get_or_create_source, upsert_document, rebuild_chunks, embed_document
from app.db.session import get_db
from app.db.models import Connector, IngestionJob, User
from app.core.google_client import GoogleClient, GoogleAPIError
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


def _iso(dt: Optional[datetime]) -> Optional[str]:
    if not dt:
        return None
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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

    ctype = payload.type.strip().lower()
    name = payload.name.strip()

    if ctype not in VALID_TYPES:
        raise HTTPException(status_code=400, detail="Invalid connector type")

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

    require_workspace_role_min(str(c.workspace_id), "admin", db, user)

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
    """
    try:
        cid = uuid.UUID(connector_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Connector not found")

    c = db.get(Connector, cid)
    if not c:
        raise HTTPException(status_code=404, detail="Connector not found")

    require_workspace_role_min(str(c.workspace_id), "member", db, user)

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
# V1 Docs ingestion job (already working)
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
        "errors": 0,
        "error_samples": [],
    }

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

            doc, created = upsert_document(
                db,
                workspace_id=ws.id,
                source_id=src.id,
                external_id=ext_id,
                title=d.title,
                raw_text=d.text,
                meta=meta,
            )
            if created:
                stats["docs_created"] += 1
            else:
                stats["docs_updated"] += 1

            stats["chunks_created"] += rebuild_chunks(db, document_id=doc.id, raw_text=doc.raw_text)

            if payload.embed_after:
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
# V1 GitHub real ingestion job
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

    stats: Dict[str, Any] = {
        "errors": 0,
        "error_samples": [],
        "documents_upserted": 0,
        "chunks_created": 0,
        "embedded_chunks": 0,
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
            releases, _dbg_rel = client.list_releases(owner, repo, per_page=releases_per_page)
            for rel in releases:
                stats["releases_seen"] += 1

                rid = str(rel.get("id"))
                tag = rel.get("tag_name") or ""
                name = rel.get("name") or tag or "Release"
                body = rel.get("body") or ""
                url = rel.get("html_url") or ""

                title = f"[Release] {name}".strip()
                raw = f"# {title}\n\nTag: {tag}\n\nURL: {url}\n\n{body}".strip()

                meta = {
                    "kind": "release",
                    "external_id": f"release:{rid}",
                    "tag": tag,
                    "url": url,
                    "connector_id": str(c.id),
                    "ingestion_job_id": str(job.id),
                    "repo": f"{owner}/{repo}",
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
                )
                stats["documents_upserted"] += 1
                if created:
                    stats["releases_created"] += 1
                else:
                    stats["releases_updated"] += 1

                stats["chunks_created"] += rebuild_chunks(db, document_id=doc.id, raw_text=doc.raw_text)
                if payload.embed_after:
                    stats["embedded_chunks"] += embed_document(db, document_id=doc.id)

        # PRs
        if payload.include_prs:
            prs, _dbg_prs = client.list_pull_requests(owner, repo, state=prs_state, per_page=prs_per_page)
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
                )
                stats["documents_upserted"] += 1
                if created:
                    stats["prs_created"] += 1
                else:
                    stats["prs_updated"] += 1

                stats["chunks_created"] += rebuild_chunks(db, document_id=doc.id, raw_text=doc.raw_text)
                if payload.embed_after:
                    stats["embedded_chunks"] += embed_document(db, document_id=doc.id)

        # Issues (filter PRs out)
        if payload.include_issues:
            items, _dbg_issues = client.list_issues(owner, repo, state=issues_state, per_page=issues_per_page)
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
                )
                stats["documents_upserted"] += 1
                if created:
                    stats["issues_created"] += 1
                else:
                    stats["issues_updated"] += 1

                stats["chunks_created"] += rebuild_chunks(db, document_id=doc.id, raw_text=doc.raw_text)
                if payload.embed_after:
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

    stats: Dict[str, Any] = {
        "errors": 0,
        "error_samples": [],
        "docs_seen": 0,
        "docs_created": 0,
        "docs_updated": 0,
        "documents_upserted": 0,
        "chunks_created": 0,
        "embedded_chunks": 0,
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
                    # Shouldn't happen due to query filter, but keep safe.
                    continue

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
                )
                stats["documents_upserted"] += 1
                if created:
                    stats["docs_created"] += 1
                else:
                    stats["docs_updated"] += 1

                stats["chunks_created"] += rebuild_chunks(db, document_id=doc.id, raw_text=doc.raw_text)

                if payload.embed_after:
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