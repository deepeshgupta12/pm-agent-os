import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge, Button, Card, Group, Stack, Text, Title } from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { PipelineRun, PipelineStep } from "../types";

type NextResponse = {
  ok: boolean;
  created_run_id?: string | null;
  pipeline_run: PipelineRun;
};

type ExecuteAllResponse = {
  ok: boolean;
  created_run_ids: string[];
  pipeline_run: PipelineRun;
};

function stepColor(status: string): string {
  const s = (status || "").toLowerCase();
  if (s === "completed") return "green";
  if (s === "running") return "blue";
  if (s === "failed") return "red";
  return "gray";
}

export default function PipelineRunDetailPage() {
  const { pipelineRunId } = useParams();
  const prid = pipelineRunId || "";

  const [pr, setPr] = useState<PipelineRun | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [execLoading, setExecLoading] = useState(false);
  const [execAllLoading, setExecAllLoading] = useState(false);

  const [lastCreatedRunId, setLastCreatedRunId] = useState<string | null>(null);
  const [createdRunIds, setCreatedRunIds] = useState<string[]>([]);

  const canExecute = useMemo(() => {
    if (!pr) return false;
    return (pr.status || "").toLowerCase() !== "completed";
  }, [pr]);

  async function load() {
    if (!prid) return;
    setErr(null);
    setLoading(true);

    const res = await apiFetch<PipelineRun>(`/pipelines/runs/${prid}`, { method: "GET" });

    setLoading(false);

    if (!res.ok) {
      setErr(`Pipeline run load failed: ${res.status} ${res.error}`);
      return;
    }

    setPr(res.data);
  }

  async function executeNext() {
    if (!prid) return;
    setErr(null);
    setExecLoading(true);

    const res = await apiFetch<NextResponse>(`/pipelines/runs/${prid}/next`, {
      method: "POST",
      body: JSON.stringify({}),
    });

    setExecLoading(false);

    if (!res.ok) {
      setErr(`Execute next failed: ${res.status} ${res.error}`);
      return;
    }

    setPr(res.data.pipeline_run);
    const rid = res.data.created_run_id ?? null;
    setLastCreatedRunId(rid);

    if (rid) {
      setCreatedRunIds((prev) => [rid, ...prev.filter((x) => x !== rid)]);
    }
  }

  async function executeAll() {
    if (!prid) return;
    setErr(null);
    setExecAllLoading(true);

    const res = await apiFetch<ExecuteAllResponse>(`/pipelines/runs/${prid}/execute-all`, {
      method: "POST",
      body: JSON.stringify({}),
    });

    setExecAllLoading(false);

    if (!res.ok) {
      setErr(`Execute all failed: ${res.status} ${res.error}`);
      return;
    }

    setPr(res.data.pipeline_run);

    const ids = (res.data.created_run_ids || []).filter(Boolean);
    if (ids.length > 0) {
      setLastCreatedRunId(ids[ids.length - 1] ?? null);
      setCreatedRunIds((prev) => {
        const merged = [...ids, ...prev];
        // de-dupe preserve order
        const seen = new Set<string>();
        return merged.filter((x) => {
          if (seen.has(x)) return false;
          seen.add(x);
          return true;
        });
      });
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prid]);

  const workspaceId = pr?.workspace_id ?? "";

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Pipeline Run</Title>
        {workspaceId ? (
          <Button component={Link} to={`/workspaces/${workspaceId}/pipelines`} variant="light">
            Back to Pipelines
          </Button>
        ) : (
          <Button component={Link} to="/workspaces" variant="light">
            Back to Workspaces
          </Button>
        )}
      </Group>

      {err ? (
        <Card withBorder>
          <Text c="red">{err}</Text>
        </Card>
      ) : null}

      {!pr ? (
        <Text c="dimmed">{loading ? "Loading pipeline run…" : "No pipeline run loaded."}</Text>
      ) : (
        <Card withBorder>
          <Stack gap="sm">
            <Group justify="space-between">
              <Group gap="sm">
                <Badge>{pr.status}</Badge>
                <Text fw={700}>template</Text>
                <Text c="dimmed" size="sm">
                  {pr.template_id}
                </Text>
              </Group>
              <Text size="xs" c="dimmed">
                {pr.id}
              </Text>
            </Group>

            <Card withBorder>
              <Text fw={600} mb={6}>
                Pipeline input payload
              </Text>
              <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                {JSON.stringify(pr.input_payload, null, 2)}
              </pre>
            </Card>

            <Group gap="sm">
              <Button onClick={executeNext} disabled={!canExecute} loading={execLoading}>
                Execute next step
              </Button>
              <Button
                onClick={executeAll}
                disabled={!canExecute}
                loading={execAllLoading}
                variant="light"
              >
                Execute all remaining
              </Button>
              <Button variant="light" onClick={load} loading={loading}>
                Refresh
              </Button>
            </Group>

            {lastCreatedRunId ? (
              <Card withBorder>
                <Group justify="space-between">
                  <Stack gap={2}>
                    <Text fw={600}>Last created Run</Text>
                    <Text size="xs" c="dimmed">
                      {lastCreatedRunId}
                    </Text>
                  </Stack>
                  <Button component={Link} to={`/runs/${lastCreatedRunId}`}>
                    Open Run
                  </Button>
                </Group>
              </Card>
            ) : null}

            {createdRunIds.length > 0 ? (
              <Card withBorder>
                <Stack gap="xs">
                  <Text fw={600}>Runs created (this session)</Text>
                  {createdRunIds.map((id) => (
                    <Group key={id} justify="space-between">
                      <Text size="xs" c="dimmed">
                        {id}
                      </Text>
                      <Button component={Link} to={`/runs/${id}`} size="xs" variant="light">
                        Open
                      </Button>
                    </Group>
                  ))}
                </Stack>
              </Card>
            ) : null}
          </Stack>
        </Card>
      )}

      {pr ? (
        <Card withBorder>
          <Stack gap="sm">
            <Group justify="space-between">
              <Text fw={700}>Steps</Text>
              <Button variant="light" onClick={load} loading={loading}>
                Refresh
              </Button>
            </Group>

            {pr.steps.length === 0 ? (
              <Text c="dimmed">No steps found in this pipeline run.</Text>
            ) : (
              <Stack gap="xs">
                {pr.steps.map((s: PipelineStep) => (
                  <Card key={s.id} withBorder>
                    <Group justify="space-between" align="flex-start">
                      <Stack gap={2}>
                        <Group gap="sm">
                          <Badge variant="light">#{s.step_index}</Badge>
                          <Badge color={stepColor(s.status)}>{s.status}</Badge>
                          <Text fw={700}>{s.step_name}</Text>
                          <Text size="sm" c="dimmed">
                            agent: {s.agent_id}
                          </Text>
                        </Group>
                        <Text size="xs" c="dimmed">
                          step_id={s.id}
                        </Text>
                      </Stack>

                      {s.run_id ? (
                        <Button component={Link} to={`/runs/${s.run_id}`}>
                          Open Run
                        </Button>
                      ) : (
                        <Badge variant="outline">run_id: null</Badge>
                      )}
                    </Group>
                  </Card>
                ))}
              </Stack>
            )}
          </Stack>
        </Card>
      ) : null}
    </Stack>
  );
}