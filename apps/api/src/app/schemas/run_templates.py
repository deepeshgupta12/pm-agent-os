from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class RunTemplateIn(BaseModel):
    name: str = Field(..., max_length=200)
    description: str = ""
    definition_json: Dict[str, Any] = Field(default_factory=dict)


class RunTemplateOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str
    definition_json: Dict[str, Any]

    is_library: bool = False
    library_label: Optional[str] = None

    class Config:
        from_attributes = True