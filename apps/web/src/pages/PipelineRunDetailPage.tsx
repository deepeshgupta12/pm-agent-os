import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge, Button, Card, Group, Stack, Text, Title, Divider, Code } from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { PipelineRun, PipelineStep, Run } from "../types";

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

type RetrievalMeta = {
  enabled?: boolean;
  query?: string;
  evidence_count?: number;
  batch_id?: string;
  batch_kind?: string;
};

function stepColor(status: string): string {
  const s = (status || "").toLowerCase();
  if (s === "completed") return "green";
  if (s === "running") return "blue";
  if (s === "failed") return "red";
  return "gray";
}

function extractRetrievalMeta(run: Run | null): RetrievalMeta | null {
  if (!run) return null;
  const ip: any = run.input_payload ?? {};
  const r = ip?._retrieval;
  if (!r || typeof r !== "object") return null;
  return {
    enabled: Boolean(r.enabled),
    query: typeof r.query === "string" ? r.query : undefined,
    evidence_count: typeof r.evidence_count === "number" ? r.evidence_count : undefined,
    batch_id: typeof r.batch_id === "string" ? r.batch_id : undefined,
    batch_kind: typeof r.batch_kind === "string" ? r.batch_kind : undefined,
  };
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

  // NEW: per-step run retrieval metadata (fetched from /runs/{run_id})
  const [runMetaById, setRunMetaById] = useState<Record<string, { retrieval: RetrievalMeta | null }>>({});

  const canExecute = useMemo(() => {
    if (!pr) return false;
    const s = (pr.status || "").toLowerCase();
    return s !== "completed" && s !== "failed";
  }, [pr]);

  async function load() {
    if (!prid) return;
    setErr(null);
    setLoading(true);

    // V3.1 alias endpoint
    const res = await apiFetch<PipelineRun>(`/pipeline-runs/${prid}`, { method: "GET" });

    setLoading(false);

    if (!res.ok) {
      setErr(`Pipeline run load failed: ${res.status} ${res.error}`);
      return;
    }

    setPr(res.data);
  }

  async function loadRunMetasForSteps(p: PipelineRun) {
    const runIds = (p.steps || [])
      .map((s) => s.run_id)
      .filter((x): x is string => Boolean(x));

    if (runIds.length === 0) return;

    // Fetch only missing run_ids
    const missing = runIds.filter((rid) => !runMetaById[rid]);
    if (missing.length === 0) return;

    // Basic fan-out (safe: small N)
    const results = await Promise.all(
      missing.map(async (rid) => {
        const r = await apiFetch<Run>(`/runs/${rid}`, { method: "GET" });
        if (!r.ok) return { rid, run: null as Run | null };
        return { rid, run: r.data };
      })
    );

    setRunMetaById((prev) => {
      const next = { ...prev };
      for (const it of results) {
        next[it.rid] = { retrieval: extractRetrievalMeta(it.run) };
      }
      return next;
    });
  }

  async function executeNext() {
    if (!prid) return;
    setErr(null);
    setExecLoading(true);

    // V3.1 alias endpoint
    const res = await apiFetch<NextResponse>(`/pipeline-runs/${prid}/execute-next`, {
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
      // fetch retrieval meta for the newly created run
      await loadRunMetasForSteps(res.data.pipeline_run);
    }
  }

  async function executeAll() {
    if (!prid) return;
    setErr(null);
    setExecAllLoading(true);

    // V3.1 alias endpoint
    const res = await apiFetch<ExecuteAllResponse>(`/pipeline-runs/${prid}/execute-all`, {
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
        const seen = new Set<string>();
        return merged.filter((x) => {
          if (seen.has(x)) return false;
          seen.add(x);
          return true;
        });
      });
    }

    await loadRunMetasForSteps(res.data.pipeline_run);
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prid]);

  // whenever pipeline run updates, fetch per-step run retrieval meta
  useEffect(() => {
    if (!pr) return;
    void loadRunMetasForSteps(pr);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pr?.id, pr?.steps?.map((s) => s.run_id).join("|")]);

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
                <Badge color={stepColor(pr.status)}>{pr.status}</Badge>
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
              <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(pr.input_payload, null, 2)}</pre>
            </Card>

            <Group gap="sm">
              <Button onClick={executeNext} disabled={!canExecute} loading={execLoading}>
                Execute next step
              </Button>
              <Button onClick={executeAll} disabled={!canExecute} loading={execAllLoading} variant="light">
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
                    Open Run Console
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
                        Open Console
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
                {pr.steps.map((s: PipelineStep) => {
                  let ctxLabel = "Prev artifact context: N/A";
                  if (s.step_index === 0) {
                    ctxLabel = "Prev artifact context: N/A (step 0)";
                  } else if (!s.run_id) {
                    ctxLabel = "Prev artifact context: — (run not created yet)";
                  } else if (s.prev_context_attached === true) {
                    ctxLabel = "Prev artifact context attached ✅";
                  } else if (s.prev_context_attached === false) {
                    ctxLabel = "Prev artifact context: not attached";
                  } else {
                    ctxLabel = "Prev artifact context: unknown";
                  }

                  let regenLabel = "Regeneration: —";
                  if (s.step_index === 0) {
                    regenLabel = "Regeneration: N/A (step 0)";
                  } else if (!s.run_id) {
                    regenLabel = "Regeneration: — (run not created yet)";
                  } else if (s.auto_regenerated === true) {
                    const v = s.latest_artifact_version ?? null;
                    regenLabel = v ? `Regenerated ✅ (latest v${v})` : "Regenerated ✅";
                  } else if (s.auto_regenerated === false) {
                    regenLabel = "Regeneration: not regenerated";
                  } else {
                    regenLabel = "Regeneration: unknown";
                  }

                  const hasLatestArtifact = !!s.latest_artifact_id;
                  const runId = s.run_id || null;
                  const retrieval = runId ? runMetaById[runId]?.retrieval ?? null : null;

                  return (
                    <Card key={s.id} withBorder>
                      <Group justify="space-between" align="flex-start">
                        <Stack gap={6} style={{ flex: 1 }}>
                          <Group gap="sm">
                            <Badge variant="light">#{s.step_index}</Badge>
                            <Badge color={stepColor(s.status)}>{s.status}</Badge>
                            <Text fw={700}>{s.step_name}</Text>
                            <Text size="sm" c="dimmed">
                              agent: {s.agent_id}
                            </Text>
                            {s.status?.toLowerCase() === "failed" ? (
                              <Badge color="red" variant="light">
                                Failed
                              </Badge>
                            ) : null}
                          </Group>

                          <Text size="xs" c="dimmed">
                            step_id={s.id}
                          </Text>

                          {runId ? (
                            <Text size="xs" c="dimmed">
                              run_id=<Code>{runId}</Code>
                            </Text>
                          ) : (
                            <Text size="xs" c="dimmed">
                              run_id=<Code>null</Code>
                            </Text>
                          )}

                          <Text size="sm" c="dimmed">
                            {ctxLabel}
                          </Text>

                          <Text size="sm" c="dimmed">
                            {regenLabel}
                          </Text>

                          <Divider />

                          <Group justify="space-between">
                            <Text fw={600}>Step Retrieval</Text>
                            {retrieval?.enabled ? (
                              <Badge variant="light">evidence: {retrieval.evidence_count ?? 0}</Badge>
                            ) : (
                              <Badge variant="outline">disabled</Badge>
                            )}
                          </Group>

                          {retrieval?.enabled ? (
                            <Text size="sm" c="dimmed">
                              query: <Code>{retrieval.query ?? "(missing)"}</Code>
                            </Text>
                          ) : (
                            <Text size="sm" c="dimmed">
                              No retrieval metadata yet (run not created OR retrieval disabled).
                            </Text>
                          )}

                          {hasLatestArtifact ? (
                            <Text size="xs" c="dimmed">
                              Latest artifact: {s.latest_artifact_title ?? "(untitled)"}{" "}
                              {s.latest_artifact_type ? `(${s.latest_artifact_type})` : ""}
                            </Text>
                          ) : null}
                        </Stack>

                        <Stack gap="xs" align="flex-end">
                          {runId ? (
                            <Button component={Link} to={`/runs/${runId}`}>
                              Open Run Console
                            </Button>
                          ) : (
                            <Badge variant="outline">run_id: null</Badge>
                          )}

                          {hasLatestArtifact ? (
                            <Button component={Link} to={`/artifacts/${s.latest_artifact_id}`} variant="light">
                              Open Latest Artifact
                            </Button>
                          ) : null}
                        </Stack>
                      </Group>
                    </Card>
                  );
                })}
              </Stack>
            )}
          </Stack>
        </Card>
      ) : null}
    </Stack>
  );
}