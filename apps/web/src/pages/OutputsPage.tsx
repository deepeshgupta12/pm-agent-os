// apps/web/src/pages/OutputsPage.tsx
import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Group, Stack, Text } from "@mantine/core";
import { Link } from "react-router-dom";
import { apiFetch } from "../apiClient";
import type { Artifact, Run, Workspace } from "../types";

import GlassPage from "../components/Glass/GlassPage";
import GlassCard from "../components/Glass/GlassCard";
import GlassSection from "../components/Glass/GlassSection";
import GlassStat from "../components/Glass/GlassStat";
import EmptyState from "../components/Glass/EmptyState";

const LAST_WS_KEY = "pmos:lastWorkspaceId";

function readLastWorkspaceId(): string | null {
  try {
    const v = window.localStorage.getItem(LAST_WS_KEY);
    if (!v) return null;
    return /^[0-9a-fA-F-]{36}$/.test(v) ? v : null;
  } catch {
    return null;
  }
}

type OutputRow = {
  run: Run;
  artifact: Artifact | null;
};

export default function OutputsPage() {
  const wid = readLastWorkspaceId();

  const [ws, setWs] = useState<Workspace | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [rows, setRows] = useState<OutputRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const total = useMemo(() => rows.length, [rows.length]);

  async function load() {
    if (!wid) return;
    setErr(null);
    setLoading(true);

    const wsRes = await apiFetch<Workspace>(`/workspaces/${wid}`, { method: "GET" });
    if (wsRes.ok) setWs(wsRes.data);

    const runsRes = await apiFetch<Run[]>(`/workspaces/${wid}/runs`, { method: "GET" });
    if (!runsRes.ok) {
      setLoading(false);
      setRuns([]);
      setRows([]);
      setErr(`Failed to load runs: ${runsRes.status} ${runsRes.error}`);
      return;
    }

    const list = (runsRes.data || []).slice(0, 12);
    setRuns(list);

    // For each run, fetch artifacts and take latest (index 0)
    const out: OutputRow[] = await Promise.all(
      list.map(async (r) => {
        const aRes = await apiFetch<Artifact[]>(`/runs/${r.id}/artifacts`, { method: "GET" });
        if (!aRes.ok) return { run: r, artifact: null };
        const arts = aRes.data || [];
        return { run: r, artifact: arts.length ? arts[0] : null };
      })
    );

    setRows(out.filter((x) => !!x.artifact));
    setLoading(false);
  }

  useEffect(() => {
    if (!wid) return;
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid]);

  if (!wid) {
    return (
      <GlassPage
        title="Outputs"
        subtitle="Browse generated artifacts."
        right={
          <Group>
            <Button component={Link} to="/workspaces" size="sm">
              Select workspace
            </Button>
          </Group>
        }
      >
        <EmptyState
          title="No workspace selected"
          description="Choose a workspace to view outputs."
          primaryLabel="Go to Workspaces"
          primaryTo="/workspaces"
        />
      </GlassPage>
    );
  }

  return (
    <GlassPage
      title="Outputs"
      subtitle={ws?.name ? `Workspace: ${ws.name}` : "Workspace outputs"}
      right={
        <Group>
          <Button component={Link} to={`/run-builder/${wid}`} size="sm">
            Create run
          </Button>
          <Button variant="light" onClick={load} loading={loading} size="sm">
            Refresh
          </Button>
        </Group>
      }
    >
      <Stack gap="md">
        {err ? (
          <GlassCard>
            <Text c="red">{err}</Text>
          </GlassCard>
        ) : null}

        <GlassSection
          title="Recent outputs"
          description="Latest artifact per recent run (last 12 runs)."
          right={<GlassStat label="Shown" value={total} />}
        >
          {loading ? <Text c="dimmed">Loading…</Text> : null}

          {!loading && rows.length === 0 ? (
            <EmptyState
              title="No outputs found yet"
              description="Create a run to generate your first output."
              primaryLabel="Create run"
              primaryTo={`/run-builder/${wid}`}
              secondaryLabel="View runs"
              secondaryTo="/runs"
            />
          ) : (
            <Stack gap="xs">
              {rows.map((r) => {
                const a = r.artifact!;
                return (
                  <GlassCard key={a.id} p="md">
                    <Group justify="space-between" align="flex-start">
                      <Stack gap={4}>
                        <Group gap="sm">
                          <Badge variant="light">{a.status}</Badge>
                          <Text fw={700}>{a.title}</Text>
                        </Group>
                        <Text size="sm" c="dimmed">
                          {a.type} · v{a.version} · key={a.logical_key}
                        </Text>
                        <Text size="xs" c="dimmed">
                          artifact={a.id} · run={r.run.id}
                        </Text>
                      </Stack>

                      <Group gap="xs">
                        <Button component={Link} to={`/artifacts/${a.id}`} size="sm">
                          Open
                        </Button>
                        <Button component={Link} to={`/runs/${r.run.id}`} size="sm" variant="light">
                          Run
                        </Button>
                      </Group>
                    </Group>
                  </GlassCard>
                );
              })}
            </Stack>
          )}
        </GlassSection>

        <GlassSection title="Note" description="Global artifact indexing is coming later. This view uses recent runs to surface outputs.">
          <Text size="sm" c="dimmed">
            Once we add a dedicated workspace artifact index endpoint, this page becomes a true outputs list with
            filtering/search.
          </Text>
        </GlassSection>
      </Stack>
    </GlassPage>
  );
}