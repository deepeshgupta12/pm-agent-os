import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Group,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
  Code,
  Divider,
  Textarea,
  Table,
} from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { GovernanceEffective, GovernanceEvents, GovernanceEvent } from "../types";

function safeJson(v: any): string {
  try {
    return JSON.stringify(v ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

function decisionColor(decision: string): string {
  const d = (decision || "").toLowerCase();
  if (d === "allow") return "green";
  if (d === "deny") return "red";
  return "gray";
}

export default function GovernancePage() {
  const { workspaceId } = useParams();
  const wid = workspaceId || "";

  const [err, setErr] = useState<string | null>(null);

  const [effective, setEffective] = useState<GovernanceEffective | null>(null);
  const [events, setEvents] = useState<GovernanceEvent[]>([]);
  const [loadingEffective, setLoadingEffective] = useState(false);
  const [loadingEvents, setLoadingEvents] = useState(false);

  // filters
  const [limit, setLimit] = useState<string>("50");
  const [decision, setDecision] = useState<string | null>(null); // allow|deny|null
  const [actionPrefix, setActionPrefix] = useState<string>("");

  const effectiveJson = useMemo(() => safeJson(effective), [effective]);

  async function loadEffective() {
    if (!wid) return;
    setErr(null);
    setLoadingEffective(true);

    const res = await apiFetch<GovernanceEffective>(`/workspaces/${wid}/governance`, { method: "GET" });

    setLoadingEffective(false);

    if (!res.ok) {
      setEffective(null);
      setErr(`Governance load failed: ${res.status} ${res.error}`);
      return;
    }

    setEffective(res.data);
  }

  async function loadEvents() {
    if (!wid) return;
    setErr(null);
    setLoadingEvents(true);

    const params = new URLSearchParams();
    params.set("limit", String(Number(limit) || 50));
    if (decision) params.set("decision", decision);
    if (actionPrefix.trim()) params.set("action_prefix", actionPrefix.trim());

    const res = await apiFetch<GovernanceEvents>(`/workspaces/${wid}/governance/events?${params.toString()}`, {
      method: "GET",
    });

    setLoadingEvents(false);

    if (!res.ok) {
      setEvents([]);
      setErr(`Governance events load failed: ${res.status} ${res.error}`);
      return;
    }

    setEvents(res.data.items || []);
  }

  async function loadAll() {
    await loadEffective();
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
            Back to Workspace
          </Button>
          <Button variant="light" onClick={loadAll} loading={loadingEffective || loadingEvents}>
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
            <Button variant="light" onClick={loadEffective} loading={loadingEffective}>
              Refresh
            </Button>
          </Group>

          <Text size="sm" c="dimmed">
            This is the merged view returned by <Code>GET /workspaces/:id/governance</Code>.
          </Text>

          <Textarea label="governance_effective (json)" autosize minRows={10} value={effectiveJson} readOnly />
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Group gap="sm">
              <Text fw={700}>Governance Events</Text>
              <Badge variant="light">audit trail</Badge>
            </Group>
            <Button variant="light" onClick={loadEvents} loading={loadingEvents}>
              Refresh
            </Button>
          </Group>

          <Text size="sm" c="dimmed">
            Events are returned by <Code>GET /workspaces/:id/governance/events</Code>. Use filters below.
          </Text>

          <Divider />

          <Group align="end" grow>
            <TextInput
              label="action_prefix (optional)"
              value={actionPrefix}
              onChange={(e) => setActionPrefix(e.currentTarget.value)}
              placeholder="e.g., policy.allowlist."
            />
            <Select
              label="decision"
              data={[
                { value: "", label: "all" },
                { value: "allow", label: "allow" },
                { value: "deny", label: "deny" },
              ]}
              value={decision ?? ""}
              onChange={(v) => setDecision(v ? v : null)}
            />
            <TextInput
              label="limit"
              value={limit}
              onChange={(e) => setLimit(e.currentTarget.value)}
              placeholder="50"
            />
            <Button onClick={loadEvents} loading={loadingEvents}>
              Apply
            </Button>
          </Group>

          <Divider />

          {events.length === 0 ? (
            <Text size="sm" c="dimmed">
              No events found.
            </Text>
          ) : (
            <Table striped withTableBorder withColumnBorders>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Decision</Table.Th>
                  <Table.Th>Action</Table.Th>
                  <Table.Th>Reason</Table.Th>
                  <Table.Th>Created</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {events.map((e) => (
                  <Table.Tr key={e.id}>
                    <Table.Td>
                      <Badge variant="light" color={decisionColor(e.decision)}>
                        {e.decision}
                      </Badge>
                    </Table.Td>
                    <Table.Td style={{ maxWidth: 520 }}>
                      <Text size="sm" style={{ wordBreak: "break-word" }}>
                        {e.action}
                      </Text>
                      <Text size="xs" c="dimmed">
                        id={e.id}
                      </Text>
                    </Table.Td>
                    <Table.Td style={{ maxWidth: 520 }}>
                      <Text size="sm" style={{ wordBreak: "break-word" }}>
                        {e.reason || "-"}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <Text size="sm">{e.created_at}</Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          )}
        </Stack>
      </Card>
    </Stack>
  );
}