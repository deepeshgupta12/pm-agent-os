// apps/web/src/pages/AgentsPage.tsx
import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Group, Stack, Text, TextInput } from "@mantine/core";
import { Link } from "react-router-dom";
import { apiFetch } from "../apiClient";
import type { Agent } from "../types";

import GlassPage from "../components/Glass/GlassPage";
import GlassCard from "../components/Glass/GlassCard";
import GlassSection from "../components/Glass/GlassSection";
import GlassStat from "../components/Glass/GlassStat";

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

function shortId(id: string): string {
  if (!id) return "";
  return id.length <= 10 ? id : `${id.slice(0, 8)}…`;
}

function inferKind(agentId: string): { kind: "built-in" | "custom"; label: string } {
  const s = (agentId || "").trim();
  if (s.startsWith("custom:")) return { kind: "custom", label: "Custom" };
  return { kind: "built-in", label: "Built-in" };
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [q, setQ] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const activeWorkspaceId = useMemo(() => readLastWorkspaceId(), []);

  async function load() {
    setErr(null);
    setLoading(true);

    const res = await apiFetch<Agent[]>("/agents", { method: "GET" });

    setLoading(false);

    if (!res.ok) {
      setAgents([]);
      setErr(`Failed to load agents: ${res.status} ${res.error}`);
      return;
    }

    setAgents(res.data || []);
  }

  useEffect(() => {
    void load();
  }, []);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return agents;

    return agents.filter((a) => {
      const hay = `${a.id} ${a.name} ${a.description} ${a.version} ${a.default_artifact_type}`.toLowerCase();
      return hay.includes(needle);
    });
  }, [agents, q]);

  const total = agents.length;
  const shown = filtered.length;

  return (
    <GlassPage
      title="Agent Library"
      subtitle="Browse available agents. Open Run Builder with the agent preselected."
      right={
        <Group>
          <Button variant="light" onClick={load} loading={loading} size="sm">
            Refresh
          </Button>
          {activeWorkspaceId ? (
            <Button component={Link} to={`/run-builder/${activeWorkspaceId}`} variant="default" size="sm">
              Run Builder
            </Button>
          ) : (
            <Button component={Link} to="/workspaces" variant="default" size="sm">
              Pick workspace
            </Button>
          )}
        </Group>
      }
    >
      <Stack gap="md">
        <GlassSection
          title="Search"
          description="Filter by name, id, description, version, or default artifact type."
          right={
            <Group gap="sm" wrap="wrap">
              <GlassStat label="Total" value={total} />
              <GlassStat label="Shown" value={shown} />
              <GlassStat label="Workspace" value={activeWorkspaceId ? shortId(activeWorkspaceId) : "None"} />
            </Group>
          }
        >
          <TextInput
            label="Search agents"
            value={q}
            onChange={(e) => setQ(e.currentTarget.value)}
            placeholder='e.g., "PRD", "monitoring", "custom:"'
          />

          {err ? (
            <Text c="red" mt="sm">
              {err}
            </Text>
          ) : null}

          {!activeWorkspaceId ? (
            <Text size="sm" c="dimmed" mt="sm">
              No workspace selected yet. You can browse agents, but “Run” requires a workspace.
              Open a workspace once to set the active workspace.
            </Text>
          ) : null}
        </GlassSection>

        <GlassSection
          title="Agents"
          description="Each agent can be run from Run Builder. Built-in agents ship with the platform; custom agents come from Agent Builder."
          right={<GlassStat label="Mode" value="V0" />}
        >
          {filtered.length === 0 ? (
            <Text c="dimmed">No matching agents.</Text>
          ) : (
            <Stack gap="xs">
              {filtered.map((a) => {
                const k = inferKind(a.id);
                const canRun = !!activeWorkspaceId;

                const runHref = activeWorkspaceId
                  ? `/run-builder/${activeWorkspaceId}?agent_id=${encodeURIComponent(a.id)}`
                  : "/workspaces";

                return (
                  <GlassCard key={a.id} p="md">
                    <Group justify="space-between" align="flex-start">
                      <Stack gap={6} style={{ maxWidth: "74%" }}>
                        <Group gap="sm" wrap="wrap">
                          <Badge variant="light">{k.label}</Badge>
                          <Badge variant="light">{a.version}</Badge>
                          <Badge variant="light" title="Default output artifact type">
                            {a.default_artifact_type}
                          </Badge>
                          <Text fw={800}>{a.name}</Text>
                        </Group>

                        <Text size="sm" c="dimmed" style={{ whiteSpace: "pre-wrap" }}>
                          {a.description || "(No description)"}
                        </Text>

                        <Text size="xs" c="dimmed">
                          id: {a.id}
                        </Text>
                      </Stack>

                      <Group>
                        <Button component={Link} to={runHref} size="sm" disabled={!canRun}>
                          Run
                        </Button>
                        {activeWorkspaceId ? (
                          <Button component={Link} to={`/run-builder/${activeWorkspaceId}`} variant="light" size="sm">
                            Builder
                          </Button>
                        ) : (
                          <Button component={Link} to="/workspaces" variant="light" size="sm">
                            Pick workspace
                          </Button>
                        )}
                      </Group>
                    </Group>
                  </GlassCard>
                );
              })}
            </Stack>
          )}
        </GlassSection>
      </Stack>
    </GlassPage>
  );
}