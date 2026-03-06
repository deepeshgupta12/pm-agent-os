// apps/web/src/pages/WorkspaceOverviewPage.tsx
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Divider,
  Group,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { Run, Workspace, WorkspaceRole, ActionItem } from "../types";

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

    // Recent runs (we keep it lightweight: show last 5)
    const runsRes = await apiFetch<Run[]>(`/workspaces/${wid}/runs`, { method: "GET" });
    if (runsRes.ok) {
      const all = runsRes.data || [];
      setRuns(all.slice(0, 5));
      setCounts((c) => ({ ...c, recentRuns: all.length }));
    } else {
      setRuns([]);
      // Do not hard-fail the page if runs fail
    }

    // Pending approvals count (Action Center)
    // If RBAC blocks, treat as 0/unknown without failing page.
    const actionsRes = await apiFetch<ActionItem[]>(
      `/workspaces/${wid}/actions?status=queued`,
      { method: "GET" }
    );
    if (actionsRes.ok) {
      setCounts((c) => ({ ...c, queuedActions: (actionsRes.data || []).length }));
    } else {
      // no-op
    }

    setLoading(false);
  }

  useEffect(() => {
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid]);

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start">
        <Stack gap={2}>
          <Title order={2}>Workspace</Title>
          <Text size="sm" c="dimmed">
            A clean starting point for runs, approvals, and governance.
          </Text>
        </Stack>

        <Group>
          <Button component={Link} to="/workspaces" variant="light">
            Back
          </Button>
          <Button component={Link} to={`/run-builder/${wid}`}>
            Create run
          </Button>
        </Group>
      </Group>

      {err ? (
        <Card withBorder>
          <Text c="red">{err}</Text>
        </Card>
      ) : null}

      <Card withBorder>
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Text fw={700}>{ws?.name || "Loading…"}</Text>
            <Text size="xs" c="dimmed">
              {ws?.id || wid}
            </Text>
          </Stack>

          <Group>
            {roleBadge}
            <Button variant="light" onClick={loadAll} loading={loading}>
              Refresh
            </Button>
          </Group>
        </Group>

        <Divider my="md" />

        <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="md">
          <Card withBorder>
            <Stack gap={6}>
              <Text fw={700}>Run Builder</Text>
              <Text size="sm" c="dimmed">
                Create a new run using an agent + optional retrieval.
              </Text>
              <Button component={Link} to={`/run-builder/${wid}`} variant="light">
                Open Run Builder
              </Button>
            </Stack>
          </Card>

          <Card withBorder>
            <Stack gap={6}>
              <Group justify="space-between">
                <Text fw={700}>Approvals</Text>
                {typeof counts.queuedActions === "number" ? (
                  <Badge variant="light">{counts.queuedActions} queued</Badge>
                ) : null}
              </Group>
              <Text size="sm" c="dimmed">
                Review and track approval items.
              </Text>
              <Button component={Link} to={`/workspaces/${wid}/actions`} variant="light">
                Open Approvals
              </Button>
            </Stack>
          </Card>

          <Card withBorder>
            <Stack gap={6}>
              <Text fw={700}>Docs</Text>
              <Text size="sm" c="dimmed">
                View ingested documents and sources.
              </Text>
              <Button component={Link} to={`/workspaces/${wid}/docs`} variant="light">
                Open Docs
              </Button>
            </Stack>
          </Card>

          <Card withBorder>
            <Stack gap={6}>
              <Text fw={700}>Schedules</Text>
              <Text size="sm" c="dimmed">
                Automate runs on cron or intervals.
              </Text>
              <Button component={Link} to={`/workspaces/${wid}/schedules`} variant="light">
                Open Schedules
              </Button>
            </Stack>
          </Card>

          <Card withBorder>
            <Stack gap={6}>
              <Text fw={700}>Pipelines</Text>
              <Text size="sm" c="dimmed">
                Run multi-step workflows.
              </Text>
              <Button component={Link} to={`/workspaces/${wid}/pipelines`} variant="light">
                Open Pipelines
              </Button>
            </Stack>
          </Card>

          <Card withBorder>
            <Stack gap={6}>
              <Text fw={700}>Agent Builder</Text>
              <Text size="sm" c="dimmed">
                Create and publish agent versions.
              </Text>
              <Button component={Link} to={`/workspaces/${wid}/agent-builder`} variant="light">
                Open Agent Builder
              </Button>
            </Stack>
          </Card>
        </SimpleGrid>
      </Card>

      <Card withBorder>
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
          <Card withBorder>
            <Stack gap={6}>
              <Text fw={700}>Workspace rules</Text>
              <Text size="sm" c="dimmed">
                Policy controls: internal-only, retention, allowlists.
              </Text>
              <Button component={Link} to={`/workspaces/${wid}/policy`} variant="light">
                Open Policy Center
              </Button>
            </Stack>
          </Card>

          <Card withBorder>
            <Stack gap={6}>
              <Text fw={700}>Audit log</Text>
              <Text size="sm" c="dimmed">
                Governance events (policy + RBAC decisions).
              </Text>
              <Button component={Link} to={`/workspaces/${wid}/governance`} variant="light">
                Open Governance
              </Button>
            </Stack>
          </Card>

          <Card withBorder>
            <Stack gap={6}>
              <Text fw={700}>Members</Text>
              <Text size="sm" c="dimmed">
                Manage roles and access (currently on legacy page).
              </Text>
              <Button component={Link} to={`/workspaces/${wid}/_legacy`} variant="light">
                Open Member Management
              </Button>
            </Stack>
          </Card>
        </SimpleGrid>

        {!isMemberPlus ? (
          <Text size="sm" c="dimmed" mt="sm">
            Some actions may be limited by your role.
          </Text>
        ) : null}
      </Card>

      <Card withBorder>
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
              <Card key={r.id} withBorder>
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
              </Card>
            ))}
          </Stack>
        )}
      </Card>
    </Stack>
  );
}