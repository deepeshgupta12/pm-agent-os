# PM Agent OS

**An AI-powered Product Management Operating System.**

PM Agent OS is a full-stack platform where specialised AI agents write product documents grounded in your team's actual evidence — PRDs, strategy memos, problem briefs, launch plans, and more. Agents can be chained into multi-step pipelines. Every artifact goes through a review and approval workflow before publishing. A Policy Center enforces governance on what knowledge sources agents can use, with PII masking and an immutable audit log of every decision the system makes.

> Built with FastAPI · PostgreSQL + pgvector · React 19 · TypeScript · OpenAI

---

## Screenshots

> *(Screenshots coming soon — replace this section with product screenshots)*

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [1 — Clone the repository](#1--clone-the-repository)
  - [2 — Configure environment](#2--configure-environment)
  - [3 — Start PostgreSQL](#3--start-postgresql)
  - [4 — Run database migrations](#4--run-database-migrations)
  - [5 — Seed agents and pipelines](#5--seed-agents-and-pipelines)
  - [6 — Start the API](#6--start-the-api)
  - [7 — Start the frontend](#7--start-the-frontend)
- [Environment Variables](#environment-variables)
- [The 16 Built-In Agents](#the-16-built-in-agents)
- [Pipeline Templates](#pipeline-templates)
- [API Reference](#api-reference)
- [Guided Mode](#guided-mode)
- [Governance & Policy](#governance--policy)
- [Agent Builder](#agent-builder)
- [Contributing](#contributing)
- [Author](#author)

---

## Features

- **16 built-in AI agents** covering the full PM lifecycle — Discovery, Research, Market & Competition, Strategy, PRD, UX Flow, Feasibility, Execution Planning, Analytics & Experiment, QA, Launch, Post-launch Monitoring, Product Ops, Stakeholder Alignment, Monetization, and Trust & Safety.
- **Hybrid RAG retrieval** — every artifact is grounded in evidence retrieved from your workspace's ingested documents via a combined FTS + vector search (`score_fts`, `score_vec`, `score_hybrid`), with a configurable `alpha` blend and an optional token-overlap rerank pass.
- **RAG Console & Debug** — inspect retrieval batches, view per-evidence scores, deep-link into any batch's debug panel, and regenerate artifacts with updated evidence.
- **4 canonical pipeline templates** — chain agents end-to-end (Discovery → Strategy → PRD, PRD → UX → Feasibility, Analytics → QA → Launch, Launch → Monitoring → Stakeholders). Each step automatically passes its artifact as evidence to the next step.
- **Artifact versioning** — every regeneration creates a new version. Compare any two versions via unified diff. Nothing is deleted.
- **Review workflow** — `draft` → `in_review` → `final`. Artifacts can be submitted for review, approved or rejected with comments, and published directly or via the Action Center.
- **Action Center** — governance-gated write actions (`decision_log_create`, `artifact_publish`, `docs_publish`) with configurable multi-reviewer approval policies. Execution is idempotent.
- **Governance audit log** — every RBAC check and policy check writes an immutable `GovernanceEvent` row. Export as CSV or JSON.
- **Policy Center** — configure allowed source types, retention days, PII masking (write-time, export-time, or both), and the internal-only toggle per workspace.
- **RBAC** — three roles (`admin`, `member`, `viewer`) with per-module, per-connector-type, and per-action-type override support.
- **Schedules** — recurring `agent_run` or `pipeline_run` tasks with daily/weekly cadence, timezone-aware execution, run-now, and per-schedule execution history.
- **Connectors** — ingest documents from GitHub, Google Docs, or manual upload. Every ingestion is tracked as an `IngestionJob` with status, stats, and error detail.
- **Agent Builder** — create custom agents with versioned definitions, configurable prompt blocks (`system`, `guardrail`, `instruction`), and retrieval knob overrides. Preview prompts before running.
- **Citation Pack** — custom agents enforce inline `[n]` citations in every generated artifact, with a deduplicated Sources section.
- **Guided Mode** — a 5-step happy-path UI for new users: Create Run → Review Output → Request Publish → Approve + Publish → Schedule.
- **Artifact collaboration** — comments with `@mention` parsing, assignment, and a `ArtifactCommentMention` audit record per mentioned user.
- **Export** — PDF and DOCX export for any artifact. Full workspace data export as JSON and CSV across runs, artifacts, evidence, action items, and governance events.

---

## Architecture

```
pm-agent-os/
├── apps/
│   ├── api/                   # FastAPI backend (Python 3.11+)
│   │   ├── src/app/
│   │   │   ├── api/           # Route handlers (runs, pipelines, artifacts, actions, schedules, ...)
│   │   │   ├── core/          # Generator, prompts, retrieval, citations, governance, LLM client
│   │   │   ├── db/            # SQLAlchemy models, retrieval models, session
│   │   │   ├── schemas/       # Pydantic request/response schemas
│   │   │   └── scripts/       # Seed scripts (agents, pipelines)
│   │   └── alembic/           # Database migrations
│   └── web/                   # React 19 + TypeScript frontend (Vite)
│       └── src/
│           ├── pages/         # 25 page components
│           ├── components/    # Glass design system (GlassPage, GlassCard, ...)
│           ├── types.ts        # All API response types
│           └── apiClient.ts    # Typed fetch wrapper
└── infra/
    └── postgres/
        └── docker-compose.yml # pgvector/pgvector:pg16
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| API Framework | FastAPI 0.115 |
| ORM | SQLAlchemy 2.0 (Mapped columns) |
| Database | PostgreSQL 16 + pgvector |
| Migrations | Alembic 1.13 |
| LLM | OpenAI `gpt-4.1-mini` |
| Embeddings | OpenAI `text-embedding-3-small` (1536 dim) |
| Auth | JWT (python-jose) + bcrypt, access token 15 min + refresh token 14 days |
| PDF Export | reportlab 4.2 |
| DOCX Export | python-docx 1.2 |
| External APIs | httpx (GitHub, Google Docs) |
| Frontend | React 19 + TypeScript 5.9 |
| Build Tool | Vite |
| Router | React Router v7 |
| UI Library | Mantine UI 8.3 + Emotion |
| Markdown | react-markdown + remark-gfm |
| Timezone | Python `zoneinfo` (stdlib) |

---

## Getting Started

### Prerequisites

- Python 3.11 or higher
- Node.js 18 or higher
- Docker and Docker Compose (for PostgreSQL)
- An OpenAI API key *(optional — the system works without one using deterministic fallback)*

---

### 1 — Clone the repository

```bash
git clone https://github.com/deepeshgupta12/pm-agent-os.git
cd pm-agent-os
```

---

### 2 — Configure environment

Copy the example environment file and fill in your values:

```bash
cp .env.example .env
```

At minimum, set `JWT_SECRET` to a strong random string. Set `LLM_ENABLED=true` and add your `OPENAI_API_KEY` to enable live LLM generation. See [Environment Variables](#environment-variables) for the full list.

---

### 3 — Start PostgreSQL

The database uses the `pgvector/pgvector:pg16` image which ships with the `pgvector` extension built in.

```bash
cd infra/postgres
docker compose up -d
cd ../..
```

PostgreSQL will be available at `localhost:5434`.

---

### 4 — Run database migrations

```bash
cd apps/api
pip install -r requirements.txt
alembic upgrade head
cd ../..
```

---

### 5 — Seed agents and pipelines

Seed the 16 built-in agent definitions and the 4 canonical pipeline templates:

```bash
cd apps/api
python -m app.scripts.seed_agents
python -m app.scripts.seed_pipelines
cd ../..
```

---

### 6 — Start the API

```bash
cd apps/api
uvicorn app.main:app --host 0.0.0.0 --port 8010 --reload
```

The API will be available at `http://localhost:8010`.
Interactive API docs (Swagger UI) are at `http://localhost:8010/docs`.

---

### 7 — Start the frontend

```bash
cd apps/web
npm install
npm run dev
```

The frontend will be available at `http://localhost:5174`.

---

## Environment Variables

All variables are loaded from a `.env` file at the repository root via `pydantic-settings`.

| Variable | Default | Description |
|---|---|---|
| `ENV` | `dev` | Environment name |
| `API_HOST` | `0.0.0.0` | API bind host |
| `API_PORT` | `8010` | API port |
| `CORS_ORIGINS` | `http://localhost:5174` | Comma-separated allowed CORS origins |
| `JWT_SECRET` | `change_me` | **Change this.** Secret key for JWT signing |
| `JWT_ALG` | `HS256` | JWT signing algorithm |
| `ACCESS_EXPIRES_MINUTES` | `15` | Access token TTL (minutes) |
| `REFRESH_EXPIRES_DAYS` | `14` | Refresh token TTL (days) |
| `DATABASE_URL` | `postgresql+psycopg://pm_agent_os_user:pm_agent_os_password@localhost:5434/pm_agent_os` | PostgreSQL connection string |
| `LLM_ENABLED` | `false` | Set to `true` to enable OpenAI generation |
| `OPENAI_API_KEY` | *(empty)* | Your OpenAI API key |
| `OPENAI_MODEL` | `gpt-4.1-mini` | OpenAI chat model |
| `OPENAI_TIMEOUT_SECONDS` | `45` | LLM request timeout |
| `EMBEDDINGS_MODEL` | `text-embedding-3-small` | OpenAI embeddings model |
| `EMBEDDINGS_DIM` | `1536` | Embedding dimensions |
| `CHUNK_SIZE_CHARS` | `1100` | Document chunk size (characters) |
| `CHUNK_OVERLAP_CHARS` | `150` | Chunk overlap (characters) |
| `GITHUB_TOKEN` | *(empty)* | GitHub PAT for repository connector (read-only) |
| `GOOGLE_CLIENT_ID` | *(empty)* | Google OAuth client ID (Google Docs connector) |
| `GOOGLE_CLIENT_SECRET` | *(empty)* | Google OAuth client secret |
| `GOOGLE_REFRESH_TOKEN` | *(empty)* | Google OAuth refresh token |
| `COOKIE_SECURE` | `false` | Set to `true` in production (HTTPS) |
| `COOKIE_SAMESITE` | `lax` | Cookie SameSite policy (`lax` / `strict` / `none`) |

---

## The 16 Built-In Agents

| Agent ID | Name | Output Artifact |
|---|---|---|
| `discovery` | Discovery | `problem_brief` |
| `research` | Research | `research_summary` |
| `market_competition` | Market & Competition | `competitive_matrix` |
| `strategy_roadmap` | Strategy & Roadmap | `strategy_memo` |
| `prd` | PRD | `prd` |
| `ux_flow` | UX Flow | `ux_spec` |
| `feasibility_architecture` | Feasibility & Architecture | `tech_brief` |
| `execution_planning` | Execution Planning | `delivery_plan` |
| `analytics_experiment` | Analytics & Experiment | `experiment_plan` |
| `qa_test` | QA & Test | `qa_suite` |
| `launch` | Launch | `launch_plan` |
| `post_launch_monitoring` | Post-launch Monitoring | `health_report` |
| `product_ops` | Product Ops | `decision_log` |
| `stakeholder_alignment` | Stakeholder Alignment | `strategy_memo` |
| `monetization_packaging` | Monetization & Packaging | `monetization_brief` |
| `trust_safety_policy` | Trust / Safety / Policy | `safety_spec` |

Each agent has a focused playbook injected into the LLM prompt. For example, the `prd` agent is told to write a PRD for the feature described by the user and explicitly instructed not to describe the agent itself or write meta instructions. Every artifact type has a required structure (fixed headings) that keeps output consistent and parseable across runs.

---

## Pipeline Templates

Four canonical templates ship out of the box. Seed them into a workspace with `POST /workspaces/{workspace_id}/pipeline-templates/seed`.

| Key | Steps | Use case |
|---|---|---|
| `discovery_strategy_prd` | Discovery → Strategy & Roadmap → PRD | End-to-end early phase flow |
| `prd_ux_feasibility` | PRD → UX Flow → Feasibility & Architecture | Spec to design to technical review |
| `analytics_qa_launch` | Analytics & Experiment → QA & Test → Launch | Operationalisation flow |
| `launch_monitoring_stakeholder` | Launch → Post-launch Monitoring → Stakeholder Alignment | Post-release loop |

Each pipeline step automatically attaches the previous step's artifact as evidence (`source_name = "pipeline_prev_artifact"`) and injects a `## Confidence` section into the generated artifact indicating how many evidence snippets were available.

---

## API Reference

Full interactive docs available at `http://localhost:8010/docs` once the API is running. Key route groups:

**Auth**
```
POST /auth/register
POST /auth/login
POST /auth/logout
POST /auth/refresh
```

**Workspaces & Members**
```
POST   /workspaces
GET    /workspaces
GET    /workspaces/{workspace_id}
GET    /workspaces/{workspace_id}/my-role
POST   /workspaces/{workspace_id}/members
PATCH  /workspaces/{workspace_id}/members/{user_id}
DELETE /workspaces/{workspace_id}/members/{user_id}
```

**Agents**
```
GET /agents
GET /agents/{agent_id}
```

**Runs**
```
POST /workspaces/{workspace_id}/runs
GET  /workspaces/{workspace_id}/runs
GET  /runs/{run_id}
POST /runs/{run_id}/regenerate-with-retrieval
GET  /runs/{run_id}/timeline
GET  /runs/{run_id}/rag-debug
GET  /runs/{run_id}/logs
```

**Artifacts**
```
POST  /runs/{run_id}/artifacts
GET   /runs/{run_id}/artifacts/latest
GET   /artifacts/{artifact_id}
PUT   /artifacts/{artifact_id}
POST  /artifacts/{artifact_id}/submit-review
POST  /artifacts/{artifact_id}/approve
POST  /artifacts/{artifact_id}/reject
POST  /artifacts/{artifact_id}/request-publish
POST  /artifacts/{artifact_id}/publish
POST  /artifacts/{artifact_id}/unpublish
GET   /artifacts/{artifact_id}/diff
GET   /artifacts/{artifact_id}/comments
POST  /artifacts/{artifact_id}/comments
PATCH /artifacts/{artifact_id}/assign
```

**Pipelines**
```
POST /workspaces/{workspace_id}/pipeline-templates
GET  /pipeline-templates/canonical
POST /workspaces/{workspace_id}/pipeline-templates/seed
POST /workspaces/{workspace_id}/pipeline-runs
GET  /workspaces/{workspace_id}/pipeline-runs
GET  /pipeline-runs/{pipeline_run_id}
POST /pipeline-runs/{pipeline_run_id}/execute-next
POST /pipeline-runs/{pipeline_run_id}/execute-all
```

**Action Center**
```
GET  /workspaces/{workspace_id}/actions
POST /workspaces/{workspace_id}/actions
GET  /actions/{action_id}
GET  /actions/{action_id}/decisions
POST /actions/{action_id}/decide
POST /actions/{action_id}/execute
POST /actions/{action_id}/cancel
```

**Schedules**
```
POST /workspaces/{workspace_id}/schedules
GET  /workspaces/{workspace_id}/schedules
GET  /schedules/{schedule_id}
PATCH /schedules/{schedule_id}
DELETE /schedules/{schedule_id}
GET  /schedules/{schedule_id}/runs
POST /schedules/{schedule_id}/run-now
POST /workspaces/{workspace_id}/schedules/run-due
```

**Connectors & Ingestion**
```
POST /workspaces/{workspace_id}/connectors
GET  /workspaces/{workspace_id}/connectors
PATCH /connectors/{connector_id}
POST /connectors/{connector_id}/sync
GET  /workspaces/{workspace_id}/ingestion-jobs
```

**Agent Builder**
```
GET  /workspaces/{workspace_id}/agent-builder/meta
GET  /workspaces/{workspace_id}/agent-bases/{base_id}/published
POST /workspaces/{workspace_id}/agent-bases/{base_id}/preview
```

**Governance & Exports**
```
GET /workspaces/{workspace_id}/governance
GET /workspaces/{workspace_id}/governance/events
GET /workspaces/{workspace_id}/governance/events/export.json
GET /workspaces/{workspace_id}/governance/events/export.csv
GET /workspaces/{workspace_id}/exports/workspace.json
GET /workspaces/{workspace_id}/exports/runs.csv
GET /workspaces/{workspace_id}/exports/artifacts.csv
GET /workspaces/{workspace_id}/exports/evidence.csv
GET /workspaces/{workspace_id}/exports/action-items.csv
GET /workspaces/{workspace_id}/exports/governance-events.csv
```

**Export (PDF / DOCX)**
```
GET /artifacts/{artifact_id}/export/pdf
GET /artifacts/{artifact_id}/export/docx
```

---

## Guided Mode

Guided Mode is a dedicated page (`/workspaces/{workspace_id}/guided`) that presents a 5-step linear happy path for shipping an output — designed for new team members or anyone who wants a clean, distraction-free flow without navigating the full system.

The page fetches live workspace state on load (latest run, latest artifact, queued approvals count, user role) and renders each step as a dynamic card that reflects the current state:

1. **Create Run** → Run Builder
2. **Review Output** → Latest artifact (shows `draft` / `in_review` / `final` status)
3. **Request Publish** → Opens the artifact page where the publish request is submitted
4. **Approve + Publish** → Action Center with live queued approvals count
5. **Schedule** *(optional)* → Workspace schedules for recurring automation

Advanced tools (Policy Center, Audit Log, Agent Builder) are accessible via a secondary panel at the bottom — visible when needed, out of the way by default.

---

## Governance & Policy

Each workspace has a `policy_json` and `rbac_json` that control system-wide behaviour:

**Policy Center** (`policy_json`)

- `allowed_source_types` — allowlist of connector types agents can retrieve from (empty = no restriction)
- `retention_days` — evidence retention policy (null = no enforcement)
- `block_external_links` — block external URLs in retrieved content
- `internal_only` — restrict the workspace to internal sources only
- `pii_masking.enabled` + `pii_masking.mode` — regex-based PII redaction at `write_time`, `export_time`, or `both` (redacts emails, phone numbers, and long numeric identifiers)

**RBAC** (`rbac_json`)

Three workspace roles: `viewer` (read-only), `member` (create and collaborate), `admin` (full access + policy management). RBAC is configurable per module (`agent_builder`, `connectors`, `action_center`) with per-connector-type and per-action-type overrides.

Every RBAC and policy check writes a `GovernanceEvent` row — `allow` or `deny`, with the user, action, reason, and metadata — regardless of outcome.

---

## Agent Builder

Create custom agents beyond the 16 built-ins. Custom agents are versioned (`draft` → `published` → `archived`). A published version defines:

- **`artifact.type`** — which artifact type to produce
- **`retrieval`** — default retrieval config (`k`, `alpha`, `min_score`, `overfetch_k`, `rerank`, `source_types`, `timeframe`)
- **`prompt_blocks`** — ordered list of `{kind, text}` prompt instructions. Supported kinds: `system`, `guardrail`, `instruction`

Custom agent runs use a Citation Pack that enforces inline `[n]` citations throughout the artifact, with a deduplicated `## Sources` section at the end.

The **preview** endpoint resolves the full prompt without executing a run — useful for inspecting what the model will receive before committing.

Retrieval knob bounds: `k` (1–50), `alpha` (0.0–1.0), `min_score` (0.0–1.0), `overfetch_k` (1–10).

---

## Contributing

Contributions, issues, and feature requests are welcome.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes
4. Push to the branch (`git push origin feature/your-feature`)
5. Open a Pull Request

Please open an issue first for any significant changes so we can discuss the approach.

---

## Author

**Deepesh Gupta**

- GitHub: [@deepeshgupta12](https://github.com/deepeshgupta12)
- LinkedIn: [linkedin.com/in/deepeshkumargupta](https://www.linkedin.com/in/deepeshkumargupta/)

---

*PM Agent OS — Built with FastAPI, PostgreSQL + pgvector, React 19, TypeScript, Mantine UI, and OpenAI. Self-hostable. API-first.*
