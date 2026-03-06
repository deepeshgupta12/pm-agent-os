import { useEffect, useState } from "react";
import { Button, Card, Group, Stack, Text, TextInput, Title, Badge } from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { Workspace } from "../types";
import { Link } from "react-router-dom";

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

  return (
    <Stack gap="md">
      <Group justify="space-between" align="flex-start">
        <Stack gap={2}>
          <Title order={2}>Workspaces</Title>
          <Text size="sm" c="dimmed">
            Pick a workspace to run agents, review approvals, and manage policy.
          </Text>
        </Stack>
        <Button variant="light" onClick={load}>
          Refresh
        </Button>
      </Group>

      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Group gap="sm">
              <Text fw={700}>Create workspace</Text>
              <Badge variant="light">V0</Badge>
            </Group>
          </Group>

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

          {err && <Text c="red">{err}</Text>}
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Text fw={700}>Your workspaces</Text>

          {workspaces.length === 0 ? (
            <Text c="dimmed">No workspaces yet.</Text>
          ) : (
            <Stack gap="xs">
              {workspaces.map((w) => (
                <Card key={w.id} withBorder>
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
                </Card>
              ))}
            </Stack>
          )}
        </Stack>
      </Card>
    </Stack>
  );
}