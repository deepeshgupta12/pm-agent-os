from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Tuple

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


def build_initial_artifact(agent_id: str, input_payload: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    Returns: (artifact_type, title, markdown_content)
    Deterministic V0 template generation.
    """
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
This is a V0 deterministic draft scaffold. In later versions, this section will be generated with OpenAI 4.1 mini (grounded + citation-ready), and will optionally attach evidence.

### What I will produce next
- A structured `{artifact_type}` draft aligned to your goal
- Clear assumptions + open questions
- Next actions checklist
"""

    return artifact_type, title, md


def build_run_summary(agent_id: str, artifact_type: str) -> str:
    return f"Run completed. Generated initial draft artifact: {artifact_type}."