// apps/web/src/types.ts

export type Workspace = { id: string; name: string; owner_user_id: string };

export type Agent = {
  id: string;
  name: string;
  description: string;
  version: string;
  input_schema: Record<string, unknown>;
  output_artifact_types: string[];
  default_artifact_type: string;
};

export type Run = {
  id: string;
  workspace_id: string;
  agent_id: string;
  created_by_user_id: string;
  status: string;
  input_payload: Record<string, unknown> & { _pipeline?: RunPipelineMeta };
  output_summary?: string | null;
};

export type PipelinePrevArtifact = {
  artifact_id: string;
  type: string;
  title: string;
  version: number;
  status: string;
  content_md_excerpt: string;
};

export type RunPipelineMeta = {
  pipeline_run_id: string;
  step_index: number;
  step_name: string;
  template_id: string;
  prev_run_id?: string | null;
  prev_artifact?: PipelinePrevArtifact;
};

export type Artifact = {
  id: string;
  run_id: string;
  type: string;
  title: string;
  content_md: string;
  logical_key: string;
  version: number;
  status: string;
  assigned_to_user_id?: string | null;
};

export type ArtifactDiffMeta = {
  id: string;
  run_id: string;
  type: string;
  title: string;
  logical_key: string;
  version: number;
  status: string;
};

export type ArtifactDiff = {
  a: ArtifactDiffMeta;
  b: ArtifactDiffMeta;
  unified_diff: string;
};

export type ArtifactReview = {
  id: string;
  artifact_id: string;
  state: "requested" | "approved" | "rejected";
  requested_by_user_id: string;
  requested_at: string; // ISO
  request_comment?: string | null;
  decided_by_user_id?: string | null;
  decided_at?: string | null; // ISO
  decision_comment?: string | null;
};

export type Evidence = {
  id: string;
  run_id: string;
  kind: string;
  source_name: string;
  source_ref?: string | null;
  excerpt: string;
  meta: Record<string, unknown>;
  created_at?: string; // ISO (optional; rag-debug includes it)
};

/** Pipelines */
export type PipelineTemplate = {
  id: string;
  workspace_id: string;
  name: string;
  description: string;
  definition_json: Record<string, unknown>;
};

export type PipelineStep = {
  id: string;
  pipeline_run_id: string;
  step_index: number;
  step_name: string;
  agent_id: string;
  status: string;
  input_payload: Record<string, unknown>;
  run_id?: string | null;

  prev_context_attached?: boolean | null;
  auto_regenerated?: boolean | null;

  latest_artifact_id?: string | null;
  latest_artifact_version?: number | null;
  latest_artifact_type?: string | null;
  latest_artifact_title?: string | null;

  // V3.2
  retrieval_enabled?: boolean | null;
  retrieval_query?: string | null;
  retrieval_evidence_count?: number | null;
  retrieval_batch_id?: string | null;
  retrieval_batch_kind?: string | null;
};

export type PipelineRun = {
  id: string;
  workspace_id: string;
  template_id: string;
  created_by_user_id: string;
  status: string;
  current_step_index: number;
  input_payload: Record<string, unknown>;
  steps: PipelineStep[];
};

export type WorkspaceMember = {
  user_id: string;
  email: string;
  role: "admin" | "member" | "viewer";
};

export type WorkspaceRole = {
  workspace_id: string;
  role: "admin" | "member" | "viewer";
};

export type RunLog = {
  id: string;
  run_id: string;
  level: "info" | "warn" | "error" | "debug";
  message: string;
  meta: Record<string, unknown>;
  created_at: string; // ISO string
};

export type RunTimelineEvent = {
  ts: string; // ISO string
  kind: "run" | "status" | "artifact" | "evidence" | "log";
  label: string;
  ref_id?: string | null;
  meta: Record<string, unknown>;
};

export type RagBatch = {
  batch_id: string; // uuid or "legacy"
  batch_kind: string; // create_run | regenerate_with_retrieval | legacy | unknown
  created_at?: string | null; // ISO
  evidence_count: number;
  retrieval?: Record<string, unknown>;
};

export type RagDebugResponse = {
  ok: boolean;
  run_id: string;
  batch_id?: string | null;
  batches?: RagBatch[];
  retrieval_config?: Record<string, unknown> | null;
  retrieval_log?: Record<string, unknown> | null;
  evidence: Evidence[];
};

/** V2.2 retrieval preview types */
export type RetrieveItem = {
  chunk_id: string;
  document_id: string;
  source_id: string;
  document_title: string;
  chunk_index: number;
  snippet: string;
  meta: Record<string, unknown>;
  score_fts: number;
  score_vec: number;
  score_hybrid: number;
  score_rerank_bonus?: number | null;
  score_final?: number | null;
  knobs?: Record<string, unknown> | null;
};

export type RetrieveResponse = {
  ok: boolean;
  q: string;
  k: number;
  alpha: number;
  min_score: number;
  overfetch_k: number;
  rerank: boolean;
  items: RetrieveItem[];
};

export type RunRegenerateWithRetrievalIn = {
  retrieval: {
    enabled: boolean;
    query: string;
    k: number;
    alpha: number;
    source_types: string[];
    timeframe: Record<string, unknown>;
    min_score: number;
    overfetch_k: number;
    rerank: boolean;
  };
};

/** V2.4 attach preview evidence payload */
export type AttachPreviewEvidenceIn = {
  retrieval: {
    query: string;
    k: number;
    alpha: number;
    source_types: string[];
    timeframe: Record<string, unknown>;
    min_score: number;
    overfetch_k: number;
    rerank: boolean;
  };
  items: Array<{
    chunk_id: string;
    document_id: string;
    source_id: string;
    document_title: string;
    chunk_index: number;
    snippet: string;
    score_fts: number;
    score_vec: number;
    score_hybrid: number;
    score_rerank_bonus?: number | null;
    score_final?: number | null;
  }>;
};

export type TemplateAdmin = {
  workspace_id: string;
  template_admin_json: Record<string, unknown>;
};

export type ActionItem = {
  id: string;
  workspace_id: string;
  created_by_user_id: string;
  assigned_to_user_id?: string | null;
  decided_by_user_id?: string | null;

  type: string;
  status: "queued" | "approved" | "rejected" | "cancelled";
  title: string;

  payload_json: Record<string, unknown>;
  target_ref?: string | null;

  decision_comment?: string | null;
  decided_at?: string | null;

  created_at: string;
  updated_at: string;

  // V2 approvals metadata (from API)
  approvals_required?: number;
  approvals_approved_count?: number;
  approvals_rejected_count?: number;
  my_decision?: "approved" | "rejected" | null;
};

export type ActionItemDecision = {
  reviewer_user_id: string;
  decision: "approved" | "rejected";
  comment?: string | null;
  decided_at: string; // ISO
};

export type ArtifactCommentMention = {
  mentioned_user_id: string;
  mentioned_email: string;
};

export type ArtifactComment = {
  id: string;
  artifact_id: string;
  author_user_id: string;
  author_email: string;
  body: string;
  created_at: string; // ISO
  mentions: ArtifactCommentMention[];
};

export type ArtifactAssignIn = {
  assigned_to_user_id: string | null;
};

// -----------------------------
// V2 Step 4: Schedules
// -----------------------------

export type ScheduleKind = "agent_run" | "pipeline_run";

export type Schedule = {
  id: string;
  workspace_id: string;
  created_by_user_id?: string | null;

  name: string;
  kind: ScheduleKind;

  timezone: string;
  cron?: string | null;
  interval_json: Record<string, unknown>;
  payload_json: Record<string, unknown>;

  enabled: boolean;

  next_run_at?: string | null; // ISO
  last_run_at?: string | null; // ISO
  last_status?: string | null;
  last_error?: string | null;

  created_at: string; // ISO
  updated_at: string; // ISO
};

export type ScheduleRun = {
  id: string;
  schedule_id: string;
  status: "running" | "success" | "failed";
  started_at: string; // ISO
  finished_at?: string | null; // ISO
  error?: string | null;

  run_id?: string | null;
  pipeline_run_id?: string | null;

  meta: Record<string, unknown>;
};

export type ScheduleRunNowResponse = {
  ok: boolean;
  schedule_id: string;
  schedule_run: ScheduleRun;
  run_id?: string | null;
  pipeline_run_id?: string | null;
};

export type ScheduleRunDueResponse = {
  ok: boolean;
  workspace_id: string;
  due_count: number;
  executed_count: number;
  schedule_runs: ScheduleRun[];
  now: string; // ISO
};

// -----------------------------
// Commit 6: Governance + Agent Builder UI types
// -----------------------------
export type GovernanceEffectiveOut = {
  workspace_id: string;
  policy_effective: Record<string, unknown>;
  rbac_effective: Record<string, unknown>;
};

export type GovernanceEventOut = {
  id: string;
  workspace_id: string;
  user_id?: string | null;
  action: string;
  decision: string; // allow|deny
  reason: string;
  meta: Record<string, unknown>;
  created_at: string; // ISO
};

export type GovernanceEventsOut = {
  workspace_id: string;
  items: GovernanceEventOut[];
};

export type AgentBaseOut = {
  id: string;
  workspace_id: string;
  key: string;
  name: string;
  description: string;
  created_by_user_id?: string | null;
  created_at: string;
  updated_at: string;
};

export type AgentVersionOut = {
  id: string;
  agent_base_id: string;
  version: number;
  status: string;
  definition_json: Record<string, unknown>;
  created_by_user_id?: string | null;
  created_at: string;
};

export type AgentBuilderMetaOut = {
  workspace_id: string;
  allowed_source_types: string[];
  timeframe_presets: string[];
  retrieval_knobs: Record<string, unknown>;
  artifact_types: string[];
  policy_effective?: Record<string, unknown>;
  rbac_effective?: Record<string, unknown>;
};

export type CustomAgentPublishedOut = {
  agent_base_id: string;
  published_version_id: string;
  published_version: number;
  status: string;
  definition_json: Record<string, unknown>;
};

export type CustomAgentPreviewOut = {
  ok: boolean;
  agent_base_id: string;
  published_version: number;
  artifact_type: string;
  retrieval_resolved: Record<string, unknown>;
  system_prompt: string;
  user_prompt: string;
  llm_enabled: boolean;
  notes: string[];
};

export type CustomAgentRunOut = Run;

// -----------------------------
// Commit 6 Step 2: Agent Builder create/publish/archive responses
// -----------------------------
export type AgentPublishOut = {
  ok: boolean;
  agent_base_id: string;
  published_version_id: string;
  published_version: number;
};

export type AgentArchiveOut = {
  ok: boolean;
  agent_version_id: string;
  status: string; // archived
};

// -----------------------------
// Commit 7: Definition JSON helper types (frontend-only)
// -----------------------------
export type PromptBlock = {
  kind: string; // instruction|constraint|checklist|...
  text: string;
};

export type AgentDefinitionJson = {
  artifact?: { type?: string };
  retrieval?: {
    enabled?: boolean;
    query?: string;
    k?: number;
    alpha?: number;
    source_types?: string[];
    timeframe?: Record<string, unknown>;
    min_score?: number;
    overfetch_k?: number;
    rerank?: boolean;
  };
  prompt_blocks?: PromptBlock[];
};