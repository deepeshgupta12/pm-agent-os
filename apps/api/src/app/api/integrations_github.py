from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.core.github_client import GitHubClient, GitHubAPIError
from app.core.ingest_common import get_or_create_source, upsert_document, rebuild_chunks, embed_document
from app.db.session import get_db
from app.db.models import Workspace, User

router = APIRouter(tags=["integrations"])


class GitHubConfigIn(BaseModel):
    owner: str = Field(min_length=1, max_length=100)
    repo: str = Field(min_length=1, max_length=200)
    releases_per_page: int = Field(default=20, ge=1, le=100)
    prs_per_page: int = Field(default=30, ge=1, le=100)
    prs_state: str = Field(default="all")  # open|closed|all
    issues_per_page: int = Field(default=50, ge=1, le=100)
    issues_state: str = Field(default="all")  # open|closed|all


class SyncOut(BaseModel):
    ok: bool = True
    source_id: str

    releases_fetched: int
    prs_fetched: int

    releases_created: int
    prs_created: int
    documents_upserted: int

    chunks_created: int
    chunks_embedded: int

    debug: Dict[str, Any]


class IssuesSyncOut(BaseModel):
    ok: bool = True
    source_id: str

    issues_fetched: int
    issues_created: int
    documents_upserted: int

    chunks_created: int
    chunks_embedded: int

    debug: Dict[str, Any]


def _ensure_workspace_access(db: Session, workspace_id: str, user: User) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if not ws or ws.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@router.post("/workspaces/{workspace_id}/sources/github/config")
def set_github_config(
    workspace_id: str,
    payload: GitHubConfigIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws = _ensure_workspace_access(db, workspace_id, user)

    cfg: Dict[str, Any] = payload.model_dump()
    src = get_or_create_source(
        db,
        workspace_id=ws.id,
        type="github",
        name=f"GitHub: {payload.owner}/{payload.repo}",
        config=cfg,
    )
    return {"ok": True, "source_id": str(src.id), "config": src.config}


@router.post("/workspaces/{workspace_id}/sources/github/sync", response_model=SyncOut)
def sync_github(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws = _ensure_workspace_access(db, workspace_id, user)

    from sqlalchemy import select
    from app.db.retrieval_models import Source

    src = db.execute(select(Source).where(Source.workspace_id == ws.id, Source.type == "github")).scalar_one_or_none()
    if not src:
        raise HTTPException(status_code=400, detail="GitHub source not configured. Call /sources/github/config first.")

    cfg = src.config or {}
    owner = cfg.get("owner")
    repo = cfg.get("repo")
    if not owner or not repo:
        raise HTTPException(status_code=400, detail="GitHub source config missing owner/repo")

    releases_per_page = int(cfg.get("releases_per_page", 20))
    prs_per_page = int(cfg.get("prs_per_page", 30))
    prs_state = cfg.get("prs_state", "all")

    client = GitHubClient()

    try:
        releases, rel_debug = client.list_releases(owner, repo, per_page=releases_per_page)
        prs, pr_debug = client.list_pull_requests(owner, repo, state=prs_state, per_page=prs_per_page)
    except GitHubAPIError as e:
        raise HTTPException(status_code=e.status_code, detail={"message": str(e), **(e.details or {})})

    releases_created = 0
    prs_created = 0
    documents_upserted = 0
    chunks_created_total = 0
    chunks_embedded_total = 0

    for rel in releases:
        external_id = str(rel.get("id"))
        tag = rel.get("tag_name") or ""
        name = rel.get("name") or tag or "Release"
        body = rel.get("body") or ""
        url = rel.get("html_url") or ""
        title = f"[Release] {name}"

        raw = f"# {title}\n\nTag: {tag}\n\nURL: {url}\n\n{body}".strip()
        meta = {"kind": "release", "tag": tag, "url": url}

        doc, created = upsert_document(
            db,
            workspace_id=ws.id,
            source_id=src.id,
            external_id=f"release:{external_id}",
            title=title,
            raw_text=raw,
            meta=meta,
        )
        documents_upserted += 1
        chunks_created_total += rebuild_chunks(db, document_id=doc.id, raw_text=doc.raw_text)
        chunks_embedded_total += embed_document(db, document_id=doc.id)
        if created:
            releases_created += 1

    for pr in prs:
        external_id = str(pr.get("id"))
        number = pr.get("number")
        pr_title = pr.get("title") or f"PR #{number}"
        body = pr.get("body") or ""
        url = pr.get("html_url") or ""
        state = pr.get("state") or ""
        merged = pr.get("merged_at") is not None

        title = f"[PR] #{number} {pr_title}".strip()
        raw = f"# {title}\n\nState: {state}\nMerged: {merged}\n\nURL: {url}\n\n{body}".strip()
        meta = {"kind": "pull_request", "number": number, "state": state, "merged": merged, "url": url}

        doc, created = upsert_document(
            db,
            workspace_id=ws.id,
            source_id=src.id,
            external_id=f"pr:{external_id}",
            title=title,
            raw_text=raw,
            meta=meta,
        )
        documents_upserted += 1
        chunks_created_total += rebuild_chunks(db, document_id=doc.id, raw_text=doc.raw_text)
        chunks_embedded_total += embed_document(db, document_id=doc.id)
        if created:
            prs_created += 1

    debug = {"repo": f"{owner}/{repo}", "releases_api": rel_debug, "prs_api": pr_debug}

    return SyncOut(
        ok=True,
        source_id=str(src.id),
        releases_fetched=len(releases),
        prs_fetched=len(prs),
        releases_created=releases_created,
        prs_created=prs_created,
        documents_upserted=documents_upserted,
        chunks_created=chunks_created_total,
        chunks_embedded=chunks_embedded_total,
        debug=debug,
    )


@router.post("/workspaces/{workspace_id}/sources/github/sync-issues", response_model=IssuesSyncOut)
def sync_github_issues(
    workspace_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    ws = _ensure_workspace_access(db, workspace_id, user)

    from sqlalchemy import select
    from app.db.retrieval_models import Source

    src = db.execute(select(Source).where(Source.workspace_id == ws.id, Source.type == "github")).scalar_one_or_none()
    if not src:
        raise HTTPException(status_code=400, detail="GitHub source not configured. Call /sources/github/config first.")

    cfg = src.config or {}
    owner = cfg.get("owner")
    repo = cfg.get("repo")
    if not owner or not repo:
        raise HTTPException(status_code=400, detail="GitHub source config missing owner/repo")

    issues_per_page = int(cfg.get("issues_per_page", 50))
    issues_state = cfg.get("issues_state", "all")

    client = GitHubClient()

    try:
        items, issues_debug = client.list_issues(owner, repo, state=issues_state, per_page=issues_per_page)
    except GitHubAPIError as e:
        raise HTTPException(status_code=e.status_code, detail={"message": str(e), **(e.details or {})})

    issues_created = 0
    documents_upserted = 0
    chunks_created_total = 0
    chunks_embedded_total = 0

    issues = []
    for it in items:
        # Filter out PRs (issues endpoint returns both)
        if it.get("pull_request") is not None:
            continue
        issues.append(it)

    for issue in issues:
        external_id = str(issue.get("id"))
        number = issue.get("number")
        title_txt = issue.get("title") or f"Issue #{number}"
        body = issue.get("body") or ""
        url = issue.get("html_url") or ""
        state = issue.get("state") or ""
        labels = [l.get("name") for l in (issue.get("labels") or []) if isinstance(l, dict)]

        title = f"[Issue] #{number} {title_txt}".strip()
        raw = f"# {title}\n\nState: {state}\n\nLabels: {', '.join(labels)}\n\nURL: {url}\n\n{body}".strip()
        meta = {"kind": "issue", "number": number, "state": state, "labels": labels, "url": url}

        doc, created = upsert_document(
            db,
            workspace_id=ws.id,
            source_id=src.id,
            external_id=f"issue:{external_id}",
            title=title,
            raw_text=raw,
            meta=meta,
        )
        documents_upserted += 1
        chunks_created_total += rebuild_chunks(db, document_id=doc.id, raw_text=doc.raw_text)
        chunks_embedded_total += embed_document(db, document_id=doc.id)
        if created:
            issues_created += 1

    debug = {"repo": f"{owner}/{repo}", "issues_api": issues_debug}

    return IssuesSyncOut(
        ok=True,
        source_id=str(src.id),
        issues_fetched=len(issues),
        issues_created=issues_created,
        documents_upserted=documents_upserted,
        chunks_created=chunks_created_total,
        chunks_embedded=chunks_embedded_total,
        debug=debug,
    )