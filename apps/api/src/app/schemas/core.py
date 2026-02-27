from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


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
    default_artifact_type: str


# -------- Retrieval Config (V1 True RAG) --------
class RetrievalConfigIn(BaseModel):
    enabled: bool = False
    query: str = Field(default="", max_length=500)
    k: int = Field(default=6, ge=1, le=20)
    alpha: float = Field(default=0.65, ge=0.0, le=1.0)
    source_types: List[str] = Field(default_factory=list)  # ["docs","github",...]
    timeframe: Dict[str, Any] = Field(default_factory=dict)  # {"preset":"30d"} or {"preset":"custom","start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD"}


# -------- Runs --------
class RunCreateIn(BaseModel):
    agent_id: str
    input_payload: Dict[str, Any] = Field(default_factory=dict)

    # Optional True-RAG pre-retrieval before generation
    retrieval: Optional[RetrievalConfigIn] = None


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
    meta: Dict[str, Any]


# -------- Run Logs + Timeline --------
class RunLogCreateIn(BaseModel):
    level: str = Field(default="info", max_length=16)
    message: str = Field(default="", min_length=1)
    meta: Dict[str, Any] = Field(default_factory=dict)


class RunLogOut(BaseModel):
    id: str
    run_id: str
    level: str
    message: str
    meta: Dict[str, Any]
    created_at: datetime


class RunTimelineEventOut(BaseModel):
    ts: datetime
    kind: str  # run|status|artifact|evidence|log
    label: str
    ref_id: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


# -------- Approvals v1 (auditable) --------
class ArtifactReviewSubmitIn(BaseModel):
    comment: Optional[str] = Field(default=None, max_length=5000)


class ArtifactReviewDecisionIn(BaseModel):
    comment: Optional[str] = Field(default=None, max_length=5000)


class ArtifactReviewOut(BaseModel):
    id: str
    artifact_id: str
    state: str  # requested|approved|rejected
    requested_by_user_id: str
    requested_at: datetime
    request_comment: Optional[str] = None
    decided_by_user_id: Optional[str] = None
    decided_at: Optional[datetime] = None
    decision_comment: Optional[str] = None