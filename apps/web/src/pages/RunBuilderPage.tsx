import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Divider,
  Group,
  Radio,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { Agent, PipelineRun, PipelineTemplate, Run, WorkspaceRole } from "../types";

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

  // RBAC role (to disable write actions for viewer)
  const [myRole, setMyRole] = useState<WorkspaceRole | null>(null);
  const canWrite = (myRole?.role || "").toLowerCase() !== "viewer";

  // Mode: agent vs pipeline
  const [mode, setMode] = useState<"agent" | "pipeline">("agent");

  // Agents
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentId, setAgentId] = useState<string | null>(null);

  // Pipelines
  const [templates, setTemplates] = useState<PipelineTemplate[]>([]);
  const [templateId, setTemplateId] = useState<string | null>(null);

  // Payload core fields
  const [goal, setGoal] = useState("Improve onboarding conversion");
  const [context, setContext] = useState("Mobile web");
  const [constraints, setConstraints] = useState("");

  // Timeframe + sources
  const [preset, setPreset] = useState<TimeframePreset>("30d");
  const [startDate, setStartDate] = useState<string>("");
  const [endDate, setEndDate] = useState<string>("");

  const [srcManual, setSrcManual] = useState(true);
  const [srcDocs, setSrcDocs] = useState(true);
  // placeholders for later
  const [srcJira, setSrcJira] = useState(false);
  const [srcSlack, setSrcSlack] = useState(false);
  const [srcGithub, setSrcGithub] = useState(false);

  const [creating, setCreating] = useState(false);

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

  function buildTimeframePayload() {
    if (preset !== "custom") {
      return { preset };
    }
    return {
      preset: "custom",
      start_date: startDate || null,
      end_date: endDate || null,
    };
  }

  function buildSourcesSelected() {
    const out: string[] = [];
    if (srcManual) out.push("manual_evidence");
    if (srcDocs) out.push("docs");
    if (srcJira) out.push("jira");
    if (srcSlack) out.push("slack");
    if (srcGithub) out.push("github");
    return out;
  }

  function buildInputPayload() {
    return {
      goal: goal.trim(),
      context: context.trim(),
      constraints: constraints.trim(),
      timeframe: buildTimeframePayload(),
      sources_selected: buildSourcesSelected(),
    };
  }

  async function loadAll() {
    if (!wid) return;
    setErr(null);

    // role
    const roleRes = await apiFetch<WorkspaceRole>(`/workspaces/${wid}/my-role`, { method: "GET" });
    if (!roleRes.ok) {
      setErr(`Role load failed: ${roleRes.status} ${roleRes.error}`);
      return;
    }
    setMyRole(roleRes.data);

    // agents
    const agentsRes = await apiFetch<Agent[]>("/agents", { method: "GET" });
    if (!agentsRes.ok) {
      setErr(`Agents load failed: ${agentsRes.status} ${agentsRes.error}`);
      return;
    }
    setAgents(agentsRes.data);
    if (!agentId && agentsRes.data.length > 0) setAgentId(agentsRes.data[0].id);

    // templates (non-fatal)
    const tplRes = await apiFetch<TemplateListResponse>(`/workspaces/${wid}/pipelines/templates`, { method: "GET" });
    if (tplRes.ok) {
      const items = normalizeTemplates(tplRes.data);
      setTemplates(items);
      if (!templateId && items.length > 0) setTemplateId(items[0].id);
    } else {
      setTemplates([]);
      // keep err soft (don’t block agent runs)
    }
  }

  async function create() {
    if (!wid) return;
    setErr(null);

    if (!canWrite) {
      setErr("You are a viewer. Creating runs/pipelines is disabled.");
      return;
    }

    const payload = buildInputPayload();

    setCreating(true);

    if (mode === "agent") {
      if (!agentId) {
        setCreating(false);
        setErr("Pick an agent.");
        return;
      }

      const res = await apiFetch<Run>(`/workspaces/${wid}/runs`, {
        method: "POST",
        body: JSON.stringify({ agent_id: agentId, input_payload: payload }),
      });

      setCreating(false);

      if (!res.ok) {
        setErr(`Create run failed: ${res.status} ${res.error}`);
        return;
      }

      nav(`/runs/${res.data.id}`);
      return;
    }

    // mode === pipeline
    if (!templateId) {
      setCreating(false);
      setErr("Pick a pipeline template.");
      return;
    }

    const res = await apiFetch<PipelineRun>(`/workspaces/${wid}/pipelines/runs`, {
      method: "POST",
      body: JSON.stringify({
        template_id: templateId,
        input_payload: payload,
      }),
    });

    setCreating(false);

    if (!res.ok) {
      setErr(`Create pipeline run failed: ${res.status} ${res.error}`);
      return;
    }

    nav(`/pipelines/runs/${res.data.id}`);
  }

  useEffect(() => {
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid]);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Run Builder</Title>
        <Button component={Link} to={`/workspaces/${wid}`} variant="light">
          Back to Workspace
        </Button>
      </Group>

      {myRole ? (
        <Card withBorder>
          <Group justify="space-between">
            <Group gap="sm">
              <Badge variant="light">role: {myRole.role}</Badge>
              <Badge variant="light">workspace: {wid.slice(0, 8)}…</Badge>
            </Group>
            {!canWrite ? <Badge color="red">viewer (read-only)</Badge> : <Badge color="green">can create</Badge>}
          </Group>
        </Card>
      ) : null}

      {err ? (
        <Card withBorder>
          <Text c="red">{err}</Text>
        </Card>
      ) : null}

      <Card withBorder>
        <Stack gap="sm">
          <Text fw={700}>1) What do you want to run?</Text>

          <Radio.Group value={mode} onChange={(v) => setMode(v as any)}>
            <Group>
              <Radio value="agent" label="Single Agent Run" />
              <Radio value="pipeline" label="Pipeline Run" />
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
            <Select
              label="Pipeline Template"
              data={templateOptions}
              value={templateId}
              onChange={setTemplateId}
              searchable
              nothingFoundMessage="No templates"
              placeholder={templates.length === 0 ? "No templates found (seed pipelines first)" : "Pick a template"}
              disabled={!canWrite || templates.length === 0}
            />
          )}

          {mode === "agent" && selectedAgent ? (
            <Text size="sm" c="dimmed">
              Selected agent will auto-create a draft artifact type: <b>{selectedAgent.default_artifact_type}</b>
            </Text>
          ) : null}
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Text fw={700}>2) Inputs</Text>

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
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Text fw={700}>3) Timeframe</Text>

          <Select
            label="Preset"
            value={preset}
            onChange={(v) => setPreset((v as any) || "30d")}
            data={[
              { value: "7d", label: "Last 7 days" },
              { value: "30d", label: "Last 30 days" },
              { value: "90d", label: "Last 90 days" },
              { value: "custom", label: "Custom range" },
            ]}
            disabled={!canWrite}
          />

          {preset === "custom" ? (
            <Group grow>
              <TextInput
                label="Start date (YYYY-MM-DD)"
                value={startDate}
                onChange={(e) => setStartDate(e.currentTarget.value)}
                placeholder="2026-02-01"
                disabled={!canWrite}
              />
              <TextInput
                label="End date (YYYY-MM-DD)"
                value={endDate}
                onChange={(e) => setEndDate(e.currentTarget.value)}
                placeholder="2026-02-25"
                disabled={!canWrite}
              />
            </Group>
          ) : (
            <Text size="sm" c="dimmed">
              Stored as metadata for now (V0). In V1, retrieval + connectors will actually filter by this window.
            </Text>
          )}
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Text fw={700}>4) Sources (V0 metadata + Docs usable)</Text>

          <Text size="sm" c="dimmed">
            For V0, this is stored in payload. Docs is usable via manual ingestion into retrieval store.
          </Text>

          <Divider />

          <Group>
            <Checkbox checked={srcManual} onChange={(e) => setSrcManual(e.currentTarget.checked)} label="Manual evidence" disabled={!canWrite} />
            <Checkbox checked={srcDocs} onChange={(e) => setSrcDocs(e.currentTarget.checked)} label="Docs (retrieval store)" disabled={!canWrite} />
          </Group>

          <Group>
            <Checkbox checked={srcJira} onChange={(e) => setSrcJira(e.currentTarget.checked)} label="Jira (later)" disabled={!canWrite} />
            <Checkbox checked={srcSlack} onChange={(e) => setSrcSlack(e.currentTarget.checked)} label="Slack (later)" disabled={!canWrite} />
            <Checkbox checked={srcGithub} onChange={(e) => setSrcGithub(e.currentTarget.checked)} label="GitHub (later)" disabled={!canWrite} />
          </Group>

          <Button onClick={create} loading={creating} disabled={!canWrite}>
            Create {mode === "agent" ? "Run" : "Pipeline Run"}
          </Button>

          <Text size="sm" c="dimmed">
            This will create a {mode === "agent" ? "Run" : "PipelineRun"} and you’ll be redirected to the detail page.
          </Text>
        </Stack>
      </Card>
    </Stack>
  );
}