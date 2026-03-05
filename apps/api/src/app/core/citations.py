from __future__ import annotations

from typing import Any, Dict, List, Tuple, Optional
import re
import hashlib


# -------------------------
# Existing helpers (kept)
# -------------------------
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
    lines.append("_Inline citations were missing in the draft body. This section was auto-added to anchor key statements to sources._")
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


# -------------------------
# Hard citation enforcement
# -------------------------

_SENT_SPLIT = re.compile(r"(?<=[\.\!\?])\s+|\n+")
_CITE = re.compile(r"\[[0-9]{1,3}\]")
_FENCE = re.compile(r"```.*?```", re.DOTALL)


def _strip_code(md: str) -> str:
    if not md:
        return ""
    return re.sub(_FENCE, "", md)


def _count_cites(s: str) -> int:
    return len(re.findall(_CITE, s or ""))


def _sentence_chunks(body: str) -> List[str]:
    body = (body or "").strip()
    if not body:
        return []
    parts = re.split(_SENT_SPLIT, body)
    out = []
    for p in parts:
        t = (p or "").strip()
        if not t:
            continue
        if len(t) < 20:
            continue
        out.append(t)
    return out


def _artifact_thresholds(artifact_type: str) -> Dict[str, Any]:
    base = {
        "require_inline_if_evidence": True,
        "min_cited_sentence_ratio": 0.25,
    }

    t = (artifact_type or "").strip().lower()
    if t == "prd":
        return {**base, "min_cited_sentence_ratio": 0.35}
    if t in {"qa_suite", "tracking_spec", "experiment_plan"}:
        return {**base, "min_cited_sentence_ratio": 0.30}
    if t in {"problem_brief", "research_summary", "competitive_matrix"}:
        return {**base, "min_cited_sentence_ratio": 0.25}
    return base


def citation_enforcement_report(
    *,
    artifact_type: str,
    md: str,
    evidence_count: int,
) -> Dict[str, Any]:
    thresholds = _artifact_thresholds(artifact_type)

    body, sources = split_body_and_sources(md or "")
    body = _strip_code(body)
    sources = _strip_code(sources)

    sentences = _sentence_chunks(body)
    total = len(sentences)
    cited = 0
    for s in sentences:
        if _count_cites(s) > 0:
            cited += 1

    ratio = (cited / total) if total > 0 else 0.0

    reasons: List[str] = []
    ok = True

    if evidence_count > 0 and thresholds.get("require_inline_if_evidence", True):
        if not body_has_inline_citations(md):
            ok = False
            reasons.append("Evidence was attached, but the draft body has no inline citations like [1].")

    min_ratio = float(thresholds.get("min_cited_sentence_ratio", 0.25))
    if evidence_count > 0:
        if ratio + 1e-9 < min_ratio:
            ok = False
            reasons.append(f"Citation density too low: cited_sentence_ratio={ratio:.2f} < required {min_ratio:.2f}.")

    if evidence_count > 0 and "## Sources" not in (md or ""):
        ok = False
        reasons.append("Missing '## Sources' section.")

    confidence = max(0.0, min(1.0, ratio))

    return {
        "ok": bool(ok),
        "confidence_score": float(confidence),
        "evidence_count": int(evidence_count),
        "total_sentences": int(total),
        "cited_sentences": int(cited),
        "cited_sentence_ratio": float(ratio),
        "reasons": reasons,
        "thresholds": thresholds,
        "mode": "enforced",
    }


def citation_enforcement_report_skipped(*, evidence_count: int, reason: str) -> Dict[str, Any]:
    """
    When LLM is disabled (deterministic scaffold), we should not FAIL citation density checks.
    """
    return {
        "ok": True,
        "confidence_score": 1.0,
        "evidence_count": int(evidence_count),
        "total_sentences": 0,
        "cited_sentences": 0,
        "cited_sentence_ratio": 1.0,
        "reasons": [str(reason or "skipped")],
        "thresholds": {},
        "mode": "skipped",
    }


def render_citation_compliance_md(report: Dict[str, Any]) -> str:
    mode = str(report.get("mode") or "enforced")
    ok = bool(report.get("ok"))
    cs = float(report.get("confidence_score") or 0.0)
    ev = int(report.get("evidence_count") or 0)
    total = int(report.get("total_sentences") or 0)
    cited = int(report.get("cited_sentences") or 0)
    ratio = float(report.get("cited_sentence_ratio") or 0.0)

    lines: List[str] = []
    lines.append("## Citation Compliance")

    if mode == "skipped":
        lines.append("- Status: ⏭️ SKIPPED")
        lines.append(f"- Evidence attached: `{ev}`")
        reasons = report.get("reasons") or []
        if reasons:
            lines.append(f"- Reason: {reasons[0]}")
        return "\n".join(lines).strip()

    lines.append(f"- Status: {'✅ PASS' if ok else '❌ FAIL'}")
    lines.append(f"- Evidence attached: `{ev}`")
    lines.append(f"- Confidence score: `{cs:.2f}` (proxy = cited sentence ratio)")
    lines.append(f"- Cited sentences: `{cited}/{total}` (`{ratio:.2f}`)")
    thresholds = report.get("thresholds") or {}
    lines.append(f"- Thresholds: `{thresholds}`")

    reasons = report.get("reasons") or []
    if reasons:
        lines.append("")
        lines.append("### Issues")
        for r in reasons:
            lines.append(f"- {r}")

        lines.append("")
        lines.append("### How to fix")
        lines.append("- Add inline citations like `[1]` at the end of sentences that rely on evidence.")
        lines.append("- If something cannot be grounded, move it to **Unknowns / Assumptions**.")
        lines.append("- Ensure **## Sources** lists the evidence IDs.")

    return "\n".join(lines).strip()