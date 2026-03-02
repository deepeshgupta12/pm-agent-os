# pm-agent-os — RAG + Pipelines 🚀

## 1) Problem statement 🧩

We wanted a **Product Management agent OS** that can:
- Run **agent-based “runs”** (Discovery, Strategy, PRD, UX, etc.) with **retrieval-grounded evidence** (RAG).
- Provide a **Run Console** where users can:
  - preview retrieval,
  - attach evidence,
  - regenerate artifacts grounded in evidence,
  - and debug retrieval (RAG debug, batch scoping).
- Add a higher-level **Pipeline** workflow so users can run a **multi-step sequence** of agents (e.g., Discovery → Strategy → PRD) with:
  - step-level status + orchestration,
  - auto-attach previous step output as evidence,
  - optional auto-regeneration,
  - and **per-step retrieval metadata** + **deep links into scoped RAG debug**.

In short: a **pipeline runner for PM artifacts**, grounded in evidence, with clean UX and robust failure handling. ✅

---

## 2) Solution overview 🧠✨

We implemented two core layers:

### A) Runs (single agent execution) ✅
A **Run** represents one agent execution + artifacts + evidence + logs + timeline.

Key concepts:
- **Evidence** is attached via retrieval (auto / preview attach / pipeline pre-retrieval).
- **Artifacts** are versioned and generated; regeneration creates a new version.
- **RAG Debug** shows evidence/logs scoped to a retrieval “batch”.

### B) Pipelines (multi-step orchestration) ✅
A **Pipeline Run** represents a sequence of steps (PipelineStep):
- Each step triggers a new Run (`step.run_id`) when executed.
- Each step can perform **pre-retrieval**, attach evidence, generate an artifact, and optionally auto-regenerate.
- The pipeline tracks:
  - step statuses,
  - current step index,
  - and failure state.

---

## 3) Scope: versions shipped 🧱

### V0 (foundation) ✅
- Base app scaffolding: FastAPI + Postgres + Web UI.
- Runs, artifacts, evidence, basic retrieval endpoints.

### V1 (retrieval “real” + connectors + hardening) ✅
- Retrieval refinements and ingestion primitives.
- Hardening: pagination/backoff, timestamps, improved retrieval metadata.
- UI improvements: run console features and exports.

### V2 (Run Console becomes RAG Console) ✅
Key milestones:
- **V2.2**: retrieval preview panel + regenerate-with-retrieval flow
- **V2.3**: batch-scoped rag-debug (`batch_id` param + batches index) + UI selector
- **V2.4**: attach retrieval preview items as evidence (`batch_kind=preview_attach`)
- **V2.5**: embeddings automation + on-demand embeddings runner
- **V2.6**: test harness improvements + export security + pytests
- **V2.7**: workspace role surfaced in UI (viewer restrictions)

### V3 (Pipelines) ✅
#### V3.0 — Pipeline step-level retrieval + evidence batch scoping ✅
- Step execution creates a run that:
  - runs pre-retrieval,
  - attaches evidence with a **batch_id** + batch_kind,
  - writes `_retrieval` into run input_payload,
  - generates artifact (or “no evidence” safe draft).

#### V3.1 — Pipeline run UI + alias routes + failed-state orchestration ✅
- Alias endpoints:
  - `GET /pipeline-runs/{id}`
  - `POST /pipeline-runs/{id}/execute-next`
  - `POST /pipeline-runs/{id}/execute-all`
- Failure orchestration:
  - if a step fails → step becomes `failed`, pipeline_run becomes `failed`,
  - further execute-next calls return `ok=false` and does not proceed.

#### V3.2 — Pipeline Run Page UI: per-step retrieval meta + scoped RAG deep-link ✅
- Backend extends PipelineStepOut with retrieval fields:
  - `retrieval_enabled`
  - `retrieval_query`
  - `retrieval_evidence_count`
  - `retrieval_batch_id`
  - `retrieval_batch_kind`
- Pipeline Run UI shows the above per step and provides direct deep-link:
  - `/runs/{run_id}?ragOpen=1&batch_id={batchId}`
- RunDetailPage supports deep-link opening RAG debug panel with selected batch.

---

## 4) Features shipped ✅ (what users can do)

### Runs — “RAG Console” 🧪
- View run overview (agent_id, status, output summary)
- View input payload and retrieval config
- Retrieval Panel:
  - preview retrieval results 🔍
  - select results and attach as evidence 📌
  - regenerate with retrieval 🔁
- Evidence + Artifacts:
  - list + create evidence
  - create artifacts manually
  - regenerate artifact versions
  - export PDF / DOCX 📄
- RAG Debug:
  - select batch scope,
  - view retrieval_config + retrieval_log,
  - inspect evidence scoped to batch 🧾

### Pipelines — “Pipeline Run Page” 🧭
- Step list with:
  - status badges (created/running/completed/failed)
  - step agent_id + run_id
  - latest artifact per step
  - prev artifact context attached status
  - auto-regenerated status
  - per-step retrieval meta (query, evidence count, batch id, kind)
- Execute controls:
  - “Execute next step”
  - “Execute all remaining”
- Deep-link into scoped RAG debug for each step:
  - “Open RAG Debug (scoped)” 🧠🔎

---

## 5) Key API routes (current) 🌐

### Pipelines
- Create template:
  - `POST /workspaces/{workspace_id}/pipelines/templates`
- Start pipeline run:
  - `POST /workspaces/{workspace_id}/pipelines/runs`
- Fetch pipeline run:
  - `GET /pipeline-runs/{pipeline_run_id}`  ✅ alias
- Execute next step:
  - `POST /pipeline-runs/{pipeline_run_id}/execute-next` ✅ alias
- Execute all steps:
  - `POST /pipeline-runs/{pipeline_run_id}/execute-all` ✅ alias

### Runs
- Fetch run:
  - `GET /runs/{run_id}`
- Run artifacts:
  - `GET /runs/{run_id}/artifacts`
  - `POST /runs/{run_id}/artifacts`
- Run evidence:
  - `GET /runs/{run_id}/evidence`
  - `POST /runs/{run_id}/evidence`
  - `POST /runs/{run_id}/evidence/auto`
  - `POST /runs/{run_id}/evidence/attach-preview`
- Retrieval:
  - `GET /workspaces/{workspace_id}/retrieve?...`
- Regeneration:
  - `POST /runs/{run_id}/regenerate`
  - `POST /runs/{run_id}/regenerate-with-retrieval`
- RAG Debug:
  - `GET /runs/{run_id}/rag-debug?batch_id=...`

---

## 6) Data model essentials 🗄️

### PipelineTemplate
- Stores `definition_json` including:
  - steps array: `{ name, agent_id, retrieval overrides }`
  - `auto_regenerate_with_evidence`

### PipelineRun
- Tracks:
  - status: created/running/completed/failed
  - current_step_index
  - input_payload

### PipelineStep
- Tracks:
  - step_index, step_name, agent_id
  - status
  - run_id (linked run if executed)
  - started_at, completed_at

### Run
- Tracks:
  - agent_id
  - status
  - input_payload (includes `_pipeline` and `_retrieval`)

### Evidence
- Attached to a run; retrieval attaches:
  - `meta.batch_id` + `meta.batch_kind`
  - retrieval knobs (query, k, alpha, source_types, timeframe, min_score, overfetch, rerank)

---

## 7) Core implementation notes (important behaviors) 🧠

### A) “No evidence” safe-mode ✅
If retrieval runs but finds **0 evidence**, we generate a draft that:
- explicitly says evidence is missing,
- lists next actions,
- avoids hallucination.

### B) Pipeline prev artifact as evidence ✅
When executing step N (N>0), the latest artifact of step N-1 is attached as evidence:
- `source_name="pipeline_prev_artifact"`
- enables continuity across steps.

### C) Failed-state orchestration ✅
If any step throws, we set:
- `pipeline_step.status = failed`
- `pipeline_run.status = failed`
Then:
- subsequent execute-next / execute-all returns `ok=false` and does not proceed.

---

## 8) Testing: end-to-end bash scripts ✅🧪

> Replace values if your local differs.

### 8.1 Auth sanity (cookies) 🔐
```bash
API="http://localhost:8010"
COOKIE_JAR="/tmp/admin.cookies"
EMAIL="guyshazam12@gmail.com"
PASSWORD='Masterchef!12'

rm -f "${COOKIE_JAR}"

curl -s -i -c "${COOKIE_JAR}" -X POST "${API}/auth/login"   -H "Content-Type: application/json"   -d "{"email":"${EMAIL}","password":"${PASSWORD}"}" > /dev/null

# sanity endpoint that exists
curl -s -i -b "${COOKIE_JAR}" "${API}/agents" | head -n 12
```

### 8.2 V3.2 smoke test: pipeline step retrieval fields ✅
```bash
set -e

API="http://localhost:8010"
COOKIE_JAR="/tmp/admin.cookies"

WS_ID="184b715a-9cdf-48ed-b6c5-6f1559e27a0d"

# create template
GOOD_TPL_JSON='{
  "name": "SMOKETEST v3.2: discovery -> prd",
  "description": "Validate PipelineStepOut retrieval fields",
  "definition_json": {
    "version": "v1",
    "auto_regenerate_with_evidence": true,
    "steps": [
      { "name": "Discovery", "agent_id": "discovery" },
      { "name": "PRD", "agent_id": "prd" }
    ]
  }
}'

tpl_resp="$(curl -s -b "${COOKIE_JAR}" -X POST "${API}/workspaces/${WS_ID}/pipelines/templates"   -H "Content-Type: application/json" -d "${GOOD_TPL_JSON}")"

echo "$tpl_resp" | python -m json.tool
TEMPLATE_ID="$(echo "$tpl_resp" | python -c "import sys,json; d=json.load(sys.stdin); print(d['id'])")"
echo "TEMPLATE_ID=${TEMPLATE_ID}"

# create run
run_resp="$(curl -s -b "${COOKIE_JAR}" -X POST "${API}/workspaces/${WS_ID}/pipelines/runs"   -H "Content-Type: application/json"   -d "{
    "template_id": "${TEMPLATE_ID}",
    "input_payload": {
      "goal": "Save search preferences",
      "context": "Web",
      "constraints": "",
      "timeframe": {"preset":"30d"},
      "sources_selected": ["docs"]
    }
  }")"

echo "$run_resp" | python -m json.tool
PIPELINE_RUN_ID="$(echo "$run_resp" | python -c "import sys,json; d=json.load(sys.stdin); print(d['id'])")"
echo "PIPELINE_RUN_ID=${PIPELINE_RUN_ID}"

# execute step 0
curl -s -b "${COOKIE_JAR}" -X POST "${API}/pipeline-runs/${PIPELINE_RUN_ID}/execute-next"   -H "Content-Type: application/json" -d '{}' | python -m json.tool

# fetch pipeline run and verify retrieval_* fields are filled for step 0
curl -s -b "${COOKIE_JAR}" "${API}/pipeline-runs/${PIPELINE_RUN_ID}" | python -m json.tool
```

### 8.3 Forced failure orchestration test ✅💥
```bash
set -e

API="http://localhost:8010"
COOKIE_JAR="/tmp/admin.cookies"

WS_ID="184b715a-9cdf-48ed-b6c5-6f1559e27a0d"
DB_URL="postgresql://pm_agent_os_user:pm_agent_os_password@localhost:5434/pm_agent_os"

GOOD_TPL_JSON='{
  "name": "FAILTEST step0 invalid agent",
  "description": "Create valid then corrupt step0 agent_id in DB",
  "definition_json": {
    "version": "v1",
    "auto_regenerate_with_evidence": true,
    "steps": [
      { "name": "Discovery", "agent_id": "discovery" },
      { "name": "PRD", "agent_id": "prd" }
    ]
  }
}'

tpl_resp="$(curl -s -b "${COOKIE_JAR}" -X POST "${API}/workspaces/${WS_ID}/pipelines/templates"   -H "Content-Type: application/json" -d "${GOOD_TPL_JSON}")"
TEMPLATE_ID="$(echo "$tpl_resp" | python -c "import sys,json; d=json.load(sys.stdin); print(d['id'])")"
echo "TEMPLATE_ID=${TEMPLATE_ID}"

run_resp="$(curl -s -b "${COOKIE_JAR}" -X POST "${API}/workspaces/${WS_ID}/pipelines/runs"   -H "Content-Type: application/json"   -d "{
    "template_id": "${TEMPLATE_ID}",
    "input_payload": {"goal":"failtest","context":"Web","constraints":"","timeframe":{"preset":"30d"},"sources_selected":["docs"]}
  }")"
PIPELINE_RUN_ID="$(echo "$run_resp" | python -c "import sys,json; d=json.load(sys.stdin); print(d['id'])")"
echo "PIPELINE_RUN_ID=${PIPELINE_RUN_ID}"

# corrupt step0 agent_id
psql "${DB_URL}" -c "UPDATE pipeline_steps SET agent_id='bad_agent'
 WHERE pipeline_run_id='${PIPELINE_RUN_ID}' AND step_index=0;"

# execute-next should fail the pipeline
curl -s -b "${COOKIE_JAR}" -X POST "${API}/pipeline-runs/${PIPELINE_RUN_ID}/execute-next"   -H "Content-Type: application/json" -d '{}' | python -m json.tool

# execute-next again should return ok=false and not proceed
curl -s -b "${COOKIE_JAR}" -X POST "${API}/pipeline-runs/${PIPELINE_RUN_ID}/execute-next"   -H "Content-Type: application/json" -d '{}' | python -m json.tool

# confirm DB
psql "${DB_URL}" -c "SELECT step_index, agent_id, status, run_id, started_at, completed_at
 FROM pipeline_steps WHERE pipeline_run_id='${PIPELINE_RUN_ID}'
 ORDER BY step_index;"

# cleanup
psql "${DB_URL}" -c "DELETE FROM pipeline_steps WHERE pipeline_run_id='${PIPELINE_RUN_ID}';"
psql "${DB_URL}" -c "DELETE FROM pipeline_runs WHERE id='${PIPELINE_RUN_ID}';"
psql "${DB_URL}" -c "DELETE FROM pipeline_templates WHERE id='${TEMPLATE_ID}';"
```

---

## 9) Git workflow (what we did) 🧑‍💻✅

### Consolidate all feature work into `main`
We:
- rebased feature branch on `origin/main`
- fast-forward merged into main
- pushed main
- deleted feature branches (remote + local)

Typical commands:
```bash
git fetch --prune origin

# feature branch rebase
git checkout feat/v2-rag-ux
git rebase origin/main
git push --force-with-lease origin feat/v2-rag-ux

# merge into main
git checkout main
git pull origin main
git merge --ff-only feat/v2-rag-ux
git push origin main

# delete branches
git branch -d feat/v2-rag-ux
git push origin --delete feat/v2-rag-ux
```

### Current repo state ✅
- Only `main` remains locally + on origin:
  - `git branch`
  - `git branch -r`

---

## 10) Security + hygiene 🛡️

### npm audit fix ✅
We ran:
```bash
npm audit
npm audit fix
```
Resolved:
- minimatch ReDoS advisory (high) ✅

Committed:
- `apps/web/package-lock.json` changes

---

## 11) UX notes (V3.2 outcome) 🧭✨

### Pipeline Run Page
Each step now shows:
- retrieval query
- evidence count
- batch id + batch kind
- button: “Open RAG Debug (scoped)”

### Run Page deep-link behavior
Opening:
```
/runs/{run_id}?ragOpen=1&batch_id={batchId}
```
will:
- auto-open the RAG Debug panel
- auto-select the given batch_id
- load scoped evidence/logs

---

## 12) Quick “mental model” of the system 🧠

- A **Pipeline** orchestrates multiple **Runs**.
- Each Pipeline step → creates a Run, attaches evidence, generates artifact.
- Retrieval evidence is grouped into **batches**, enabling scoped debugging.
- UI supports navigating from pipeline step → run console → scoped rag debug.

---

## 13) Known warnings (safe to ignore for now) ⚠️
- Vite chunk size warning (>500kb) during build.
  - Not a functional issue.
  - We can later code-split heavy pages via `React.lazy()` if needed.

---

## 14) What’s next (optional backlog) 🧾
Ideas (only if/when needed):
- Pipeline “retry failed step” support
- Pipeline step manual override / rerun
- Better retrieval summary (top sources, avg score, etc.)
- Performance: avoid N+1 by providing richer step metadata in pipeline response
- Code-splitting to reduce bundle size

---

✅ **Status: V3.2 shipped end-to-end**  
Pipelines show per-step retrieval batch + deep-link into scoped RAG debug, and the run page respects that deep-link.
