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
# V1 Ingestion Job (Docs)
# -------------------------
class DocsItemIn(BaseModel):
    external_id: str = Field(min_length=1, max_length=256)
    title: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1)
    # optional extra meta fields (kept in doc meta)
    meta: Dict[str, Any] = Field(default_factory=dict)


class IngestionTimeframeIn(BaseModel):
    # Keep flexible for V1, aligns with your run-builder shape
    preset: Optional[str] = Field(default=None, max_length=32)  # 7d|30d|90d|custom
    start_date: Optional[str] = Field(default=None, max_length=32)  # YYYY-MM-DD
    end_date: Optional[str] = Field(default=None, max_length=32)  # YYYY-MM-DD


class DocsIngestionJobCreateIn(BaseModel):
    # V1 “connector fetch” is simulated by sending docs in the request
    docs: List[DocsItemIn] = Field(default_factory=list)

    timeframe: Dict[str, Any] = Field(default_factory=dict)  # stored as-is into ingestion_jobs.timeframe
    params: Dict[str, Any] = Field(default_factory=dict)  # stored as-is into ingestion_jobs.params

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