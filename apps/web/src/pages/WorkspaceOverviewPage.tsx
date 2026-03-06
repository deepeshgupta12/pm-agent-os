// apps/web/src/pages/WorkspaceOverviewPage.tsx
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge, Button, Divider, Group, SimpleGrid, Stack, Text } from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { Run, Workspace, WorkspaceRole, ActionItem } from "../types";
import GlassCard from "../components/Glass/GlassCard";
import GlassPage from "../components/Glass/GlassPage";

type Counts = {
  queuedActions?: number;
  recentRuns?: number;
};

export default function WorkspaceOverviewPage() {
  const { workspaceId } = useParams();
  const wid = workspaceId || "";

  const [ws, setWs] = useState<Workspace | null>(null);
  const [myRole, setMyRole] = useState<WorkspaceRole | null>(null);

  const [runs, setRuns] = useState<Run[]>([]);
  const [counts, setCounts] = useState<Counts>({});

  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const roleStr = (myRole?.role || "").toLowerCase();
  const isAdmin = roleStr === "admin";
  const isMemberPlus = roleStr === "admin" || roleStr === "member";

  const roleBadge = useMemo(() => {
    if (!roleStr) return null;
    const c = roleStr === "admin" ? "grape" : roleStr === "member" ? "blue" : "gray";
    return (
      <Badge variant="light" color={c}>
        {roleStr}
      </Badge>
    );
  }, [roleStr]);

  async function loadAll() {
    if (!wid) return;
    setErr(null);
    setLoading(true);

    const wsRes = await apiFetch<Workspace>(`/workspaces/${wid}`, { method: "GET" });
    if (!wsRes.ok) {
      setLoading(false);
      setErr(`Workspace load failed: ${wsRes.status} ${wsRes.error}`);
      return;
    }
    setWs(wsRes.data);

    const roleRes = await apiFetch<WorkspaceRole>(`/workspaces/${wid}/my-role`, { method: "GET" });
    if (!roleRes.ok) {
      setLoading(false);
      setErr(`Role load failed: ${roleRes.status} ${roleRes.error}`);
      return;
    }
    setMyRole(roleRes.data);

    const runsRes = await apiFetch<Run[]>(`/workspaces/${wid}/runs`, { method: "GET" });
    if (runsRes.ok) {
      const all = runsRes.data || [];
      setRuns(all.slice(0, 5));
      setCounts((c) => ({ ...c, recentRuns: all.length }));
    } else {
      setRuns([]);
    }

    const actionsRes = await apiFetch<ActionItem[]>(
      `/workspaces/${wid}/actions?status=queued`,
      { method: "GET" }
    );
    if (actionsRes.ok) {
      setCounts((c) => ({ ...c, queuedActions: (actionsRes.data || []).length }));
    }

    setLoading(false);
  }

  useEffect(() => {
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid]);

  return (
    <GlassPage
      title={ws?.name ? `Workspace · ${ws.name}` : "Workspace"}
      subtitle="A calm starting point for runs, approvals, and governance."
      right={
        <Group>
          <Button component={Link} to="/workspaces" variant="light">
            Back
          </Button>
          <Button component={Link} to={`/run-builder/${wid}`}>
            Create run
          </Button>
          <Button variant="light" onClick={loadAll} loading={loading}>
            Refresh
          </Button>
        </Group>
      }
    >
      {err ? (
        <GlassCard>
          <Text c="red">{err}</Text>
        </GlassCard>
      ) : null}

      <GlassCard>
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Text fw={700}>{ws?.name || "Loading…"}</Text>
            <Text size="xs" c="dimmed">
              {ws?.id || wid}
            </Text>
          </Stack>

          <Group>{roleBadge}</Group>
        </Group>

        <Divider my="md" />

        <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="md">
          <GlassCard p="md">
            <Stack gap={6}>
              <Text fw={700}>Run Builder</Text>
              <Text size="sm" c="dimmed">
                Create a run using an agent and optional retrieval.
              </Text>
              <Button component={Link} to={`/run-builder/${wid}`} variant="light">
                Open Run Builder
              </Button>
            </Stack>
          </GlassCard>

          <GlassCard p="md">
            <Stack gap={6}>
              <Group justify="space-between">
                <Text fw={700}>Approvals</Text>
                {typeof counts.queuedActions === "number" ? (
                  <Badge variant="light">{counts.queuedActions} queued</Badge>
                ) : null}
              </Group>
              <Text size="sm" c="dimmed">
                Review approval items and execution outcomes.
              </Text>
              <Button component={Link} to={`/workspaces/${wid}/actions`} variant="light">
                Open Approvals
              </Button>
            </Stack>
          </GlassCard>

          <GlassCard p="md">
            <Stack gap={6}>
              <Text fw={700}>Docs</Text>
              <Text size="sm" c="dimmed">
                Ingest and search workspace knowledge.
              </Text>
              <Button component={Link} to={`/workspaces/${wid}/docs`} variant="light">
                Open Docs
              </Button>
            </Stack>
          </GlassCard>

          <GlassCard p="md">
            <Stack gap={6}>
              <Text fw={700}>Schedules</Text>
              <Text size="sm" c="dimmed">
                Automate runs on intervals.
              </Text>
              <Button component={Link} to={`/workspaces/${wid}/schedules`} variant="light">
                Open Schedules
              </Button>
            </Stack>
          </GlassCard>

          <GlassCard p="md">
            <Stack gap={6}>
              <Text fw={700}>Pipelines</Text>
              <Text size="sm" c="dimmed">
                Execute multi-step workflows.
              </Text>
              <Button component={Link} to={`/workspaces/${wid}/pipelines`} variant="light">
                Open Pipelines
              </Button>
            </Stack>
          </GlassCard>

          <GlassCard p="md">
            <Stack gap={6}>
              <Text fw={700}>Agent Builder</Text>
              <Text size="sm" c="dimmed">
                Create and publish agent versions.
              </Text>
              <Button component={Link} to={`/workspaces/${wid}/agent-builder`} variant="light">
                Open Agent Builder
              </Button>
            </Stack>
          </GlassCard>
        </SimpleGrid>
      </GlassCard>

      <GlassCard>
        <Group justify="space-between">
          <Group gap="sm">
            <Text fw={700}>Workspace settings</Text>
            <Badge variant="light" color={isAdmin ? "grape" : "gray"}>
              {isAdmin ? "admin" : "read-only"}
            </Badge>
          </Group>
        </Group>

        <Divider my="md" />

        <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="md">
          <GlassCard p="md">
            <Stack gap={6}>
              <Text fw={700}>Policy Center</Text>
              <Text size="sm" c="dimmed">
                Internal-only, allowlists, retention.
              </Text>
              <Button component={Link} to={`/workspaces/${wid}/policy`} variant="light">
                Open Policy Center
              </Button>
            </Stack>
          </GlassCard>

          <GlassCard p="md">
            <Stack gap={6}>
              <Text fw={700}>Audit log</Text>
              <Text size="sm" c="dimmed">
                Governance events (policy + RBAC).
              </Text>
              <Button component={Link} to={`/workspaces/${wid}/governance`} variant="light">
                Open Governance
              </Button>
            </Stack>
          </GlassCard>

          <GlassCard p="md">
            <Stack gap={6}>
              <Text fw={700}>Member management</Text>
              <Text size="sm" c="dimmed">
                Roles and access (legacy page).
              </Text>
              <Button component={Link} to={`/workspaces/${wid}/_legacy`} variant="light">
                Open Members
              </Button>
            </Stack>
          </GlassCard>
        </SimpleGrid>

        {!isMemberPlus ? (
          <Text size="sm" c="dimmed" mt="sm">
            Some actions may be limited by your role.
          </Text>
        ) : null}
      </GlassCard>

      <GlassCard>
        <Group justify="space-between" align="center">
          <Text fw={700}>Recent runs</Text>
          {typeof counts.recentRuns === "number" ? (
            <Text size="sm" c="dimmed">
              total: {counts.recentRuns}
            </Text>
          ) : null}
        </Group>

        <Divider my="md" />

        {runs.length === 0 ? (
          <Text c="dimmed">No runs yet.</Text>
        ) : (
          <Stack gap="xs">
            {runs.map((r) => (
              <GlassCard key={r.id} p="md">
                <Group justify="space-between" align="flex-start">
                  <Stack gap={4}>
                    <Group gap="sm">
                      <Badge variant="light">{r.status}</Badge>
                      <Text fw={600}>{r.agent_id}</Text>
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

                  <Button component={Link} to={`/runs/${r.id}`} variant="light">
                    Open
                  </Button>
                </Group>
              </GlassCard>
            ))}
          </Stack>
        )}
      </GlassCard>
    </GlassPage>
  );
}