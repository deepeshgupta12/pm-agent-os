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