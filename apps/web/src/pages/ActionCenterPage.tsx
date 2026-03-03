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
  Code,
} from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { ActionItem, ActionItemDecision, WorkspaceRole } from "../types";

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "queued", label: "queued" },
  { value: "approved", label: "approved" },
  { value: "rejected", label: "rejected" },
  { value: "cancelled", label: "cancelled" },
];

function plural(n: number, one: string, many?: string) {
  const m = many ?? `${one}s`;
  return n === 1 ? one : m;
}

function stableJsonStringify(v: any): string {
  try {
    return JSON.stringify(v ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

export default function ActionCenterPage() {
  const { workspaceId } = useParams();
  const wid = workspaceId || "";

  const [myRole, setMyRole] = useState<WorkspaceRole | null>(null);
  const role = (myRole?.role || "").toLowerCase();
  const canWrite = role === "admin" || role === "member";
  const isAdmin = role === "admin";

  const [items, setItems] = useState<ActionItem[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // filters
  const [status, setStatus] = useState<string>("");
  const [type, setType] = useState<string>("");

  // create form
  const [createType, setCreateType] = useState("decision_log_create");
  const [createTitle, setCreateTitle] = useState("Decision log: onboarding trade-offs");
  const [createTargetRef, setCreateTargetRef] = useState("");
  const [createPayloadJson, setCreatePayloadJson] = useState<string>(
    JSON.stringify(
      {
        decision_title: "Onboarding trade-offs",
        context: "We need to decide between speed vs completeness",
        options: ["Option A", "Option B"],
        recommendation: "Option A",
        constraints: "No regression in activation",
      },
      null,
      2
    )
  );
  const [creating, setCreating] = useState(false);

  // decisions drawer (per action)
  const [decisionsByAction, setDecisionsByAction] = useState<Record<string, ActionItemDecision[]>>({});
  const [decisionsLoading, setDecisionsLoading] = useState<Record<string, boolean>>({});

  async function loadRole() {
    if (!wid) return;
    const res = await apiFetch<WorkspaceRole>(`/workspaces/${wid}/my-role`, { method: "GET" });
    if (!res.ok) return;
    setMyRole(res.data);
  }

  async function loadItems() {
    if (!wid) return;
    setErr(null);
    setInfo(null);
    setLoading(true);

    const qs = new URLSearchParams();
    if (status) qs.set("status", status);
    if (type.trim()) qs.set("type", type.trim());

    const res = await apiFetch<ActionItem[]>(`/workspaces/${wid}/actions?${qs.toString()}`, {
      method: "GET",
    });

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
    setInfo(null);

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

    setInfo(`Created action: ${res.data.id}`);
    await loadItems();
  }

  async function decide(id: string, decision: "approved" | "rejected") {
    if (!wid) return;
    setErr(null);
    setInfo(null);

    const res = await apiFetch<ActionItem>(`/actions/${id}/decide`, {
      method: "POST",
      body: JSON.stringify({ decision, comment: null }),
    });

    if (!res.ok) {
      setErr(`Decision failed: ${res.status} ${res.error}`);
      return;
    }

    setInfo(`Decision recorded: ${decision}`);
    await loadItems();
  }

  async function cancel(id: string) {
    if (!wid) return;
    setErr(null);
    setInfo(null);

    const res = await apiFetch<ActionItem>(`/actions/${id}/cancel`, {
      method: "POST",
      body: JSON.stringify({ comment: "Cancelled from Action Center UI" }),
    });

    if (!res.ok) {
      setErr(`Cancel failed: ${res.status} ${res.error}`);
      return;
    }

    setInfo(`Cancelled: ${id}`);
    await loadItems();
  }

  async function loadDecisions(actionId: string) {
    setErr(null);
    setInfo(null);

    setDecisionsLoading((m) => ({ ...m, [actionId]: true }));
    const res = await apiFetch<ActionItemDecision[]>(`/actions/${actionId}/decisions`, { method: "GET" });
    setDecisionsLoading((m) => ({ ...m, [actionId]: false }));

    if (!res.ok) {
      setErr(`Load decisions failed: ${res.status} ${res.error}`);
      return;
    }

    setDecisionsByAction((m) => ({ ...m, [actionId]: res.data || [] }));
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

  const isReviewer = useMemo(() => {
    // Server is source of truth; UI shows buttons for member/admin only.
    return role === "admin" || role === "member";
  }, [role]);

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

      {info ? (
        <Card withBorder>
          <Text>{info}</Text>
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
                const req = a.approvals_required ?? 1;
                const ok = a.approvals_approved_count ?? 0;
                const rej = a.approvals_rejected_count ?? 0;
                const mine = a.my_decision ?? null;

                const showDecide = a.status === "queued" && isReviewer;
                const alreadyDecided = !!mine;

                const decisions = decisionsByAction[a.id] || [];
                const loadingDec = !!decisionsLoading[a.id];

                return (
                  <Card key={a.id} withBorder>
                    <Stack gap={6}>
                      <Group justify="space-between" align="flex-start">
                        <Stack gap={2} style={{ flex: 1 }}>
                          <Group gap="sm" wrap="wrap">
                            <Badge>{a.status}</Badge>
                            <Badge variant="light">{a.type}</Badge>
                            {a.target_ref ? <Badge variant="outline">{a.target_ref}</Badge> : null}

                            <Badge variant="light">
                              approvals: {ok}/{req} {rej > 0 ? `· ${rej} ${plural(rej, "reject")}` : ""}
                            </Badge>

                            {mine ? <Badge variant="outline">my_decision: {mine}</Badge> : null}
                          </Group>

                          <Text fw={600}>{a.title}</Text>
                          <Text size="xs" c="dimmed">
                            {a.id}
                          </Text>
                        </Stack>

                        {showDecide ? (
                          <Group>
                            <Button size="xs" onClick={() => decide(a.id, "approved")} disabled={alreadyDecided}>
                              Approve
                            </Button>
                            <Button size="xs" color="red" onClick={() => decide(a.id, "rejected")} disabled={alreadyDecided}>
                              Reject
                            </Button>
                            <Button
                              size="xs"
                              variant="light"
                              color="red"
                              onClick={() => cancel(a.id)}
                              disabled={!isAdmin}
                            >
                              Cancel
                            </Button>
                          </Group>
                        ) : (
                          <Group>
                            {a.status === "queued" ? (
                              <Button
                                size="xs"
                                variant="light"
                                color="red"
                                onClick={() => cancel(a.id)}
                                disabled={!isAdmin}
                              >
                                Cancel
                              </Button>
                            ) : null}
                          </Group>
                        )}
                      </Group>

                      <Text size="sm" c="dimmed">
                        created_by: {a.created_by_user_id}
                        {a.assigned_to_user_id ? ` · assigned_to: ${a.assigned_to_user_id}` : ""}
                        {a.decided_by_user_id ? ` · decided_by: ${a.decided_by_user_id}` : ""}
                      </Text>

                      {a.decision_comment ? <Text size="sm">decision_comment: {a.decision_comment}</Text> : null}

                      <Group justify="space-between">
                        <Button
                          size="xs"
                          variant="light"
                          onClick={() => loadDecisions(a.id)}
                          loading={loadingDec}
                        >
                          View decisions
                        </Button>

                        <Text size="xs" c="dimmed">
                          payload_json keys:{" "}
                          <Code>{Object.keys(a.payload_json || {}).join(", ") || "-"}</Code>
                        </Text>
                      </Group>

                      {decisions.length > 0 ? (
                        <Card withBorder>
                          <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                            {stableJsonStringify(decisions)}
                          </pre>
                        </Card>
                      ) : null}

                      {/* show output pointers if executor ran */}
                      {a.payload_json && (a.payload_json as any).created_run_id ? (
                        <Text size="sm">
                          created_run_id: <Code>{String((a.payload_json as any).created_run_id)}</Code>{" "}
                          {(a.payload_json as any).created_artifact_id ? (
                            <>
                              · created_artifact_id:{" "}
                              <Code>{String((a.payload_json as any).created_artifact_id)}</Code>
                            </>
                          ) : null}
                        </Text>
                      ) : null}
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
            V2: policy-enforced creators + multi-reviewer decisions + executor on approval (decision_log_create).
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

          <TextInput label="title" value={createTitle} onChange={(e) => setCreateTitle(e.currentTarget.value)} disabled={!canWrite} />

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