from __future__ import annotations

from typing import List

from openai import OpenAI

from app.core.config import settings

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not settings.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is missing for embeddings")
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Returns list of embeddings (each is a list[float]).
    Uses OpenAI embeddings API.
    """
    if not texts:
        return []

    client = _get_client()
    resp = client.embeddings.create(
        model=settings.EMBEDDINGS_MODEL,
        input=texts,
    )
    # Ensure ordering preserved
    return [d.embedding for d in resp.data]