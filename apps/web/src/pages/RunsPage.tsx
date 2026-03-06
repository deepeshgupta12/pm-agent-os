// apps/web/src/pages/RunsPage.tsx
import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Group, Stack, Text } from "@mantine/core";
import { Link } from "react-router-dom";
import { apiFetch } from "../apiClient";
import type { Run, Workspace } from "../types";

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

export default function RunsPage() {
  const wid = readLastWorkspaceId();

  const [ws, setWs] = useState<Workspace | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const total = useMemo(() => runs.length, [runs.length]);

  async function load() {
    if (!wid) return;
    setErr(null);
    setLoading(true);

    const wsRes = await apiFetch<Workspace>(`/workspaces/${wid}`, { method: "GET" });
    if (wsRes.ok) setWs(wsRes.data);

    const res = await apiFetch<Run[]>(`/workspaces/${wid}/runs`, { method: "GET" });
    setLoading(false);

    if (!res.ok) {
      setRuns([]);
      setErr(`Failed to load runs: ${res.status} ${res.error}`);
      return;
    }
    setRuns(res.data || []);
  }

  useEffect(() => {
    if (!wid) return;
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid]);

  if (!wid) {
    return (
      <GlassPage
        title="Runs"
        subtitle="View run history across a workspace."
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
          description="Choose a workspace to view runs."
          primaryLabel="Go to Workspaces"
          primaryTo="/workspaces"
        />
      </GlassPage>
    );
  }

  return (
    <GlassPage
      title="Runs"
      subtitle={ws?.name ? `Workspace: ${ws.name}` : "Workspace runs"}
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
          title="Run history"
          description="Newest first."
          right={<GlassStat label="Total" value={total} />}
        >
          {runs.length === 0 ? (
            <Text c="dimmed">No runs yet.</Text>
          ) : (
            <Stack gap="xs">
              {runs.slice(0, 50).map((r) => (
                <GlassCard key={r.id} p="md">
                  <Group justify="space-between" align="flex-start">
                    <Stack gap={4}>
                      <Group gap="sm">
                        <Badge variant="light">{r.status}</Badge>
                        <Text fw={700}>{r.agent_id}</Text>
                      </Group>
                      {r.output_summary ? (
                        <Text size="sm" c="dimmed">
                          {r.output_summary}
                        </Text>
                      ) : null}
                      <Text size="xs" c="dimmed">
                        {r.id}
                      </Text>
                    </Stack>

                    <Group gap="xs">
                      <Button component={Link} to={`/runs/${r.id}`} size="sm" variant="light">
                        Open
                      </Button>
                    </Group>
                  </Group>
                </GlassCard>
              ))}
            </Stack>
          )}
        </GlassSection>
      </Stack>
    </GlassPage>
  );
}