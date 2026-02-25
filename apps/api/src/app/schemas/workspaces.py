from __future__ import annotations

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