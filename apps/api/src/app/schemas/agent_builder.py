from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.schemas.core import RetrievalConfigIn


class AgentBuilderMetaOut(BaseModel):
    workspace_id: str

    # Governance-effective constraints for the builder UI
    allowed_source_types: List[str] = Field(default_factory=list)

    # Presets the UI can offer
    timeframe_presets: List[str] = Field(default_factory=lambda: ["7d", "30d", "90d", "custom"])

    # Knob defaults + bounds for UI sliders
    retrieval_knobs: Dict[str, Any] = Field(
        default_factory=lambda: {
            "defaults": {"k": 6, "alpha": 0.65, "min_score": 0.15, "overfetch_k": 3, "rerank": False},
            "bounds": {
                "k": {"min": 1, "max": 50},
                "alpha": {"min": 0.0, "max": 1.0},
                "min_score": {"min": 0.0, "max": 1.0},
                "overfetch_k": {"min": 1, "max": 10},
                "rerank": {"min": 0, "max": 1},
            },
        }
    )

    # Output templates supported by the app
    artifact_types: List[str] = Field(default_factory=list)


class CustomAgentPublishedOut(BaseModel):
    agent_base_id: str
    published_version_id: str
    published_version: int
    status: str = "published"
    definition_json: Dict[str, Any] = Field(default_factory=dict)


class CustomAgentPreviewIn(BaseModel):
    input_payload: Dict[str, Any] = Field(default_factory=dict)
    retrieval: Optional[RetrievalConfigIn] = None


class CustomAgentPreviewOut(BaseModel):
    ok: bool = True
    agent_base_id: str
    published_version: int

    artifact_type: str
    retrieval_resolved: Dict[str, Any] = Field(default_factory=dict)

    # Prompt preview (UI can show this to the user)
    system_prompt: str = ""
    user_prompt: str = ""

    # If LLM disabled we still return prompts, but note it explicitly
    llm_enabled: bool = False
    notes: List[str] = Field(default_factory=list)