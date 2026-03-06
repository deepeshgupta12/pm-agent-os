// apps/web/src/pages/ApprovalsPage.tsx
import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Group, Stack, Text } from "@mantine/core";
import { Link } from "react-router-dom";
import { apiFetch } from "../apiClient";
import type { ActionItem, Workspace } from "../types";

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

export default function ApprovalsPage() {
  const wid = readLastWorkspaceId();

  const [ws, setWs] = useState<Workspace | null>(null);
  const [queued, setQueued] = useState<ActionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const total = useMemo(() => queued.length, [queued.length]);

  async function load() {
    if (!wid) return;
    setErr(null);
    setLoading(true);

    const wsRes = await apiFetch<Workspace>(`/workspaces/${wid}`, { method: "GET" });
    if (wsRes.ok) setWs(wsRes.data);

    const res = await apiFetch<ActionItem[]>(`/workspaces/${wid}/actions?status=queued`, { method: "GET" });
    setLoading(false);

    if (!res.ok) {
      setQueued([]);
      setErr(`Failed to load approvals: ${res.status} ${res.error}`);
      return;
    }

    setQueued(res.data || []);
  }

  useEffect(() => {
    if (!wid) return;
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid]);

  if (!wid) {
    return (
      <GlassPage
        title="Approvals"
        subtitle="Review queued items and publish requests."
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
          description="Choose a workspace to view approvals."
          primaryLabel="Go to Workspaces"
          primaryTo="/workspaces"
        />
      </GlassPage>
    );
  }

  return (
    <GlassPage
      title="Approvals"
      subtitle={ws?.name ? `Workspace: ${ws.name}` : "Workspace approvals"}
      right={
        <Group>
          <Button component={Link} to={`/workspaces/${wid}/actions`} size="sm" variant="light">
            Open Action Center
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

        <GlassSection title="Queued approvals" description="Items awaiting a decision." right={<GlassStat label="Queued" value={total} />}>
          {queued.length === 0 ? (
            <Text c="dimmed">No queued approvals right now.</Text>
          ) : (
            <Stack gap="xs">
              {queued.slice(0, 50).map((a) => (
                <GlassCard key={a.id} p="md">
                  <Group justify="space-between" align="flex-start">
                    <Stack gap={4}>
                      <Group gap="sm">
                        <Badge variant="light">{a.status}</Badge>
                        <Text fw={700}>{a.title}</Text>
                      </Group>
                      <Text size="sm" c="dimmed">
                        type={a.type} · action_id={a.id}
                      </Text>
                    </Stack>

                    <Button component={Link} to={`/workspaces/${wid}/actions`} size="sm" variant="light">
                      Review
                    </Button>
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