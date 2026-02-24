import { useEffect, useState } from "react";
import { Button, Card, Group, Stack, Text, TextInput, Title } from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { Workspace } from "../types";
import { Link } from "react-router-dom";

export default function WorkspacesPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [name, setName] = useState("My First Workspace");
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
    <Stack gap="md">
      <Title order={2}>Workspaces</Title>
      <Card withBorder>
        <Stack gap="sm">
          <Text fw={600}>Create workspace</Text>
          <Group align="end">
            <TextInput
              label="Workspace name"
              value={name}
              onChange={(e) => setName(e.currentTarget.value)}
              placeholder="e.g., Growth Team"
              style={{ flex: 1 }}
            />
            <Button onClick={createWorkspace} loading={loading}>
              Create
            </Button>
          </Group>
          <Text size="sm" c="dimmed">
            Note: You must be logged in (Me → Login) to use platform features.
          </Text>
          {err && <Text c="red">{err}</Text>}
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={600}>Your workspaces</Text>
            <Button variant="light" onClick={load}>
              Refresh
            </Button>
          </Group>

          {workspaces.length === 0 ? (
            <Text c="dimmed">No workspaces yet.</Text>
          ) : (
            <Stack gap="xs">
              {workspaces.map((w) => (
                <Card key={w.id} withBorder>
                  <Group justify="space-between">
                    <Stack gap={2}>
                      <Text fw={600}>{w.name}</Text>
                      <Text size="xs" c="dimmed">
                        {w.id}
                      </Text>
                    </Stack>
                    <Group>
                      <Button component={Link} to={`/workspaces/${w.id}/pipelines`} variant="light">
                        Pipelines
                      </Button>
                      <Button component={Link} to={`/workspaces/${w.id}`}>
                        Open
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