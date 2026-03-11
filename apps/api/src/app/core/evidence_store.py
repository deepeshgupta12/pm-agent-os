from __future__ import annotations

import hashlib
from typing import Optional


def evidence_fingerprint(source_ref: Optional[str], excerpt: Optional[str]) -> str:
    sr = (source_ref or "").strip()
    ex = (excerpt or "").strip()
    # Must match migration backfill semantics: source_ref + "\n" + excerpt
    return hashlib.md5((sr + "\n" + ex).encode("utf-8")).hexdigest()