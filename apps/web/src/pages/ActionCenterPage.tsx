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

function safeJsonParse(s: string): { ok: boolean; value: any; error?: string } {
  try {
    const v = s.trim() ? JSON.parse(s) : {};
    return { ok: true, value: v };
  } catch (e: any) {
    return { ok: false, value: null, error: e?.message || "Invalid JSON" };
  }
}

export default function ActionCenterPage() {
  const { workspaceId } = useParams();
  const wid = workspaceId || "";

  const [myRole, setMyRole] = useState<WorkspaceRole | null>(null);
  const role = (myRole?.role || "").toLowerCase();
  const canReview = role === "admin" || role === "member"; // reviewers can be admin/member (policy may still block per type)

  const [items, setItems] = useState<ActionItem[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [okMsg, setOkMsg] = useState<string | null>(null);
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

  const [decidingId, setDecidingId] = useState<string | null>(null);

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
    if (!wid) return;
    if (role === "viewer") return;

    setErr(null);
    setOkMsg(null);

    const parsed = safeJsonParse(createPayloadJson);
    if (!parsed.ok) {
      setErr(`payload_json is invalid JSON: ${parsed.error}`);
      return;
    }

    setCreating(true);
    const res = await apiFetch<ActionItem>(`/workspaces/${wid}/actions`, {
      method: "POST",
      body: JSON.stringify({
        type: createType.trim(),
        title: createTitle.trim(),
        target_ref: createTargetRef.trim() || null,
        payload_json: parsed.value,
      }),
    });
    setCreating(false);

    if (!res.ok) {
      setErr(`Create failed: ${res.status} ${res.error}`);
      return;
    }

    setOkMsg(`Action created: ${res.data.id}`);
    await loadItems();
  }

  async function decide(id: string, decision: "approved" | "rejected") {
    if (!canReview) return;
    setErr(null);
    setOkMsg(null);

    setDecidingId(id);
    const res = await apiFetch<ActionItem>(`/actions/${id}/decide`, {
      method: "POST",
      body: JSON.stringify({ decision, comment: null }),
    });
    setDecidingId(null);

    if (!res.ok) {
      setErr(`Decision failed: ${res.status} ${res.error}`);
      return;
    }

    const a = res.data;
    const req = (a as any).approvals_required ?? null;
    const approved = (a as any).approvals_approved_count ?? null;

    if (typeof req === "number" && typeof approved === "number") {
      setOkMsg(`Vote recorded. approvals: ${approved}/${req}. status: ${a.status}`);
    } else {
      setOkMsg(`Vote recorded. status: ${a.status}`);
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

      {myRole ? (
        <Group gap="sm">
          <Badge variant="light">role: {myRole.role}</Badge>
          <Badge variant="light" color={canReview ? "grape" : "gray"}>
            {canReview ? "can review (member/admin)" : "read-only"}
          </Badge>
        </Group>
      ) : null}

      {err ? (
        <Card withBorder>
          <Text c="red">{err}</Text>
        </Card>
      ) : null}

      {okMsg ? (
        <Card withBorder>
          <Text>{okMsg}</Text>
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
              {items.map((a) => {
                const approvalsRequired = (a as any).approvals_required as number | undefined;
                const approvedCount = (a as any).approvals_approved_count as number | undefined;
                const rejectedCount = (a as any).approvals_rejected_count as number | undefined;
                const myDecision = ((a as any).my_decision as string | null | undefined) ?? null;

                const showVoteControls = canReview && a.status === "queued";
                const alreadyVoted = !!myDecision;
                const isBusy = decidingId === a.id;

                return (
                  <Card key={a.id} withBorder>
                    <Stack gap={6}>
                      <Group justify="space-between" align="flex-start">
                        <Stack gap={2}>
                          <Group gap="sm">
                            <Badge>{a.status}</Badge>
                            <Badge variant="light">{a.type}</Badge>
                            {a.target_ref ? <Badge variant="outline">{a.target_ref}</Badge> : null}

                            {typeof approvalsRequired === "number" ? (
                              <Badge variant="light">
                                approvals: {typeof approvedCount === "number" ? approvedCount : 0}/{approvalsRequired}
                              </Badge>
                            ) : null}

                            {typeof rejectedCount === "number" ? (
                              <Badge variant="light" color={rejectedCount > 0 ? "red" : "gray"}>
                                rejected: {rejectedCount}
                              </Badge>
                            ) : null}

                            {myDecision ? <Badge variant="outline">you: {myDecision}</Badge> : null}
                          </Group>

                          <Text fw={600}>{a.title}</Text>

                          <Text size="xs" c="dimmed">
                            {a.id}
                          </Text>
                        </Stack>

                        {showVoteControls ? (
                          <Group>
                            <Button
                              size="xs"
                              onClick={() => decide(a.id, "approved")}
                              disabled={alreadyVoted || isBusy}
                              loading={isBusy}
                              title={alreadyVoted ? "You already voted" : undefined}
                            >
                              Approve
                            </Button>
                            <Button
                              size="xs"
                              color="red"
                              onClick={() => decide(a.id, "rejected")}
                              disabled={alreadyVoted || isBusy}
                              loading={isBusy}
                              title={alreadyVoted ? "You already voted" : undefined}
                            >
                              Reject
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
                );
              })}
            </Stack>
          )}
        </Stack>
      </Card>

      <Divider />

      <Card withBorder>
        <Stack gap="sm">
          <Text fw={700}>Create action item</Text>
          <Text size="sm" c="dimmed">
            Internal-only actions. Approval requirements are controlled by workspace approvals policy.
          </Text>

          <Group grow>
            <TextInput
              label="type"
              value={createType}
              onChange={(e) => setCreateType(e.currentTarget.value)}
              disabled={role === "viewer"}
            />
            <TextInput
              label="target_ref (optional)"
              value={createTargetRef}
              onChange={(e) => setCreateTargetRef(e.currentTarget.value)}
              placeholder="artifact:UUID"
              disabled={role === "viewer"}
            />
          </Group>

          <TextInput
            label="title"
            value={createTitle}
            onChange={(e) => setCreateTitle(e.currentTarget.value)}
            disabled={role === "viewer"}
          />

          <Textarea
            label="payload_json"
            autosize
            minRows={8}
            value={createPayloadJson}
            onChange={(e) => setCreatePayloadJson(e.currentTarget.value)}
            disabled={role === "viewer"}
          />

          <Button onClick={createAction} loading={creating} disabled={role === "viewer"}>
            Create
          </Button>

          {role === "viewer" ? <Text size="sm" c="dimmed">Viewer role cannot create actions.</Text> : null}
        </Stack>
      </Card>
    </Stack>
  );
}