from __future__ import annotations

from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field


class GovernanceEffectiveOut(BaseModel):
    workspace_id: str
    policy_effective: Dict[str, Any] = Field(default_factory=dict)
    rbac_effective: Dict[str, Any] = Field(default_factory=dict)


class GovernanceEventOut(BaseModel):
    id: str
    workspace_id: str
    user_id: Optional[str] = None
    action: str
    decision: str
    reason: str
    meta: Dict[str, Any] = Field(default_factory=dict)
    created_at: str


class GovernanceEventsOut(BaseModel):
    workspace_id: str
    items: List[GovernanceEventOut] = Field(default_factory=list)