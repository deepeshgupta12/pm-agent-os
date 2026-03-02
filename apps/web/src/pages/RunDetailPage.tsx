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
  Checkbox,
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
  RetrieveResponse,
  RetrieveItem,
  RagBatch,
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

function fmtScore(v: any): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "-";
  return n.toFixed(3);
}

function fmtBatchLabel(b: RagBatch): string {
  const kind = b.batch_kind || "unknown";
  const q = (b.retrieval as any)?.query ? ` · q=${String((b.retrieval as any).query)}` : "";
  const ts = b.created_at ? ` · ${new Date(b.created_at).toLocaleString()}` : "";
  return `${kind}${q} · ${b.evidence_count} ev${ts}`;
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

  // NEW (V2.3): batch selector state
  const [ragBatchId, setRagBatchId] = useState<string | null>(null);

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

  // Auto evidence (existing endpoint)
  const [autoQuery, setAutoQuery] = useState("");
  const [autoK, setAutoK] = useState<number>(6);
  const [autoAlpha, setAutoAlpha] = useState<number>(0.65);
  const [autoLoading, setAutoLoading] = useState(false);

  // Existing regenerate (uses evidence)
  const [regenLoading, setRegenLoading] = useState(false);

  // Logs (create)
  const [logLevel, setLogLevel] = useState<string | null>("info");
  const [logMessage, setLogMessage] = useState<string>("Ran quick check");
  const [logMetaJson, setLogMetaJson] = useState<string>("{}");
  const [creatingLog, setCreatingLog] = useState(false);

  // Logs filter
  const [logFilter, setLogFilter] = useState<string | null>("all");

  // -------------------------
  // V2.2 Retrieval Panel state
  // -------------------------
  const [rpOpen, setRpOpen] = useState(true);
  const [rpQuery, setRpQuery] = useState("");
  const [rpK, setRpK] = useState<number>(5);
  const [rpAlpha, setRpAlpha] = useState<number>(0.0);
  const [rpSourceTypes, setRpSourceTypes] = useState<string>("docs");
  const [rpPreset, setRpPreset] = useState<string | null>("30d");
  const [rpStartDate, setRpStartDate] = useState<string>("");
  const [rpEndDate, setRpEndDate] = useState<string>("");

  const [rpMinScore, setRpMinScore] = useState<number>(0.15);
  const [rpOverfetchK, setRpOverfetchK] = useState<number>(3);
  const [rpRerank, setRpRerank] = useState<boolean>(false);

  const [previewLoading, setPreviewLoading] = useState(false);
  const [preview, setPreview] = useState<RetrieveResponse | null>(null);

  const [regenWithRetrievalLoading, setRegenWithRetrievalLoading] = useState(false);

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

  function normalizeSourceTypes(s: string): string[] {
    return (s || "")
      .split(",")
      .map((x) => x.trim())
      .filter((x) => !!x);
  }

  function buildTimeframeForRunsPayload(): any {
    if (rpPreset === "custom") {
      return {
        preset: "custom",
        ...(rpStartDate ? { start_date: rpStartDate } : {}),
        ...(rpEndDate ? { end_date: rpEndDate } : {}),
      };
    }
    if (rpPreset && ["7d", "30d", "90d"].includes(rpPreset)) {
      return { preset: rpPreset };
    }
    return {};
  }

  function buildRetrieveQueryParams(workspaceId: string): string {
    const q = (rpQuery || "").trim();
    const params = new URLSearchParams();
    params.set("q", q);
    params.set("k", String(rpK));
    params.set("alpha", String(rpAlpha));

    const st = normalizeSourceTypes(rpSourceTypes);
    if (st.length > 0) params.set("source_types", st.join(","));

    if (rpPreset && rpPreset !== "custom" && rpPreset !== "none") {
      params.set("timeframe_preset", rpPreset);
    } else if (rpPreset === "custom") {
      if (rpStartDate) params.set("start_date", rpStartDate);
      if (rpEndDate) params.set("end_date", rpEndDate);
    }

    params.set("min_score", String(rpMinScore));
    params.set("overfetch_k", String(rpOverfetchK));
    params.set("rerank", String(rpRerank));

    return `/workspaces/${workspaceId}/retrieve?${params.toString()}`;
  }

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

  async function loadRagDebug(batchId?: string | null) {
    setRagLoading(true);
    setErr(null);

    const qs = batchId ? `?batch_id=${encodeURIComponent(batchId)}` : "";
    const res = await apiFetch<RagDebugResponse>(`/runs/${rid}/rag-debug${qs}`, { method: "GET" });
    setRagLoading(false);

    if (!res.ok) {
      setErr(`RAG debug failed: ${res.status} ${res.error}`);
      setRagDebug(null);
      return;
    }

    const data = res.data;
    setRagDebug(data);

    // If batch not selected yet, pick:
    // 1) run._retrieval.batch_id if present AND exists in batches
    // 2) newest batch in batches
    // 3) null (shows unscoped)
    if (!ragBatchId) {
      const batches = data.batches || [];
      const preferred = (retrievalCfg as any)?.batch_id ? String((retrievalCfg as any).batch_id) : null;

      const hasPreferred = preferred && batches.some((b) => String(b.batch_id) === preferred);
      if (hasPreferred) {
        setRagBatchId(preferred);
        // Also immediately scope-fetch to match selection
        if (String(batchId || "") !== preferred) {
          void loadRagDebug(preferred);
          return;
        }
      } else if (batches.length > 0) {
        const first = String(batches[0].batch_id);
        setRagBatchId(first);
        if (String(batchId || "") !== first) {
          void loadRagDebug(first);
          return;
        }
      }
    }
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
    if (ragOpen) await loadRagDebug(ragBatchId);
  }

  async function previewRetrieve() {
    if (!run) {
      setErr("Run not loaded yet.");
      return;
    }
    if (!rpQuery.trim()) {
      setErr("Enter a query for retrieval preview.");
      return;
    }

    setPreviewLoading(true);
    setErr(null);
    setPreview(null);

    const path = buildRetrieveQueryParams(run.workspace_id);
    const res = await apiFetch<RetrieveResponse>(path, { method: "GET" });
    setPreviewLoading(false);

    if (!res.ok) {
      setErr(`Retrieve preview failed: ${res.status} ${res.error}`);
      return;
    }
    setPreview(res.data);
  }

  async function regenerateWithRetrieval() {
    if (!run) {
      setErr("Run not loaded yet.");
      return;
    }
    if (!rpQuery.trim()) {
      setErr("Enter a query for regenerate-with-retrieval.");
      return;
    }

    setRegenWithRetrievalLoading(true);
    setErr(null);

    const body = {
      retrieval: {
        enabled: true,
        query: rpQuery.trim(),
        k: Number(rpK) || 5,
        alpha: Number(rpAlpha) || 0.0,
        source_types: normalizeSourceTypes(rpSourceTypes),
        timeframe: buildTimeframeForRunsPayload(),
        min_score: Number(rpMinScore) || 0.15,
        overfetch_k: Number(rpOverfetchK) || 3,
        rerank: Boolean(rpRerank),
      },
    };

    const res = await apiFetch<Run>(`/runs/${rid}/regenerate-with-retrieval`, {
      method: "POST",
      body: JSON.stringify(body),
    });

    setRegenWithRetrievalLoading(false);

    if (!res.ok) {
      setErr(`Regenerate-with-retrieval failed: ${res.status} ${res.error}`);
      return;
    }

    await loadAll();

    // After regen, refresh rag batches (unscoped), then auto-select latest
    if (ragOpen) {
      setRagBatchId(null);
      await loadRagDebug(null);
    }
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
    if (ragOpen) await loadRagDebug(ragBatchId);
  }

  useEffect(() => {
    if (!rid) return;
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rid]);

  useEffect(() => {
    if (!rid) return;
    if (!ragOpen) return;
    void loadRagDebug(ragBatchId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ragOpen, rid]);

  // helpful: prefill panel from run._retrieval once run loads
  useEffect(() => {
    const cfg: any = retrievalCfg;
    if (!cfg) return;

    if (typeof cfg.query === "string" && cfg.query.trim() && !rpQuery.trim()) setRpQuery(cfg.query);
    if (typeof cfg.k === "number") setRpK(cfg.k);
    if (typeof cfg.alpha === "number") setRpAlpha(cfg.alpha);

    if (Array.isArray(cfg.source_types) && cfg.source_types.length > 0) {
      setRpSourceTypes(cfg.source_types.join(", "));
    }

    const tf = cfg.timeframe;
    if (tf && typeof tf === "object") {
      if (tf.preset === "custom") {
        setRpPreset("custom");
        if (tf.start_date) setRpStartDate(String(tf.start_date));
        if (tf.end_date) setRpEndDate(String(tf.end_date));
      } else if (tf.preset && ["7d", "30d", "90d"].includes(String(tf.preset))) {
        setRpPreset(String(tf.preset));
      }
    }

    if (typeof cfg.min_score === "number") setRpMinScore(cfg.min_score);
    if (typeof cfg.overfetch_k === "number") setRpOverfetchK(cfg.overfetch_k);
    if (typeof cfg.rerank === "boolean") setRpRerank(cfg.rerank);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.id]);

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
                {retrievalCfg ? (
                  <Badge variant="light">retrieval enabled</Badge>
                ) : (
                  <Badge variant="light">no retrieval</Badge>
                )}
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
                  <Text fw={600}>Last retrieval config (run._retrieval)</Text>
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
                    source_types:{" "}
                    {Array.isArray(retrievalCfg.source_types)
                      ? retrievalCfg.source_types.join(", ")
                      : "(none)"}{" "}
                    · timeframe: {retrievalCfg.timeframe ? JSON.stringify(retrievalCfg.timeframe) : "(none)"}
                  </Text>
                  <Text size="sm" c="dimmed">
                    knobs: min_score={String(retrievalCfg.min_score ?? "")}, overfetch_k=
                    {String(retrievalCfg.overfetch_k ?? "")}, rerank={String(retrievalCfg.rerank ?? "")}
                  </Text>
                  {retrievalCfg.batch_id ? (
                    <Text size="sm" c="dimmed">
                      batch_id: <Code>{String(retrievalCfg.batch_id)}</Code>
                    </Text>
                  ) : null}
                </Stack>
              </Card>
            ) : null}

            {/* Existing regenerate */}
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

      {/* V2.2 Retrieval panel */}
      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={700}>Retrieval Panel</Text>
            <Button variant="light" onClick={() => setRpOpen((x) => !x)}>
              {rpOpen ? "Hide" : "Show"}
            </Button>
          </Group>

          <Collapse in={rpOpen}>
            <Stack gap="sm">
              <Text size="sm" c="dimmed">
                Use this to preview retrieval results, then regenerate a new artifact version using fresh retrieval evidence.
              </Text>

              <TextInput
                label="Query"
                value={rpQuery}
                onChange={(e) => setRpQuery(e.currentTarget.value)}
                placeholder='e.g., "save preferences"'
              />

              <Group grow>
                <NumberInput
                  label="k"
                  value={rpK}
                  min={1}
                  max={50}
                  onChange={(v) => setRpK(Number(v) || 5)}
                />
                <NumberInput
                  label="alpha"
                  value={rpAlpha}
                  min={0}
                  max={1}
                  step={0.05}
                  onChange={(v) => setRpAlpha(Number(v) || 0)}
                />
                <TextInput
                  label="source_types (comma-separated)"
                  value={rpSourceTypes}
                  onChange={(e) => setRpSourceTypes(e.currentTarget.value)}
                  placeholder="docs, github"
                />
              </Group>

              <Group grow>
                <Select
                  label="timeframe preset"
                  data={[
                    { value: "7d", label: "7d" },
                    { value: "30d", label: "30d" },
                    { value: "90d", label: "90d" },
                    { value: "custom", label: "custom" },
                    { value: "none", label: "none" },
                  ]}
                  value={rpPreset}
                  onChange={(v) => setRpPreset(v)}
                />
                <TextInput
                  label="start_date (YYYY-MM-DD)"
                  value={rpStartDate}
                  onChange={(e) => setRpStartDate(e.currentTarget.value)}
                  disabled={rpPreset !== "custom"}
                />
                <TextInput
                  label="end_date (YYYY-MM-DD)"
                  value={rpEndDate}
                  onChange={(e) => setRpEndDate(e.currentTarget.value)}
                  disabled={rpPreset !== "custom"}
                />
              </Group>

              <Group grow>
                <NumberInput
                  label="min_score"
                  value={rpMinScore}
                  min={0}
                  max={1}
                  step={0.05}
                  onChange={(v) => setRpMinScore(Number(v) || 0.15)}
                />
                <NumberInput
                  label="overfetch_k"
                  value={rpOverfetchK}
                  min={1}
                  max={10}
                  step={1}
                  onChange={(v) => setRpOverfetchK(Number(v) || 3)}
                />
                <div style={{ paddingTop: 26 }}>
                  <Checkbox
                    label="rerank"
                    checked={rpRerank}
                    onChange={(e) => setRpRerank(e.currentTarget.checked)}
                  />
                </div>
              </Group>

              <Group>
                <Button onClick={previewRetrieve} loading={previewLoading} variant="default" disabled={!run}>
                  Retrieve Preview
                </Button>
                <Button
                  onClick={regenerateWithRetrieval}
                  loading={regenWithRetrievalLoading}
                  disabled={!run}
                >
                  Regenerate with Retrieval
                </Button>
              </Group>

              {preview ? (
                <Card withBorder>
                  <Group justify="space-between">
                    <Text fw={600}>Preview results</Text>
                    <Badge variant="light">{preview.items?.length ?? 0}</Badge>
                  </Group>
                  <Text size="sm" c="dimmed">
                    q=<Code>{preview.q}</Code> · k=<Code>{String(preview.k)}</Code> · alpha=<Code>{String(preview.alpha)}</Code> · min_score=<Code>{String(preview.min_score)}</Code> · overfetch_k=<Code>{String(preview.overfetch_k)}</Code> · rerank=<Code>{String(preview.rerank)}</Code>
                  </Text>
                  <Divider my="sm" />

                  {preview.items.length === 0 ? (
                    <Text c="dimmed">No results (after min_score filter).</Text>
                  ) : (
                    <Stack gap="xs">
                      {preview.items.map((it: RetrieveItem) => (
                        <Card key={it.chunk_id} withBorder>
                          <Stack gap={6}>
                            <Group justify="space-between" align="flex-start">
                              <Stack gap={2}>
                                <Text fw={700}>{it.document_title}</Text>
                                <Text size="xs" c="dimmed">
                                  doc={it.document_id} · chunk={it.chunk_id} · idx={it.chunk_index}
                                </Text>
                              </Stack>
                              <Group gap="xs">
                                <Badge variant="light">hyb {fmtScore(it.score_hybrid)}</Badge>
                                {it.score_final != null ? (
                                  <Badge color="grape" variant="light">
                                    final {fmtScore(it.score_final)}
                                  </Badge>
                                ) : null}
                              </Group>
                            </Group>

                            <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                              {it.snippet}
                            </Text>

                            <Text size="xs" c="dimmed">
                              fts={fmtScore(it.score_fts)} · vec={fmtScore(it.score_vec)}
                              {it.score_rerank_bonus != null ? ` · bonus=${fmtScore(it.score_rerank_bonus)}` : ""}
                            </Text>
                          </Stack>
                        </Card>
                      ))}
                    </Stack>
                  )}
                </Card>
              ) : null}
            </Stack>
          </Collapse>
        </Stack>
      </Card>

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
              <Button
                variant="default"
                onClick={() => loadRagDebug(ragBatchId)}
                loading={ragLoading}
                disabled={!ragOpen}
              >
                Refresh
              </Button>
            </Group>
          </Group>

          <Collapse in={ragOpen}>
            <Stack gap="sm">
              {/* NEW: Batch selector */}
              <Card withBorder>
                <Stack gap="xs">
                  <Text fw={600}>Batch scope</Text>
                  <Text size="sm" c="dimmed">
                    Select a batch to view only the evidence/logs created in that retrieval execution.
                  </Text>

                  <Group grow>
                    <Select
                      label="Batch"
                      data={(ragDebug?.batches || []).map((b) => ({
                        value: String(b.batch_id),
                        label: fmtBatchLabel(b),
                      }))}
                      value={ragBatchId}
                      onChange={(v) => {
                        const next = v || null;
                        setRagBatchId(next);
                        if (next) void loadRagDebug(next);
                      }}
                      placeholder={(ragDebug?.batches || []).length === 0 ? "No batches yet" : "Select batch"}
                      searchable
                      nothingFoundMessage="No batches"
                      disabled={(ragDebug?.batches || []).length === 0}
                    />
                    <Button
                      mt={22}
                      variant="default"
                      onClick={() => {
                        setRagBatchId(null);
                        void loadRagDebug(null);
                      }}
                    >
                      Show all
                    </Button>
                  </Group>

                  {ragBatchId ? (
                    <Text size="sm" c="dimmed">
                      scoped batch_id: <Code>{ragBatchId}</Code>
                    </Text>
                  ) : (
                    <Text size="sm" c="dimmed">
                      showing all evidence (unscoped)
                    </Text>
                  )}
                </Stack>
              </Card>

              <Card withBorder>
                <Text fw={600} mb={6}>
                  retrieval_config (best available for current scope)
                </Text>
                <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{safeJson(ragDebug?.retrieval_config ?? retrievalCfg)}</pre>
              </Card>

              <Card withBorder>
                <Text fw={600} mb={6}>
                  retrieval_log (scoped latest retrieval RunLog meta)
                </Text>
                <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                  {safeJson(ragDebug?.retrieval_log ?? null)}
                </pre>
              </Card>

              <Card withBorder>
                <Group justify="space-between">
                  <Text fw={600}>Evidence (scoped)</Text>
                  <Badge variant="light">{ragDebug?.evidence?.length ?? 0}</Badge>
                </Group>
                <Divider my="sm" />
                {!ragDebug || !ragDebug.evidence || ragDebug.evidence.length === 0 ? (
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
                            {e.created_at ? ` · ${new Date(e.created_at).toLocaleString()}` : ""}
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