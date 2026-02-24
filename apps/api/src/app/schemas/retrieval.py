from __future__ import annotations

from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field


class SourceOut(BaseModel):
    id: str
    workspace_id: str
    type: str
    name: str
    config: Dict[str, Any]


class DocumentIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    markdown: str = Field(min_length=1)


class DocumentOut(BaseModel):
    id: str
    workspace_id: str
    source_id: str
    title: str
    external_id: Optional[str]
    meta: Dict[str, Any]


class ChunkOut(BaseModel):
    id: str
    document_id: str
    chunk_index: int
    text: str
    meta: Dict[str, Any]


class IngestResult(BaseModel):
    document: DocumentOut
    chunks_created: int


class EmbedResult(BaseModel):
    document_id: str
    model: str
    chunks_embedded: int