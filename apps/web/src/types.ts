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

export type Evidence = {
  id: string;
  run_id: string;
  kind: string;
  source_name: string;
  source_ref?: string | null;
  excerpt: string;
  meta: Record<string, unknown>;
};

/** Pipelines */
export type PipelineTemplate = {
  id: string;
  workspace_id: string;
  name: string;
  description: string;
  // backend stores full json definition; keep loose for now
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

  // Step 16B (server-side)
  prev_context_attached?: boolean | null;

  // Step 19 (server-side, optional fields)
  auto_regenerated?: boolean | null;

  latest_artifact_id?: string | null;
  latest_artifact_version?: number | null;
  latest_artifact_type?: string | null;
  latest_artifact_title?: string | null;
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