from __future__ import annotations

from typing import Any, Dict, List

from app.core.generator import AGENT_TO_DEFAULT_ARTIFACT_TYPE


def build_system_prompt() -> str:
    return (
        "You are a senior Product Manager. "
        "You write crisp, structured, execution-ready documents. "
        "You never invent metrics, data, or citations. "
        "If something is unknown, state it explicitly and ask for it under Open Questions. "
        "Output only valid Markdown. No preamble."
    )


_AGENT_PLAYBOOK: dict[str, str] = {
    "discovery": (
        "Focus on identifying user problems and sizing opportunities using proxy sizing if needed. "
        "Output should be a Problem Brief with clear problem statements and prioritization rationale."
    ),
    "research": ("Focus on research plan + synthesis. Provide interview plan, key questions, and synthesis structure."),
    "market_competition": (
        "Focus on competitor comparison and positioning. Provide a competitor matrix and differentiation angles."
    ),
    "strategy_roadmap": ("Focus on prioritization and sequencing. Provide options, trade-offs, dependencies, and a recommendation."),
    "prd": (
        "Focus on writing a PRD for the FEATURE/INITIATIVE described by the user. "
        "Do NOT describe the agent itself. Do NOT write meta instructions."
    ),
    "ux_flow": ("Focus on user journeys, states, edge cases, empty states, and microcopy requirements."),
    "feasibility_architecture": ("Focus on system touchpoints, APIs, non-functional requirements, dependencies, and risks."),
    "execution_planning": ("Focus on milestones, critical path, owners/roles, RAID log, and delivery plan."),
    "analytics_experiment": ("Focus on KPIs, guardrails, event tracking spec, and experiment design."),
    "qa_test": ("Focus on test cases: happy path, edge cases, failure states, validation errors, and UAT checklist."),
    "launch": ("Focus on rollout plan, enablement, release notes, comms checklist, and rollback plan."),
    "post_launch_monitoring": ("Focus on monitoring plan, dashboards, alert thresholds, anomaly triage, and iteration plan."),
    "product_ops": ("Focus on backlog hygiene, taxonomy, triage rules, doc freshness, and operating cadence."),
    "stakeholder_alignment": ("Focus on role-based updates and decision memos with clear asks and trade-offs."),
    "monetization_packaging": ("Focus on value metric, packaging options, risks (cannibalization/churn), and experiments."),
    "trust_safety_policy": ("Focus on allowed/disallowed behaviors, refusal rules, escalation paths, and red-team test cases."),
}


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def build_user_prompt(agent_id: str, input_payload: Dict[str, Any], evidence_text: str = "") -> str:
    artifact_type = AGENT_TO_DEFAULT_ARTIFACT_TYPE.get(agent_id, "strategy_memo")
    goal = _s(input_payload.get("goal"))
    context = _s(input_payload.get("context"))
    constraints = _s(input_payload.get("constraints"))

    agent_instruction = _AGENT_PLAYBOOK.get(agent_id, "")

    evidence_block = ""
    if evidence_text.strip():
        evidence_block = f"""
Known Evidence (only use what is provided below; do not invent anything):
{evidence_text}

Evidence Rules:
- If you state something derived from evidence, prefix the bullet with: **[EVIDENCE]**
- If you state something that is an assumption, prefix it with: **[ASSUMPTION]**
- If you need data not present, list it under Open Questions.
""".strip()

    common_requirements = f"""
You must produce a **{artifact_type}** draft for the user's goal.

User goal:
{goal or "(not provided)"}

Context:
{context or "(not provided)"}

Constraints:
{constraints or "(not provided)"}

{evidence_block}

Rules:
- Use the goal/context/constraints explicitly in the draft (do not ignore them).
- No fake metrics, no fake baselines. If unknown, mark as unknown.
- End with: Assumptions and Open Questions.
- Output must be actionable (decisions, next actions).
""".strip()

    structure = _structure_for_artifact_type(artifact_type)

    return f"""
{common_requirements}

Agent focus:
{agent_instruction}

Required structure (use these headings in order):
{structure}
""".strip()


def _structure_for_artifact_type(artifact_type: str) -> str:
    # Keep headings stable for consistent downstream parsing later.
    if artifact_type == "prd":
        return """
# Summary
# Problem
# Users / Segments
# Success Metrics
# Scope (In Scope / Out of Scope)
# User Journey (Happy Path + Edge Cases)
# Requirements (Functional + Non-Functional)
# Risks
# Assumptions
# Open Questions
# Next Actions
""".strip()

    if artifact_type in ("problem_brief",):
        return """
# Summary
# Problem Statements
# Who is impacted (Segments)
# Evidence (what we know / unknown)
# Opportunity Sizing (proxy if needed)
# Recommended Focus
# Risks
# Assumptions
# Open Questions
# Next Actions
""".strip()

    if artifact_type in ("qa_suite",):
        return """
# Summary
# Test Scenarios (Happy Path)
# Edge Cases
# Validation & Error Cases
# Security / Abuse Cases (if relevant)
# UAT Checklist
# Assumptions
# Open Questions
# Next Actions
""".strip()

    if artifact_type in ("launch_plan",):
        return """
# Summary
# Launch Type & Cohort
# Rollout Plan (Flags / Phases)
# Enablement (Sales/Support)
# Release Notes Draft
# Risk & Rollback Plan
# Assumptions
# Open Questions
# Next Actions
""".strip()

    if artifact_type in ("experiment_plan", "tracking_spec"):
        return """
# Summary
# Primary KPI + Guardrails
# Hypothesis
# Experiment Design (A/B or Rollout)
# Tracking Plan (events/properties)
# Segments to Analyze
# Risks & Confounders
# Assumptions
# Open Questions
# Next Actions
""".strip()

    # Default generic memo
    return """
# Summary
# Context
# Proposed Approach
# Trade-offs
# Risks
# Assumptions
# Open Questions
# Next Actions
""".strip()


# -------------------------
# Custom agent prompt builder
# -------------------------
def _prompt_blocks(definition_json: Dict[str, Any]) -> List[Dict[str, str]]:
    pb = definition_json.get("prompt_blocks") or []
    if not isinstance(pb, list):
        return []
    out: List[Dict[str, str]] = []
    for x in pb:
        if not isinstance(x, dict):
            continue
        kind = str(x.get("kind") or "").strip().lower()
        text = str(x.get("text") or "").strip()
        if not kind or not text:
            continue
        out.append({"kind": kind, "text": text})
    return out


def build_user_prompt_custom(
    *,
    definition_json: Dict[str, Any],
    input_payload: Dict[str, Any],
    evidence_text: str,
    artifact_type: str,
    citations_block: str = "",
) -> str:
    goal = _s(input_payload.get("goal"))
    context = _s(input_payload.get("context"))
    constraints = _s(input_payload.get("constraints"))

    blocks = _prompt_blocks(definition_json)

    guardrails: List[str] = []
    for b in blocks:
        if b["kind"] in ("system", "guardrail", "instruction"):
            guardrails.append(f"- ({b['kind']}) {b['text']}")

    guardrail_block = ""
    if guardrails:
        guardrail_block = "Guardrails / Instructions:\n" + "\n".join(guardrails)

    structure = _structure_for_artifact_type(artifact_type)

    evidence_block = ""
    if evidence_text.strip():
        evidence_block = f"""
Known Evidence (ONLY use what is provided; do not invent anything):
{evidence_text}
""".strip()

    citation_rules = f"""
You MUST ground claims in the Evidence Pack below.

Citation rules (STRICT):
- Any factual claim, decision, requirement, risk, or number MUST include at least one inline citation like [1] or [2].
- Do NOT cluster citations only in one section. Distribute citations throughout the document.
- No more than 2 consecutive sentences may appear without a citation when evidence is available.
- Prefer 1–2 citations per paragraph where evidence applies.
- Do NOT invent sources. Only cite from the Evidence Pack IDs.
- If evidence is insufficient for a claim, write it under "## Unknowns / Assumptions" instead of guessing.

Output requirements (MANDATORY when Evidence Pack is provided):
1) Start with a clear H1 title.
2) Include a section "## Unknowns / Assumptions".
3) Include a section "## Sources" at the end with the exact [n] references.

Evidence Pack (cite as [n]):
{citations_block}
""".strip()

    return f"""
You must produce a **{artifact_type}** draft.

User goal:
{goal or "(not provided)"}

Context:
{context or "(not provided)"}

Constraints:
{constraints or "(not provided)"}

{guardrail_block}

{evidence_block}

{citation_rules}

Required structure (use these headings in order):
{structure}

Additional rules:
- Be explicit about Unknowns / Assumptions.
- End with Open Questions and Next Actions.
- Output only Markdown.
""".strip()