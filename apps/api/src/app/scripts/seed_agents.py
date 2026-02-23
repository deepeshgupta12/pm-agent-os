from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.db.models import AgentDefinition


AGENTS = [
    ("discovery", "Discovery", "Identify and size problems from signals, and propose top opportunities."),
    ("research", "Research", "Create research plans, synthesize qualitative insights, and produce research summaries."),
    ("market_competition", "Market & Competition", "Competitive scan, comparison matrix, and positioning options."),
    ("strategy_roadmap", "Strategy & Roadmap", "Prioritization, sequencing, trade-offs, and roadmap proposal."),
    ("prd", "PRD", "Generate structured PRD with scope, acceptance criteria, and measurement plan."),
    ("ux_flow", "UX Flow", "Define user journeys, states, empty states, and microcopy requirements."),
    ("feasibility_architecture", "Feasibility & Architecture", "System touchpoints, API contracts, NFRs, risks."),
    ("execution_planning", "Execution Planning", "Milestones, owners, dependencies, and RAID log."),
    ("analytics_experiment", "Analytics & Experiment", "KPIs, events spec, experiment design, guardrails."),
    ("qa_test", "QA & Test", "Test cases across happy/edge/failure paths + UAT checklist."),
    ("launch", "Launch", "Rollout strategy, runbook, enablement, and comms drafts."),
    ("post_launch_monitoring", "Post-launch Monitoring", "Launch health reporting, anomaly detection plan, next actions."),
    ("product_ops", "Product Ops", "Backlog hygiene, taxonomy, docs freshness, operational cadence."),
    ("stakeholder_alignment", "Stakeholder Alignment", "Role-based summaries and decision memos."),
    ("monetization_packaging", "Monetization & Packaging", "Pricing/packaging hypotheses and monetization tests."),
    ("trust_safety_policy", "Trust/Safety/Policy", "Guardrails, refusal behaviors, PII handling, red-team tests."),
]


DEFAULT_ARTIFACT_TYPES = [
    "problem_brief",
    "research_summary",
    "competitive_matrix",
    "strategy_memo",
    "prd",
    "ux_spec",
    "tech_brief",
    "delivery_plan",
    "tracking_spec",
    "experiment_plan",
    "qa_suite",
    "launch_plan",
    "health_report",
    "decision_log",
    "monetization_brief",
    "safety_spec",
]


def seed() -> None:
    db: Session = SessionLocal()
    try:
        existing = {a.id for a in db.execute(select(AgentDefinition)).scalars().all()}

        created = 0
        for agent_id, name, desc in AGENTS:
            if agent_id in existing:
                continue

            a = AgentDefinition(
                id=agent_id,
                name=name,
                description=desc,
                version="v0",
                input_schema={
                    "type": "object",
                    "properties": {
                        "goal": {"type": "string"},
                        "context": {"type": "string"},
                        "constraints": {"type": "string"},
                    },
                    "required": [],
                },
                output_artifact_types=DEFAULT_ARTIFACT_TYPES,
            )
            db.add(a)
            created += 1

        db.commit()
        print(f"Seed complete. Created {created} agents.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()