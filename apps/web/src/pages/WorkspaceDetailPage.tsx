import { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Group,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { Agent, Run, Workspace, WorkspaceMember, WorkspaceRole } from "../types";

export default function WorkspaceDetailPage() {
  const { workspaceId } = useParams();
  const wid = workspaceId || "";

  const [ws, setWs] = useState<Workspace | null>(null);
  const [myRole, setMyRole] = useState<WorkspaceRole | null>(null);

  const [members, setMembers] = useState<WorkspaceMember[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<"admin" | "member" | "viewer">("member");
  const [membersLoading, setMembersLoading] = useState(false);

  const [agents, setAgents] = useState<Agent[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const [agentId, setAgentId] = useState<string | null>(null);
  const [inputJson, setInputJson] = useState<string>(
    JSON.stringify({ goal: "Describe what you want the agent to do", context: "", constraints: "" }, null, 2)
  );
  const [creating, setCreating] = useState(false);

  const isAdmin = (myRole?.role || "").toLowerCase() === "admin";

  const selectedAgent = useMemo(() => agents.find((a) => a.id === agentId) || null, [agents, agentId]);

  const agentOptions = useMemo(
    () =>
      agents.map((a) => ({
        value: a.id,
        label: `${a.name} (${a.id})`,
      })),
    [agents]
  );

  async function loadAll() {
    setErr(null);

    const wsRes = await apiFetch<Workspace>(`/workspaces/${wid}`, { method: "GET" });
    if (!wsRes.ok) {
      setErr(`Workspace load failed: ${wsRes.status} ${wsRes.error}`);
      return;
    }
    setWs(wsRes.data);

    const roleRes = await apiFetch<WorkspaceRole>(`/workspaces/${wid}/my-role`, { method: "GET" });
    if (!roleRes.ok) {
      setErr(`Role load failed: ${roleRes.status} ${roleRes.error}`);
      return;
    }
    setMyRole(roleRes.data);

    const agentsRes = await apiFetch<Agent[]>("/agents", { method: "GET" });
    if (!agentsRes.ok) {
      setErr(`Agents load failed: ${agentsRes.status} ${agentsRes.error}`);
      return;
    }
    setAgents(agentsRes.data);
    if (!agentId && agentsRes.data.length > 0) setAgentId(agentsRes.data[0].id);

    const runsRes = await apiFetch<Run[]>(`/workspaces/${wid}/runs`, { method: "GET" });
    if (!runsRes.ok) {
      setErr(`Runs load failed: ${runsRes.status} ${runsRes.error}`);
      return;
    }
    setRuns(runsRes.data);

    await loadMembers();
  }

  async function loadMembers() {
    if (!wid) return;
    setMembersLoading(true);
    const res = await apiFetch<WorkspaceMember[]>(`/workspaces/${wid}/members`, { method: "GET" });
    setMembersLoading(false);

    if (!res.ok) {
      setErr(`Members load failed: ${res.status} ${res.error}`);
      setMembers([]);
      return;
    }
    setMembers(res.data);
  }

  async function inviteMember() {
    if (!wid) return;
    setErr(null);
    setMembersLoading(true);

    const res = await apiFetch<WorkspaceMember>(`/workspaces/${wid}/members`, {
      method: "POST",
      body: JSON.stringify({ email: inviteEmail, role: inviteRole }),
    });

    setMembersLoading(false);

    if (!res.ok) {
      setErr(`Invite failed: ${res.status} ${res.error}`);
      return;
    }

    setInviteEmail("");
    setInviteRole("member");
    await loadMembers();
  }

  async function updateMemberRole(userId: string, role: "admin" | "member" | "viewer") {
    if (!wid) return;
    setErr(null);
    setMembersLoading(true);

    const res = await apiFetch<WorkspaceMember>(`/workspaces/${wid}/members/${userId}`, {
      method: "PATCH",
      body: JSON.stringify({ email: "ignored", role }),
    });

    setMembersLoading(false);

    if (!res.ok) {
      setErr(`Role update failed: ${res.status} ${res.error}`);
      return;
    }

    await loadMembers();
  }

  async function removeMember(userId: string) {
    if (!wid) return;
    setErr(null);
    setMembersLoading(true);

    const res = await apiFetch<{ ok: boolean }>(`/workspaces/${wid}/members/${userId}`, {
      method: "DELETE",
    });

    setMembersLoading(false);

    if (!res.ok) {
      setErr(`Remove failed: ${res.status} ${res.error}`);
      return;
    }

    await loadMembers();
  }

  async function createRun() {
    if (!agentId) return;
    setErr(null);
    setCreating(true);

    let payload: any = {};
    try {
      payload = inputJson.trim() ? JSON.parse(inputJson) : {};
    } catch {
      setCreating(false);
      setErr("Input JSON is invalid. Please fix JSON format.");
      return;
    }

    const res = await apiFetch<Run>(`/workspaces/${wid}/runs`, {
      method: "POST",
      body: JSON.stringify({ agent_id: agentId, input_payload: payload }),
    });

    setCreating(false);

    if (!res.ok) {
      setErr(`Create run failed: ${res.status} ${res.error}`);
      return;
    }

    await loadAll();
  }

  useEffect(() => {
    if (!wid) return;
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid]);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Workspace</Title>
        <Button component={Link} to="/workspaces" variant="light">
          Back
        </Button>
      </Group>

      {ws ? (
        <Card withBorder>
          <Group justify="space-between">
            <Stack gap={2}>
              <Text fw={700}>{ws.name}</Text>
              <Text size="xs" c="dimmed">
                {ws.id}
              </Text>
            </Stack>
            {myRole ? <Badge variant="light">role: {myRole.role}</Badge> : null}
          </Group>
        </Card>
      ) : (
        <Text c="dimmed">Loading workspace…</Text>
      )}

      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={700}>Members</Text>
            <Button variant="light" onClick={loadMembers} loading={membersLoading}>
              Refresh
            </Button>
          </Group>

          {isAdmin ? (
            <Card withBorder>
              <Stack gap="sm">
                <Text fw={600}>Invite member</Text>
                <Group align="end">
                  <TextInput
                    label="Email"
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.currentTarget.value)}
                    placeholder="name@company.com"
                    style={{ flex: 1 }}
                  />
                  <Select
                    label="Role"
                    data={[
                      { value: "admin", label: "admin" },
                      { value: "member", label: "member" },
                      { value: "viewer", label: "viewer" },
                    ]}
                    value={inviteRole}
                    onChange={(v) => setInviteRole((v as any) || "member")}
                    style={{ width: 160 }}
                  />
                  <Button onClick={inviteMember} disabled={!inviteEmail.trim()} loading={membersLoading}>
                    Invite
                  </Button>
                </Group>
                <Text size="xs" c="dimmed">
                  Note: users must already exist in the system (registered) for invite-by-email in V0.
                </Text>
              </Stack>
            </Card>
          ) : (
            <Text size="sm" c="dimmed">
              You are not an admin — member management is disabled.
            </Text>
          )}

          {members.length === 0 ? (
            <Text c="dimmed">No members found.</Text>
          ) : (
            <Stack gap="xs">
              {members.map((m) => (
                <Card key={m.user_id} withBorder>
                  <Group justify="space-between" align="center">
                    <Stack gap={2}>
                      <Text fw={600}>{m.email}</Text>
                      <Text size="xs" c="dimmed">
                        {m.user_id}
                      </Text>
                    </Stack>

                    <Group>
                      <Badge variant="light">{m.role}</Badge>

                      {isAdmin && m.role !== "admin" ? (
                        <Select
                          data={[
                            { value: "admin", label: "admin" },
                            { value: "member", label: "member" },
                            { value: "viewer", label: "viewer" },
                          ]}
                          value={m.role}
                          onChange={(v) => v && updateMemberRole(m.user_id, v as any)}
                          style={{ width: 140 }}
                        />
                      ) : null}

                      {isAdmin && m.role !== "admin" ? (
                        <Button variant="light" color="red" onClick={() => removeMember(m.user_id)}>
                          Remove
                        </Button>
                      ) : null}
                    </Group>
                  </Group>
                </Card>
              ))}
            </Stack>
          )}
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Text fw={700}>Create Run</Text>
          <Select
            label="Pick an agent"
            data={agentOptions}
            value={agentId}
            onChange={setAgentId}
            searchable
            nothingFoundMessage="No agents"
          />

          {selectedAgent ? (
            <Card withBorder>
              <Stack gap={4}>
                <Group gap="sm">
                  <Badge>{selectedAgent.id}</Badge>
                  <Badge variant="light">{selectedAgent.version}</Badge>
                  <Text fw={600}>{selectedAgent.name}</Text>
                </Group>
                <Text size="sm" c="dimmed">
                  {selectedAgent.description}
                </Text>
                <Text size="sm">
                  This run will auto-create a draft artifact of type:{" "}
                  <Text span fw={700}>
                    {selectedAgent.default_artifact_type}
                  </Text>
                </Text>
              </Stack>
            </Card>
          ) : null}

          <Textarea
            label="Input payload (JSON)"
            autosize
            minRows={6}
            value={inputJson}
            onChange={(e) => setInputJson(e.currentTarget.value)}
          />
          <Group>
            <Button onClick={createRun} loading={creating}>
              Create Run
            </Button>
            <Button variant="light" onClick={loadAll}>
              Refresh
            </Button>
          </Group>

          {err && <Text c="red">{err}</Text>}
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={700}>Runs</Text>
            <Button variant="light" onClick={loadAll}>
              Refresh
            </Button>
          </Group>

          {runs.length === 0 ? (
            <Text c="dimmed">No runs yet.</Text>
          ) : (
            <Stack gap="xs">
              {runs.map((r) => (
                <Card key={r.id} withBorder>
                  <Group justify="space-between" align="flex-start">
                    <Stack gap={4}>
                      <Group gap="sm">
                        <Badge>{r.status}</Badge>
                        <Text fw={600}>{r.agent_id}</Text>
                      </Group>
                      {r.output_summary ? (
                        <Text size="sm" c="dimmed">
                          {r.output_summary}
                        </Text>
                      ) : null}
                      <Text size="xs" c="dimmed">
                        {r.id}
                      </Text>
                    </Stack>
                    <Button component={Link} to={`/runs/${r.id}`}>
                      Open
                    </Button>
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