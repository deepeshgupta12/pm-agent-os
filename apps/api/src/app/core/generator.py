from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from app.core.config import settings

AGENT_TO_DEFAULT_ARTIFACT_TYPE: dict[str, str] = {
    "discovery": "problem_brief",
    "research": "research_summary",
    "market_competition": "competitive_matrix",
    "strategy_roadmap": "strategy_memo",
    "prd": "prd",
    "ux_flow": "ux_spec",
    "feasibility_architecture": "tech_brief",
    "execution_planning": "delivery_plan",
    "analytics_experiment": "experiment_plan",
    "qa_test": "qa_suite",
    "launch": "launch_plan",
    "post_launch_monitoring": "health_report",
    "product_ops": "decision_log",
    "stakeholder_alignment": "strategy_memo",
    "monetization_packaging": "monetization_brief",
    "trust_safety_policy": "safety_spec",
}


def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _deterministic_template(agent_id: str, input_payload: Dict[str, Any]) -> Tuple[str, str, str]:
    artifact_type = AGENT_TO_DEFAULT_ARTIFACT_TYPE.get(agent_id, "strategy_memo")

    goal = _safe_str(input_payload.get("goal"))
    context = _safe_str(input_payload.get("context"))
    constraints = _safe_str(input_payload.get("constraints"))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    title = f"{artifact_type.replace('_', ' ').title()} — Draft"
    md = f"""# {title}

**Agent:** `{agent_id}`  
**Generated:** {now}

## Goal
{goal or "- (not provided)"}

## Context
{context or "- (not provided)"}

## Constraints
{constraints or "- (not provided)"}

## Draft Output (V0 Template)
This is a deterministic draft scaffold.
"""

    return artifact_type, title, md


def build_initial_artifact(agent_id: str, input_payload: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    Returns: (artifact_type, title, markdown_content)

    V1 behavior:
    - If LLM_ENABLED=true and OPENAI_API_KEY is present, generate content via OpenAI.
    - Otherwise fallback to deterministic template.
    """
    artifact_type = AGENT_TO_DEFAULT_ARTIFACT_TYPE.get(agent_id, "strategy_memo")
    title = f"{artifact_type.replace('_', ' ').title()} — Draft"

    if settings.LLM_ENABLED and settings.OPENAI_API_KEY:
        try:
            from app.core.prompts import build_system_prompt, build_user_prompt
            from app.core.llm_client import llm_generate_markdown

            system_prompt = build_system_prompt()
            user_prompt = build_user_prompt(agent_id=agent_id, input_payload=input_payload)
            md = llm_generate_markdown(system_prompt=system_prompt, user_prompt=user_prompt)

            # Ensure at least starts with a heading
            if not md.lstrip().startswith("#"):
                md = f"# {title}\n\n" + md

            return artifact_type, title, md
        except Exception:
            # Safety fallback: never fail run creation due to LLM issues
            return _deterministic_template(agent_id, input_payload)

    return _deterministic_template(agent_id, input_payload)


def build_run_summary(agent_id: str, artifact_type: str) -> str:
    if settings.LLM_ENABLED and settings.OPENAI_API_KEY:
        return f"Run completed. Generated initial draft artifact via LLM: {artifact_type}."
    return f"Run completed. Generated initial draft artifact: {artifact_type}."