// apps/web/src/pages/WorkspacesPage.tsx
import { useEffect, useState } from "react";
import { Button, Group, Stack, Text, TextInput } from "@mantine/core";
import { Link } from "react-router-dom";
import { apiFetch } from "../apiClient";
import type { Workspace } from "../types";
import GlassCard from "../components/Glass/GlassCard";
import GlassPage from "../components/Glass/GlassPage";

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
    void load();
  }, []);

  return (
    <GlassPage
      title="Workspaces"
      subtitle="Pick a workspace to run agents, review approvals, and manage policy."
      right={
        <Group>
          <Button variant="light" onClick={load}>
            Refresh
          </Button>
          <Button component={Link} to="/me" variant="default">
            Account
          </Button>
        </Group>
      }
    >
      <GlassCard>
        <Stack gap="sm">
          <Text fw={700}>Create workspace</Text>

          <Group align="end">
            <TextInput
              label="Workspace name"
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
              placeholder="e.g., Growth Team"
              style={{ flex: 1 }}
            />
            <Button onClick={createWorkspace} loading={loading} disabled={!name.trim()}>
              Create
            </Button>
          </Group>

          {err ? <Text c="red">{err}</Text> : null}
        </Stack>
      </GlassCard>

      <GlassCard>
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={700}>Your workspaces</Text>
          </Group>

          {workspaces.length === 0 ? (
            <Text c="dimmed">No workspaces yet.</Text>
          ) : (
            <Stack gap="xs">
              {workspaces.map((w) => (
                <GlassCard key={w.id} p="md">
                  <Group justify="space-between" align="flex-start">
                    <Stack gap={2}>
                      <Text fw={600}>{w.name}</Text>
                      <Text size="xs" c="dimmed">
                        {w.id}
                      </Text>
                    </Stack>

                    <Group>
                      <Button component={Link} to={`/workspaces/${w.id}`}>
                        Open
                      </Button>
                      <Button component={Link} to={`/run-builder/${w.id}`} variant="light">
                        Run Builder
                      </Button>
                      <Button component={Link} to={`/workspaces/${w.id}/docs`} variant="light">
                        Docs
                      </Button>
                    </Group>
                  </Group>
                </GlassCard>
              ))}
            </Stack>
          )}
        </Stack>
      </GlassCard>
    </GlassPage>
  );
}