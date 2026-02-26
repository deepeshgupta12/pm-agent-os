from __future__ import annotations

from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field


class ConnectorCreateIn(BaseModel):
    type: str = Field(min_length=2, max_length=32)  # docs|jira|github|slack|support|analytics
    name: str = Field(min_length=1, max_length=200)
    config: Dict[str, Any] = Field(default_factory=dict)


class ConnectorUpdateIn(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    status: Optional[str] = Field(default=None, min_length=2, max_length=32)
    config: Optional[Dict[str, Any]] = None


class ConnectorOut(BaseModel):
    id: str
    workspace_id: str
    type: str
    name: str
    status: str
    config: Dict[str, Any]
    last_sync_at: Optional[str] = None
    last_error: Optional[str] = None


# -------------------------
# V1 Ingestion Jobs (Docs)
# -------------------------
class DocsItemIn(BaseModel):
    external_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1)
    meta: Dict[str, Any] = Field(default_factory=dict)


class DocsIngestionJobCreateIn(BaseModel):
    docs: List[DocsItemIn] = Field(default_factory=list)
    timeframe: Dict[str, Any] = Field(default_factory=dict)  # stored into ingestion_jobs.timeframe
    params: Dict[str, Any] = Field(default_factory=dict)  # stored into ingestion_jobs.params
    upsert: bool = True
    embed_after: bool = False


class IngestionJobOut(BaseModel):
    id: str
    workspace_id: str
    connector_id: Optional[str] = None
    source_id: Optional[str] = None
    kind: str
    status: str
    timeframe: Dict[str, Any]
    params: Dict[str, Any]
    stats: Dict[str, Any]
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    created_by_user_id: str
    created_at: Optional[str] = None


# -------------------------
# V1 Ingestion Jobs (GitHub)
# -------------------------
class GitHubIngestionJobCreateIn(BaseModel):
    """
    Uses connector.config to decide what to fetch:
      - owner, repo
      - prs_state, prs_per_page
      - releases_per_page
      - issues_state, issues_per_page
    """
    timeframe: Dict[str, Any] = Field(default_factory=dict)  # stored into ingestion_jobs.timeframe
    params: Dict[str, Any] = Field(default_factory=dict)  # stored into ingestion_jobs.params
    upsert: bool = True
    embed_after: bool = False

    # Allow selective ingestion if you want to reduce load
    include_releases: bool = True
    include_prs: bool = True
    include_issues: bool = True