import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Group,
  Stack,
  Text,
  Title,
  Divider,
  Select,
  TextInput,
  Textarea,
  Switch,
  Tabs,
  Code,
} from "@mantine/core";
import { apiFetch } from "../apiClient";
import type {
  Agent,
  PipelineTemplate,
  Schedule,
  ScheduleRun,
  ScheduleRunDueResponse,
  ScheduleRunNowResponse,
  WorkspaceRole,
} from "../types";

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

function fmtIso(s?: string | null): string {
  if (!s) return "-";
  return s;
}

function scheduleKindLabel(k: string): string {
  return k === "pipeline_run" ? "pipeline_run" : "agent_run";
}

export default function SchedulesPage() {
  const { workspaceId } = useParams();
  const wid = workspaceId || "";

  const [myRole, setMyRole] = useState<WorkspaceRole | null>(null);
  const roleStr = (myRole?.role || "").toLowerCase();
  const canWrite = roleStr === "admin" || roleStr === "member";
  const isAdmin = roleStr === "admin";

  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [loading, setLoading] = useState(false);

  // create form
  const [createName, setCreateName] = useState("Daily monitoring — Post-launch monitoring");
  const [createKind, setCreateKind] = useState<"agent_run" | "pipeline_run">("agent_run");
  const [createTimezone, setCreateTimezone] = useState("UTC");
  const [createMode, setCreateMode] = useState<"daily" | "weekly">("daily");
  const [createAt, setCreateAt] = useState("09:00");
  const [createDays, setCreateDays] = useState<string[]>(["1", "3", "5"]); // Mon/Wed/Fri by default
  const [createEnabled, setCreateEnabled] = useState(true);

  // for agent_run
  const [agents, setAgents] = useState<Agent[]>([]);
  const [agentId, setAgentId] = useState<string | null>(null);
  const [agentInputJson, setAgentInputJson] = useState(
    JSON.stringify({ goal: "Daily monitoring pack", context: "", constraints: "" }, null, 2)
  );
  const [agentRetrievalJson, setAgentRetrievalJson] = useState<string>("null");

  // for pipeline_run
  const [templates, setTemplates] = useState<PipelineTemplate[]>([]);
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [pipelineInputJson, setPipelineInputJson] = useState(
    JSON.stringify({ goal: "Weekly pack", context: "", constraints: "" }, null, 2)
  );

  const [creating, setCreating] = useState(false);

  // selection + runs drawer
  const [selectedScheduleId, setSelectedScheduleId] = useState<string | null>(null);
  const selectedSchedule = useMemo(
    () => schedules.find((s) => s.id === selectedScheduleId) || null,
    [schedules, selectedScheduleId]
  );

  const [runs, setRuns] = useState<ScheduleRun[]>([]);
  const [runsLoading, setRunsLoading] = useState(false);

  const [runNowLoading, setRunNowLoading] = useState(false);
  const [runDueLoading, setRunDueLoading] = useState(false);

  async function loadRole() {
    if (!wid) return;
    const res = await apiFetch<WorkspaceRole>(`/workspaces/${wid}/my-role`, { method: "GET" });
    if (!res.ok) return;
    setMyRole(res.data);
  }

  async function loadAgents() {
    const res = await apiFetch<Agent[]>("/agents", { method: "GET" });
    if (!res.ok) return;
    setAgents(res.data || []);
    if (!agentId && (res.data || []).length > 0) setAgentId(res.data[0].id);
  }

  async function loadPipelineTemplates() {
    if (!wid) return;
    // Pipeline templates exist per workspace
    const res = await apiFetch<PipelineTemplate[]>(`/workspaces/${wid}/pipelines/templates`, { method: "GET" });
    if (!res.ok) return;
    setTemplates(res.data || []);
    if (!templateId && (res.data || []).length > 0) setTemplateId(res.data[0].id);
  }

  async function loadSchedules() {
    if (!wid) return;
    setErr(null);
    setInfo(null);
    setLoading(true);

    const res = await apiFetch<Schedule[]>(`/workspaces/${wid}/schedules`, { method: "GET" });

    setLoading(false);

    if (!res.ok) {
      setErr(`Load schedules failed: ${res.status} ${res.error}`);
      setSchedules([]);
      return;
    }

    const data = res.data || [];
    setSchedules(data);

    // keep selection stable if possible
    if (!selectedScheduleId && data.length > 0) setSelectedScheduleId(data[0].id);
    if (selectedScheduleId && !data.find((x) => x.id === selectedScheduleId)) {
      setSelectedScheduleId(data.length > 0 ? data[0].id : null);
    }
  }

  async function loadRuns(scheduleId: string) {
    setErr(null);
    setInfo(null);
    setRunsLoading(true);

    const res = await apiFetch<ScheduleRun[]>(`/schedules/${scheduleId}/runs`, { method: "GET" });

    setRunsLoading(false);

    if (!res.ok) {
      setErr(`Load schedule runs failed: ${res.status} ${res.error}`);
      setRuns([]);
      return;
    }

    setRuns(res.data || []);
  }

  async function createSchedule() {
    if (!wid || !canWrite) return;
    setErr(null);
    setInfo(null);

    // validate json inputs
    const ip = createKind === "agent_run" ? safeJsonParse(agentInputJson) : safeJsonParse(pipelineInputJson);
    if (!ip.ok) {
      setErr(`Input JSON invalid: ${ip.error}`);
      return;
    }

    let retrievalVal: any = null;
    if (createKind === "agent_run") {
      const rr = agentRetrievalJson.trim();
      if (rr === "" || rr === "null") {
        retrievalVal = null;
      } else {
        const parsed = safeJsonParse(rr);
        if (!parsed.ok) {
          setErr(`Retrieval JSON invalid: ${parsed.error}`);
          return;
        }
        retrievalVal = parsed.value;
      }
    }

    const interval_json =
      createMode === "daily"
        ? { mode: "daily", at: createAt }
        : {
            mode: "weekly",
            days: createDays.map((d) => Number(d)).filter((n) => Number.isFinite(n)),
            at: createAt,
          };

    let payload_json: any = {};
    if (createKind === "agent_run") {
      if (!agentId) {
        setErr("Pick an agent_id.");
        return;
      }
      payload_json = {
        agent_id: agentId,
        input_payload: ip.value,
        retrieval: retrievalVal,
      };
    } else {
      if (!templateId) {
        setErr("Pick a pipeline template_id.");
        return;
      }
      payload_json = {
        template_id: templateId,
        input_payload: ip.value,
      };
    }

    setCreating(true);
    const res = await apiFetch<Schedule>(`/workspaces/${wid}/schedules`, {
      method: "POST",
      body: JSON.stringify({
        name: createName.trim(),
        kind: createKind,
        timezone: createTimezone.trim() || "UTC",
        interval_json,
        payload_json,
        enabled: createEnabled,
      }),
    });
    setCreating(false);

    if (!res.ok) {
      setErr(`Create schedule failed: ${res.status} ${res.error}`);
      return;
    }

    setInfo(`Schedule created: ${res.data.id}`);
    await loadSchedules();
    setSelectedScheduleId(res.data.id);
  }

  async function toggleEnabled(s: Schedule, enabled: boolean) {
    if (!canWrite) return;
    setErr(null);
    setInfo(null);

    const res = await apiFetch<Schedule>(`/schedules/${s.id}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    });

    if (!res.ok) {
      setErr(`Update schedule failed: ${res.status} ${res.error}`);
      return;
    }

    setInfo(`Updated schedule: ${s.id}`);
    await loadSchedules();
  }

  async function deleteSchedule(s: Schedule) {
    if (!isAdmin) return;
    setErr(null);
    setInfo(null);

    const res = await apiFetch<{ ok: boolean }>(`/schedules/${s.id}`, { method: "DELETE" });

    if (!res.ok) {
      setErr(`Delete schedule failed: ${res.status} ${res.error}`);
      return;
    }

    setInfo(`Deleted schedule: ${s.id}`);
    setSelectedScheduleId(null);
    setRuns([]);
    await loadSchedules();
  }

  async function runNow(scheduleId: string) {
    setErr(null);
    setInfo(null);
    setRunNowLoading(true);

    const res = await apiFetch<ScheduleRunNowResponse>(`/schedules/${scheduleId}/run-now`, {
      method: "POST",
      body: JSON.stringify({}),
    });

    setRunNowLoading(false);

    if (!res.ok) {
      setErr(`Run now failed: ${res.status} ${res.error}`);
      return;
    }

    const rid = res.data.run_id || res.data.pipeline_run_id || "";
    setInfo(`Run executed: ${res.data.schedule_run.status}${rid ? ` (id=${rid})` : ""}`);
    await loadSchedules();
    await loadRuns(scheduleId);
  }

  async function runDueNow() {
    if (!wid) return;
    setErr(null);
    setInfo(null);
    setRunDueLoading(true);

    const res = await apiFetch<ScheduleRunDueResponse>(`/workspaces/${wid}/schedules/run-due`, {
      method: "POST",
      body: JSON.stringify({}),
    });

    setRunDueLoading(false);

    if (!res.ok) {
      setErr(`Run due failed: ${res.status} ${res.error}`);
      return;
    }

    setInfo(`run-due executed: due=${res.data.due_count} executed=${res.data.executed_count}`);
    await loadSchedules();

    // If a schedule is selected, refresh its run history too (best effort)
    if (selectedScheduleId) await loadRuns(selectedScheduleId);
  }

  useEffect(() => {
    if (!wid) return;
    void loadRole();
    void loadAgents();
    void loadPipelineTemplates();
    void loadSchedules();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid]);

  useEffect(() => {
    if (!selectedScheduleId) return;
    void loadRuns(selectedScheduleId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedScheduleId]);

  const agentOptions = useMemo(
    () =>
      agents.map((a) => ({
        value: a.id,
        label: `${a.name} (${a.id})`,
      })),
    [agents]
  );

  const templateOptions = useMemo(
    () =>
      templates.map((t) => ({
        value: t.id,
        label: `${t.name} (${t.id})`,
      })),
    [templates]
  );

  const weekdayOptions = [
    { value: "1", label: "Mon" },
    { value: "2", label: "Tue" },
    { value: "3", label: "Wed" },
    { value: "4", label: "Thu" },
    { value: "5", label: "Fri" },
    { value: "6", label: "Sat" },
    { value: "0", label: "Sun" },
  ];

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Schedules</Title>
        <Group>
          <Button component={Link} to={`/workspaces/${wid}`} variant="light">
            Back to Workspace
          </Button>
          <Button variant="light" onClick={loadSchedules} loading={loading}>
            Refresh
          </Button>
          <Button variant="light" onClick={runDueNow} loading={runDueLoading} disabled={!canWrite}>
            Run due now
          </Button>
        </Group>
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

      <Group align="flex-start" grow>
        {/* Left: list */}
        <Card withBorder style={{ flex: 1 }}>
          <Stack gap="sm">
            <Group justify="space-between">
              <Text fw={700}>Existing schedules</Text>
              <Badge variant="light">{schedules.length}</Badge>
            </Group>

            {schedules.length === 0 ? (
              <Text c="dimmed">No schedules yet.</Text>
            ) : (
              <Stack gap="xs">
                {schedules.map((s) => (
                  <Card
                    key={s.id}
                    withBorder
                    style={{
                      cursor: "pointer",
                      borderColor: s.id === selectedScheduleId ? "var(--mantine-color-blue-5)" : undefined,
                    }}
                    onClick={() => setSelectedScheduleId(s.id)}
                  >
                    <Stack gap={6}>
                      <Group justify="space-between" align="flex-start">
                        <Stack gap={2} style={{ flex: 1 }}>
                          <Group gap="sm" wrap="wrap">
                            <Badge>{scheduleKindLabel(s.kind)}</Badge>
                            <Badge variant="light">{s.enabled ? "enabled" : "disabled"}</Badge>
                            {s.last_status ? <Badge variant="light">last: {s.last_status}</Badge> : null}
                            {s.next_run_at ? <Badge variant="outline">next: {s.next_run_at}</Badge> : null}
                          </Group>
                          <Text fw={600}>{s.name}</Text>
                          <Text size="xs" c="dimmed">
                            {s.id}
                          </Text>
                        </Stack>

                        <Switch
                          checked={!!s.enabled}
                          onChange={(e) => toggleEnabled(s, e.currentTarget.checked)}
                          disabled={!canWrite}
                          label="Enabled"
                        />
                      </Group>

                      {s.last_error ? (
                        <Text size="sm" c="red">
                          last_error: {s.last_error}
                        </Text>
                      ) : null}
                    </Stack>
                  </Card>
                ))}
              </Stack>
            )}
          </Stack>
        </Card>

        {/* Right: details */}
        <Card withBorder style={{ flex: 1 }}>
          <Stack gap="sm">
            <Group justify="space-between">
              <Text fw={700}>Selected</Text>
              {selectedSchedule ? <Badge variant="light">{selectedSchedule.kind}</Badge> : null}
            </Group>

            {!selectedSchedule ? (
              <Text c="dimmed">Pick a schedule from the list.</Text>
            ) : (
              <>
                <Group justify="space-between" align="flex-start">
                  <Stack gap={2}>
                    <Text fw={600}>{selectedSchedule.name}</Text>
                    <Text size="xs" c="dimmed">
                      {selectedSchedule.id}
                    </Text>
                  </Stack>

                  <Group>
                    <Button
                      size="sm"
                      onClick={() => runNow(selectedSchedule.id)}
                      loading={runNowLoading}
                      disabled={!canWrite}
                    >
                      Run now
                    </Button>
                    <Button
                      size="sm"
                      color="red"
                      variant="light"
                      onClick={() => deleteSchedule(selectedSchedule)}
                      disabled={!isAdmin}
                    >
                      Delete
                    </Button>
                  </Group>
                </Group>

                <Divider />

                <Text size="sm" c="dimmed">
                  <b>Timing</b>: timezone=<Code>{selectedSchedule.timezone}</Code>{" "}
                  cron=<Code>{String(selectedSchedule.cron ?? "null")}</Code>{" "}
                  interval_json=<Code>{stableJsonStringify(selectedSchedule.interval_json)}</Code>
                </Text>

                <Text size="sm" c="dimmed">
                  next_run_at=<Code>{fmtIso(selectedSchedule.next_run_at)}</Code> · last_run_at=
                  <Code>{fmtIso(selectedSchedule.last_run_at)}</Code>
                </Text>

                <Divider />

                <Text fw={600}>Payload</Text>
                <Card withBorder>
                  <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                    {stableJsonStringify(selectedSchedule.payload_json)}
                  </pre>
                </Card>

                <Divider />

                <Group justify="space-between">
                  <Text fw={600}>Run history</Text>
                  <Button variant="light" size="xs" onClick={() => loadRuns(selectedSchedule.id)} loading={runsLoading}>
                    Refresh history
                  </Button>
                </Group>

                {runs.length === 0 ? (
                  <Text c="dimmed">No runs yet.</Text>
                ) : (
                  <Stack gap="xs">
                    {runs.map((r) => (
                      <Card key={r.id} withBorder>
                        <Stack gap={4}>
                          <Group gap="sm" wrap="wrap">
                            <Badge>{r.status}</Badge>
                            <Badge variant="light">started: {r.started_at}</Badge>
                            {r.finished_at ? <Badge variant="light">finished: {r.finished_at}</Badge> : null}
                            {r.run_id ? (
                              <Button
                                component={Link}
                                to={`/runs/${r.run_id}`}
                                size="xs"
                                variant="light"
                              >
                                Open run
                              </Button>
                            ) : null}
                            {r.pipeline_run_id ? (
                              <Button
                                component={Link}
                                to={`/pipelines/runs/${r.pipeline_run_id}`}
                                size="xs"
                                variant="light"
                              >
                                Open pipeline run
                              </Button>
                            ) : null}
                          </Group>

                          {r.error ? (
                            <Text c="red" size="sm">
                              error: {r.error}
                            </Text>
                          ) : null}

                          <Text size="xs" c="dimmed">
                            {r.id}
                          </Text>

                          <Card withBorder>
                            <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                              {stableJsonStringify(r.meta)}
                            </pre>
                          </Card>
                        </Stack>
                      </Card>
                    ))}
                  </Stack>
                )}
              </>
            )}
          </Stack>
        </Card>
      </Group>

      <Divider />

      {/* Create */}
      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={700}>Create schedule</Text>
            <Badge variant="light">Commit 3</Badge>
          </Group>

          {!canWrite ? (
            <Text size="sm" c="dimmed">
              Viewer role cannot create schedules.
            </Text>
          ) : null}

          <Group grow>
            <TextInput
              label="name"
              value={createName}
              onChange={(e) => setCreateName(e.currentTarget.value)}
              disabled={!canWrite}
            />
            <Select
              label="kind"
              data={[
                { value: "agent_run", label: "agent_run" },
                { value: "pipeline_run", label: "pipeline_run" },
              ]}
              value={createKind}
              onChange={(v) => setCreateKind((v as any) || "agent_run")}
              disabled={!canWrite}
            />
          </Group>

          <Group grow>
            <TextInput
              label="timezone"
              value={createTimezone}
              onChange={(e) => setCreateTimezone(e.currentTarget.value)}
              placeholder="UTC"
              disabled={!canWrite}
            />
            <Select
              label="interval mode"
              data={[
                { value: "daily", label: "daily" },
                { value: "weekly", label: "weekly" },
              ]}
              value={createMode}
              onChange={(v) => setCreateMode((v as any) || "daily")}
              disabled={!canWrite}
            />
            <TextInput
              label="at (HH:MM)"
              value={createAt}
              onChange={(e) => setCreateAt(e.currentTarget.value)}
              placeholder="09:00"
              disabled={!canWrite}
            />
          </Group>

          {createMode === "weekly" ? (
            <Select
              label="days (0=Sun ... 6=Sat)"
              data={weekdayOptions}
              value={createDays}
              onChange={(v) => setCreateDays((v as any) || [])}
              multiple
              searchable
              disabled={!canWrite}
            />
          ) : null}

          <Switch
            checked={createEnabled}
            onChange={(e) => setCreateEnabled(e.currentTarget.checked)}
            label="Enabled"
            disabled={!canWrite}
          />

          <Tabs defaultValue="payload">
            <Tabs.List>
              <Tabs.Tab value="payload">Payload</Tabs.Tab>
              <Tabs.Tab value="examples">Examples</Tabs.Tab>
            </Tabs.List>

            <Tabs.Panel value="payload" pt="sm">
              {createKind === "agent_run" ? (
                <Stack gap="sm">
                  <Select
                    label="agent_id"
                    data={agentOptions}
                    value={agentId}
                    onChange={setAgentId}
                    searchable
                    nothingFoundMessage="No agents"
                    disabled={!canWrite}
                  />

                  <Textarea
                    label="input_payload (JSON)"
                    autosize
                    minRows={6}
                    value={agentInputJson}
                    onChange={(e) => setAgentInputJson(e.currentTarget.value)}
                    disabled={!canWrite}
                  />

                  <Textarea
                    label="retrieval (JSON or null)"
                    description='Use "null" for no retrieval. Otherwise paste the retrieval object.'
                    autosize
                    minRows={6}
                    value={agentRetrievalJson}
                    onChange={(e) => setAgentRetrievalJson(e.currentTarget.value)}
                    disabled={!canWrite}
                  />
                </Stack>
              ) : (
                <Stack gap="sm">
                  <Select
                    label="template_id"
                    data={templateOptions}
                    value={templateId}
                    onChange={setTemplateId}
                    searchable
                    nothingFoundMessage="No templates"
                    disabled={!canWrite}
                  />

                  <Textarea
                    label="input_payload (JSON)"
                    autosize
                    minRows={8}
                    value={pipelineInputJson}
                    onChange={(e) => setPipelineInputJson(e.currentTarget.value)}
                    disabled={!canWrite}
                  />
                </Stack>
              )}
            </Tabs.Panel>

            <Tabs.Panel value="examples" pt="sm">
              <Stack gap="sm">
                <Text size="sm" c="dimmed">
                  Daily (09:00): <Code>{`{ "mode": "daily", "at": "09:00" }`}</Code>
                </Text>
                <Text size="sm" c="dimmed">
                  Weekly (Mon/Wed/Fri 10:30):{" "}
                  <Code>{`{ "mode": "weekly", "days": [1,3,5], "at": "10:30" }`}</Code>
                </Text>
                <Text size="sm" c="dimmed">
                  agent_run payload:{" "}
                  <Code>
                    {`{ "agent_id": "post_launch_monitoring", "input_payload": { "goal": "Daily monitoring pack" }, "retrieval": null }`}
                  </Code>
                </Text>
                <Text size="sm" c="dimmed">
                  pipeline_run payload:{" "}
                  <Code>
                    {`{ "template_id": "<pipeline_template_uuid>", "input_payload": { "goal": "Weekly pack" } }`}
                  </Code>
                </Text>
              </Stack>
            </Tabs.Panel>
          </Tabs>

          <Group>
            <Button onClick={createSchedule} loading={creating} disabled={!canWrite}>
              Create schedule
            </Button>
            <Button variant="light" onClick={loadSchedules} loading={loading}>
              Refresh
            </Button>
          </Group>

          <Text size="xs" c="dimmed">
            RBAC: member/admin can create & run schedules. Admin can delete schedules. Viewer is read-only.
          </Text>
        </Stack>
      </Card>
    </Stack>
  );
}