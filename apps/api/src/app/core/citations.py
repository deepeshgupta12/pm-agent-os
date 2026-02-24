from __future__ import annotations

from typing import Any, Dict, List, Tuple


def build_citation_pack(evidence: List[Dict[str, Any]]) -> Tuple[str, str, List[Dict[str, Any]]]:
    """
    Returns:
      (citations_block_for_prompt, sources_section_markdown, normalized_citations)

    Evidence items should be dicts with keys:
      - excerpt (str)
      - source_ref (str|None)
      - meta (dict)
      - source_name (str)
    """
    normalized: List[Dict[str, Any]] = []

    for i, ev in enumerate(evidence, start=1):
        meta = ev.get("meta") or {}
        title = meta.get("document_title") or meta.get("title") or "Source"
        url = meta.get("url") or meta.get("link") or ""
        source_ref = ev.get("source_ref") or ""
        excerpt = (ev.get("excerpt") or "").strip()

        normalized.append(
            {
                "n": i,
                "title": str(title),
                "url": str(url),
                "source_ref": str(source_ref),
                "excerpt": excerpt,
            }
        )

    # Prompt block: include short excerpts with stable IDs
    lines: List[str] = []
    for c in normalized:
        head = f"[{c['n']}] {c['title']}"
        if c["url"]:
            head += f" — {c['url']}"
        if c["source_ref"]:
            head += f" — {c['source_ref']}"
        lines.append(head)
        if c["excerpt"]:
            # keep excerpt short-ish for prompt
            ex = c["excerpt"]
            if len(ex) > 600:
                ex = ex[:600] + "…"
            lines.append(ex)
        lines.append("")  # spacer

    citations_block = "\n".join(lines).strip()

    # Sources section to append in output
    src_md: List[str] = ["## Sources"]
    for c in normalized:
        row = f"- [{c['n']}] {c['title']}"
        if c["url"]:
            row += f" — {c['url']}"
        if c["source_ref"]:
            row += f" — {c['source_ref']}"
        src_md.append(row)
    sources_section = "\n".join(src_md).strip()

    return citations_block, sources_section, normalized


def output_has_any_citations(md: str) -> bool:
    # very lightweight check: look for [1] style tokens
    import re
    return bool(re.search(r"\[[0-9]+\]", md or ""))