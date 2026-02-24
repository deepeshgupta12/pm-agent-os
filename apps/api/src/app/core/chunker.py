from __future__ import annotations

from typing import List, Tuple


def chunk_text(text: str, *, chunk_size: int, overlap: int) -> List[Tuple[int, int, str]]:
    """
    Returns list of (start_idx, end_idx, chunk_text).
    Simple char-based chunker with overlap.
    """
    t = (text or "").strip()
    if not t:
        return []

    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0:
        raise ValueError("overlap must be >= 0")
    if overlap >= chunk_size:
        raise ValueError("overlap must be < chunk_size")

    out: List[Tuple[int, int, str]] = []
    n = len(t)
    start = 0
    while start < n:
        end = min(start + chunk_size, n)
        chunk = t[start:end].strip()
        if chunk:
            out.append((start, end, chunk))
        if end >= n:
            break
        start = end - overlap
        if start < 0:
            start = 0

    return out