// apps/web/src/pages/WorkspaceGuidedPage.tsx
import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Group, Stack, Text, SimpleGrid, Divider } from "@mantine/core";
import { Link, useParams } from "react-router-dom";
import { apiFetch } from "../apiClient";
import type { Artifact, Run, Workspace, ActionItem, WorkspaceRole } from "../types";

import GlassPage from "../components/Glass/GlassPage";
import GlassCard from "../components/Glass/GlassCard";
import GlassSection from "../components/Glass/GlassSection";
import GlassStat from "../components/Glass/GlassStat";
import EmptyState from "../components/Glass/EmptyState";

type Latest = {
  run: Run | null;
  artifact: Artifact | null;
};

function roleBadgeColor(role: string | null): string {
  if (role === "admin") return "grape";
  if (role === "member") return "blue";
  if (role === "viewer") return "gray";
  return "dark";
}

function shortId(id: string): string {
  if (!id) return "";
  return id.length <= 10 ? id : `${id.slice(0, 8)}…`;
}

export default function WorkspaceGuidedPage() {
  const { workspaceId } = useParams();
  const wid = workspaceId || "";

  const [ws, setWs] = useState<Workspace | null>(null);
  const [myRole, setMyRole] = useState<WorkspaceRole | null>(null);

  const [latest, setLatest] = useState<Latest>({ run: null, artifact: null });
  const [queuedApprovals, setQueuedApprovals] = useState<ActionItem[]>([]);

  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const roleStr = (myRole?.role || "").toLowerCase() || null;

  const approvalsCount = useMemo(() => queuedApprovals.length, [queuedApprovals.length]);

  async function loadLatestArtifactForRun(runId: string): Promise<Artifact | null> {
    const aRes = await apiFetch<Artifact[]>(`/runs/${runId}/artifacts`, { method: "GET" });
    if (!aRes.ok) return null;
    const arts = aRes.data || [];
    return arts.length ? arts[0] : null; // newest first
  }

  async function load() {
    if (!wid) return;
    setErr(null);
    setLoading(true);

    // workspace
    const wsRes = await apiFetch<Workspace>(`/workspaces/${wid}`, { method: "GET" });
    if (!wsRes.ok) {
      setLoading(false);
      setErr(`Workspace load failed: ${wsRes.status} ${wsRes.error}`);
      return;
    }
    setWs(wsRes.data);

    // role
    const roleRes = await apiFetch<WorkspaceRole>(`/workspaces/${wid}/my-role`, { method: "GET" });
    if (roleRes.ok) setMyRole(roleRes.data);

    // approvals
    const apRes = await apiFetch<ActionItem[]>(`/workspaces/${wid}/actions?status=queued`, { method: "GET" });
    if (apRes.ok) setQueuedApprovals(apRes.data || []);
    else setQueuedApprovals([]);

    // latest run
    const runsRes = await apiFetch<Run[]>(`/workspaces/${wid}/runs`, { method: "GET" });
    if (!runsRes.ok) {
      setLatest({ run: null, artifact: null });
      setLoading(false);
      setErr(`Runs load failed: ${runsRes.status} ${runsRes.error}`);
      return;
    }

    const runs = runsRes.data || [];
    const first = runs.length ? runs[0] : null;

    if (!first) {
      setLatest({ run: null, artifact: null });
      setLoading(false);
      return;
    }

    const art = await loadLatestArtifactForRun(first.id);
    setLatest({ run: first, artifact: art });

    setLoading(false);
  }

  useEffect(() => {
    if (!wid) return;
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid]);

  const step1Cta = `/run-builder/${wid}`;
  const step2ArtifactHref = latest.artifact ? `/artifacts/${latest.artifact.id}` : null;
  const step2RunHref = latest.run ? `/runs/${latest.run.id}` : null;

  const step3PrimaryHref = step2ArtifactHref; // request publish happens from artifact page
  const step4ApprovalsHref = `/workspaces/${wid}/actions`;
  const step5SchedulesHref = `/workspaces/${wid}/schedules`;

  const artifactStatus = latest.artifact?.status || null;

  const step2Status = latest.artifact
    ? `Latest output ready (${artifactStatus})`
    : latest.run
      ? "Run exists, but no outputs yet"
      : "No run yet";

  const step3Status = !latest.artifact
    ? "Create an output first"
    : artifactStatus === "final"
      ? "Already published"
      : artifactStatus === "in_review"
        ? "In review (locked)"
        : "Draft — request publish when ready";

  const step4Status = approvalsCount === 0 ? "No approvals queued" : `${approvalsCount} queued approval(s)`;

  return (
    <GlassPage
      title="Guided mode"
      subtitle={ws?.name ? `Workspace: ${ws.name}` : "A guided workflow for shipping outputs."}
      right={
        <Group>
          <Button component={Link} to={`/workspaces/${wid}/overview`} variant="light" size="sm">
            Overview
          </Button>
          <Button variant="light" onClick={load} loading={loading} size="sm">
            Refresh
          </Button>
        </Group>
      }
    >
      {!wid ? (
        <EmptyState
          title="No workspace selected"
          description="Open a workspace to use Guided mode."
          primaryLabel="Go to Workspaces"
          primaryTo="/workspaces"
        />
      ) : (
        <Stack gap="md">
          {err ? (
            <GlassCard>
              <Text c="red">{err}</Text>
            </GlassCard>
          ) : null}

          <GlassSection
            title="Happy path"
            description="One default journey. Advanced tools stay available, but this is the main flow."
            right={
              <Group gap="sm" wrap="wrap">
                <Badge variant="light" color={roleBadgeColor(roleStr)}>
                  Role: {roleStr ?? "unknown"}
                </Badge>
                <GlassStat label="Queued approvals" value={approvalsCount} />
                {latest.run ? (
                  <GlassStat label="Latest run" value={latest.run.status} />
                ) : (
                  <GlassStat label="Latest run" value="none" />
                )}
                {latest.artifact ? (
                  <GlassStat label="Latest output" value={latest.artifact.status} />
                ) : (
                  <GlassStat label="Latest output" value="none" />
                )}
              </Group>
            }
          >
            <SimpleGrid cols={{ base: 1, sm: 2, md: 2 }} spacing="md">
              {/* Step 1 */}
              <GlassCard p="md">
                <Stack gap={8}>
                  <Group justify="space-between">
                    <Text fw={800}>1) Create run</Text>
                    <Badge variant="light">Start</Badge>
                  </Group>
                  <Text size="sm" c="dimmed">
                    Create a run using a simple input. Use references only if needed.
                  </Text>
                  <Group>
                    <Button component={Link} to={step1Cta} size="sm">
                      Create run
                    </Button>
                    <Button component={Link} to="/runs" variant="light" size="sm">
                      View runs
                    </Button>
                  </Group>
                </Stack>
              </GlassCard>

              {/* Step 2 */}
              <GlassCard p="md">
                <Stack gap={8}>
                  <Group justify="space-between">
                    <Text fw={800}>2) Review output</Text>
                    <Badge variant="light" color={latest.artifact ? "blue" : "gray"}>
                      {latest.artifact ? "Ready" : "Pending"}
                    </Badge>
                  </Group>
                  <Text size="sm" c="dimmed">
                    {step2Status}
                  </Text>
                  <Group>
                    <Button component={Link} to={step2ArtifactHref || "/outputs"} size="sm" disabled={!latest.artifact}>
                      Open output
                    </Button>
                    <Button component={Link} to={step2RunHref || "/runs"} variant="light" size="sm" disabled={!latest.run}>
                      Open run
                    </Button>
                  </Group>
                  {latest.run ? (
                    <Text size="xs" c="dimmed">
                      Latest run: {shortId(latest.run.id)}
                    </Text>
                  ) : null}
                </Stack>
              </GlassCard>

              {/* Step 3 */}
              <GlassCard p="md">
                <Stack gap={8}>
                  <Group justify="space-between">
                    <Text fw={800}>3) Request publish</Text>
                    <Badge
                      variant="light"
                      color={!latest.artifact ? "gray" : artifactStatus === "final" ? "green" : "yellow"}
                    >
                      {!latest.artifact ? "Blocked" : artifactStatus === "final" ? "Done" : "Action"}
                    </Badge>
                  </Group>
                  <Text size="sm" c="dimmed">
                    Request publish from the output page. This creates an approval item.
                  </Text>
                  <Text size="sm" c="dimmed">
                    Status: {step3Status}
                  </Text>
                  <Group>
                    <Button component={Link} to={step3PrimaryHref || "/outputs"} size="sm" disabled={!latest.artifact}>
                      Open output to request publish
                    </Button>
                    <Button component={Link} to="/outputs" variant="light" size="sm">
                      Outputs
                    </Button>
                  </Group>
                </Stack>
              </GlassCard>

              {/* Step 4 */}
              <GlassCard p="md">
                <Stack gap={8}>
                  <Group justify="space-between">
                    <Text fw={800}>4) Approve + publish</Text>
                    <Badge variant="light" color={approvalsCount > 0 ? "yellow" : "gray"}>
                      {approvalsCount > 0 ? "Waiting" : "Clear"}
                    </Badge>
                  </Group>
                  <Text size="sm" c="dimmed">
                    Approvals in Action Center finalize publishing.
                  </Text>
                  <Text size="sm" c="dimmed">
                    Status: {step4Status}
                  </Text>
                  <Group>
                    <Button component={Link} to={step4ApprovalsHref} size="sm">
                      Open Action Center
                    </Button>
                    <Button component={Link} to="/approvals" variant="light" size="sm">
                      Approvals
                    </Button>
                  </Group>
                </Stack>
              </GlassCard>

              {/* Step 5 */}
              <GlassCard p="md" style={{ gridColumn: "1 / -1" }}>
                <Stack gap={8}>
                  <Group justify="space-between">
                    <Text fw={800}>5) Schedule</Text>
                    <Badge variant="light">Optional</Badge>
                  </Group>
                  <Text size="sm" c="dimmed">
                    Automate recurring runs (e.g., weekly health report, daily monitoring, monthly brief).
                  </Text>
                  <Group>
                    <Button component={Link} to={step5SchedulesHref} size="sm">
                      Open schedules
                    </Button>
                    <Button component={Link} to="/schedules" variant="light" size="sm">
                      Schedules home
                    </Button>
                  </Group>
                </Stack>
              </GlassCard>
            </SimpleGrid>

            <Divider my="sm" />

            <Text size="sm" c="dimmed">
              Advanced tools are available under workspace settings (rules, audit log, agent builder), but Guided mode is the default journey.
            </Text>
          </GlassSection>

          <GlassSection title="Advanced tools" description="Only when you need them.">
            <Group wrap="wrap">
              <Button component={Link} to={`/workspaces/${wid}/policy`} variant="light" size="sm">
                Workspace rules
              </Button>
              <Button component={Link} to={`/workspaces/${wid}/governance`} variant="light" size="sm">
                Audit log
              </Button>
              <Button component={Link} to={`/workspaces/${wid}/agent-builder`} variant="light" size="sm">
                Agent builder
              </Button>
              <Button component={Link} to={`/workspaces/${wid}/_legacy`} variant="light" size="sm">
                Members (legacy)
              </Button>
              <Button component={Link} to={`/workspaces/${wid}/overview`} variant="light" size="sm">
                Workspace overview
              </Button>
            </Group>
          </GlassSection>
        </Stack>
      )}
    </GlassPage>
  );
}