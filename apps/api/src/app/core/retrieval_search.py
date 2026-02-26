from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.embeddings import embed_texts


def _normalize_scores(pairs: List[Tuple[str, float]]) -> Dict[str, float]:
    """
    Normalize scores to 0..1 using min-max. If all equal, return 1.0 for all.
    """
    if not pairs:
        return {}
    scores = [s for _, s in pairs]
    lo = min(scores)
    hi = max(scores)
    if hi == lo:
        return {k: 1.0 for k, _ in pairs}
    return {k: (s - lo) / (hi - lo) for k, s in pairs}


def hybrid_retrieve(
    db: Session,
    *,
    workspace_id: str,
    q: str,
    k: int,
    alpha: float,
    source_types: Optional[List[str]] = None,
    start_ts: Optional[datetime] = None,
    end_ts: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    Returns list of items with chunk/document metadata and score breakdown.

    V1 improvements:
      - source filtering happens IN SQL (FTS + vector)
      - timeframe filtering happens IN SQL (FTS + vector)
      - embeddings/vector part is optional; if embeddings unavailable, fall back to FTS only.
    """
    q = (q or "").strip()
    if not q:
        return []

    k = max(1, min(int(k), 50))

    alpha = float(alpha)
    if alpha < 0.0:
        alpha = 0.0
    if alpha > 1.0:
        alpha = 1.0

    # Defensive sanitization of source_types
    stypes = [s.strip().lower() for s in (source_types or []) if s and s.strip()]
    if not stypes:
        stypes = []

    # Timeframe filter uses documents.updated_at (fallback documents.created_at)
    # If both start_ts/end_ts provided, apply both bounds.
    timeframe_sql = ""
    params: Dict[str, Any] = {"workspace_id": workspace_id, "q": q, "limit": k * 3}

    if stypes:
        timeframe_sql += " AND s.type = ANY(:source_types) "
        params["source_types"] = stypes

    if start_ts is not None:
        timeframe_sql += " AND COALESCE(d.updated_at, d.created_at) >= :start_ts "
        params["start_ts"] = start_ts

    if end_ts is not None:
        timeframe_sql += " AND COALESCE(d.updated_at, d.created_at) <= :end_ts "
        params["end_ts"] = end_ts

    # -----------------------------
    # 1) FTS search (chunks.tsv_tsvector)
    # -----------------------------
    fts_rows = db.execute(
        sql_text(
            f"""
            SELECT
              c.id::text AS chunk_id,
              d.id::text AS document_id,
              d.source_id::text AS source_id,
              d.title AS document_title,
              c.chunk_index AS chunk_index,
              left(c.text, 240) AS snippet,
              c.meta AS meta,
              ts_rank_cd(c.tsv_tsvector, websearch_to_tsquery('english', :q)) AS score_fts
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            JOIN sources s ON s.id = d.source_id
            WHERE d.workspace_id = :workspace_id
              AND c.tsv_tsvector @@ websearch_to_tsquery('english', :q)
              {timeframe_sql}
            ORDER BY score_fts DESC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()

    fts_scores = _normalize_scores([(r["chunk_id"], float(r["score_fts"])) for r in fts_rows])

    # -----------------------------
    # 2) Vector search (optional)
    # -----------------------------
    vec_rows = []
    vec_scores: Dict[str, float] = {}

    # Only attempt embeddings if we can (avoid crashing when key missing)
    can_embed = bool(settings.OPENAI_API_KEY) and bool(settings.EMBEDDINGS_MODEL)

    if can_embed:
        try:
            q_vec = embed_texts([q])[0]
            vec_params = {
                "workspace_id": workspace_id,
                "qvec": q_vec,
                "model": settings.EMBEDDINGS_MODEL,
                "limit": k * 3,
            }
            if stypes:
                vec_params["source_types"] = stypes
            if start_ts is not None:
                vec_params["start_ts"] = start_ts
            if end_ts is not None:
                vec_params["end_ts"] = end_ts

            vec_rows = db.execute(
                sql_text(
                    f"""
                    SELECT
                      c.id::text AS chunk_id,
                      d.id::text AS document_id,
                      d.source_id::text AS source_id,
                      d.title AS document_title,
                      c.chunk_index AS chunk_index,
                      left(c.text, 240) AS snippet,
                      c.meta AS meta,
                      (1 - (e.embedding_vec <=> CAST(:qvec AS vector))) AS score_vec
                    FROM embeddings e
                    JOIN chunks c ON c.id = e.chunk_id
                    JOIN documents d ON d.id = c.document_id
                    JOIN sources s ON s.id = d.source_id
                    WHERE d.workspace_id = :workspace_id
                      AND e.model = :model
                      AND e.embedding_vec IS NOT NULL
                      {timeframe_sql}
                    ORDER BY e.embedding_vec <=> CAST(:qvec AS vector) ASC
                    LIMIT :limit
                    """
                ),
                {**vec_params, **{k: v for k, v in params.items() if k in ("source_types", "start_ts", "end_ts")}},
            ).mappings().all()

            vec_scores = _normalize_scores([(r["chunk_id"], float(r["score_vec"])) for r in vec_rows])

        except Exception:
            # Fail closed on vector part: return FTS-only hybrid (vec=0.0)
            vec_rows = []
            vec_scores = {}

    # -----------------------------
    # 3) Merge candidates by chunk_id
    # -----------------------------
    by_id: Dict[str, Dict[str, Any]] = {}

    def upsert(row: Dict[str, Any], score_fts: float, score_vec: float):
        cid = row["chunk_id"]
        if cid not in by_id:
            by_id[cid] = {
                "chunk_id": cid,
                "document_id": row["document_id"],
                "source_id": row["source_id"],
                "document_title": row["document_title"],
                "chunk_index": int(row["chunk_index"]),
                "snippet": row["snippet"],
                "meta": row["meta"] or {},
                "score_fts": 0.0,
                "score_vec": 0.0,
            }
        by_id[cid]["score_fts"] = max(float(by_id[cid]["score_fts"]), float(score_fts))
        by_id[cid]["score_vec"] = max(float(by_id[cid]["score_vec"]), float(score_vec))

    for r in fts_rows:
        upsert(r, fts_scores.get(r["chunk_id"], 0.0), 0.0)

    for r in vec_rows:
        upsert(r, 0.0, vec_scores.get(r["chunk_id"], 0.0))

    # -----------------------------
    # 4) Hybrid score
    # -----------------------------
    items: List[Dict[str, Any]] = []
    for _, item in by_id.items():
        s_fts = float(item["score_fts"])
        s_vec = float(item["score_vec"])
        item["score_hybrid"] = alpha * s_vec + (1.0 - alpha) * s_fts
        items.append(item)

    items.sort(key=lambda x: float(x["score_hybrid"]), reverse=True)
    return items[:k]