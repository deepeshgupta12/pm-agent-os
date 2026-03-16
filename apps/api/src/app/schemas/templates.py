from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


TemplateSurface = Literal["pipeline", "agent", "tool", "prompt"]


class TemplateLibraryCreate(BaseModel):
    surface: TemplateSurface
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    # When true, workspace_id MUST be null (system/global library)
    is_system: bool = False


class TemplateLibraryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None


class TemplateLibraryOut(BaseModel):
    id: uuid.UUID
    workspace_id: Optional[uuid.UUID] = None
    surface: TemplateSurface
    name: str
    description: str
    is_system: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TemplateBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    spec: Dict[str, Any] = Field(default_factory=dict)
    # Optional: attach to a library instead of direct workspace ownership
    library_id: Optional[uuid.UUID] = None


class TemplateBaseUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    spec: Optional[Dict[str, Any]] = None
    library_id: Optional[uuid.UUID] = None


class TemplateOut(BaseModel):
    id: uuid.UUID
    workspace_id: Optional[uuid.UUID] = None
    library_id: Optional[uuid.UUID] = None
    name: str
    description: str
    spec: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# PipelineTemplate uses definition_json in DB. We expose it as `spec` for consistency.
class PipelineTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    definition_json: Dict[str, Any] = Field(default_factory=dict)
    library_id: Optional[uuid.UUID] = None


class PipelineTemplateUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    definition_json: Optional[Dict[str, Any]] = None
    library_id: Optional[uuid.UUID] = None