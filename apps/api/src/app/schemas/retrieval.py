from __future__ import annotations

from typing import Any, Dict, Optional, List
from pydantic import BaseModel


class SourceOut(BaseModel):
    id: str
    workspace_id: str
    type: str
    name: str
    config: Dict[str, Any]


class DocumentOut(BaseModel):
    id: str
    workspace_id: str
    source_id: str
    title: str
    external_id: Optional[str]
    meta: Dict[str, Any]


class IngestResult(BaseModel):
    document: DocumentOut
    chunks_created: int


class EmbedResult(BaseModel):
    document_id: str
    model: str
    chunks_embedded: int


class RetrieveItem(BaseModel):
    chunk_id: str
    document_id: str
    source_id: str
    document_title: str
    chunk_index: int
    snippet: str
    meta: Dict[str, Any]

    score_fts: float
    score_vec: float
    score_hybrid: float

    # V2.1 optional fields (safe if absent)
    score_rerank_bonus: Optional[float] = None
    score_final: Optional[float] = None
    knobs: Optional[Dict[str, Any]] = None


class RetrieveResponse(BaseModel):
    ok: bool = True
    q: str
    k: int
    alpha: float

    # V2.1 knobs (echo back)
    min_score: float
    overfetch_k: int
    rerank: bool

    items: List[RetrieveItem]


# -------------------------
# V1 traceability schemas
# -------------------------
class RetrievalRequestOut(BaseModel):
    id: str
    workspace_id: str
    created_by_user_id: str
    q: str
    k: int
    alpha: float
    source_types: Optional[str] = None
    timeframe: Dict[str, Any]
    created_at: str


class RetrievalRequestItemOut(BaseModel):
    id: str
    request_id: str
    rank: int

    chunk_id: Optional[str] = None
    document_id: Optional[str] = None
    source_id: Optional[str] = None

    snippet: str
    meta: Dict[str, Any]
    score_fts: float
    score_vec: float
    score_hybrid: float
    created_at: str