// apps/web/src/pages/GovernancePage.tsx
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Code,
  Group,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
  Divider,
} from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { GovernanceEffectiveOut, GovernanceEventsOut, GovernanceEventOut } from "../types";

function safeJson(v: any): string {
  try {
    return JSON.stringify(v ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

export default function GovernancePage() {
  const { workspaceId } = useParams();
  const wid = workspaceId || "";

  const [err, setErr] = useState<string | null>(null);

  const [gov, setGov] = useState<GovernanceEffectiveOut | null>(null);
  const [govLoading, setGovLoading] = useState(false);

  const [events, setEvents] = useState<GovernanceEventOut[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);

  // filters
  const [actionPrefix, setActionPrefix] = useState<string>("policy.allowlist");
  const [decision, setDecision] = useState<string>("all"); // all|allow|deny
  const [limit, setLimit] = useState<string>("50");

  const limitNum = useMemo(() => {
    const n = Number(limit);
    if (!Number.isFinite(n) || n < 1) return 50;
    return Math.min(200, Math.floor(n));
  }, [limit]);

  async function loadGovernance() {
    if (!wid) return;
    setErr(null);
    setGovLoading(true);

    const res = await apiFetch<GovernanceEffectiveOut>(`/workspaces/${wid}/governance`, { method: "GET" });

    setGovLoading(false);

    if (!res.ok) {
      setGov(null);
      setErr(`Governance load failed: ${res.status} ${res.error}`);
      return;
    }

    setGov(res.data);
  }

  async function loadEvents() {
    if (!wid) return;
    setErr(null);
    setEventsLoading(true);

    const params = new URLSearchParams();
    params.set("limit", String(limitNum));

    if (decision !== "all") params.set("decision", decision);
    if (actionPrefix.trim()) params.set("action_prefix", actionPrefix.trim());

    const res = await apiFetch<GovernanceEventsOut>(
      `/workspaces/${wid}/governance/events?${params.toString()}`,
      { method: "GET" }
    );

    setEventsLoading(false);

    if (!res.ok) {
      setEvents([]);
      setErr(`Governance events load failed: ${res.status} ${res.error}`);
      return;
    }

    setEvents(res.data.items || []);
  }

  async function loadAll() {
    await loadGovernance();
    await loadEvents();
  }

  useEffect(() => {
    if (!wid) return;
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid]);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Governance</Title>
        <Group>
          <Button component={Link} to={`/workspaces/${wid}`} variant="light">
            Back
          </Button>
          <Button onClick={loadAll} loading={govLoading || eventsLoading}>
            Refresh
          </Button>
        </Group>
      </Group>

      {err ? (
        <Card withBorder>
          <Text c="red">{err}</Text>
        </Card>
      ) : null}

      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Group gap="sm">
              <Text fw={700}>Effective Governance</Text>
              <Badge variant="light">policy + rbac</Badge>
            </Group>
            <Button variant="light" onClick={loadGovernance} loading={govLoading}>
              Refresh
            </Button>
          </Group>

          {!gov ? (
            <Text c="dimmed">{govLoading ? "Loading…" : "No governance payload loaded yet."}</Text>
          ) : (
            <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
              {safeJson({ policy_effective: gov.policy_effective, rbac_effective: gov.rbac_effective })}
            </pre>
          )}

          {gov ? (
            <Text size="xs" c="dimmed">
              workspace_id: <Code>{gov.workspace_id}</Code>
            </Text>
          ) : null}
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Group gap="sm">
              <Text fw={700}>Governance Events</Text>
              <Badge variant="light">audit trail</Badge>
            </Group>
            <Button variant="light" onClick={loadEvents} loading={eventsLoading}>
              Refresh
            </Button>
          </Group>

          <Text size="sm" c="dimmed">
            Events are returned by <Code>GET /workspaces/:id/governance/events</Code>. Use filters below.
          </Text>

          <Divider />

          <Group grow>
            <TextInput
              label="action_prefix (optional)"
              value={actionPrefix}
              onChange={(e) => setActionPrefix(e.currentTarget.value)}
              placeholder="e.g., policy.allowlist."
            />
            <Select
              label="decision"
              data={[
                { value: "all", label: "all" },
                { value: "allow", label: "allow" },
                { value: "deny", label: "deny" },
              ]}
              value={decision}
              onChange={(v) => setDecision(v || "all")}
            />
            <TextInput
              label="limit"
              value={limit}
              onChange={(e) => setLimit(e.currentTarget.value)}
              placeholder="50"
            />
          </Group>

          <Button onClick={loadEvents} loading={eventsLoading}>
            Apply
          </Button>

          <Divider />

          {eventsLoading ? (
            <Text c="dimmed">Loading events…</Text>
          ) : events.length === 0 ? (
            <Text c="dimmed">No events found.</Text>
          ) : (
            <Stack gap="xs">
              {events.map((e) => (
                <Card key={e.id} withBorder>
                  <Stack gap={4}>
                    <Group justify="space-between">
                      <Group gap="sm">
                        <Badge variant="light" color={e.decision === "deny" ? "red" : "green"}>
                          {e.decision}
                        </Badge>
                        <Text fw={600}>{e.action}</Text>
                      </Group>
                      <Text size="xs" c="dimmed">
                        {new Date(e.created_at).toLocaleString()}
                      </Text>
                    </Group>

                    {e.reason ? (
                      <Text size="sm">
                        <Text span fw={600}>
                          reason:
                        </Text>{" "}
                        {e.reason}
                      </Text>
                    ) : null}

                    <Text size="xs" c="dimmed">
                      ws=<Code>{e.workspace_id}</Code> · user=<Code>{e.user_id ?? "null"}</Code>
                    </Text>

                    {e.meta && Object.keys(e.meta).length ? (
                      <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{safeJson(e.meta)}</pre>
                    ) : (
                      <Text size="sm" c="dimmed">
                        meta: (empty)
                      </Text>
                    )}
                  </Stack>
                </Card>
              ))}
            </Stack>
          )}
        </Stack>
      </Card>
    </Stack>
  );
}