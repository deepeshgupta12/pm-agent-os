// apps/web/src/pages/WorkspacesPage.tsx
import { useEffect, useMemo, useState } from "react";
import { Button, Group, Stack, Text, TextInput } from "@mantine/core";
import { Link } from "react-router-dom";
import { apiFetch } from "../apiClient";
import type { Workspace } from "../types";

import GlassPage from "../components/Glass/GlassPage";
import GlassCard from "../components/Glass/GlassCard";
import GlassSection from "../components/Glass/GlassSection";
import GlassStat from "../components/Glass/GlassStat";

export default function WorkspacesPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [name, setName] = useState("My Workspace");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function load() {
    setErr(null);
    const res = await apiFetch<Workspace[]>("/workspaces", { method: "GET" });
    if (!res.ok) {
      setWorkspaces([]);
      setErr(`Failed to load workspaces: ${res.status} ${res.error}`);
      return;
    }
    setWorkspaces(res.data);
  }

  async function createWorkspace() {
    setLoading(true);
    setErr(null);

    const res = await apiFetch<Workspace>("/workspaces", {
      method: "POST",
      body: JSON.stringify({ name }),
    });

    setLoading(false);

    if (!res.ok) {
      setErr(`Create failed: ${res.status} ${res.error}`);
      return;
    }

    setName("");
    await load();
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, []);

  const total = useMemo(() => workspaces.length, [workspaces.length]);

  return (
    <GlassPage
      title="Workspaces"
      subtitle="Pick a workspace to run agents, review approvals, and manage policy."
      right={
        <Group>
          <Button variant="light" onClick={load} size="sm">
            Refresh
          </Button>
          <Button component={Link} to="/me" variant="default" size="sm">
            Account
          </Button>
        </Group>
      }
    >
      <Stack gap="md">
        <GlassSection
          title="Create workspace"
          description="A workspace contains runs, approvals, schedules, and governance settings."
          right={<GlassStat label="Mode" value="Console" />}
        >
          <Group align="end">
            <TextInput
              label="Workspace name"
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
              placeholder="e.g., Growth Team"
              style={{ flex: 1 }}
            />
            <Button onClick={createWorkspace} loading={loading} disabled={!name.trim()} size="sm">
              Create
            </Button>
          </Group>

          {err ? <Text c="red">{err}</Text> : null}
        </GlassSection>

        <GlassSection
          title="Your workspaces"
          description="Open a workspace to access its overview and tools."
          right={<GlassStat label="Total" value={total} />}
        >
          {workspaces.length === 0 ? (
            <Text c="dimmed">No workspaces yet.</Text>
          ) : (
            <Stack gap="xs">
              {workspaces.map((w) => (
                <GlassCard key={w.id} p="md">
                  <Group justify="space-between" align="flex-start">
                    <Stack gap={2}>
                      <Text fw={700}>{w.name}</Text>
                      <Text size="xs" c="dimmed">
                        {w.id}
                      </Text>
                    </Stack>

                    <Group>
                      <Button component={Link} to={`/workspaces/${w.id}`} size="sm">
                        Open
                      </Button>
                      <Button component={Link} to={`/run-builder/${w.id}`} variant="light" size="sm">
                        Run Builder
                      </Button>
                      <Button component={Link} to={`/workspaces/${w.id}/docs`} variant="light" size="sm">
                        Docs
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