from __future__ import annotations

from typing import Any, Dict

from app.core.generator import AGENT_TO_DEFAULT_ARTIFACT_TYPE


def build_system_prompt() -> str:
    return (
        "You are a senior Product Manager assistant. "
        "Write crisp, structured, execution-ready markdown. "
        "Do not invent metrics or citations. "
        "If data is missing, explicitly list assumptions and open questions. "
        "Output only markdown."
    )


def build_user_prompt(agent_id: str, input_payload: Dict[str, Any]) -> str:
    artifact_type = AGENT_TO_DEFAULT_ARTIFACT_TYPE.get(agent_id, "strategy_memo")

    goal = str(input_payload.get("goal", "")).strip()
    context = str(input_payload.get("context", "")).strip()
    constraints = str(input_payload.get("constraints", "")).strip()

    return f"""
Generate a V1 draft for:

Agent: {agent_id}
Primary artifact type: {artifact_type}

Goal:
{goal or "(not provided)"}

Context:
{context or "(not provided)"}

Constraints:
{constraints or "(not provided)"}

Requirements:
- Output must be valid Markdown.
- Use headings and bullet points.
- Include sections: Summary, Problem, Users/Segments, Current Baseline (if unknown, say unknown), Proposed Solution, Scope (In/Out), Risks, Open Questions, Success Metrics, Next Actions.
- Avoid fake numbers. If you need numbers, ask for them under Open Questions.
"""