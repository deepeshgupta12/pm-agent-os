from __future__ import annotations

from typing import Any, Dict, Optional
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