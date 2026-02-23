from __future__ import annotations

from typing import Any, Dict

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
    "research": (
        "Focus on research plan + synthesis. Provide interview plan, key questions, and synthesis structure."
    ),
    "market_competition": (
        "Focus on competitor comparison and positioning. Provide a competitor matrix and differentiation angles."
    ),
    "strategy_roadmap": (
        "Focus on prioritization and sequencing. Provide options, trade-offs, dependencies, and a recommendation."
    ),
    "prd": (
        "Focus on writing a PRD for the FEATURE/INITIATIVE described by the user. "
        "Do NOT describe the agent itself. Do NOT write meta instructions."
    ),
    "ux_flow": (
        "Focus on user journeys, states, edge cases, empty states, and microcopy requirements."
    ),
    "feasibility_architecture": (
        "Focus on system touchpoints, APIs, non-functional requirements, dependencies, and risks."
    ),
    "execution_planning": (
        "Focus on milestones, critical path, owners/roles, RAID log, and delivery plan."
    ),
    "analytics_experiment": (
        "Focus on KPIs, guardrails, event tracking spec, and experiment design."
    ),
    "qa_test": (
        "Focus on test cases: happy path, edge cases, failure states, validation errors, and UAT checklist."
    ),
    "launch": (
        "Focus on rollout plan, enablement, release notes, comms checklist, and rollback plan."
    ),
    "post_launch_monitoring": (
        "Focus on monitoring plan, dashboards, alert thresholds, anomaly triage, and iteration plan."
    ),
    "product_ops": (
        "Focus on backlog hygiene, taxonomy, triage rules, doc freshness, and operating cadence."
    ),
    "stakeholder_alignment": (
        "Focus on role-based updates and decision memos with clear asks and trade-offs."
    ),
    "monetization_packaging": (
        "Focus on value metric, packaging options, risks (cannibalization/churn), and experiments."
    ),
    "trust_safety_policy": (
        "Focus on allowed/disallowed behaviors, refusal rules, escalation paths, and red-team test cases."
    ),
}


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def build_user_prompt(agent_id: str, input_payload: Dict[str, Any]) -> str:
    artifact_type = AGENT_TO_DEFAULT_ARTIFACT_TYPE.get(agent_id, "strategy_memo")
    goal = _s(input_payload.get("goal"))
    context = _s(input_payload.get("context"))
    constraints = _s(input_payload.get("constraints"))

    agent_instruction = _AGENT_PLAYBOOK.get(agent_id, "")

    # Common skeleton required across all agents
    common_requirements = f"""
You must produce a **{artifact_type}** draft for the user's goal.

User goal:
{goal or "(not provided)"}

Context:
{context or "(not provided)"}

Constraints:
{constraints or "(not provided)"}

Rules:
- Use the goal/context/constraints explicitly in the draft (do not ignore them).
- No fake metrics, no fake baselines. If unknown, mark as unknown.
- End with: Assumptions and Open Questions.
- Output must be actionable (decisions, next actions).
"""

    # Artifact-type specific structure
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