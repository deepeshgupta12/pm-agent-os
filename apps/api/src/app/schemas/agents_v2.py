from __future__ import annotations

from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field


# -------------------------
# AgentBase
# -------------------------
class AgentBaseCreateIn(BaseModel):
    key: str = Field(min_length=2, max_length=120)
    name: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=20000)


class AgentBaseOut(BaseModel):
    id: str
    workspace_id: str
    key: str
    name: str
    description: str
    created_by_user_id: Optional[str] = None
    created_at: str
    updated_at: str


# -------------------------
# AgentVersion
# -------------------------
class AgentVersionCreateIn(BaseModel):
    """
    Create a new DRAFT version.
    If definition_json omitted => {}.
    """
    definition_json: Dict[str, Any] = Field(default_factory=dict)


class AgentVersionOut(BaseModel):
    id: str
    agent_base_id: str
    version: int
    status: str  # draft|published|archived
    definition_json: Dict[str, Any]
    created_by_user_id: Optional[str] = None
    created_at: str


class AgentPublishOut(BaseModel):
    ok: bool = True
    agent_base_id: str
    published_version_id: str
    published_version: int