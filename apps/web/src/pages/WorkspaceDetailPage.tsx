// apps/web/src/pages/WorkspaceDetailPage.tsx
import { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  Badge,
  Button,
  Group,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
  Divider,
  Code,
  Tooltip,
} from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { Agent, Run, Workspace, WorkspaceMember, WorkspaceRole, TemplateAdmin } from "../types";

import GlassPage from "../components/Glass/GlassPage";
import GlassCard from "../components/Glass/GlassCard";
import GlassSection from "../components/Glass/GlassSection";
import GlassStat from "../components/Glass/GlassStat";

function safeJsonParse(s: string): { ok: boolean; value: any; error?: string } {
  try {
    const v = s.trim() ? JSON.parse(s) : {};
    return { ok: true, value: v };
  } catch (e: any) {
    return { ok: false, value: null, error: e?.message || "Invalid JSON" };
  }
}

function stableJsonStringify(v: any): string {
  try {
    return JSON.stringify(v ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

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

  // Template Admin
  const [tplAdmin, setTplAdmin] = useState<TemplateAdmin | null>(null);
  const [tplAdminLoading, setTplAdminLoading] = useState(false);
  const [tplAdminSaving, setTplAdminSaving] = useState(false);
  const [tplAdminJson, setTplAdminJson] = useState<string>("{}");
  const [tplAdminDirty, setTplAdminDirty] = useState(false);
  const [tplAdminErr, setTplAdminErr] = useState<string | null>(null);

  const roleStr = (myRole?.role || "").toLowerCase();
  const isAdmin = roleStr === "admin";

  const selectedAgent = useMemo(() => agents.find((a) => a.id === agentId) || null, [agents, agentId]);

  const agentOptions = useMemo(
    () =>
      agents.map((a) => ({
        value: a.id,
        label: `${a.name} (${a.id})`,
      })),
    [agents]
  );

  async function loadTemplateAdmin() {
    if (!wid) return;
    setTplAdminErr(null);
    setTplAdminLoading(true);

    const res = await apiFetch<TemplateAdmin>(`/workspaces/${wid}/template-admin`, { method: "GET" });
    setTplAdminLoading(false);

    if (!res.ok) {
      setTplAdmin(null);
      setTplAdminJson("{}");
      setTplAdminDirty(false);
      setTplAdminErr(`Template Admin load failed: ${res.status} ${res.error}`);
      return;
    }

    setTplAdmin(res.data);
    setTplAdminJson(stableJsonStringify(res.data.template_admin_json || {}));
    setTplAdminDirty(false);
  }

  async function saveTemplateAdmin() {
    if (!wid) return;
    if (!isAdmin) {
      setTplAdminErr("Only admins can update Template Admin.");
      return;
    }

    const parsed = safeJsonParse(tplAdminJson);
    if (!parsed.ok) {
      setTplAdminErr(`Template Admin JSON invalid: ${parsed.error}`);
      return;
    }

    setTplAdminErr(null);
    setTplAdminSaving(true);

    const res = await apiFetch<TemplateAdmin>(`/workspaces/${wid}/template-admin`, {
      method: "PUT",
      body: JSON.stringify({ template_admin_json: parsed.value }),
    });

    setTplAdminSaving(false);

    if (!res.ok) {
      setTplAdminErr(`Template Admin save failed: ${res.status} ${res.error}`);
      return;
    }

    setTplAdmin(res.data);
    setTplAdminJson(stableJsonStringify(res.data.template_admin_json || {}));
    setTplAdminDirty(false);
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
    await loadTemplateAdmin();
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

  const tplAdminParsed = useMemo(() => safeJsonParse(tplAdminJson), [tplAdminJson]);

  const headerRight = (
    <Group>
      <Button component={Link} to={`/workspaces/${wid}`} variant="light" size="sm">
        Overview
      </Button>
      <Button component={Link} to={`/run-builder/${wid}`} size="sm">
        Create run
      </Button>
      <Button variant="light" onClick={loadAll} size="sm">
        Refresh
      </Button>
    </Group>
  );

  return (
    <GlassPage
      title={ws?.name ? `Workspace · ${ws.name}` : "Workspace"}
      subtitle="Legacy admin panel (members, template config, and quick run creation)."
      right={headerRight}
    >
      <Stack gap="md">
        {err ? (
          <GlassCard>
            <Text c="red">{err}</Text>
          </GlassCard>
        ) : null}

        <GlassSection
          title={ws?.name || "Loading…"}
          description={ws?.id || wid}
          right={
            <Group gap="sm" wrap="wrap">
              <GlassStat label="Access" value={isAdmin ? "Admin" : "Read-only"} />
              <GlassStat label="Members" value={members.length} />
              <GlassStat label="Runs" value={runs.length} />
            </Group>
          }
        >
          <Text size="sm" c="dimmed">
            This page stays available for advanced controls. Most day-to-day work happens in the Overview.
          </Text>
        </GlassSection>

        {/* Template Admin */}
        <GlassSection
          title="Template Admin"
          description="Workspace-scoped JSON configuration used by agents and templates."
          right={
            <Group>
              <Button variant="light" onClick={loadTemplateAdmin} loading={tplAdminLoading} size="sm">
                Refresh
              </Button>
              <Tooltip
                withArrow
                label={isAdmin ? "Saves template_admin_json for this workspace." : "Admin only."}
              >
                <span>
                  <Button
                    onClick={saveTemplateAdmin}
                    loading={tplAdminSaving}
                    disabled={!isAdmin || tplAdminLoading || !tplAdminDirty}
                    size="sm"
                  >
                    Save
                  </Button>
                </span>
              </Tooltip>
            </Group>
          }
        >
          <Stack gap="sm">
            <Group gap="sm">
              <Badge variant="light">V1</Badge>
              <Badge variant="light" color={isAdmin ? "grape" : "gray"}>
                {isAdmin ? "admin can edit" : "read-only"}
              </Badge>
              <Tooltip
                withArrow
                label="Stored at workspaces.template_admin_json. New workspaces default to {} until saved."
              >
                <Badge variant="light">Stored JSON</Badge>
              </Tooltip>
            </Group>

            {tplAdminErr ? (
              <GlassCard>
                <Text c="red">{tplAdminErr}</Text>
              </GlassCard>
            ) : null}

            <Textarea
              label="template_admin_json"
              description={
                tplAdminLoading
                  ? "Loading…"
                  : isAdmin
                    ? "Edit JSON and click Save."
                    : "Viewer/Member: read-only. Ask an admin to update."
              }
              autosize
              minRows={10}
              value={tplAdminJson}
              onChange={(e) => {
                setTplAdminJson(e.currentTarget.value);
                setTplAdminDirty(true);
                setTplAdminErr(null);
              }}
              disabled={!isAdmin || tplAdminLoading}
            />

            {!tplAdminParsed.ok ? (
              <Text c="red" size="sm">
                JSON error: {tplAdminParsed.error}
              </Text>
            ) : null}

            <Divider />

            <Text fw={600}>Suggested shape (example)</Text>
            <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
              {`{
  "prd_fields": {
    "required": ["Summary", "Problem", "Users / Segments", "Success Metrics", "Scope", "Requirements"],
    "optional": ["Risks", "Assumptions", "Open Questions", "Next Actions"]
  },
  "event_naming": {
    "format": "category_action_object",
    "examples": ["onboarding_click_cta", "pricing_view_plan"]
  },
  "research_taxonomy_tags": {
    "themes": ["pricing", "onboarding", "performance", "trust"],
    "personas": ["new_user", "power_user", "admin"]
  }
}`}
            </pre>

            {tplAdmin ? (
              <Text size="xs" c="dimmed">
                Loaded for workspace: <Code>{tplAdmin.workspace_id}</Code>
              </Text>
            ) : null}
          </Stack>
        </GlassSection>

        {/* Members */}
        <GlassSection
          title="Members"
          description="Manage workspace access (admin / member / viewer)."
          right={
            <Button variant="light" onClick={loadMembers} loading={membersLoading} size="sm">
              Refresh
            </Button>
          }
        >
          <Stack gap="sm">
            {!isAdmin ? (
              <Text size="sm" c="dimmed">
                You are not an admin — member management is disabled.
              </Text>
            ) : (
              <GlassCard p="md">
                <Stack gap="sm">
                  <Group justify="space-between" align="center">
                    <Text fw={700}>Invite member</Text>
                    <Tooltip withArrow label="In V0, the user must already be registered in the system.">
                      <Badge variant="light">V0 constraint</Badge>
                    </Tooltip>
                  </Group>

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
                    <Button onClick={inviteMember} disabled={!inviteEmail.trim()} loading={membersLoading} size="sm">
                      Invite
                    </Button>
                  </Group>
                </Stack>
              </GlassCard>
            )}

            {members.length === 0 ? (
              <Text c="dimmed">No members found.</Text>
            ) : (
              <Stack gap="xs">
                {members.map((m) => (
                  <GlassCard key={m.user_id} p="md">
                    <Group justify="space-between" align="center">
                      <Stack gap={2}>
                        <Text fw={700}>{m.email}</Text>
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
                          <Button variant="light" color="red" onClick={() => removeMember(m.user_id)} size="sm">
                            Remove
                          </Button>
                        ) : null}
                      </Group>
                    </Group>
                  </GlassCard>
                ))}
              </Stack>
            )}
          </Stack>
        </GlassSection>

        {/* Quick run creation */}
        <GlassSection
          title="Quick run (legacy)"
          description="Create a run directly from an agent with a raw JSON payload."
          right={
            <Tooltip withArrow label="Prefer Run Builder for a guided flow. This is a fast admin shortcut.">
              <Badge variant="light">Advanced</Badge>
            </Tooltip>
          }
        >
          <Stack gap="sm">
            <Select
              label="Agent"
              data={agentOptions}
              value={agentId}
              onChange={setAgentId}
              searchable
              nothingFoundMessage="No agents"
            />

            {selectedAgent ? (
              <GlassCard p="md">
                <Stack gap={4}>
                  <Group gap="sm">
                    <Badge variant="light">{selectedAgent.id}</Badge>
                    <Badge variant="light">{selectedAgent.version}</Badge>
                    <Text fw={700}>{selectedAgent.name}</Text>
                  </Group>
                  <Text size="sm" c="dimmed">
                    {selectedAgent.description}
                  </Text>
                  <Text size="sm">
                    Default artifact type:{" "}
                    <Text span fw={700}>
                      {selectedAgent.default_artifact_type}
                    </Text>
                  </Text>
                </Stack>
              </GlassCard>
            ) : null}

            <Textarea
              label="Input payload (JSON)"
              description={
                <Tooltip
                  withArrow
                  label="This is sent as input_payload. Keep it small and well-formed. Invalid JSON will fail fast."
                >
                  <span>Raw JSON input for the agent.</span>
                </Tooltip>
              }
              autosize
              minRows={6}
              value={inputJson}
              onChange={(e) => setInputJson(e.currentTarget.value)}
            />

            <Group>
              <Button onClick={createRun} loading={creating} size="sm">
                Create run
              </Button>
              <Button variant="light" onClick={loadAll} size="sm">
                Refresh
              </Button>
            </Group>
          </Stack>
        </GlassSection>

        {/* Runs list */}
        <GlassSection
          title="Runs"
          description="Latest runs in this workspace (newest first)."
          right={<GlassStat label="Total" value={runs.length} />}
        >
          {runs.length === 0 ? (
            <Text c="dimmed">No runs yet.</Text>
          ) : (
            <Stack gap="xs">
              {runs.slice(0, 15).map((r) => (
                <GlassCard key={r.id} p="md">
                  <Group justify="space-between" align="flex-start">
                    <Stack gap={6}>
                      <Group gap="sm">
                        <Badge variant="light">{r.status}</Badge>
                        <Text fw={700}>{r.agent_id}</Text>
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

                    <Button component={Link} to={`/runs/${r.id}`} variant="light" size="sm">
                      Open
                    </Button>
                  </Group>
                </GlassCard>
              ))}
            </Stack>
          )}
        </GlassSection>
      </Stack>
    </GlassPage>
  );
}