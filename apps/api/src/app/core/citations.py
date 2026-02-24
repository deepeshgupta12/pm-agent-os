from __future__ import annotations

from typing import Any, Dict, List, Tuple
import re
import hashlib


def _fingerprint(ev: Dict[str, Any]) -> str:
    source_ref = str(ev.get("source_ref") or "").strip()
    excerpt = str(ev.get("excerpt") or "").strip()
    h = hashlib.sha256((source_ref + "\n" + excerpt).encode("utf-8")).hexdigest()[:16]
    return h


def build_citation_pack(evidence: List[Dict[str, Any]]) -> Tuple[str, str, List[Dict[str, Any]]]:
    """
    Returns:
      (citations_block_for_prompt, sources_section_markdown, normalized_citations)

    Dedupes evidence rows to avoid exploding citation lists when auto-evidence is run multiple times.
    """
    normalized: List[Dict[str, Any]] = []
    seen: set[str] = set()

    # Deduplicate while keeping order
    deduped: List[Dict[str, Any]] = []
    for ev in evidence:
        fp = _fingerprint(ev)
        if fp in seen:
            continue
        seen.add(fp)
        deduped.append(ev)

    for i, ev in enumerate(deduped, start=1):
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
    if not citations:
        return ""

    lines: List[str] = []
    lines.append("## Evidence-backed notes")
    lines.append(
        "_Inline citations were missing in the draft body. This section was auto-added to anchor key statements to sources._"
    )
    lines.append("")

    for c in citations[:10]:
        t = c.get("title") or "Source"
        n = c.get("n")
        lines.append(f"- Relevant source available: **{t}**. [{n}]")

    lines.append("")
    lines.append("## Inline citation checklist")
    lines.append("- Add citations like `[1]` at the end of sentences that rely on evidence.")
    lines.append("- If a claim cannot be grounded, move it to **Unknowns / Assumptions**.")
    return "\n".join(lines).strip()