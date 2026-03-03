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
  Textarea,
  Title,
  Divider,
} from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { ActionItem, WorkspaceRole } from "../types";

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "queued", label: "queued" },
  { value: "approved", label: "approved" },
  { value: "rejected", label: "rejected" },
  { value: "cancelled", label: "cancelled" },
];

export default function ActionCenterPage() {
  const { workspaceId } = useParams();
  const wid = workspaceId || "";

  const [myRole, setMyRole] = useState<WorkspaceRole | null>(null);
  const role = (myRole?.role || "").toLowerCase();
  const isAdmin = role === "admin";
  const canWrite = role === "admin" || role === "member";

  const [items, setItems] = useState<ActionItem[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // filters
  const [status, setStatus] = useState<string>("");
  const [type, setType] = useState<string>("");

  // create form
  const [createType, setCreateType] = useState("decision_log_create");
  const [createTitle, setCreateTitle] = useState("Create decision log for onboarding trade-offs");
  const [createTargetRef, setCreateTargetRef] = useState("");
  const [createPayloadJson, setCreatePayloadJson] = useState<string>(
    JSON.stringify(
      {
        decision_title: "Onboarding trade-offs",
        context: "We need to decide between speed vs completeness",
        options: ["Option A", "Option B"],
        recommendation: "Option A",
      },
      null,
      2
    )
  );
  const [creating, setCreating] = useState(false);

  async function loadRole() {
    if (!wid) return;
    const res = await apiFetch<WorkspaceRole>(`/workspaces/${wid}/my-role`, { method: "GET" });
    if (!res.ok) return;
    setMyRole(res.data);
  }

  async function loadItems() {
    if (!wid) return;
    setErr(null);
    setLoading(true);

    const qs = new URLSearchParams();
    if (status) qs.set("status", status);
    if (type.trim()) qs.set("type", type.trim());

    const res = await apiFetch<ActionItem[]>(`/workspaces/${wid}/actions?${qs.toString()}`, { method: "GET" });

    setLoading(false);

    if (!res.ok) {
      setErr(`Load failed: ${res.status} ${res.error}`);
      setItems([]);
      return;
    }

    setItems(res.data || []);
  }

  async function createAction() {
    if (!wid || !canWrite) return;
    setErr(null);

    let payload: any = {};
    try {
      payload = createPayloadJson.trim() ? JSON.parse(createPayloadJson) : {};
    } catch {
      setErr("payload_json is invalid JSON.");
      return;
    }

    setCreating(true);
    const res = await apiFetch<ActionItem>(`/workspaces/${wid}/actions`, {
      method: "POST",
      body: JSON.stringify({
        type: createType.trim(),
        title: createTitle.trim(),
        target_ref: createTargetRef.trim() || null,
        payload_json: payload,
      }),
    });
    setCreating(false);

    if (!res.ok) {
      setErr(`Create failed: ${res.status} ${res.error}`);
      return;
    }

    await loadItems();
  }

  async function decide(id: string, decision: "approved" | "rejected" | "cancelled") {
    if (!isAdmin) return;
    setErr(null);

    const res = await apiFetch<ActionItem>(`/actions/${id}/decide`, {
      method: "POST",
      body: JSON.stringify({ decision, comment: null }),
    });

    if (!res.ok) {
      setErr(`Decision failed: ${res.status} ${res.error}`);
      return;
    }

    await loadItems();
  }

  const typeOptions = useMemo(() => {
    const uniq = Array.from(new Set(items.map((x) => x.type))).sort();
    return [{ value: "", label: "All types" }, ...uniq.map((t) => ({ value: t, label: t }))];
  }, [items]);

  useEffect(() => {
    void loadRole();
    void loadItems();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid]);

  useEffect(() => {
    void loadItems();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, type]);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Action Center</Title>
        <Button component={Link} to={`/workspaces/${wid}`} variant="light">
          Back to Workspace
        </Button>
      </Group>

      {myRole ? <Badge variant="light">role: {myRole.role}</Badge> : null}

      {err ? (
        <Card withBorder>
          <Text c="red">{err}</Text>
        </Card>
      ) : null}

      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={700}>Queue</Text>
            <Button variant="light" onClick={loadItems} loading={loading}>
              Refresh
            </Button>
          </Group>

          <Group gap="sm" align="flex-end">
            <Select label="Status" data={STATUS_OPTIONS} value={status} onChange={(v) => setStatus(v || "")} />
            <Select
              label="Type"
              data={typeOptions}
              value={type}
              onChange={(v) => setType(v || "")}
              searchable
              nothingFoundMessage="No types"
              style={{ flex: 1 }}
            />
          </Group>

          {items.length === 0 ? (
            <Text c="dimmed">No action items.</Text>
          ) : (
            <Stack gap="xs">
              {items.map((a) => (
                <Card key={a.id} withBorder>
                  <Stack gap={6}>
                    <Group justify="space-between" align="flex-start">
                      <Stack gap={2}>
                        <Group gap="sm">
                          <Badge>{a.status}</Badge>
                          <Badge variant="light">{a.type}</Badge>
                          {a.target_ref ? <Badge variant="outline">{a.target_ref}</Badge> : null}
                        </Group>
                        <Text fw={600}>{a.title}</Text>
                        <Text size="xs" c="dimmed">
                          {a.id}
                        </Text>
                      </Stack>

                      {isAdmin && a.status === "queued" ? (
                        <Group>
                          <Button size="xs" onClick={() => decide(a.id, "approved")}>
                            Approve
                          </Button>
                          <Button size="xs" color="red" onClick={() => decide(a.id, "rejected")}>
                            Reject
                          </Button>
                          <Button size="xs" variant="light" onClick={() => decide(a.id, "cancelled")}>
                            Cancel
                          </Button>
                        </Group>
                      ) : null}
                    </Group>

                    <Text size="sm" c="dimmed">
                      created_by: {a.created_by_user_id}
                      {a.assigned_to_user_id ? ` · assigned_to: ${a.assigned_to_user_id}` : ""}
                      {a.decided_by_user_id ? ` · decided_by: ${a.decided_by_user_id}` : ""}
                    </Text>

                    {a.decision_comment ? <Text size="sm">decision_comment: {a.decision_comment}</Text> : null}
                  </Stack>
                </Card>
              ))}
            </Stack>
          )}
        </Stack>
      </Card>

      <Divider />

      <Card withBorder>
        <Stack gap="sm">
          <Text fw={700}>Create action item</Text>
          <Text size="sm" c="dimmed">
            V2 Step 1: internal-only actions (no external integrations).
          </Text>

          <Group grow>
            <TextInput
              label="type"
              value={createType}
              onChange={(e) => setCreateType(e.currentTarget.value)}
              disabled={!canWrite}
            />
            <TextInput
              label="target_ref (optional)"
              value={createTargetRef}
              onChange={(e) => setCreateTargetRef(e.currentTarget.value)}
              placeholder="artifact:UUID"
              disabled={!canWrite}
            />
          </Group>

          <TextInput
            label="title"
            value={createTitle}
            onChange={(e) => setCreateTitle(e.currentTarget.value)}
            disabled={!canWrite}
          />

          <Textarea
            label="payload_json"
            autosize
            minRows={8}
            value={createPayloadJson}
            onChange={(e) => setCreatePayloadJson(e.currentTarget.value)}
            disabled={!canWrite}
          />

          <Button onClick={createAction} loading={creating} disabled={!canWrite}>
            Create
          </Button>

          {!canWrite ? <Text size="sm" c="dimmed">Viewer role cannot create actions.</Text> : null}
        </Stack>
      </Card>
    </Stack>
  );
}