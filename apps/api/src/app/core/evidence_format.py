from __future__ import annotations

from typing import List
from app.db.models import Evidence


def format_evidence_for_prompt(items: List[Evidence], limit: int = 8) -> str:
    """
    Convert evidence records into a compact prompt block.
    """
    if not items:
        return ""

    lines: list[str] = []
    for e in items[:limit]:
        ref = f" ({e.source_ref})" if e.source_ref else ""
        excerpt = (e.excerpt or "").strip()
        excerpt = excerpt[:600]  # keep prompt bounded
        lines.append(f"- kind={e.kind}, source={e.source_name}{ref}: {excerpt}")

    return "\n".join(lines)