import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Divider,
  Group,
  NumberInput,
  Radio,
  Select,
  Stack,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { Agent, PipelineTemplate, Run, PipelineRun } from "../types";

type WorkspaceRole = {
  workspace_id: string;
  role: "admin" | "member" | "viewer";
};

type RetrieveItem = {
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
};

type RetrieveResponse = {
  ok: boolean;
  q: string;
  k: number;
  alpha: number;
  items: RetrieveItem[];
};

type TemplateListResponse = PipelineTemplate[] | { items: PipelineTemplate[] };

function normalizeTemplates(res: TemplateListResponse): PipelineTemplate[] {
  if (Array.isArray(res)) return res;
  return res.items ?? [];
}

type TimeframePreset = "7d" | "30d" | "90d" | "custom";

export default function RunBuilderPage() {
  const { workspaceId } = useParams();
  const wid = workspaceId || "";
  const nav = useNavigate();

  const [err, setErr] = useState<string | null>(null);

  // Role
  const [myRole, setMyRole] = useState<WorkspaceRole | null>(null);
  const canWrite = (myRole?.role || "").toLowerCase() !== "viewer";

  // Mode: single agent run vs pipeline run
  const [mode, setMode] = useState<"agent" | "pipeline">("agent");

  // Agents
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentId, setAgentId] = useState<string | null>(null);

  // Pipelines templates
  const [templates, setTemplates] = useState<PipelineTemplate[]>([]);
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [loadingTemplates, setLoadingTemplates] = useState(false);

  // Shared input payload (goal/context/constraints)
  const [goal, setGoal] = useState("Improve onboarding conversion");
  const [context, setContext] = useState("Desktop web");
  const [constraints, setConstraints] = useState("");

  // Timeframe
  const [preset, setPreset] = useState<TimeframePreset>("30d");
  const [startDate, setStartDate] = useState<string>(""); // YYYY-MM-DD
  const [endDate, setEndDate] = useState<string>(""); // YYYY-MM-DD

  // Sources selection (stored in payload; used by retrieval test)
  const [srcDocs, setSrcDocs] = useState(true);
  const [srcManual, setSrcManual] = useState(true);
  const [srcGithub, setSrcGithub] = useState(false);
  const [srcJira, setSrcJira] = useState(false);
  const [srcSlack, setSrcSlack] = useState(false);

  // Create
  const [creating, setCreating] = useState(false);

  // Retrieval test
  const [rq, setRq] = useState("retrieval later");
  const [rk, setRk] = useState<number>(5);
  const [ralpha, setRalpha] = useState<number>(0.65);
  const [rloading, setRloading] = useState(false);
  const [rres, setRres] = useState<RetrieveResponse | null>(null);

  const agentOptions = useMemo(
    () => agents.map((a) => ({ value: a.id, label: `${a.name} (${a.id})` })),
    [agents]
  );

  const templateOptions = useMemo(
    () => templates.map((t) => ({ value: t.id, label: t.name })),
    [templates]
  );

  const selectedAgent = useMemo(() => agents.find((a) => a.id === agentId) || null, [agents, agentId]);

  const selectedSources = useMemo(() => {
    const out: string[] = [];
    if (srcDocs) out.push("docs");
    if (srcManual) out.push("manual");
    if (srcGithub) out.push("github");
    if (srcJira) out.push("jira");
    if (srcSlack) out.push("slack");
    return out;
  }, [srcDocs, srcManual, srcGithub, srcJira, srcSlack]);

  const timeframePayload = useMemo(() => {
    if (preset !== "custom") return { preset };
    return { preset, start_date: startDate || null, end_date: endDate || null };
  }, [preset, startDate, endDate]);

  const inputPayload = useMemo(() => {
    return {
      goal: goal.trim(),
      context: context.trim(),
      constraints: constraints.trim(),
      timeframe: timeframePayload,
      sources_selected: selectedSources,
    };
  }, [goal, context, constraints, timeframePayload, selectedSources]);

  async function loadMyRole() {
    if (!wid) return;
    const res = await apiFetch<WorkspaceRole>(`/workspaces/${wid}/my-role`, { method: "GET" });
    if (!res.ok) {
      setMyRole(null);
      setErr(`Role load failed: ${res.status} ${res.error}`);
      return;
    }
    setMyRole(res.data);
  }

  async function loadAgents() {
    const res = await apiFetch<Agent[]>("/agents", { method: "GET" });
    if (!res.ok) {
      setAgents([]);
      setErr(`Agents load failed: ${res.status} ${res.error}`);
      return;
    }
    setAgents(res.data);
    if (!agentId && res.data.length > 0) setAgentId(res.data[0].id);
  }

  async function loadTemplates() {
    if (!wid) return;
    setLoadingTemplates(true);
    const res = await apiFetch<TemplateListResponse>(`/workspaces/${wid}/pipelines/templates`, { method: "GET" });
    setLoadingTemplates(false);

    if (!res.ok) {
      setTemplates([]);
      setErr(`Templates load failed: ${res.status} ${res.error}`);
      return;
    }

    const items = normalizeTemplates(res.data);
    setTemplates(items);
    if (!templateId && items.length > 0) setTemplateId(items[0].id);
  }

  async function create() {
    if (!wid) return;

    if (!canWrite) {
      setErr("You are a viewer. Creating runs/pipelines is disabled.");
      return;
    }

    setErr(null);
    setCreating(true);

    if (mode === "agent") {
      if (!agentId) {
        setCreating(false);
        setErr("Pick an agent.");
        return;
      }

      const res = await apiFetch<Run>(`/workspaces/${wid}/runs`, {
        method: "POST",
        body: JSON.stringify({ agent_id: agentId, input_payload: inputPayload }),
      });

      setCreating(false);

      if (!res.ok) {
        setErr(`Create run failed: ${res.status} ${res.error}`);
        return;
      }

      nav(`/runs/${res.data.id}`);
      return;
    }

    // pipeline
    if (!templateId) {
      setCreating(false);
      setErr("Pick a pipeline template.");
      return;
    }

    const pres = await apiFetch<PipelineRun>(`/workspaces/${wid}/pipelines/runs`, {
      method: "POST",
      body: JSON.stringify({ template_id: templateId, input_payload: inputPayload }),
    });

    setCreating(false);

    if (!pres.ok) {
      setErr(`Create pipeline run failed: ${pres.status} ${pres.error}`);
      return;
    }

    nav(`/pipelines/runs/${pres.data.id}`);
  }

  async function testRetrieve() {
    if (!wid) return;
    if (!rq.trim()) {
      setErr("Enter a retrieval query.");
      return;
    }
    setErr(null);
    setRloading(true);

    const params = new URLSearchParams();
    params.set("q", rq.trim());
    params.set("k", String(rk || 5));
    params.set("alpha", String(ralpha ?? 0.65));

    // backend supports source_types as comma-separated
    if (selectedSources.length > 0) {
      params.set("source_types", selectedSources.join(","));
    }

    const res = await apiFetch<RetrieveResponse>(`/workspaces/${wid}/retrieve?${params.toString()}`, {
      method: "GET",
    });

    setRloading(false);

    if (!res.ok) {
      setErr(`Retrieve failed: ${res.status} ${res.error}`);
      setRres(null);
      return;
    }

    setRres(res.data);
  }

  useEffect(() => {
    setErr(null);
    setMyRole(null);
    void loadMyRole();
    void loadAgents();
    void loadTemplates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid]);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Run Builder</Title>
        <Group>
          <Button component={Link} to={`/workspaces/${wid}`} variant="light">
            Back to Workspace
          </Button>
          <Button component={Link} to={`/workspaces/${wid}/docs`} variant="default">
            Docs
          </Button>
        </Group>
      </Group>

      {myRole ? (
        <Card withBorder>
          <Group justify="space-between">
            <Text fw={700}>Workspace role</Text>
            <Badge variant="light">{myRole.role}</Badge>
          </Group>
          <Text size="sm" c="dimmed">
            Viewer can test retrieval. Member/Admin can create runs and pipeline runs.
          </Text>
        </Card>
      ) : null}

      {err ? (
        <Card withBorder>
          <Text c="red">{err}</Text>
        </Card>
      ) : null}

      <Card withBorder>
        <Stack gap="sm">
          <Text fw={700}>Mode</Text>
          <Radio.Group value={mode} onChange={(v) => setMode(v as any)}>
            <Group>
              <Radio value="agent" label="Single agent run" />
              <Radio value="pipeline" label="Pipeline run" />
            </Group>
          </Radio.Group>

          {mode === "agent" ? (
            <Select
              label="Pick agent"
              data={agentOptions}
              value={agentId}
              onChange={setAgentId}
              searchable
              nothingFoundMessage="No agents"
              disabled={!canWrite}
            />
          ) : (
            <Stack gap="xs">
              <Group justify="space-between" align="flex-end">
                <Select
                  label="Pick pipeline template"
                  data={templateOptions}
                  value={templateId}
                  onChange={setTemplateId}
                  searchable
                  nothingFoundMessage="No templates"
                  style={{ flex: 1 }}
                  disabled={!canWrite}
                />
                <Button variant="light" onClick={loadTemplates} loading={loadingTemplates} disabled={!canWrite}>
                  Refresh templates
                </Button>
              </Group>

              {templates.length === 0 ? (
                <TextInput
                  label="Template ID (manual)"
                  value={templateId ?? ""}
                  onChange={(e) => setTemplateId(e.currentTarget.value)}
                  placeholder="Paste template UUID"
                  disabled={!canWrite}
                />
              ) : null}
            </Stack>
          )}

          {!canWrite ? (
            <Text size="sm" c="dimmed">
              You are a viewer — creating runs/pipelines is disabled.
            </Text>
          ) : null}

          {mode === "agent" && selectedAgent ? (
            <Card withBorder>
              <Stack gap={4}>
                <Group gap="sm">
                  <Badge>{selectedAgent.id}</Badge>
                  <Badge variant="light">{selectedAgent.version}</Badge>
                  <Text fw={600}>{selectedAgent.name}</Text>
                </Group>
                <Text size="sm" c="dimmed">
                  {selectedAgent.description}
                </Text>
                <Text size="sm">
                  Default artifact type:{" "}
                  <Text span fw={700}>
                    {selectedAgent.default_artifact_type}
                  </Text>
                </Text>
              </Stack>
            </Card>
          ) : null}

          <Divider />

          <Text fw={700}>Payload</Text>
          <Group grow>
            <TextInput label="Goal" value={goal} onChange={(e) => setGoal(e.currentTarget.value)} disabled={!canWrite} />
            <TextInput
              label="Context"
              value={context}
              onChange={(e) => setContext(e.currentTarget.value)}
              disabled={!canWrite}
            />
          </Group>
          <TextInput
            label="Constraints (optional)"
            value={constraints}
            onChange={(e) => setConstraints(e.currentTarget.value)}
            disabled={!canWrite}
          />

          <Divider />

          <Text fw={700}>Timeframe</Text>
          <Select
            label="Preset"
            value={preset}
            onChange={(v) => setPreset((v as any) || "30d")}
            data={[
              { value: "7d", label: "Last 7 days" },
              { value: "30d", label: "Last 30 days" },
              { value: "90d", label: "Last 90 days" },
              { value: "custom", label: "Custom" },
            ]}
            style={{ maxWidth: 280 }}
            disabled={!canWrite}
          />
          {preset === "custom" ? (
            <Group grow>
              <TextInput
                label="Start date (YYYY-MM-DD)"
                value={startDate}
                onChange={(e) => setStartDate(e.currentTarget.value)}
                disabled={!canWrite}
              />
              <TextInput
                label="End date (YYYY-MM-DD)"
                value={endDate}
                onChange={(e) => setEndDate(e.currentTarget.value)}
                disabled={!canWrite}
              />
            </Group>
          ) : null}

          <Divider />

          <Text fw={700}>Sources (stored in payload)</Text>
          <Group>
            <Checkbox checked={srcDocs} onChange={(e) => setSrcDocs(e.currentTarget.checked)} label="Docs" />
            <Checkbox checked={srcManual} onChange={(e) => setSrcManual(e.currentTarget.checked)} label="Manual" />
            <Checkbox checked={srcGithub} onChange={(e) => setSrcGithub(e.currentTarget.checked)} label="GitHub" />
            <Checkbox checked={srcJira} onChange={(e) => setSrcJira(e.currentTarget.checked)} label="Jira" />
            <Checkbox checked={srcSlack} onChange={(e) => setSrcSlack(e.currentTarget.checked)} label="Slack" />
          </Group>
          <Text size="sm" c="dimmed">
            In V0, these are stored on the run/pipeline payload and used for retrieval test. Real connector sync comes in V1.
          </Text>

          <Divider />

          <Text fw={700}>Preview payload</Text>
          <Textarea
            autosize
            minRows={6}
            value={JSON.stringify(inputPayload, null, 2)}
            onChange={() => {}}
            readOnly
          />

          <Group>
            <Button onClick={create} loading={creating} disabled={!canWrite}>
              Create {mode === "agent" ? "Run" : "Pipeline Run"}
            </Button>
          </Group>
        </Stack>
      </Card>

      {/* Retrieval test */}
      <Card withBorder>
        <Stack gap="sm">
          <Text fw={700}>Test Retrieval (viewer+)</Text>
          <Text size="sm" c="dimmed">
            Uses your selected sources (source_types) and current query parameters. Timeframe is stored in payload only (V0).
          </Text>

          <TextInput
            label="Query"
            value={rq}
            onChange={(e) => setRq(e.currentTarget.value)}
            placeholder='e.g., "retrieval later"'
          />

          <Group grow>
            <NumberInput label="Top K" value={rk} min={1} max={50} onChange={(v) => setRk(Number(v) || 5)} />
            <NumberInput
              label="Alpha (vector weight)"
              value={ralpha}
              min={0}
              max={1}
              step={0.05}
              onChange={(v) => setRalpha(Number(v) || 0.65)}
            />
          </Group>

          <Group>
            <Button onClick={testRetrieve} loading={rloading}>
              Search
            </Button>
            <Badge variant="light">source_types: {selectedSources.length ? selectedSources.join(",") : "none"}</Badge>
          </Group>

          {rres ? (
            <Card withBorder>
              <Stack gap="xs">
                <Group justify="space-between">
                  <Text fw={600}>Results</Text>
                  <Badge variant="light">items: {rres.items?.length ?? 0}</Badge>
                </Group>

                {(rres.items || []).length === 0 ? (
                  <Text size="sm" c="dimmed">
                    No matches.
                  </Text>
                ) : (
                  <Stack gap="xs">
                    {rres.items.map((it) => (
                      <Card key={it.chunk_id} withBorder>
                        <Stack gap={4}>
                          <Group gap="sm">
                            <Badge variant="light">score: {Number(it.score_hybrid).toFixed(3)}</Badge>
                            <Text fw={600}>{it.document_title}</Text>
                          </Group>
                          <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                            {it.snippet}
                          </Text>
                          <Text size="xs" c="dimmed">
                            doc={it.document_id} · chunk={it.chunk_id} · source={it.source_id}
                          </Text>
                        </Stack>
                      </Card>
                    ))}
                  </Stack>
                )}
              </Stack>
            </Card>
          ) : (
            <Text size="sm" c="dimmed">
              Run a retrieval search to validate your docs ingestion + source filters.
            </Text>
          )}
        </Stack>
      </Card>
    </Stack>
  );
}