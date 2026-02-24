from __future__ import annotations

from typing import Any, Dict, List, Tuple
import re


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
            ex = c["excerpt"]
            if len(ex) > 600:
                ex = ex[:600] + "…"
            lines.append(ex)
        lines.append("")

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
    return bool(re.search(r"\[[0-9]+\]", md or ""))


def split_body_and_sources(md: str) -> Tuple[str, str]:
    """
    Split markdown into (body, sources_section_and_beyond).
    If no Sources section present, sources part is "".
    """
    if not md:
        return "", ""
    idx = md.find("## Sources")
    if idx == -1:
        return md, ""
    return md[:idx].rstrip(), md[idx:].lstrip()


def body_has_inline_citations(md: str) -> bool:
    body, _ = split_body_and_sources(md)
    return bool(re.search(r"\[[0-9]+\]", body or ""))


def build_inline_citation_patch(citations: List[Dict[str, Any]]) -> str:
    """
    Deterministic fallback block to ensure citations appear in-body.
    Uses evidence titles and adds [n] inline tokens.
    """
    if not citations:
        return ""

    lines: List[str] = []
    lines.append("## Evidence-backed notes")
    lines.append(
        "_Inline citations were missing in the draft body. This section was auto-added to anchor key statements to sources._"
    )
    lines.append("")

    # Add 1 bullet per citation with a generic grounded statement.
    # (We avoid hallucinating facts; we simply point to what evidence exists.)
    for c in citations[:10]:
        t = c.get("title") or "Source"
        n = c.get("n")
        lines.append(f"- Relevant source available: **{t}**. [{n}]")

    lines.append("")
    lines.append("## Inline citation checklist")
    lines.append("- Add citations like `[1]` at the end of sentences that rely on evidence.")
    lines.append("- If a claim cannot be grounded, move it to **Unknowns / Assumptions**.")
    return "\n".join(lines).strip()