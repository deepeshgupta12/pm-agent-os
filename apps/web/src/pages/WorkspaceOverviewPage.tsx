// apps/web/src/pages/WorkspaceOverviewPage.tsx
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge, Button, Divider, Group, SimpleGrid, Stack, Text, Collapse } from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { Run, Workspace, WorkspaceRole, ActionItem } from "../types";

import GlassPage from "../components/Glass/GlassPage";
import GlassCard from "../components/Glass/GlassCard";
import GlassSection from "../components/Glass/GlassSection";
import GlassStat from "../components/Glass/GlassStat";

type Counts = {
  queuedActions?: number;
  recentRuns?: number;
};

function shortId(id: string): string {
  if (!id) return "";
  return id.length <= 10 ? id : `${id.slice(0, 8)}…`;
}

export default function WorkspaceOverviewPage() {
  const { workspaceId } = useParams();
  const wid = workspaceId || "";

  const [ws, setWs] = useState<Workspace | null>(null);
  const [myRole, setMyRole] = useState<WorkspaceRole | null>(null);

  const [runs, setRuns] = useState<Run[]>([]);
  const [counts, setCounts] = useState<Counts>({});

  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const [advancedOpen, setAdvancedOpen] = useState(false);

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

    const actionsRes = await apiFetch<ActionItem[]>(`/workspaces/${wid}/actions?status=queued`, { method: "GET" });
    if (actionsRes.ok) {
      setCounts((c) => ({ ...c, queuedActions: (actionsRes.data || []).length }));
    }

    setLoading(false);
  }

  useEffect(() => {
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid]);

  const headerRight = (
    <Group>
      <Button component={Link} to={`/workspaces/${wid}`} variant="light" size="sm">
        Guided mode
      </Button>
      <Button component={Link} to={`/run-builder/${wid}`} size="sm">
        Create run
      </Button>
      <Button variant="light" onClick={loadAll} loading={loading} size="sm">
        Refresh
      </Button>
    </Group>
  );

  const statsRight = (
    <Group gap="sm" wrap="wrap">
      {roleBadge}
      {typeof counts.queuedActions === "number" ? <GlassStat label="Approvals" value={counts.queuedActions} /> : null}
      {typeof counts.recentRuns === "number" ? <GlassStat label="Runs" value={counts.recentRuns} /> : null}
      <GlassStat label="Access" value={isAdmin ? "Admin" : "Read-only"} />
    </Group>
  );

  return (
    <GlassPage
      title={ws?.name ? `Workspace · ${ws.name}` : "Workspace"}
      subtitle="Workspace shortcuts and recent activity."
      right={headerRight}
    >
      <Stack gap="md">
        {err ? (
          <GlassCard>
            <Text c="red">{err}</Text>
          </GlassCard>
        ) : null}

        <GlassSection
          title={ws?.name ? ws.name : "Loading…"}
          description="Overview (IDs hidden by default)"
          right={statsRight}
        >
          <Divider />

          <Group justify="space-between" align="center">
            <Text size="sm" c="dimmed">
              Use Guided mode for the main workflow. Overview is for shortcuts and context.
            </Text>
            <Button variant="light" size="xs" onClick={() => setAdvancedOpen((x) => !x)}>
              {advancedOpen ? "Hide advanced" : "Show advanced"}
            </Button>
          </Group>

          <Collapse in={advancedOpen}>
            <GlassCard p="md" mt="sm">
              <Stack gap={6}>
                <Text fw={700}>Advanced details</Text>
                <Text size="sm" c="dimmed">
                  Workspace ID: <b>{shortId(wid)}</b>
                </Text>
              </Stack>
            </GlassCard>
          </Collapse>

          <Divider my="md" />

          <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="md">
            <GlassCard p="md">
              <Stack gap={8}>
                <Text fw={700}>Create run</Text>
                <Text size="sm" c="dimmed">
                  Create a run using an agent. Use references only if needed.
                </Text>
                <Group>
                  <Button component={Link} to={`/run-builder/${wid}`} variant="light" size="sm">
                    Open
                  </Button>
                </Group>
              </Stack>
            </GlassCard>

            <GlassCard p="md">
              <Stack gap={8}>
                <Group justify="space-between">
                  <Text fw={700}>Approvals</Text>
                  {typeof counts.queuedActions === "number" ? <GlassStat label="Queued" value={counts.queuedActions} /> : null}
                </Group>
                <Text size="sm" c="dimmed">
                  Review publish requests and approval items.
                </Text>
                <Group>
                  <Button component={Link} to={`/workspaces/${wid}/actions`} variant="light" size="sm">
                    Open Action Center
                  </Button>
                </Group>
              </Stack>
            </GlassCard>

            <GlassCard p="md">
              <Stack gap={8}>
                <Text fw={700}>Docs</Text>
                <Text size="sm" c="dimmed">
                  Ingest and search workspace knowledge.
                </Text>
                <Group>
                  <Button component={Link} to={`/workspaces/${wid}/docs`} variant="light" size="sm">
                    Open
                  </Button>
                </Group>
              </Stack>
            </GlassCard>

            <GlassCard p="md">
              <Stack gap={8}>
                <Text fw={700}>Schedules</Text>
                <Text size="sm" c="dimmed">
                  Automate recurring runs.
                </Text>
                <Group>
                  <Button component={Link} to={`/workspaces/${wid}/schedules`} variant="light" size="sm">
                    Open
                  </Button>
                </Group>
              </Stack>
            </GlassCard>

            <GlassCard p="md">
              <Stack gap={8}>
                <Text fw={700}>Pipelines</Text>
                <Text size="sm" c="dimmed">
                  Execute multi-step workflows.
                </Text>
                <Group>
                  <Button component={Link} to={`/workspaces/${wid}/pipelines`} variant="light" size="sm">
                    Open
                  </Button>
                </Group>
              </Stack>
            </GlassCard>

            <GlassCard p="md">
              <Stack gap={8}>
                <Text fw={700}>Agent builder</Text>
                <Text size="sm" c="dimmed">
                  Create and publish agent versions.
                </Text>
                <Group>
                  <Button component={Link} to={`/workspaces/${wid}/agent-builder`} variant="light" size="sm">
                    Open
                  </Button>
                </Group>
              </Stack>
            </GlassCard>
          </SimpleGrid>
        </GlassSection>

        <GlassSection
          title="Workspace settings"
          description="Rules and audit logs (advanced)."
          right={
            <Group gap="sm" wrap="wrap">
              <GlassStat label="Access" value={isAdmin ? "Admin" : "Read-only"} />
            </Group>
          }
        >
          <SimpleGrid cols={{ base: 1, sm: 2, md: 3 }} spacing="md">
            <GlassCard p="md">
              <Stack gap={8}>
                <Text fw={700}>Workspace rules</Text>
                <Text size="sm" c="dimmed">
                  Internal-only, allowed sources, retention.
                </Text>
                <Group>
                  <Button component={Link} to={`/workspaces/${wid}/policy`} variant="light" size="sm">
                    Open
                  </Button>
                </Group>
              </Stack>
            </GlassCard>

            <GlassCard p="md">
              <Stack gap={8}>
                <Text fw={700}>Audit log</Text>
                <Text size="sm" c="dimmed">
                  Governance events and decisions.
                </Text>
                <Group>
                  <Button component={Link} to={`/workspaces/${wid}/governance`} variant="light" size="sm">
                    Open
                  </Button>
                </Group>
              </Stack>
            </GlassCard>

            <GlassCard p="md">
              <Stack gap={8}>
                <Text fw={700}>Members</Text>
                <Text size="sm" c="dimmed">
                  Roles and access (legacy admin).
                </Text>
                <Group>
                  <Button component={Link} to={`/workspaces/${wid}/_legacy`} variant="light" size="sm">
                    Open
                  </Button>
                </Group>
              </Stack>
            </GlassCard>
          </SimpleGrid>

          {!isMemberPlus ? (
            <Text size="sm" c="dimmed" mt="sm">
              Some actions may be limited by your role.
            </Text>
          ) : null}
        </GlassSection>

        <GlassSection
          title="Recent runs"
          description="Latest activity (IDs hidden by default)."
          right={typeof counts.recentRuns === "number" ? <GlassStat label="Total" value={counts.recentRuns} /> : undefined}
        >
          {runs.length === 0 ? (
            <Text c="dimmed">No runs yet.</Text>
          ) : (
            <Stack gap="xs">
              {runs.map((r) => (
                <GlassCard key={r.id} p="md">
                  <Group justify="space-between" align="flex-start">
                    <Stack gap={6}>
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
                        Run: {shortId(r.id)}
                      </Text>
                    </Stack>

                    <Button component={Link} to={`/runs/${r.id}`} variant="light" size="sm">
                      Open
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