from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PipelineTemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="")
    definition_json: Dict[str, Any] = Field(default_factory=dict)


class PipelineTemplateOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    description: str
    definition_json: Dict[str, Any]


class PipelineTemplatesSeedOut(BaseModel):
    ok: bool = True
    workspace_id: str
    created_count: int
    existing_count: int
    created_template_ids: List[str] = Field(default_factory=list)
    existing_template_ids: List[str] = Field(default_factory=list)


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

    # Existing flag (Step 17A+)
    prev_context_attached: Optional[bool] = None

    # Step 18: auto-regenerate status + latest artifact metadata
    auto_regenerated: Optional[bool] = None
    latest_artifact_id: Optional[str] = None
    latest_artifact_version: Optional[int] = None
    latest_artifact_type: Optional[str] = None
    latest_artifact_title: Optional[str] = None


class PipelineRunOut(BaseModel):
    id: str
    workspace_id: str
    template_id: str
    created_by_user_id: str
    status: str
    current_step_index: int
    input_payload: Dict[str, Any]
    steps: List[PipelineStepOut] = Field(default_factory=list)


class PipelineNextOut(BaseModel):
    ok: bool = True
    pipeline_run: PipelineRunOut
    created_run_id: Optional[str] = None


class PipelineExecuteAllOut(BaseModel):
    ok: bool = True
    pipeline_run: PipelineRunOut
    created_run_ids: List[str] = Field(default_factory=list)