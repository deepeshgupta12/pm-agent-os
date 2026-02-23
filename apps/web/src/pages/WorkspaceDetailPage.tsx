import { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Group,
  Select,
  Stack,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { Agent, Run, Workspace } from "../types";

export default function WorkspaceDetailPage() {
  const { workspaceId } = useParams();
  const wid = workspaceId || "";

  const [ws, setWs] = useState<Workspace | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const [agentId, setAgentId] = useState<string | null>(null);
  const [inputJson, setInputJson] = useState<string>(
    JSON.stringify(
      { goal: "Describe what you want the agent to do", context: "", constraints: "" },
      null,
      2
    )
  );
  const [creating, setCreating] = useState(false);

  const agentOptions = useMemo(
    () =>
      agents.map((a) => ({
        value: a.id,
        label: `${a.name} (${a.id})`,
      })),
    [agents]
  );

  async function loadAll() {
    setErr(null);

    const wsRes = await apiFetch<Workspace>(`/workspaces/${wid}`, { method: "GET" });
    if (!wsRes.ok) {
      setErr(`Workspace load failed: ${wsRes.status} ${wsRes.error}`);
      return;
    }
    setWs(wsRes.data);

    const agentsRes = await apiFetch<Agent[]>("/agents", { method: "GET" });
    if (!agentsRes.ok) {
      setErr(`Agents load failed: ${agentsRes.status} ${agentsRes.error}`);
      return;
    }
    setAgents(agentsRes.data);
    if (!agentId && agentsRes.data.length > 0) setAgentId(agentsRes.data[0].id);

    const runsRes = await apiFetch<Run[]>(`/workspaces/${wid}/runs`, { method: "GET" });
    if (!runsRes.ok) {
      setErr(`Runs load failed: ${runsRes.status} ${runsRes.error}`);
      return;
    }
    setRuns(runsRes.data);
  }

  async function createRun() {
    if (!agentId) return;
    setErr(null);
    setCreating(true);

    let payload: any = {};
    try {
      payload = inputJson.trim() ? JSON.parse(inputJson) : {};
    } catch (e: any) {
      setCreating(false);
      setErr("Input JSON is invalid. Please fix JSON format.");
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

    await loadAll();
  }

  useEffect(() => {
    if (!wid) return;
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid]);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Workspace</Title>
        <Button component={Link} to="/workspaces" variant="light">
          Back
        </Button>
      </Group>

      {ws ? (
        <Card withBorder>
          <Text fw={700}>{ws.name}</Text>
          <Text size="xs" c="dimmed">
            {ws.id}
          </Text>
        </Card>
      ) : (
        <Text c="dimmed">Loading workspace…</Text>
      )}

      <Card withBorder>
        <Stack gap="sm">
          <Text fw={700}>Create Run</Text>
          <Select
            label="Pick an agent"
            data={agentOptions}
            value={agentId}
            onChange={setAgentId}
            searchable
            nothingFoundMessage="No agents"
          />
          <Textarea
            label="Input payload (JSON)"
            autosize
            minRows={6}
            value={inputJson}
            onChange={(e) => setInputJson(e.currentTarget.value)}
          />
          <Group>
            <Button onClick={createRun} loading={creating}>
              Create Run
            </Button>
            <Button variant="light" onClick={loadAll}>
              Refresh
            </Button>
          </Group>
          {err && <Text c="red">{err}</Text>}
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={700}>Runs</Text>
            <Button variant="light" onClick={loadAll}>
              Refresh
            </Button>
          </Group>

          {runs.length === 0 ? (
            <Text c="dimmed">No runs yet.</Text>
          ) : (
            <Stack gap="xs">
              {runs.map((r) => (
                <Card key={r.id} withBorder>
                  <Group justify="space-between" align="flex-start">
                    <Stack gap={4}>
                      <Group gap="sm">
                        <Badge>{r.status}</Badge>
                        <Text fw={600}>{r.agent_id}</Text>
                      </Group>
                      <Text size="xs" c="dimmed">
                        {r.id}
                      </Text>
                    </Stack>
                    <Button component={Link} to={`/runs/${r.id}`}>
                      Open
                    </Button>
                  </Group>
                </Card>
              ))}
            </Stack>
          )}
        </Stack>
      </Card>
    </Stack>
  );
}