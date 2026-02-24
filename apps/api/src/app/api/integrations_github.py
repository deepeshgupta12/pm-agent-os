from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import require_user
from app.core.github_client import GitHubClient
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


class SyncOut(BaseModel):
    ok: bool = True
    source_id: str
    releases_docs: int
    prs_docs: int
    chunks_created: int
    chunks_embedded: int


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

    # Find github source
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

    releases = client.list_releases(owner, repo, per_page=releases_per_page)
    prs = client.list_pull_requests(owner, repo, state=prs_state, per_page=prs_per_page)

    releases_docs = 0
    prs_docs = 0
    chunks_created_total = 0
    chunks_embedded_total = 0

    # Ingest releases
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
        # Always rebuild chunks on update to keep text aligned
        chunks_created_total += rebuild_chunks(db, document_id=doc.id, raw_text=doc.raw_text)
        chunks_embedded_total += embed_document(db, document_id=doc.id)
        if created:
            releases_docs += 1

    # Ingest PRs
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
        chunks_created_total += rebuild_chunks(db, document_id=doc.id, raw_text=doc.raw_text)
        chunks_embedded_total += embed_document(db, document_id=doc.id)
        if created:
            prs_docs += 1

    return SyncOut(
        ok=True,
        source_id=str(src.id),
        releases_docs=releases_docs,
        prs_docs=prs_docs,
        chunks_created=chunks_created_total,
        chunks_embedded=chunks_embedded_total,
    )