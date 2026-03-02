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
  TextInput,
  Textarea,
  Title,
  NumberInput,
  Divider,
  Collapse,
  Code,
} from "@mantine/core";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { apiFetch } from "../apiClient";
import type {
  Artifact,
  Evidence,
  Run,
  RunLog,
  RunTimelineEvent,
  RagDebugResponse,
} from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL as string;

const ARTIFACT_TYPES = [
  "problem_brief",
  "research_summary",
  "competitive_matrix",
  "strategy_memo",
  "prd",
  "ux_spec",
  "tech_brief",
  "delivery_plan",
  "tracking_spec",
  "experiment_plan",
  "qa_suite",
  "launch_plan",
  "health_report",
  "decision_log",
  "monetization_brief",
  "safety_spec",
];

function eventBadgeColor(kind: string): string {
  if (kind === "artifact") return "grape";
  if (kind === "evidence") return "teal";
  if (kind === "log") return "gray";
  if (kind === "status") return "blue";
  return "dark";
}

function logBadgeColor(level: string): string {
  if (level === "error") return "red";
  if (level === "warn") return "yellow";
  if (level === "debug") return "gray";
  return "blue";
}

function safeJson(v: any): string {
  try {
    return JSON.stringify(v ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

export default function RunDetailPage() {
  const { runId } = useParams();
  const rid = runId || "";

  const [run, setRun] = useState<Run | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [timeline, setTimeline] = useState<RunTimelineEvent[]>([]);
  const [logs, setLogs] = useState<RunLog[]>([]);
  const [err, setErr] = useState<string | null>(null);

  // RAG debug panel
  const [ragOpen, setRagOpen] = useState(false);
  const [ragLoading, setRagLoading] = useState(false);
  const [ragDebug, setRagDebug] = useState<RagDebugResponse | null>(null);

  // Create artifact form
  const [atype, setAtype] = useState<string | null>("prd");
  const [title, setTitle] = useState("Untitled");
  const [logicalKey, setLogicalKey] = useState("prd");
  const [contentMd, setContentMd] = useState("# Draft\n\nWrite your draft here…");
  const [creatingArtifact, setCreatingArtifact] = useState(false);

  // Evidence form
  const [ekind, setEkind] = useState<string | null>("snippet");
  const [sourceName, setSourceName] = useState("manual");
  const [sourceRef, setSourceRef] = useState("");
  const [excerpt, setExcerpt] = useState("Evidence excerpt…");
  const [metaJson, setMetaJson] = useState("{}");
  const [creatingEvidence, setCreatingEvidence] = useState(false);

  // Auto evidence
  const [autoQuery, setAutoQuery] = useState("");
  const [autoK, setAutoK] = useState<number>(6);
  const [autoAlpha, setAutoAlpha] = useState<number>(0.65);
  const [autoLoading, setAutoLoading] = useState(false);

  // Regenerate
  const [regenLoading, setRegenLoading] = useState(false);

  // Logs (create)
  const [logLevel, setLogLevel] = useState<string | null>("info");
  const [logMessage, setLogMessage] = useState<string>("Ran quick check");
  const [logMetaJson, setLogMetaJson] = useState<string>("{}");
  const [creatingLog, setCreatingLog] = useState(false);

  // Logs filter
  const [logFilter, setLogFilter] = useState<string | null>("all");

  const artifactTypeOptions = useMemo(
    () => ARTIFACT_TYPES.map((t) => ({ value: t, label: t })),
    []
  );

  const latestArtifact = useMemo(() => {
    if (artifacts.length === 0) return null;
    return artifacts[0]; // newest first
  }, [artifacts]);

  const retrievalCfg = useMemo(() => {
    const ip: any = run?.input_payload ?? {};
    return (ip?._retrieval as any) || null;
  }, [run]);

  const filteredLogs = useMemo(() => {
    if (logFilter === "all") return logs;
    return logs.filter((l) => l.level === logFilter);
  }, [logs, logFilter]);

  async function loadAll() {
    setErr(null);

    const runRes = await apiFetch<Run>(`/runs/${rid}`, { method: "GET" });
    if (!runRes.ok) {
      setErr(`Run load failed: ${runRes.status} ${runRes.error}`);
      return;
    }
    setRun(runRes.data);

    const artRes = await apiFetch<Artifact[]>(`/runs/${rid}/artifacts`, { method: "GET" });
    if (!artRes.ok) {
      setErr(`Artifacts load failed: ${artRes.status} ${artRes.error}`);
      return;
    }
    setArtifacts(artRes.data);

    const evRes = await apiFetch<Evidence[]>(`/runs/${rid}/evidence`, { method: "GET" });
    if (!evRes.ok) {
      setErr(`Evidence load failed: ${evRes.status} ${evRes.error}`);
      return;
    }
    setEvidence(evRes.data);

    const tlRes = await apiFetch<RunTimelineEvent[]>(`/runs/${rid}/timeline`, { method: "GET" });
    if (!tlRes.ok) {
      setErr(`Timeline load failed: ${tlRes.status} ${tlRes.error}`);
      return;
    }
    setTimeline(tlRes.data);

    const logsRes = await apiFetch<RunLog[]>(`/runs/${rid}/logs`, { method: "GET" });
    if (!logsRes.ok) {
      setErr(`Logs load failed: ${logsRes.status} ${logsRes.error}`);
      return;
    }
    setLogs(logsRes.data);
  }

  async function loadRagDebug() {
    setRagLoading(true);
    setErr(null);

    const res = await apiFetch<RagDebugResponse>(`/runs/${rid}/rag-debug`, { method: "GET" });
    setRagLoading(false);

    if (!res.ok) {
      setErr(`RAG debug failed: ${res.status} ${res.error}`);
      setRagDebug(null);
      return;
    }
    setRagDebug(res.data);
  }

  function exportPdf(artifactId: string) {
    window.open(`${API_BASE}/artifacts/${artifactId}/export/pdf`, "_blank");
  }

  function exportDocx(artifactId: string) {
    window.open(`${API_BASE}/artifacts/${artifactId}/export/docx`, "_blank");
  }

  async function createArtifact() {
    if (!atype) return;
    setCreatingArtifact(true);
    setErr(null);

    const res = await apiFetch<Artifact>(`/runs/${rid}/artifacts`, {
      method: "POST",
      body: JSON.stringify({
        type: atype,
        title,
        content_md: contentMd,
        logical_key: logicalKey,
      }),
    });

    setCreatingArtifact(false);

    if (!res.ok) {
      setErr(`Create artifact failed: ${res.status} ${res.error}`);
      return;
    }

    await loadAll();
  }

  async function addEvidence() {
    if (!ekind) return;
    setCreatingEvidence(true);
    setErr(null);

    let meta: any = {};
    try {
      meta = metaJson.trim() ? JSON.parse(metaJson) : {};
    } catch {
      setCreatingEvidence(false);
      setErr("Evidence meta JSON is invalid.");
      return;
    }

    const res = await apiFetch<Evidence>(`/runs/${rid}/evidence`, {
      method: "POST",
      body: JSON.stringify({
        kind: ekind,
        source_name: sourceName,
        source_ref: sourceRef || null,
        excerpt,
        meta,
      }),
    });

    setCreatingEvidence(false);

    if (!res.ok) {
      setErr(`Add evidence failed: ${res.status} ${res.error}`);
      return;
    }

    await loadAll();
  }

  async function autoAddEvidence() {
    if (!autoQuery.trim()) {
      setErr("Enter a query to auto-add evidence.");
      return;
    }
    setAutoLoading(true);
    setErr(null);

    const res = await apiFetch<Evidence[]>(`/runs/${rid}/evidence/auto`, {
      method: "POST",
      body: JSON.stringify({
        query: autoQuery.trim(),
        k: autoK,
        alpha: autoAlpha,
      }),
    });

    setAutoLoading(false);

    if (!res.ok) {
      setErr(`Auto evidence failed: ${res.status} ${res.error}`);
      return;
    }

    await loadAll();
    if (ragOpen) await loadRagDebug();
  }

  async function regenerate() {
    setRegenLoading(true);
    setErr(null);

    const res = await apiFetch<Run>(`/runs/${rid}/regenerate`, {
      method: "POST",
      body: JSON.stringify({}),
    });

    setRegenLoading(false);

    if (!res.ok) {
      setErr(`Regenerate failed: ${res.status} ${res.error}`);
      return;
    }

    await loadAll();
  }

  async function createLog() {
    if (!logLevel) return;
    if (!logMessage.trim()) {
      setErr("Log message cannot be empty.");
      return;
    }

    setCreatingLog(true);
    setErr(null);

    let meta: any = {};
    try {
      meta = logMetaJson.trim() ? JSON.parse(logMetaJson) : {};
    } catch {
      setCreatingLog(false);
      setErr("Log meta JSON is invalid.");
      return;
    }

    const res = await apiFetch<RunLog>(`/runs/${rid}/logs`, {
      method: "POST",
      body: JSON.stringify({
        level: logLevel,
        message: logMessage.trim(),
        meta,
      }),
    });

    setCreatingLog(false);

    if (!res.ok) {
      setErr(`Create log failed: ${res.status} ${res.error}`);
      return;
    }

    await loadAll();
    if (ragOpen) await loadRagDebug();
  }

  useEffect(() => {
    if (!rid) return;
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rid]);

  useEffect(() => {
    if (!rid) return;
    if (!ragOpen) return;
    void loadRagDebug();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ragOpen, rid]);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Run · RAG Console</Title>
        <Button component={Link} to="/workspaces" variant="light">
          Back to Workspaces
        </Button>
      </Group>

      {err && (
        <Card withBorder>
          <Text c="red">{err}</Text>
        </Card>
      )}

      {/* Run overview */}
      {run ? (
        <Card withBorder>
          <Stack gap="xs">
            <Group justify="space-between">
              <Group gap="sm">
                <Badge>{run.status}</Badge>
                <Text fw={700}>{run.agent_id}</Text>
                {retrievalCfg ? <Badge variant="light">retrieval enabled</Badge> : <Badge variant="light">no retrieval</Badge>}
              </Group>
              <Text size="xs" c="dimmed">
                {run.id}
              </Text>
            </Group>

            {run.output_summary ? <Text c="dimmed">{run.output_summary}</Text> : null}

            {/* Retrieval summary */}
            {retrievalCfg ? (
              <Card withBorder>
                <Stack gap={6}>
                  <Text fw={600}>Retrieval config</Text>
                  <Group gap="sm">
                    <Text size="sm">
                      query: <Code>{String(retrievalCfg.query ?? "")}</Code>
                    </Text>
                    <Text size="sm">
                      k: <Code>{String(retrievalCfg.k ?? "")}</Code>
                    </Text>
                    <Text size="sm">
                      alpha: <Code>{String(retrievalCfg.alpha ?? "")}</Code>
                    </Text>
                    <Text size="sm">
                      evidence_count: <Code>{String(retrievalCfg.evidence_count ?? "")}</Code>
                    </Text>
                  </Group>
                  <Text size="sm" c="dimmed">
                    source_types: {Array.isArray(retrievalCfg.source_types) ? retrievalCfg.source_types.join(", ") : "(none)"} · timeframe:{" "}
                    {retrievalCfg.timeframe ? JSON.stringify(retrievalCfg.timeframe) : "(none)"}
                  </Text>
                </Stack>
              </Card>
            ) : null}

            {/* Regenerate */}
            <Group gap="sm">
              <Button onClick={regenerate} loading={regenLoading} disabled={evidence.length === 0}>
                Regenerate using evidence
              </Button>
              <Text size="sm" c="dimmed">
                {evidence.length === 0
                  ? "Add evidence first to enable regenerate."
                  : `Uses ${evidence.length} evidence item(s). Creates a new artifact version.`}
              </Text>
            </Group>

            {/* Input payload */}
            <Card withBorder>
              <Text fw={600} mb={6}>
                Input payload
              </Text>
              <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                {JSON.stringify(run.input_payload, null, 2)}
              </pre>
            </Card>
          </Stack>
        </Card>
      ) : (
        <Text c="dimmed">Loading run…</Text>
      )}

      {/* Latest artifact console */}
      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={700}>Latest Artifact</Text>
            {latestArtifact ? (
              <Group>
                <Button size="xs" variant="light" component={Link} to={`/artifacts/${latestArtifact.id}`}>
                  Open
                </Button>
                <Button size="xs" variant="default" onClick={() => exportPdf(latestArtifact.id)}>
                  Export PDF
                </Button>
                <Button size="xs" variant="default" onClick={() => exportDocx(latestArtifact.id)}>
                  Export DOCX
                </Button>
              </Group>
            ) : (
              <Badge variant="light">none</Badge>
            )}
          </Group>

          {!latestArtifact ? (
            <Text c="dimmed">No artifacts yet.</Text>
          ) : (
            <Card withBorder style={{ maxHeight: 420, overflow: "auto" }}>
              <Stack gap={6}>
                <Text size="sm" c="dimmed">
                  {latestArtifact.type} · v{latestArtifact.version} · {latestArtifact.status} · key={latestArtifact.logical_key}
                </Text>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{latestArtifact.content_md || ""}</ReactMarkdown>
              </Stack>
            </Card>
          )}
        </Stack>
      </Card>

      {/* RAG debug */}
      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={700}>RAG Debug</Text>
            <Group>
              <Button variant="light" onClick={() => setRagOpen((x) => !x)}>
                {ragOpen ? "Hide" : "Show"}
              </Button>
              <Button variant="default" onClick={loadRagDebug} loading={ragLoading} disabled={!ragOpen}>
                Refresh
              </Button>
            </Group>
          </Group>

          <Collapse in={ragOpen}>
            <Stack gap="sm">
              <Card withBorder>
                <Text fw={600} mb={6}>
                  retrieval_config (from run.input_payload._retrieval)
                </Text>
                <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                  {safeJson(retrievalCfg)}
                </pre>
              </Card>

              <Card withBorder>
                <Text fw={600} mb={6}>
                  retrieval_log (latest “Pre-retrieval…” RunLog meta)
                </Text>
                <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                  {safeJson(ragDebug?.retrieval_log ?? null)}
                </pre>
              </Card>

              <Card withBorder>
                <Group justify="space-between">
                  <Text fw={600}>Evidence (from rag-debug)</Text>
                  <Badge variant="light">{ragDebug?.evidence?.length ?? 0}</Badge>
                </Group>
                <Divider my="sm" />
                {(!ragDebug || !ragDebug.evidence || ragDebug.evidence.length === 0) ? (
                  <Text c="dimmed">No evidence attached.</Text>
                ) : (
                  <Stack gap="xs">
                    {ragDebug.evidence.map((e) => (
                      <Card key={e.id} withBorder>
                        <Stack gap={4}>
                          <Group gap="sm">
                            <Badge variant="light">{e.kind}</Badge>
                            <Text fw={600}>{e.source_name}</Text>
                            {e.source_ref ? (
                              <Text size="sm" c="dimmed">
                                {e.source_ref}
                              </Text>
                            ) : null}
                          </Group>
                          <Text size="sm">{e.excerpt}</Text>
                          <Text size="xs" c="dimmed">
                            {e.id}
                          </Text>
                        </Stack>
                      </Card>
                    ))}
                  </Stack>
                )}
              </Card>
            </Stack>
          </Collapse>
        </Stack>
      </Card>

      {/* Timeline */}
      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={700}>Timeline</Text>
            <Button variant="light" onClick={loadAll}>
              Refresh
            </Button>
          </Group>

          {timeline.length === 0 ? (
            <Text c="dimmed">No timeline events yet.</Text>
          ) : (
            <Stack gap="xs">
              {timeline.map((ev, idx) => (
                <Card key={`${ev.kind}:${ev.ref_id ?? "x"}:${idx}`} withBorder>
                  <Group justify="space-between" align="flex-start">
                    <Stack gap={2}>
                      <Group gap="sm">
                        <Badge color={eventBadgeColor(ev.kind)} variant="light">
                          {ev.kind}
                        </Badge>
                        <Text fw={600}>{ev.label}</Text>
                      </Group>
                      <Text size="xs" c="dimmed">
                        {new Date(ev.ts).toLocaleString()}
                        {ev.ref_id ? ` · ref=${ev.ref_id}` : ""}
                      </Text>
                    </Stack>

                    {ev.kind === "artifact" && ev.ref_id ? (
                      <Button size="xs" variant="light" component={Link} to={`/artifacts/${ev.ref_id}`}>
                        Open
                      </Button>
                    ) : null}
                  </Group>
                </Card>
              ))}
            </Stack>
          )}
        </Stack>
      </Card>

      {/* Logs */}
      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={700}>Logs</Text>
            <Group>
              <Select
                data={[
                  { value: "all", label: "all" },
                  { value: "info", label: "info" },
                  { value: "warn", label: "warn" },
                  { value: "error", label: "error" },
                  { value: "debug", label: "debug" },
                ]}
                value={logFilter}
                onChange={setLogFilter}
                w={160}
              />
              <Button variant="light" onClick={loadAll}>
                Refresh
              </Button>
            </Group>
          </Group>

          <Divider />

          <Text fw={600}>Add log (member+)</Text>
          <Group grow>
            <Select
              label="Level"
              data={[
                { value: "info", label: "info" },
                { value: "warn", label: "warn" },
                { value: "error", label: "error" },
                { value: "debug", label: "debug" },
              ]}
              value={logLevel}
              onChange={setLogLevel}
            />
            <TextInput
              label="Message"
              value={logMessage}
              onChange={(e) => setLogMessage(e.currentTarget.value)}
            />
          </Group>

          <Textarea
            label="Meta (JSON)"
            autosize
            minRows={2}
            value={logMetaJson}
            onChange={(e) => setLogMetaJson(e.currentTarget.value)}
          />

          <Button onClick={createLog} loading={creatingLog}>
            Add Log
          </Button>

          <Divider />

          {filteredLogs.length === 0 ? (
            <Text c="dimmed">No logs yet.</Text>
          ) : (
            <Stack gap="xs">
              {filteredLogs.map((l) => (
                <Card key={l.id} withBorder>
                  <Stack gap={4}>
                    <Group gap="sm">
                      <Badge color={logBadgeColor(l.level)} variant="light">
                        {l.level}
                      </Badge>
                      <Text fw={600}>{l.message}</Text>
                    </Group>
                    <Text size="xs" c="dimmed">
                      {new Date(l.created_at).toLocaleString()} · {l.id}
                    </Text>
                    {l.meta && Object.keys(l.meta).length > 0 ? (
                      <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                        {JSON.stringify(l.meta, null, 2)}
                      </pre>
                    ) : null}
                  </Stack>
                </Card>
              ))}
            </Stack>
          )}
        </Stack>
      </Card>

      {/* Auto evidence */}
      <Card withBorder>
        <Stack gap="sm">
          <Text fw={700}>Auto-add Evidence (from Retrieval)</Text>
          <Text size="sm" c="dimmed">
            Provide a query. We’ll fetch top retrieval chunks and attach them as evidence.
          </Text>

          <Divider />

          <TextInput
            label="Query"
            value={autoQuery}
            onChange={(e) => setAutoQuery(e.currentTarget.value)}
            placeholder='e.g., "refresh tokens"'
          />

          <Group grow>
            <NumberInput
              label="Top K"
              value={autoK}
              min={1}
              max={20}
              onChange={(v) => setAutoK(Number(v) || 6)}
            />
            <NumberInput
              label="Alpha (vector weight)"
              value={autoAlpha}
              min={0}
              max={1}
              step={0.05}
              onChange={(v) => setAutoAlpha(Number(v) || 0.65)}
            />
          </Group>

          <Button onClick={autoAddEvidence} loading={autoLoading}>
            Fetch & attach evidence
          </Button>
        </Stack>
      </Card>

      {/* Create artifact */}
      <Card withBorder>
        <Stack gap="sm">
          <Text fw={700}>Create Artifact</Text>
          <Select label="Type" data={artifactTypeOptions} value={atype} onChange={setAtype} />
          <Group grow>
            <TextInput label="Title" value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
            <TextInput
              label="Logical key (for versioning)"
              value={logicalKey}
              onChange={(e) => setLogicalKey(e.currentTarget.value)}
            />
          </Group>
          <Textarea
            label="Content (Markdown)"
            autosize
            minRows={6}
            value={contentMd}
            onChange={(e) => setContentMd(e.currentTarget.value)}
          />
          <Button onClick={createArtifact} loading={creatingArtifact}>
            Create
          </Button>
        </Stack>
      </Card>

      {/* Evidence create */}
      <Card withBorder>
        <Stack gap="sm">
          <Text fw={700}>Add Evidence</Text>
          <Group grow>
            <Select
              label="Kind"
              data={[
                { value: "metric", label: "metric" },
                { value: "snippet", label: "snippet" },
                { value: "link", label: "link" },
              ]}
              value={ekind}
              onChange={setEkind}
            />
            <TextInput
              label="Source name"
              value={sourceName}
              onChange={(e) => setSourceName(e.currentTarget.value)}
            />
          </Group>

          <TextInput
            label="Source ref (URL/id)"
            value={sourceRef}
            onChange={(e) => setSourceRef(e.currentTarget.value)}
            placeholder="optional"
          />
          <Textarea
            label="Excerpt"
            autosize
            minRows={3}
            value={excerpt}
            onChange={(e) => setExcerpt(e.currentTarget.value)}
          />
          <Textarea
            label="Meta (JSON)"
            autosize
            minRows={3}
            value={metaJson}
            onChange={(e) => setMetaJson(e.currentTarget.value)}
          />
          <Button onClick={addEvidence} loading={creatingEvidence}>
            Add Evidence
          </Button>
        </Stack>
      </Card>
    </Stack>
  );
}