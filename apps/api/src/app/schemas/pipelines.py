from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PipelineTemplateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=240)
    description: str = Field(default="", max_length=2000)
    definition_json: Dict[str, Any] = Field(default_factory=dict)


class PipelineTemplateOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    description: str
    definition_json: Dict[str, Any] = Field(default_factory=dict)

    # Commit 23 Step A: Multi-workspace template libraries
    # If a template is surfaced via a consumer workspace's configured libraries,
    # this will be True and library_label may be populated.
    is_library: bool = False
    library_label: Optional[str] = None


class PipelineTemplatesSeedOut(BaseModel):
    ok: bool
    workspace_id: str
    created_count: int
    existing_count: int
    created_template_ids: List[str]
    existing_template_ids: List[str]


class PipelineRunCreateIn(BaseModel):
    template_id: str
    input_payload: Dict[str, Any] = Field(default_factory=dict)


class PipelineStepOut(BaseModel):
    id: str
    pipeline_run_id: str
    step_index: int
    step_name: str
    agent_id: str
    status: str
    input_payload: Dict[str, Any]
    run_id: Optional[str] = None
    prev_context_attached: Optional[bool] = None
    auto_regenerated: Optional[bool] = None

    # Commit 23: show latest artifact metadata per step
    latest_artifact_id: Optional[str] = None
    latest_artifact_version: Optional[int] = None
    latest_artifact_type: Optional[str] = None
    latest_artifact_title: Optional[str] = None

    # Commit 23 Step A: retrieval meta surfaced on the step
    retrieval_enabled: Optional[bool] = None
    retrieval_query: Optional[str] = None
    retrieval_evidence_count: Optional[int] = None
    retrieval_batch_id: Optional[str] = None
    retrieval_batch_kind: Optional[str] = None


class PipelineRunOut(BaseModel):
    id: str
    workspace_id: str
    template_id: str

    # Commit 23 Step A: resolved template origin
    template_workspace_id: Optional[str] = None
    template_is_library: Optional[bool] = None
    template_library_label: Optional[str] = None

    created_by_user_id: str
    status: str
    current_step_index: int
    input_payload: Dict[str, Any]
    steps: List[PipelineStepOut]


class PipelineNextOut(BaseModel):
    ok: bool
    pipeline_run: PipelineRunOut
    created_run_id: Optional[str] = None


class PipelineExecuteAllOut(BaseModel):
    ok: bool
    pipeline_run: PipelineRunOut
    created_run_ids: List[str] = Field(default_factory=list)
