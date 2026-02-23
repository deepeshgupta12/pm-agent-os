from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# -------- Workspaces --------
class WorkspaceCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)


class WorkspaceOut(BaseModel):
    id: str
    name: str
    owner_user_id: str


# -------- Agents --------
class AgentOut(BaseModel):
    id: str
    name: str
    description: str
    version: str
    input_schema: Dict[str, Any]
    output_artifact_types: List[str]


# -------- Runs --------
class RunCreateIn(BaseModel):
    agent_id: str
    input_payload: Dict[str, Any] = Field(default_factory=dict)


class RunOut(BaseModel):
    id: str
    workspace_id: str
    agent_id: str
    created_by_user_id: str
    status: str
    input_payload: Dict[str, Any]
    output_summary: Optional[str] = None


class RunStatusUpdateIn(BaseModel):
    status: str = Field(min_length=2, max_length=32)
    output_summary: Optional[str] = None


# -------- Artifacts --------
class ArtifactCreateIn(BaseModel):
    type: str
    title: str = Field(min_length=1, max_length=240)
    content_md: str = ""
    logical_key: str = Field(min_length=1, max_length=64)


class ArtifactOut(BaseModel):
    id: str
    run_id: str
    type: str
    title: str
    content_md: str
    logical_key: str
    version: int
    status: str


class ArtifactUpdateIn(BaseModel):
    title: Optional[str] = None
    content_md: Optional[str] = None
    status: Optional[str] = None


class ArtifactNewVersionIn(BaseModel):
    title: Optional[str] = None
    content_md: str = ""
    status: str = "draft"


# -------- Evidence --------
class EvidenceCreateIn(BaseModel):
    kind: str = Field(min_length=2, max_length=32)
    source_name: str = Field(default="manual", max_length=120)
    source_ref: Optional[str] = Field(default=None, max_length=500)
    excerpt: str = ""
    meta: Dict[str, Any] = Field(default_factory=dict)


class EvidenceOut(BaseModel):
    id: str
    run_id: str
    kind: str
    source_name: str
    source_ref: Optional[str]
    excerpt: str
    metadata: Dict[str, Any]