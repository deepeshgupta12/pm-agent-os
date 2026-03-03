from __future__ import annotations

from typing import Any, Dict
from pydantic import BaseModel, Field


class WorkspaceMemberInviteIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: str = Field(default="member", pattern="^(admin|member|viewer)$")


class WorkspaceMemberOut(BaseModel):
    user_id: str
    email: str
    role: str


class WorkspaceRoleOut(BaseModel):
    workspace_id: str
    role: str


class TemplateAdminOut(BaseModel):
    workspace_id: str
    template_admin_json: Dict[str, Any] = Field(default_factory=dict)


class TemplateAdminUpdateIn(BaseModel):
    template_admin_json: Dict[str, Any] = Field(default_factory=dict)


# -------------------------
# V3 Governance: Policy + RBAC
# -------------------------
class WorkspacePolicyOut(BaseModel):
    workspace_id: str
    policy_json: Dict[str, Any] = Field(default_factory=dict)


class WorkspacePolicyUpdateIn(BaseModel):
    policy_json: Dict[str, Any] = Field(default_factory=dict)


class WorkspaceRBACOut(BaseModel):
    workspace_id: str
    rbac_json: Dict[str, Any] = Field(default_factory=dict)


class WorkspaceRBACUpdateIn(BaseModel):
    rbac_json: Dict[str, Any] = Field(default_factory=dict)