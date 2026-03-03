# pm-agent-os — Product Ops OS (Runs, RAG, Pipelines, Approvals, Scheduling)

## 1) Problem statement

We wanted a Product Management Agent OS that can:

- Run agent-based runs (Discovery, Strategy, PRD, UX, etc.) with retrieval-grounded evidence (RAG).
- Provide a Run Console (RAG Console) where users can:
  - preview retrieval,
  - attach evidence,
  - regenerate artifacts grounded in evidence,
  - debug retrieval (RAG debug, batch scoping).
- Add a Pipeline workflow so users can run a multi-step sequence of agents (e.g., Discovery → Strategy → PRD) with:
  - step-level status + orchestration,
  - auto-attach previous step output as evidence,
  - optional auto-regeneration,
  - per-step retrieval metadata + deep-links into scoped RAG debug.
- Add governed write actions:
  - an Action Center where certain write operations are approval-gated,
  - multi-reviewer approvals with auditable decisions,
  - executors that materialize approved actions (e.g., decision logs; publish artifacts).
- Add run scheduling so teams can:
  - schedule weekly packs / daily monitoring,
  - run-now and run-due execution,
  - keep schedule run history.

In short: a pipeline runner for PM artifacts, grounded in evidence, with governed write actions and scheduling.

---

## 2) Solution overview

We implemented four core layers:

### A) Runs (single agent execution)
A Run represents one agent execution plus artifacts, evidence, logs, and a timeline.

Key concepts:
- Evidence is attached via retrieval (auto / preview attach / pipeline pre-retrieval).
- Artifacts are versioned; regeneration creates a new version.
- RAG Debug shows evidence/logs scoped to a retrieval batch.

### B) Pipelines (multi-step orchestration)
A Pipeline Run represents a sequence of steps (PipelineStep):
- Each step triggers a new Run (step.run_id) when executed.
- Each step can perform pre-retrieval, attach evidence, generate an artifact, and optionally auto-regenerate.
- The pipeline tracks step statuses, current step index, and failure state.

### C) Action Center (approval-gated actions)
An ActionItem is a governed action with:
- policy-defined creator permissions,
- policy-defined reviewer permissions (roles or explicit allow-list),
- multi-reviewer decisions (auditable),
- an executor that runs side-effects when an action reaches approved.

Implemented action types:
- decision_log_create: on approval, creates a new Run + Artifact (better audit trail).
- artifact_publish: on approval, finalizes the target artifact (moves to final) and writes executor audit fields back to the action payload.

### D) Scheduling (agent runs / pipeline runs)
A Schedule can run:
- agent_run (Run),
- pipeline_run (PipelineRun),
using cron or interval JSON (daily/weekly). It records executions as ScheduleRun entries.

---

## 3) Scope: versions shipped

### V0 (foundation)
- Base app scaffolding: FastAPI + Postgres + Web UI.
- Runs, artifacts, evidence, basic retrieval endpoints.

### V1 (retrieval + pipelines + RAG console)
- Retrieval refinements and ingestion primitives.
- RAG Console: retrieval preview, evidence attach, regenerate flows, RAG debug with batch scoping.
- Pipelines: multi-step orchestration, prev-artifact evidence, failure-state orchestration, step-level retrieval metadata and deep-links.

### V2 (approvals/workflows + scheduling + artifact studio collaboration)
- Action Center:
  - approvals policy stored per workspace (workspaces.approvals_json)
  - multi-reviewer decisions (action_item_decisions)
  - cancel path for queued actions
  - executor system for approved actions
- Approval-gated publish:
  - artifact submit-review and approve/reject (artifact_reviews)
  - request-publish creates ActionItem(type=artifact_publish)
  - approval triggers publish executor (finalizes artifact)
- Artifact Studio collaboration:
  - assignment UI + API
  - comments UI + API
  - mentions parsing via @email (stored as comment mentions)
- Scheduling:
  - schedules UI + API
  - schedule run history + run-now + run-due
  - weekly interval normalization (legacy days accepted; normalized to weekdays Mon=0..Sun=6)

---

## 4) Features shipped (what users can do)

### Runs — RAG Console
- View run overview (agent_id, status, output summary)
- View input payload and retrieval config
- Retrieval Panel:
  - preview retrieval results
  - select results and attach as evidence
  - regenerate with retrieval
- Evidence + Artifacts:
  - list + create evidence
  - create artifacts manually
  - regenerate artifact versions
  - export PDF / DOCX
- RAG Debug:
  - select batch scope
  - view retrieval_config + retrieval_log
  - inspect evidence scoped to batch

### Pipelines — Pipeline Run Page
- Step list with:
  - status badges (created/running/completed/failed)
  - step agent_id + run_id
  - latest artifact per step
  - prev artifact context attached status
  - auto-regenerated status
  - per-step retrieval meta (query, evidence count, batch id, kind)
- Execute controls:
  - Execute next step
  - Execute all remaining
- Deep-link into scoped RAG debug for each step:
  - /runs/{run_id}?ragOpen=1&batch_id={batchId}

### Action Center — approvals and governance
- Create action items (policy-gated by creator roles)
- Filter queue by status/type
- Approve/reject (policy-gated by reviewer roles or allow-list)
- Multi-reviewer counting:
  - any reject → rejected
  - approvals >= approvals_required → approved
- View decisions audit trail per action
- Cancel queued actions (admin or creator)
- Executors:
  - decision_log_create → creates new Run + Artifact; writes created_run_id/created_artifact_id into action payload
  - artifact_publish → finalizes artifact; writes publish audit fields into action payload

### Scheduling
- Create schedules (daily/weekly)
- Legacy UI support for weekly keys:
  - accepts interval_json.days with Mon=1..Sun=7 and normalizes to interval_json.weekdays Mon=0..Sun=6
- Run due schedules, run-now
- View schedule run history

### Artifact Studio collaboration
- Assignment (member/admin)
- Comments (member/admin)
- Mentions (store mentions for users in the same workspace)
- Viewer UX restrictions across mutation actions

---

## 5) Key API routes (current)

### Workspaces
- GET /workspaces
- POST /workspaces
- GET /workspaces/{id}
- GET /workspaces/{id}/my-role
- GET /workspaces/{id}/members

### Runs
- POST /workspaces/{workspace_id}/runs
- GET /workspaces/{workspace_id}/runs
- GET /runs/{run_id}
- GET /runs/{run_id}/timeline
- GET /runs/{run_id}/logs
- POST /runs/{run_id}/logs

### Artifacts
- GET /runs/{run_id}/artifacts
- POST /runs/{run_id}/artifacts
- GET /artifacts/{artifact_id}
- PUT /artifacts/{artifact_id}
- POST /artifacts/{artifact_id}/versions
- POST /artifacts/{artifact_id}/unpublish
- Exports:
  - GET /artifacts/{artifact_id}/export/pdf
  - GET /artifacts/{artifact_id}/export/docx
- Diff:
  - GET /artifacts/{artifact_id}/diff?other_id=...

### Artifact reviews (review gate)
- GET /artifacts/{artifact_id}/reviews
- POST /artifacts/{artifact_id}/submit-review
- POST /artifacts/{artifact_id}/approve
- POST /artifacts/{artifact_id}/reject

### Approval-gated publish
- POST /artifacts/{artifact_id}/request-publish
- Legacy direct publish (blocked when policy gates publish):
  - POST /artifacts/{artifact_id}/publish

### Artifact comments / mentions / assignment
- GET /artifacts/{artifact_id}/comments
- POST /artifacts/{artifact_id}/comments
- PATCH /artifacts/{artifact_id}/assign

### Retrieval
- GET /workspaces/{workspace_id}/retrieve?...

### Regeneration
- POST /runs/{run_id}/regenerate
- POST /runs/{run_id}/regenerate-with-retrieval

### RAG Debug
- GET /runs/{run_id}/rag-debug?batch_id=...

### Pipelines
- POST /workspaces/{workspace_id}/pipelines/templates
- POST /workspaces/{workspace_id}/pipelines/runs
- Alias endpoints:
  - GET /pipeline-runs/{pipeline_run_id}
  - POST /pipeline-runs/{pipeline_run_id}/execute-next
  - POST /pipeline-runs/{pipeline_run_id}/execute-all

### Action Center
- GET /workspaces/{workspace_id}/actions
- POST /workspaces/{workspace_id}/actions
- GET /actions/{action_id}
- GET /actions/{action_id}/decisions
- POST /actions/{action_id}/decide
- POST /actions/{action_id}/cancel
- PATCH /actions/{action_id}/assign

### Schedules
- POST /workspaces/{workspace_id}/schedules
- GET /workspaces/{workspace_id}/schedules
- GET /schedules/{schedule_id}
- PATCH /schedules/{schedule_id}
- POST /schedules/{schedule_id}/run-now
- POST /workspaces/{workspace_id}/schedules/run-due
- GET /schedules/{schedule_id}/runs

---

## 6) Data model essentials

### Workspace
- approvals_json stores approvals policy (per action type rules).

### ActionItem
- type, status, title, payload_json, target_ref
- approvals_required snapshot on creation
- decisions tracked in action_item_decisions

### Schedule / ScheduleRun
- Schedules: cron or interval_json, payload_json, next_run_at
- Runs: execution records with status + links (run_id, pipeline_run_id)

### Run
- input_payload includes optional:
  - _retrieval (last retrieval meta)
  - _pipeline (pipeline step meta)

### Evidence
- retrieval attaches:
  - meta.batch_id, meta.batch_kind
  - retrieval knobs, scores, rank, document titles

### Artifact
- versioned by (run_id, logical_key)
- statuses: draft | in_review | final
- supports assignment + comments + mentions

---

## 7) Core implementation notes (important behaviors)

### A) No evidence safe-mode
If retrieval runs but finds 0 evidence, we generate a draft that:
- explicitly says evidence is missing,
- lists next actions,
- avoids hallucination.

### B) Pipeline prev artifact as evidence
When executing step N (N>0), the latest artifact of step N-1 is attached as evidence:
- source_name="pipeline_prev_artifact"

### C) Failed-state orchestration (pipelines)
If any step throws:
- pipeline_step.status = failed
- pipeline_run.status = failed
Then execute-next / execute-all returns ok=false and does not proceed.

### D) Multi-reviewer approvals (actions)
- any reject → action status becomes rejected
- approvals >= approvals_required → action status becomes approved
- action_item_decisions is immutable audit history (1 decision per reviewer)
- explicit reviewer allow-list (if provided) becomes required reviewers:
  - approvals_required = len(allow_list) (min 1)

---

## 8) Testing: end-to-end bash scripts

Replace values if your local differs.

### 8.1 Auth sanity (cookies)
```bash
API="http://localhost:8010"
COOKIE_JAR="/tmp/admin.cookies"
EMAIL="guyshazam12@gmail.com"
PASSWORD='Masterchef!12'

rm -f "${COOKIE_JAR}"

curl -sS -i -c "${COOKIE_JAR}" -X POST "${API}/auth/login"   -H "Content-Type: application/json"   -d "{"email":"${EMAIL}","password":"${PASSWORD}"}" >/dev/null

curl -sS -i -b "${COOKIE_JAR}" "${API}/agents" | head -n 12
```

### 8.2 Scheduling smoke test (weekly legacy keys)
```bash
set -euo pipefail

API="http://localhost:8010"
COOKIE_JAR="/tmp/admin.cookies"
EMAIL="guyshazam12@gmail.com"
PASSWORD='Masterchef!12'
WS_ID="YOUR_WORKSPACE_ID"

rm -f "${COOKIE_JAR}"

curl -sS -i -c "${COOKIE_JAR}" -X POST "${API}/auth/login"   -H "Content-Type: application/json"   -d "{"email":"${EMAIL}","password":"${PASSWORD}"}" >/dev/null

curl -sS -f -b "${COOKIE_JAR}" -X POST "${API}/workspaces/${WS_ID}/schedules"   -H "Content-Type: application/json"   -d '{
    "name": "Legacy weekly schedule",
    "kind": "agent_run",
    "timezone": "UTC",
    "interval_json": { "mode": "weekly", "at": "09:00", "days": [1,3,5] },
    "payload_json": {
      "agent_id": "post_launch_monitoring",
      "input_payload": { "goal": "Weekly pack", "context": "", "constraints": "" },
      "retrieval": null
    },
    "enabled": true
  }' > /tmp/sched.json

SCHEDULE_ID="$(python -c "import json; print(json.load(open('/tmp/sched.json'))['id'])")"
echo "SCHEDULE_ID=${SCHEDULE_ID}"

curl -sS -f -b "${COOKIE_JAR}" "${API}/schedules/${SCHEDULE_ID}" | python -m json.tool | head -n 200
```

### 8.3 Action Center smoke test (decision_log_create executor)
```bash
set -euo pipefail

API="http://localhost:8010"
COOKIE_JAR="/tmp/admin.cookies"
EMAIL="guyshazam12@gmail.com"
PASSWORD='Masterchef!12'
WS_ID="YOUR_WORKSPACE_ID"

rm -f "${COOKIE_JAR}"
curl -sS -i -c "${COOKIE_JAR}" -X POST "${API}/auth/login"   -H "Content-Type: application/json"   -d "{"email":"${EMAIL}","password":"${PASSWORD}"}" >/dev/null

curl -sS -f -b "${COOKIE_JAR}" -X POST "${API}/workspaces/${WS_ID}/actions"   -H "Content-Type: application/json"   -d '{
    "type": "decision_log_create",
    "title": "Decision log: onboarding trade-offs",
    "payload_json": {
      "decision_title": "Onboarding trade-offs",
      "context": "We need to decide between speed vs completeness",
      "options": ["Option A", "Option B"],
      "recommendation": "Option A",
      "constraints": "No regression in activation"
    }
  }' > /tmp/action.json

ACTION_ID="$(python -c "import json; print(json.load(open('/tmp/action.json'))['id'])")"
echo "ACTION_ID=${ACTION_ID}"

curl -sS -f -b "${COOKIE_JAR}" -X POST "${API}/actions/${ACTION_ID}/decide"   -H "Content-Type: application/json"   -d '{"decision":"approved","comment":"Approved - proceed"}' > /tmp/action_after.json

python - <<'PY'
import json
d=json.load(open("/tmp/action_after.json"))
pj=d.get("payload_json") or {}
print("created_run_id:", pj.get("created_run_id"))
print("created_artifact_id:", pj.get("created_artifact_id"))
print("executor_error:", pj.get("executor_error"))
PY
```

### 8.4 Approval-gated publish smoke test (artifact_publish executor)
```bash
set -euo pipefail

API="http://localhost:8010"
COOKIE_JAR="/tmp/admin.cookies"
EMAIL="guyshazam12@gmail.com"
PASSWORD='Masterchef!12'
WS_ID="YOUR_WORKSPACE_ID"

rm -f "${COOKIE_JAR}"
curl -sS -i -c "${COOKIE_JAR}" -X POST "${API}/auth/login"   -H "Content-Type: application/json"   -d "{"email":"${EMAIL}","password":"${PASSWORD}"}" >/dev/null

curl -sS -f -b "${COOKIE_JAR}" -X POST "${API}/workspaces/${WS_ID}/runs"   -H "Content-Type: application/json"   -d '{
    "agent_id": "product_ops",
    "input_payload": { "goal": "Publish gating smoke", "context": "Testing approval-gated publish", "constraints": "" },
    "retrieval": null
  }' > /tmp/run.json

RUN_ID="$(python -c "import json; print(json.load(open('/tmp/run.json'))['id'])")"
curl -sS -f -b "${COOKIE_JAR}" "${API}/runs/${RUN_ID}/artifacts" > /tmp/run_artifacts.json
ART_ID="$(python - <<'PY'
import json
arts=json.load(open('/tmp/run_artifacts.json'))
print(arts[0]['id'])
PY
)"
echo "ART_ID=${ART_ID}"

curl -sS -f -b "${COOKIE_JAR}" -X POST "${API}/artifacts/${ART_ID}/submit-review"   -H "Content-Type: application/json"   -d '{"comment":"submit for review"}' >/dev/null

curl -sS -f -b "${COOKIE_JAR}" -X POST "${API}/artifacts/${ART_ID}/approve"   -H "Content-Type: application/json"   -d '{"comment":"approved"}' >/dev/null

curl -sS -f -b "${COOKIE_JAR}" -X POST "${API}/artifacts/${ART_ID}/request-publish"   -H "Content-Type: application/json"   -d '{"title":null,"comment":"publish request"}' > /tmp/publish_action.json

ACTION_ID="$(python -c "import json; print(json.load(open('/tmp/publish_action.json'))['action_id'])")"
echo "ACTION_ID=${ACTION_ID}"

curl -sS -f -b "${COOKIE_JAR}" -X POST "${API}/actions/${ACTION_ID}/decide"   -H "Content-Type: application/json"   -d '{"decision":"approved","comment":"approve publish"}' > /tmp/action_after.json

curl -sS -f -b "${COOKIE_JAR}" "${API}/artifacts/${ART_ID}" | python -m json.tool | head -n 40
```

---

## 9) Known build warnings

- Vite chunk size warning (>500kb) during build.
  - Not a functional issue.
  - Optional follow-up: code-split heavy pages via React.lazy().

---

## 10) Next: V3 (Customization + governance + enterprise) — not started

All pending:
- Custom Agent Builder v1 (no-code)
- Policy Center (allowed sources, retention, PII masking, internal-only toggles)
- Advanced RBAC (per connector / per action / per workspace rules)
- Audit exports (CSV/JSON/PDF) for runs/artifacts/evidence (beyond artifact export)
- Multi-workspace template libraries
- Warehouse connector read + webhook listeners
