// apps/web/src/pages/RunBuilderPage.tsx
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Badge,
  Button,
  Checkbox,
  Code,
  Divider,
  Group,
  NumberInput,
  Radio,
  Select,
  Stack,
  Text,
  TextInput,
  Textarea,
  Tooltip,
} from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { Agent, PipelineTemplate, Run, PipelineRun } from "../types";

import GlassPage from "../components/Glass/GlassPage";
import GlassCard from "../components/Glass/GlassCard";
import GlassSection from "../components/Glass/GlassSection";
import GlassStat from "../components/Glass/GlassStat";

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

function HelpPill({ label }: { label: string }) {
  return (
    <Tooltip label={label} withArrow>
      <Badge variant="light">?</Badge>
    </Tooltip>
  );
}

export default function RunBuilderPage() {
  const { workspaceId } = useParams();
  const wid = workspaceId || "";
  const nav = useNavigate();

  const [err, setErr] = useState<string | null>(null);

  // Role
  const [myRole, setMyRole] = useState<WorkspaceRole | null>(null);
  const roleStr = (myRole?.role || "").toLowerCase();
  const canWrite = roleStr !== "viewer";

  // Mode: single agent run vs pipeline run
  const [mode, setMode] = useState<"agent" | "pipeline">("agent");

  // Agents
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentId, setAgentId] = useState<string | null>(null);

  // Pipeline templates
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

  // Retrieval test + run retrieval config
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

  const selectedAgent = useMemo(
    () => agents.find((a) => a.id === agentId) || null,
    [agents, agentId]
  );

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
      setErr("Viewer role: creating runs/pipelines is disabled.");
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
        body: JSON.stringify({
          agent_id: agentId,
          input_payload: inputPayload,
          retrieval: {
            enabled: Boolean(rq.trim()),
            query: rq.trim(),
            k: rk || 6,
            alpha: ralpha ?? 0.65,
            source_types: selectedSources,
            timeframe:
              preset === "custom"
                ? { preset: "custom", start_date: startDate.trim(), end_date: endDate.trim() }
                : { preset },
          },
        }),
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

  const headerRight = (
    <Group>
      <Button component={Link} to={`/workspaces/${wid}`} variant="light" size="sm">
        Back
      </Button>
      <Button component={Link} to={`/workspaces/${wid}/docs`} variant="light" size="sm">
        Docs
      </Button>
    </Group>
  );

  const accessRight = myRole ? (
    <Group gap="sm" wrap="wrap">
      <Badge variant="light">{myRole.role}</Badge>
      <GlassStat label="Mode" value={mode === "agent" ? "Agent" : "Pipeline"} />
      <GlassStat label="Write" value={canWrite ? "Enabled" : "Disabled"} />
    </Group>
  ) : undefined;

  return (
    <GlassPage
      title="Run Builder"
      subtitle="Create a run (agent) or a pipeline run. Preview retrieval to validate evidence coverage."
      right={headerRight}
    >
      <Stack gap="md">
        {err ? (
          <GlassCard>
            <Text c="red">{err}</Text>
          </GlassCard>
        ) : null}

        <GlassSection
          title="Access"
          description="Viewer can preview retrieval. Member/Admin can create runs and pipeline runs."
          right={accessRight}
        >
          {!canWrite ? (
            <Text size="sm" c="dimmed">
              Viewer role: creation is disabled. You can still use “Test retrieval” below.
            </Text>
          ) : (
            <Text size="sm" c="dimmed">
              You can create runs and pipelines. Retrieval config is stored on the run payload (V0).
            </Text>
          )}
        </GlassSection>

        <GlassSection
          title="Create"
          description="Pick a mode, set your input payload, and create a run."
          right={
            <Group gap="sm">
              <Button variant="light" onClick={loadTemplates} loading={loadingTemplates} disabled={!canWrite} size="sm">
                Refresh templates
              </Button>
            </Group>
          }
        >
          <Stack gap="sm">
            <Group justify="space-between" align="center">
              <Group gap="sm">
                <Text fw={700}>Mode</Text>
                <HelpPill label="Agent creates a single run. Pipeline executes a template workflow." />
              </Group>
            </Group>

            <Radio.Group value={mode} onChange={(v) => setMode(v as any)}>
              <Group>
                <Radio value="agent" label="Single agent run" />
                <Radio value="pipeline" label="Pipeline run" />
              </Group>
            </Radio.Group>

            {mode === "agent" ? (
              <Select
                label="Agent"
                data={agentOptions}
                value={agentId}
                onChange={setAgentId}
                searchable
                nothingFoundMessage="No agents"
                disabled={!canWrite}
              />
            ) : (
              <Stack gap="xs">
                <Select
                  label="Pipeline template"
                  data={templateOptions}
                  value={templateId}
                  onChange={setTemplateId}
                  searchable
                  nothingFoundMessage="No templates"
                  disabled={!canWrite}
                />
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

            {mode === "agent" && selectedAgent ? (
              <GlassCard p="md">
                <Stack gap={6}>
                  <Group gap="sm">
                    <Badge variant="light">{selectedAgent.id}</Badge>
                    <Badge variant="light">{selectedAgent.version}</Badge>
                    <Text fw={700}>{selectedAgent.name}</Text>
                  </Group>
                  <Text size="sm" c="dimmed">
                    {selectedAgent.description}
                  </Text>
                  <Text size="sm" c="dimmed">
                    Default artifact type: <Code>{selectedAgent.default_artifact_type}</Code>
                  </Text>
                </Stack>
              </GlassCard>
            ) : null}

            <Divider />

            <Group gap="sm" align="center">
              <Text fw={700}>Input</Text>
              <HelpPill label="This is the high-level context the agent/pipeline receives as input_payload." />
            </Group>

            <Group grow>
              <TextInput
                label="Goal"
                value={goal}
                onChange={(e) => setGoal(e.currentTarget.value)}
                disabled={!canWrite}
              />
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

            <Group gap="sm" align="center">
              <Text fw={700}>Timeframe</Text>
              <HelpPill label="Used by retrieval config on run creation. In V0, timeframe is also stored in payload for reference." />
            </Group>

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
              style={{ maxWidth: 320 }}
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

            <Group gap="sm" align="center">
              <Text fw={700}>Sources</Text>
              <HelpPill label="Selected source types are stored in payload and also used for retrieval preview." />
            </Group>

            <Group>
              <Checkbox checked={srcDocs} onChange={(e) => setSrcDocs(e.currentTarget.checked)} label="Docs" />
              <Checkbox checked={srcManual} onChange={(e) => setSrcManual(e.currentTarget.checked)} label="Manual" />
              <Checkbox checked={srcGithub} onChange={(e) => setSrcGithub(e.currentTarget.checked)} label="GitHub" />
              <Checkbox checked={srcJira} onChange={(e) => setSrcJira(e.currentTarget.checked)} label="Jira" />
              <Checkbox checked={srcSlack} onChange={(e) => setSrcSlack(e.currentTarget.checked)} label="Slack" />
            </Group>

            <Text size="sm" c="dimmed">
              In V0, these are stored on the run/pipeline payload and used for retrieval preview. Connector ingestion comes later.
            </Text>

            <Divider />

            <Group gap="sm" align="center">
              <Text fw={700}>Retrieval config (for this run)</Text>
              <HelpPill label="These parameters are sent when creating an agent run. Use 'Test retrieval' to validate results first." />
            </Group>

            <TextInput
              label="Query"
              value={rq}
              onChange={(e) => setRq(e.currentTarget.value)}
              placeholder='e.g., "how to name events"'
              disabled={!canWrite && mode === "agent"}
            />

            <Group grow>
              <NumberInput
                label="k"
                value={rk}
                min={1}
                max={50}
                onChange={(v) => setRk(Number(v) || 5)}
                disabled={!canWrite && mode === "agent"}
              />
              <NumberInput
                label="alpha"
                value={ralpha}
                min={0}
                max={1}
                step={0.05}
                onChange={(v) => setRalpha(Number(v) || 0.65)}
                disabled={!canWrite && mode === "agent"}
              />
            </Group>

            <Divider />

            <Text fw={700}>Preview payload</Text>
            <Textarea autosize minRows={6} value={JSON.stringify(inputPayload, null, 2)} readOnly />

            <Group>
              <Tooltip withArrow label={canWrite ? "Creates the run and redirects to Run detail." : "Viewer role cannot create runs."}>
                <span>
                  <Button onClick={create} loading={creating} disabled={!canWrite} size="sm">
                    Create {mode === "agent" ? "run" : "pipeline run"}
                  </Button>
                </span>
              </Tooltip>
            </Group>
          </Stack>
        </GlassSection>

        <GlassSection
          title="Test retrieval"
          description="Preview what retrieval would return with your current query and source types."
          right={<GlassStat label="Sources" value={selectedSources.length ? selectedSources.join(", ") : "none"} />}
        >
          <Stack gap="sm">
            <Text size="sm" c="dimmed">
              Uses <Code>GET /workspaces/:id/retrieve</Code>. Viewer+ allowed.
            </Text>

            <TextInput
              label="Query"
              value={rq}
              onChange={(e) => setRq(e.currentTarget.value)}
              placeholder='e.g., "refresh tokens"'
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
              <Button onClick={testRetrieve} loading={rloading} size="sm">
                Search
              </Button>
              <Badge variant="light">source_types: {selectedSources.length ? selectedSources.join(",") : "none"}</Badge>
            </Group>

            {rres ? (
              <GlassCard p="md">
                <Stack gap="xs">
                  <Group justify="space-between">
                    <Text fw={700}>Results</Text>
                    <Badge variant="light">items: {rres.items?.length ?? 0}</Badge>
                  </Group>

                  {(rres.items || []).length === 0 ? (
                    <Text size="sm" c="dimmed">
                      No matches.
                    </Text>
                  ) : (
                    <Stack gap="xs">
                      {rres.items.map((it) => (
                        <GlassCard key={it.chunk_id} p="md">
                          <Stack gap={6}>
                            <Group gap="sm">
                              <Badge variant="light">score: {Number(it.score_hybrid).toFixed(3)}</Badge>
                              <Text fw={700}>{it.document_title}</Text>
                            </Group>
                            <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                              {it.snippet}
                            </Text>
                            <Text size="xs" c="dimmed">
                              doc={it.document_id} · chunk={it.chunk_id} · source={it.source_id}
                            </Text>
                          </Stack>
                        </GlassCard>
                      ))}
                    </Stack>
                  )}
                </Stack>
              </GlassCard>
            ) : (
              <Text size="sm" c="dimmed">
                Run a retrieval search to validate docs ingestion and filters before you create a run.
              </Text>
            )}
          </Stack>
        </GlassSection>
      </Stack>
    </GlassPage>
  );
}