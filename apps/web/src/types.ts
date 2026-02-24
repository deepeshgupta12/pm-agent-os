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
  input_payload: Record<string, unknown>;
  output_summary?: string | null;
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