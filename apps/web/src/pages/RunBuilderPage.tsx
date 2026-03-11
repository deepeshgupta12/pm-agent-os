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
  Select,
  Stack,
  Text,
  TextInput,
  Textarea,
  Tooltip,
  Collapse,
  Switch,
} from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { Agent, PipelineTemplate, Run, PipelineRun, WorkspaceRole, RetrieveResponse, RetrieveItem } from "../types";

import GlassPage from "../components/Glass/GlassPage";
import GlassCard from "../components/Glass/GlassCard";
import GlassSection from "../components/Glass/GlassSection";
import GlassStat from "../components/Glass/GlassStat";

type TemplateListResponse = PipelineTemplate[] | { items: PipelineTemplate[] };

function normalizeTemplates(res: TemplateListResponse): PipelineTemplate[] {
  if (Array.isArray(res)) return res;
  return res.items ?? [];
}

type TimeframePreset = "7d" | "30d" | "90d" | "custom";

function shortId(id: string): string {
  if (!id) return "";
  return id.length <= 10 ? id : `${id.slice(0, 8)}…`;
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

  // Agents
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentId, setAgentId] = useState<string | null>(null);

  // Simple payload
  const [goal, setGoal] = useState("Improve onboarding conversion");
  const [context, setContext] = useState("Desktop web");
  const [constraints, setConstraints] = useState("");

  // References (simple)
  const [useReferences, setUseReferences] = useState(false);
  const [preset, setPreset] = useState<TimeframePreset>("30d");

  // Advanced toggle
  const [advancedOpen, setAdvancedOpen] = useState(false);

  // Advanced timeframe plumbing
  const [startDate, setStartDate] = useState<string>(""); // YYYY-MM-DD
  const [endDate, setEndDate] = useState<string>(""); // YYYY-MM-DD

  // Advanced sources selection
  const [srcDocs, setSrcDocs] = useState(true);
  const [srcManual, setSrcManual] = useState(true);
  const [srcGithub, setSrcGithub] = useState(false);
  const [srcJira, setSrcJira] = useState(false);
  const [srcSlack, setSrcSlack] = useState(false);

  // Create
  const [creating, setCreating] = useState(false);

  // Retrieval test + run retrieval config (advanced)
  const [rq, setRq] = useState("");
  const [rk, setRk] = useState<number>(5);
  const [ralpha, setRalpha] = useState<number>(0.65);
  const [rloading, setRloading] = useState(false);
  const [rres, setRres] = useState<RetrieveResponse | null>(null);

  // Pipeline (keep available, but advanced-only for V0)
  const [templates, setTemplates] = useState<PipelineTemplate[]>([]);
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [loadingTemplates, setLoadingTemplates] = useState(false);

  const agentOptions = useMemo(
    () => agents.map((a) => ({ value: a.id, label: `${a.name}` })),
    [agents]
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
      ...(constraints.trim() ? { constraints: constraints.trim() } : {}),
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

  async function createRun() {
    if (!wid) return;

    if (!canWrite) {
      setErr("Viewer role: creating runs is disabled.");
      return;
    }

    if (!agentId) {
      setErr("Pick an agent.");
      return;
    }

    setErr(null);
    setCreating(true);

    const retrievalEnabled = useReferences && rq.trim().length > 0;

    const res = await apiFetch<Run>(`/workspaces/${wid}/runs`, {
      method: "POST",
      body: JSON.stringify({
        agent_id: agentId,
        input_payload: inputPayload,
        retrieval: {
          enabled: retrievalEnabled,
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
  }

  async function createPipelineRun() {
    if (!wid) return;

    if (!canWrite) {
      setErr("Viewer role: creating pipeline runs is disabled.");
      return;
    }

    if (!templateId) {
      setErr("Pick a pipeline template.");
      return;
    }

    setErr(null);
    setCreating(true);

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
      setErr("Enter a query to test references.");
      return;
    }
    setErr(null);
    setRloading(true);

    const params = new URLSearchParams();
    params.set("q", rq.trim());
    params.set("k", String(rk || 5));
    params.set("alpha", String(ralpha ?? 0.65));

    if (selectedSources.length > 0) params.set("source_types", selectedSources.join(","));

    // Keep timeframe preset in preview if supported by backend
    if (preset && preset !== "custom") params.set("timeframe_preset", preset);

    const res = await apiFetch<RetrieveResponse>(`/workspaces/${wid}/retrieve?${params.toString()}`, {
      method: "GET",
    });

    setRloading(false);

    if (!res.ok) {
      setErr(`References search failed: ${res.status} ${res.error}`);
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
        Guided mode
      </Button>
      <Button component={Link} to={`/workspaces/${wid}/overview`} variant="light" size="sm">
        Overview
      </Button>
      <Button component={Link} to={`/workspaces/${wid}/docs`} variant="light" size="sm">
        Docs
      </Button>
    </Group>
  );

  const accessRight = myRole ? (
    <Group gap="sm" wrap="wrap">
      <Badge variant="light">{myRole.role}</Badge>
      <GlassStat label="Write" value={canWrite ? "Enabled" : "Disabled"} />
    </Group>
  ) : undefined;

  return (
    <GlassPage
      title="Create run"
      subtitle="Simple-first run creation. Advanced options are available when you need them."
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
          description="Viewer can test references. Member/Admin can create runs."
          right={accessRight}
        >
          {!canWrite ? (
            <Text size="sm" c="dimmed">
              Viewer role: creation is disabled. You can still test references in Advanced.
            </Text>
          ) : (
            <Text size="sm" c="dimmed">
              Create runs with a minimal input. Use references only when needed.
            </Text>
          )}
        </GlassSection>

        {/* SIMPLE-FIRST */}
        <GlassSection
          title="Create run"
          description="Pick an agent, describe the goal, optionally use references, then create."
          right={
            <Group gap="sm">
              <Button variant="light" size="sm" onClick={() => setAdvancedOpen((x) => !x)}>
                {advancedOpen ? "Hide advanced" : "Show advanced"}
              </Button>
            </Group>
          }
        >
          <Stack gap="sm">
            <Select
              label="Agent"
              data={agentOptions}
              value={agentId}
              onChange={setAgentId}
              searchable
              nothingFoundMessage="No agents"
              disabled={!canWrite}
            />

            {selectedAgent ? (
              <GlassCard p="md">
                <Stack gap={6}>
                  <Group gap="sm">
                    <Badge variant="light">{shortId(selectedAgent.id)}</Badge>
                    <Badge variant="light">{selectedAgent.version}</Badge>
                    <Text fw={700}>{selectedAgent.name}</Text>
                  </Group>
                  <Text size="sm" c="dimmed">
                    {selectedAgent.description}
                  </Text>
                  <Text size="sm" c="dimmed">
                    Default output: <Code>{selectedAgent.default_artifact_type}</Code>
                  </Text>
                </Stack>
              </GlassCard>
            ) : null}

            <Divider />

            <Group grow>
              <TextInput
                label="Goal"
                value={goal}
                onChange={(e) => setGoal(e.currentTarget.value)}
                disabled={!canWrite}
                placeholder="What do you want this run to achieve?"
              />
              <TextInput
                label="Context"
                value={context}
                onChange={(e) => setContext(e.currentTarget.value)}
                disabled={!canWrite}
                placeholder="Where / for whom?"
              />
            </Group>

            <Textarea
              label="Constraints (optional)"
              value={constraints}
              onChange={(e) => setConstraints(e.currentTarget.value)}
              disabled={!canWrite}
              autosize
              minRows={2}
              placeholder="Any constraints, caveats, scope limits?"
            />

            <Divider />

            <Group justify="space-between" align="center">
              <Group gap="sm">
                <Text fw={700}>Use references</Text>
                <Tooltip
                  withArrow
                  label="If enabled, the run can pull evidence from workspace sources. Keep off for simple runs."
                >
                  <Badge variant="light">?</Badge>
                </Tooltip>
              </Group>

              <Switch checked={useReferences} onChange={(e) => setUseReferences(e.currentTarget.checked)} disabled={!canWrite} />
            </Group>

            {useReferences ? (
              <Stack gap="sm">
                <TextInput
                  label="Reference query"
                  value={rq}
                  onChange={(e) => setRq(e.currentTarget.value)}
                  placeholder='e.g., "refresh tokens", "onboarding drop-offs", "pricing experiments"'
                  disabled={!canWrite}
                />

                <Select
                  label="Timeframe (optional)"
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
              </Stack>
            ) : (
              <Text size="sm" c="dimmed">
                References are off. This run will execute using only your input.
              </Text>
            )}

            <Divider />

            <Group>
              <Tooltip withArrow label={canWrite ? "Creates the run and opens it." : "Viewer role cannot create runs."}>
                <span>
                  <Button onClick={createRun} loading={creating} disabled={!canWrite} size="sm">
                    Create run
                  </Button>
                </span>
              </Tooltip>
              <Button component={Link} to="/runs" variant="light" size="sm">
                View runs
              </Button>
              <Button component={Link} to="/outputs" variant="light" size="sm">
                View outputs
              </Button>
            </Group>

            {/* ADVANCED */}
            <Collapse in={advancedOpen}>
              <Divider my="md" />

              <GlassCard p="md">
                <Stack gap="sm">
                  <Group justify="space-between" align="center">
                    <Text fw={800}>Advanced</Text>
                    <Badge variant="light">Optional</Badge>
                  </Group>

                  <Text size="sm" c="dimmed">
                    Advanced settings are for tuning references and running pipelines. Keep these hidden for normal use.
                  </Text>

                  <Divider />

                  <Text fw={700}>Sources</Text>
                  <Group>
                    <Checkbox checked={srcDocs} onChange={(e) => setSrcDocs(e.currentTarget.checked)} label="Docs" />
                    <Checkbox checked={srcManual} onChange={(e) => setSrcManual(e.currentTarget.checked)} label="Manual" />
                    <Checkbox checked={srcGithub} onChange={(e) => setSrcGithub(e.currentTarget.checked)} label="GitHub" />
                    <Checkbox checked={srcJira} onChange={(e) => setSrcJira(e.currentTarget.checked)} label="Jira" />
                    <Checkbox checked={srcSlack} onChange={(e) => setSrcSlack(e.currentTarget.checked)} label="Slack" />
                  </Group>

                  <Text size="sm" c="dimmed">
                    Selected sources: <Code>{selectedSources.length ? selectedSources.join(", ") : "none"}</Code>
                  </Text>

                  <Divider />

                  <Text fw={700}>Reference tuning</Text>
                  <Group grow>
                    <NumberInput
                      label="Top K"
                      value={rk}
                      min={1}
                      max={50}
                      onChange={(v) => setRk(Number(v) || 5)}
                    />
                    <NumberInput
                      label="Alpha (vector weight)"
                      value={ralpha}
                      min={0}
                      max={1}
                      step={0.05}
                      onChange={(v) => setRalpha(Number(v) || 0.65)}
                    />
                  </Group>

                  <Divider />

                  <Text fw={700}>Test references</Text>
                  <Text size="sm" c="dimmed">
                    Uses <Code>GET /workspaces/:id/retrieve</Code> to preview reference coverage.
                  </Text>

                  <Group>
                    <Button onClick={testRetrieve} loading={rloading} size="sm" variant="light">
                      Search references
                    </Button>
                    <Badge variant="light">sources: {selectedSources.length ? selectedSources.join(",") : "none"}</Badge>
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
                            {(rres.items as RetrieveItem[]).map((it) => (
                              <GlassCard key={it.chunk_id} p="md">
                                <Stack gap={6}>
                                  <Group gap="sm">
                                    <Badge variant="light">score: {Number(it.score_hybrid).toFixed(3)}</Badge>
                                    <Text fw={700}>{it.document_title}</Text>
                                  </Group>
                                  <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                                    {it.snippet}
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
                      Run a reference search to validate ingestion and source selection.
                    </Text>
                  )}

                  <Divider />

                  <Text fw={700}>Pipelines (advanced)</Text>
                  <Text size="sm" c="dimmed">
                    Pipelines are supported, but not the default workflow in V0.
                  </Text>

                  <Group>
                    <Button
                      variant="light"
                      onClick={loadTemplates}
                      loading={loadingTemplates}
                      disabled={!canWrite}
                      size="sm"
                    >
                      Refresh templates
                    </Button>
                  </Group>

                  <Select
                    label="Pipeline template"
                    data={templates.map((t) => ({ value: t.id, label: t.name }))}
                    value={templateId}
                    onChange={setTemplateId}
                    searchable
                    nothingFoundMessage="No templates"
                    disabled={!canWrite}
                  />

                  <Tooltip withArrow label={canWrite ? "Creates the pipeline run and opens it." : "Viewer cannot create."}>
                    <span>
                      <Button onClick={createPipelineRun} loading={creating} disabled={!canWrite || !templateId} size="sm">
                        Create pipeline run
                      </Button>
                    </span>
                  </Tooltip>

                  <Divider />

                  <Text fw={700}>Preview payload (advanced)</Text>
                  <Textarea autosize minRows={6} value={JSON.stringify(inputPayload, null, 2)} readOnly />
                </Stack>
              </GlassCard>
            </Collapse>
          </Stack>
        </GlassSection>
      </Stack>
    </GlassPage>
  );
}