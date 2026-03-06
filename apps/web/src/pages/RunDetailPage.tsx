// apps/web/src/pages/RunDetailPage.tsx
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, Link, useLocation } from "react-router-dom";
import {
  Badge,
  Button,
  Group,
  Select,
  Stack,
  Text,
  TextInput,
  Textarea,
  NumberInput,
  Divider,
  Collapse,
  Code,
  Checkbox,
  Tooltip,
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
  AttachPreviewEvidenceIn,
  WorkspaceRole,
} from "../types";

import GlassPage from "../components/Glass/GlassPage";
import GlassCard from "../components/Glass/GlassCard";
import GlassSection from "../components/Glass/GlassSection";
import GlassStat from "../components/Glass/GlassStat";

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

function roleBadgeColor(role: string | null): string {
  if (role === "admin") return "grape";
  if (role === "member") return "blue";
  if (role === "viewer") return "gray";
  return "dark";
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

function MutateTooltip({ canMutate, children }: { canMutate: boolean; children: React.ReactNode }) {
  if (canMutate) return <>{children}</>;
  return (
    <Tooltip label="Viewer role: edits are disabled" withArrow>
      <span style={{ display: "inline-block" }}>{children}</span>
    </Tooltip>
  );
}

function HelpTip({ label }: { label: string }) {
  return (
    <Tooltip label={label} withArrow>
      <Badge variant="light">?</Badge>
    </Tooltip>
  );
}

export default function RunDetailPage() {
  const { runId } = useParams();
  const rid = runId || "";
  const loc = useLocation();

  const [run, setRun] = useState<Run | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [timeline, setTimeline] = useState<RunTimelineEvent[]>([]);
  const [logs, setLogs] = useState<RunLog[]>([]);
  const [err, setErr] = useState<string | null>(null);

  // workspace role
  const [wsRole, setWsRole] = useState<WorkspaceRole | null>(null);
  const [wsRoleLoading, setWsRoleLoading] = useState(false);

  // RAG debug panel
  const [ragOpen, setRagOpen] = useState(false);
  const [ragLoading, setRagLoading] = useState(false);
  const [ragDebug, setRagDebug] = useState<RagDebugResponse | null>(null);

  // batch selector
  const [ragBatchId, setRagBatchId] = useState<string | null>(null);

  // deep-link: prevent immediate double-fetch after programmatic open
  const skipNextRagOpenFetchRef = useRef(false);

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

  // Retrieval Panel state
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

  // Attach preview as Evidence
  const [previewSelected, setPreviewSelected] = useState<Record<string, boolean>>({});
  const [attachLoading, setAttachLoading] = useState(false);

  const artifactTypeOptions = useMemo(() => ARTIFACT_TYPES.map((t) => ({ value: t, label: t })), []);

  const latestArtifact = useMemo(() => {
    if (artifacts.length === 0) return null;
    return artifacts[0];
  }, [artifacts]);

  const retrievalCfg = useMemo(() => {
    const ip: any = run?.input_payload ?? {};
    return (ip?._retrieval as any) || null;
  }, [run]);

  const filteredLogs = useMemo(() => {
    if (logFilter === "all") return logs;
    return logs.filter((l) => l.level === logFilter);
  }, [logs, logFilter]);

  const roleStr = wsRole?.role ?? null;
  const canMutate = roleStr === "admin" || roleStr === "member";

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
    if (rpPreset && ["7d", "30d", "90d"].includes(rpPreset)) return { preset: rpPreset };
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

  function selectedPreviewItems(): RetrieveItem[] {
    if (!preview?.items?.length) return [];
    return preview.items.filter((it) => !!previewSelected[it.chunk_id]);
  }

  function toggleAllPreview(on: boolean) {
    if (!preview?.items?.length) return;
    const next: Record<string, boolean> = {};
    for (const it of preview.items) next[it.chunk_id] = on;
    setPreviewSelected(next);
  }

  async function loadWorkspaceRole(workspaceId: string) {
    setWsRoleLoading(true);
    const res = await apiFetch<WorkspaceRole>(`/workspaces/${workspaceId}/my-role`, { method: "GET" });
    setWsRoleLoading(false);

    if (!res.ok) {
      setWsRole(null);
      return;
    }
    setWsRole(res.data);
  }

  async function loadAll() {
    setErr(null);

    const runRes = await apiFetch<Run>(`/runs/${rid}`, { method: "GET" });
    if (!runRes.ok) {
      setErr(`Run load failed: ${runRes.status} ${runRes.error}`);
      return;
    }
    setRun(runRes.data);

    if (runRes.data?.workspace_id) {
      void loadWorkspaceRole(runRes.data.workspace_id);
    }

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

    if (!ragBatchId) {
      const batches = data.batches || [];
      const preferred = (retrievalCfg as any)?.batch_id ? String((retrievalCfg as any).batch_id) : null;

      const hasPreferred = preferred && batches.some((b) => String(b.batch_id) === preferred);
      if (hasPreferred) {
        setRagBatchId(preferred);
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

    const nextSel: Record<string, boolean> = {};
    for (const it of res.data.items || []) nextSel[it.chunk_id] = false;
    setPreviewSelected(nextSel);
  }

  async function regenerateWithRetrieval() {
    if (!canMutate) {
      setErr("Viewer role cannot regenerate.");
      return;
    }
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

    if (ragOpen) {
      setRagBatchId(null);
      await loadRagDebug(null);
    }
  }

  async function attachSelectedPreviewAsEvidence() {
    if (!canMutate) {
      setErr("Viewer role cannot attach evidence.");
      return;
    }
    if (!run) {
      setErr("Run not loaded yet.");
      return;
    }
    if (!preview || !preview.items || preview.items.length === 0) {
      setErr("No preview results to attach.");
      return;
    }

    const picked = selectedPreviewItems();
    if (picked.length === 0) {
      setErr("Select at least one preview result to attach.");
      return;
    }

    setAttachLoading(true);
    setErr(null);

    const body: AttachPreviewEvidenceIn = {
      retrieval: {
        query: rpQuery.trim(),
        k: Number(rpK) || 5,
        alpha: Number(rpAlpha) || 0.0,
        source_types: normalizeSourceTypes(rpSourceTypes),
        timeframe: buildTimeframeForRunsPayload(),
        min_score: Number(rpMinScore) || 0.15,
        overfetch_k: Number(rpOverfetchK) || 3,
        rerank: Boolean(rpRerank),
      },
      items: picked.map((it) => ({
        chunk_id: it.chunk_id,
        document_id: it.document_id,
        source_id: it.source_id,
        document_title: it.document_title,
        chunk_index: it.chunk_index,
        snippet: it.snippet,
        score_fts: it.score_fts,
        score_vec: it.score_vec,
        score_hybrid: it.score_hybrid,
        score_rerank_bonus: it.score_rerank_bonus ?? null,
        score_final: it.score_final ?? null,
      })),
    };

    const res = await apiFetch<Evidence[]>(`/runs/${rid}/evidence/attach-preview`, {
      method: "POST",
      body: JSON.stringify(body),
    });

    setAttachLoading(false);

    if (!res.ok) {
      setErr(`Attach preview evidence failed: ${res.status} ${res.error}`);
      return;
    }

    await loadAll();

    if (ragOpen) {
      setRagBatchId(null);
      await loadRagDebug(null);
    }
  }

  function exportPdf(artifactId: string) {
    window.open(`${API_BASE}/artifacts/${artifactId}/export/pdf`, "_blank");
  }

  function exportDocx(artifactId: string) {
    window.open(`${API_BASE}/artifacts/${artifactId}/export/docx`, "_blank");
  }

  async function createArtifact() {
    if (!canMutate) {
      setErr("Viewer role cannot create artifacts.");
      return;
    }
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
    if (!canMutate) {
      setErr("Viewer role cannot add evidence.");
      return;
    }
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
    if (!canMutate) {
      setErr("Viewer role cannot auto-add evidence.");
      return;
    }
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

  async function regenerate() {
    if (!canMutate) {
      setErr("Viewer role cannot regenerate.");
      return;
    }

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
    if (!canMutate) {
      setErr("Viewer role cannot add logs.");
      return;
    }
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

  // Effects
  useEffect(() => {
    if (!rid) return;
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rid]);

  // Deep link: /runs/{id}?ragOpen=1&batch_id=...
  useEffect(() => {
    if (!rid) return;

    const params = new URLSearchParams(loc.search);
    const open = (params.get("ragOpen") || "").toLowerCase();
    const batch = params.get("batch_id");
    const shouldOpen = open === "1" || open === "true";
    if (!shouldOpen) return;

    const bid = batch ? String(batch) : null;

    skipNextRagOpenFetchRef.current = true;

    setRagOpen(true);
    setRagBatchId(bid);

    void loadRagDebug(bid);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rid, loc.search]);

  useEffect(() => {
    if (!rid) return;
    if (!ragOpen) return;

    if (skipNextRagOpenFetchRef.current) {
      skipNextRagOpenFetchRef.current = false;
      return;
    }

    void loadRagDebug(ragBatchId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ragOpen, rid, ragBatchId]);

  // Prefill retrieval panel from run._retrieval once run loads
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

  const headerRight = (
    <Group>
      <Button component={Link} to="/workspaces" variant="light" size="sm">
        Workspaces
      </Button>
      <Button variant="light" onClick={loadAll} size="sm">
        Refresh
      </Button>
    </Group>
  );

  return (
    <GlassPage title="Run" subtitle="RAG console for artifacts, evidence, retrieval, and debugging." right={headerRight}>
      <Stack gap="md">
        {err ? (
          <GlassCard>
            <Text c="red">{err}</Text>
          </GlassCard>
        ) : null}

        <GlassSection
          title="Run overview"
          description={run ? run.id : rid}
          right={
            <Group gap="sm" wrap="wrap">
              <Badge variant="light" color={roleBadgeColor(roleStr)} title="Your role in this workspace">
                Role: {wsRoleLoading ? "…" : roleStr ?? "unknown"}
              </Badge>
              {run?.status ? <GlassStat label="Status" value={run.status} /> : null}
              {run?.agent_id ? <GlassStat label="Agent" value={run.agent_id} /> : null}
              <GlassStat label="Evidence" value={evidence.length} />
            </Group>
          }
        >
          {run ? (
            <Stack gap="sm">
              {run.output_summary ? <Text c="dimmed">{run.output_summary}</Text> : null}

              {retrievalCfg ? (
                <GlassCard p="md">
                  <Stack gap={6}>
                    <Group justify="space-between">
                      <Text fw={700}>Last retrieval config</Text>
                      <Badge variant="light">run._retrieval</Badge>
                    </Group>
                    <Text size="sm" c="dimmed">
                      query: <Code>{String(retrievalCfg.query ?? "")}</Code> · k: <Code>{String(retrievalCfg.k ?? "")}</Code> · alpha:{" "}
                      <Code>{String(retrievalCfg.alpha ?? "")}</Code>
                    </Text>
                    <Text size="sm" c="dimmed">
                      min_score={String(retrievalCfg.min_score ?? "")}, overfetch_k={String(retrievalCfg.overfetch_k ?? "")}, rerank={String(
                        retrievalCfg.rerank ?? ""
                      )}
                    </Text>
                    {retrievalCfg.batch_id ? (
                      <Text size="sm" c="dimmed">
                        batch_id: <Code>{String(retrievalCfg.batch_id)}</Code>
                      </Text>
                    ) : null}
                  </Stack>
                </GlassCard>
              ) : (
                <Text size="sm" c="dimmed">
                  Retrieval: not used on the last execution.
                </Text>
              )}

              <Group gap="sm" align="center">
                <MutateTooltip canMutate={canMutate}>
                  <Button onClick={regenerate} loading={regenLoading} disabled={!canMutate || evidence.length === 0} size="sm">
                    Regenerate from evidence
                  </Button>
                </MutateTooltip>
                <Text size="sm" c="dimmed">
                  {evidence.length === 0
                    ? "Add evidence to enable regeneration."
                    : canMutate
                      ? `Uses ${evidence.length} evidence item(s) to create a new artifact version.`
                      : "Viewer: regeneration disabled."}
                </Text>
              </Group>

              <GlassCard p="md">
                <Text fw={700} mb={6}>
                  Input payload
                </Text>
                <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(run.input_payload, null, 2)}</pre>
              </GlassCard>
            </Stack>
          ) : (
            <Text c="dimmed">Loading run…</Text>
          )}
        </GlassSection>

        <GlassSection
          title="Retrieval"
          description="Preview results, attach as evidence, and regenerate with retrieval."
          right={
            <Group gap="sm">
              <Button variant="light" onClick={() => setRpOpen((x) => !x)} size="sm">
                {rpOpen ? "Hide" : "Show"}
              </Button>
            </Group>
          }
        >
          <Collapse in={rpOpen}>
            <Stack gap="sm">
              <Text size="sm" c="dimmed">
                Viewer can preview. Member/Admin can attach evidence and regenerate.
              </Text>

              <TextInput
                label="Query"
                value={rpQuery}
                onChange={(e) => setRpQuery(e.currentTarget.value)}
                placeholder='e.g., "save preferences"'
              />

              <Group grow>
                <Group gap="xs" align="end">
                  <NumberInput label="k" value={rpK} min={1} max={50} onChange={(v) => setRpK(Number(v) || 5)} />
                  <HelpTip label="How many chunks to fetch before filtering/rerank." />
                </Group>
                <Group gap="xs" align="end">
                  <NumberInput label="alpha" value={rpAlpha} min={0} max={1} step={0.05} onChange={(v) => setRpAlpha(Number(v) || 0)} />
                  <HelpTip label="Hybrid weighting: 0=keyword-only, 1=vector-heavy (implementation-dependent)." />
                </Group>
                <TextInput
                  label="source_types (comma-separated)"
                  value={rpSourceTypes}
                  onChange={(e) => setRpSourceTypes(e.currentTarget.value)}
                  placeholder="docs, github"
                />
              </Group>

              <Group grow>
                <Select
                  label="Timeframe"
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
                <TextInput label="Start date (YYYY-MM-DD)" value={rpStartDate} onChange={(e) => setRpStartDate(e.currentTarget.value)} disabled={rpPreset !== "custom"} />
                <TextInput label="End date (YYYY-MM-DD)" value={rpEndDate} onChange={(e) => setRpEndDate(e.currentTarget.value)} disabled={rpPreset !== "custom"} />
              </Group>

              <Group grow>
                <Group gap="xs" align="end">
                  <NumberInput
                    label="min_score"
                    value={rpMinScore}
                    min={0}
                    max={1}
                    step={0.05}
                    onChange={(v) => setRpMinScore(Number(v) || 0.15)}
                  />
                  <HelpTip label="Filters weak matches. Raise to improve precision; lower to improve recall." />
                </Group>

                <Group gap="xs" align="end">
                  <NumberInput
                    label="overfetch_k"
                    value={rpOverfetchK}
                    min={1}
                    max={10}
                    step={1}
                    onChange={(v) => setRpOverfetchK(Number(v) || 3)}
                  />
                  <HelpTip label="Fetch extra items for better final selection (especially when reranking)." />
                </Group>

                <div style={{ paddingTop: 26 }}>
                  <Group gap="xs">
                    <Checkbox label="rerank" checked={rpRerank} onChange={(e) => setRpRerank(e.currentTarget.checked)} />
                    <HelpTip label="If enabled, applies a reranking step (when available) to improve ordering." />
                  </Group>
                </div>
              </Group>

              <Group>
                <Button onClick={previewRetrieve} loading={previewLoading} variant="default" disabled={!run} size="sm">
                  Retrieve preview
                </Button>

                <MutateTooltip canMutate={canMutate}>
                  <Button onClick={regenerateWithRetrieval} loading={regenWithRetrievalLoading} disabled={!run || !canMutate} size="sm">
                    Regenerate with retrieval
                  </Button>
                </MutateTooltip>
              </Group>

              {preview ? (
                <GlassCard p="md">
                  <Stack gap="sm">
                    <Group justify="space-between">
                      <Text fw={700}>Preview results</Text>
                      <GlassStat label="Items" value={preview.items?.length ?? 0} />
                    </Group>

                    <Text size="sm" c="dimmed">
                      q=<Code>{preview.q}</Code> · k=<Code>{String(preview.k)}</Code> · alpha=<Code>{String(preview.alpha)}</Code> · min_score=
                      <Code>{String(preview.min_score)}</Code> · overfetch_k=<Code>{String(preview.overfetch_k)}</Code> · rerank=<Code>{String(preview.rerank)}</Code>
                    </Text>

                    <Group justify="space-between">
                      <Group gap="xs">
                        <Button size="xs" variant="light" onClick={() => toggleAllPreview(true)} disabled={!preview.items?.length}>
                          Select all
                        </Button>
                        <Button size="xs" variant="light" onClick={() => toggleAllPreview(false)} disabled={!preview.items?.length}>
                          Clear
                        </Button>
                      </Group>

                      <Group gap="xs">
                        <Badge variant="light">
                          selected {selectedPreviewItems().length}/{preview.items.length}
                        </Badge>

                        <MutateTooltip canMutate={canMutate}>
                          <Button
                            size="xs"
                            onClick={attachSelectedPreviewAsEvidence}
                            loading={attachLoading}
                            disabled={!canMutate || selectedPreviewItems().length === 0}
                          >
                            Attach selected as evidence
                          </Button>
                        </MutateTooltip>
                      </Group>
                    </Group>

                    <Divider />

                    {preview.items.length === 0 ? (
                      <Text c="dimmed">No results (after min_score filter).</Text>
                    ) : (
                      <Stack gap="xs">
                        {preview.items.map((it: RetrieveItem) => (
                          <GlassCard key={it.chunk_id} p="md">
                            <Stack gap={6}>
                              <Group justify="space-between" align="flex-start">
                                <Stack gap={2}>
                                  <Text fw={700}>{it.document_title}</Text>
                                  <Text size="xs" c="dimmed">
                                    doc={it.document_id} · chunk={it.chunk_id} · idx={it.chunk_index}
                                  </Text>
                                </Stack>

                                <Group gap="xs">
                                  <Checkbox
                                    checked={!!previewSelected[it.chunk_id]}
                                    onChange={(e) =>
                                      setPreviewSelected((prev) => ({
                                        ...prev,
                                        [it.chunk_id]: e.currentTarget.checked,
                                      }))
                                    }
                                  />
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
                          </GlassCard>
                        ))}
                      </Stack>
                    )}
                  </Stack>
                </GlassCard>
              ) : (
                <Text size="sm" c="dimmed">
                  Run a preview to validate retrieval quality and filters.
                </Text>
              )}
            </Stack>
          </Collapse>
        </GlassSection>

        <GlassSection
          title="Latest artifact"
          description="Newest artifact generated by this run."
          right={
            latestArtifact ? (
              <Group gap="xs">
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
            )
          }
        >
          {!latestArtifact ? (
            <Text c="dimmed">No artifacts yet.</Text>
          ) : (
            <GlassCard p="md" style={{ maxHeight: 420, overflow: "auto" }}>
              <Stack gap={6}>
                <Text size="sm" c="dimmed">
                  {latestArtifact.type} · v{latestArtifact.version} · {latestArtifact.status} · key={latestArtifact.logical_key}
                </Text>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{latestArtifact.content_md || ""}</ReactMarkdown>
              </Stack>
            </GlassCard>
          )}
        </GlassSection>

        <GlassSection
          title="RAG debug"
          description="Inspect batches, scoped evidence, and retrieval logs."
          right={
            <Group>
              <Button variant="light" onClick={() => setRagOpen((x) => !x)} size="sm">
                {ragOpen ? "Hide" : "Show"}
              </Button>
              <Button variant="default" onClick={() => loadRagDebug(ragBatchId)} loading={ragLoading} disabled={!ragOpen} size="sm">
                Refresh
              </Button>
            </Group>
          }
        >
          <Collapse in={ragOpen}>
            <Stack gap="sm">
              <GlassCard p="md">
                <Stack gap="xs">
                  <Group justify="space-between">
                    <Text fw={700}>Batch scope</Text>
                    <Tooltip
                      withArrow
                      label="Scope the debug view to a single retrieval execution. Helpful when multiple runs/regenerations exist."
                    >
                      <Badge variant="light">Advanced</Badge>
                    </Tooltip>
                  </Group>

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
                      size="sm"
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
              </GlassCard>

              <GlassCard p="md">
                <Text fw={700} mb={6}>
                  retrieval_config (best available)
                </Text>
                <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{safeJson(ragDebug?.retrieval_config ?? retrievalCfg)}</pre>
              </GlassCard>

              <GlassCard p="md">
                <Text fw={700} mb={6}>
                  retrieval_log (latest)
                </Text>
                <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{safeJson(ragDebug?.retrieval_log ?? null)}</pre>
              </GlassCard>

              <GlassCard p="md">
                <Group justify="space-between">
                  <Text fw={700}>Evidence (scoped)</Text>
                  <GlassStat label="Count" value={ragDebug?.evidence?.length ?? 0} />
                </Group>
                <Divider my="sm" />
                {!ragDebug || !ragDebug.evidence || ragDebug.evidence.length === 0 ? (
                  <Text c="dimmed">No evidence attached.</Text>
                ) : (
                  <Stack gap="xs">
                    {ragDebug.evidence.map((e) => (
                      <GlassCard key={e.id} p="md">
                        <Stack gap={4}>
                          <Group gap="sm">
                            <Badge variant="light">{e.kind}</Badge>
                            <Text fw={700}>{e.source_name}</Text>
                            {e.source_ref ? <Text size="sm" c="dimmed">{e.source_ref}</Text> : null}
                          </Group>
                          <Text size="sm">{e.excerpt}</Text>
                          <Text size="xs" c="dimmed">
                            {e.id}
                            {e.created_at ? ` · ${new Date(e.created_at).toLocaleString()}` : ""}
                          </Text>
                        </Stack>
                      </GlassCard>
                    ))}
                  </Stack>
                )}
              </GlassCard>
            </Stack>
          </Collapse>
        </GlassSection>

        <GlassSection
          title="Timeline"
          description="Key events for this run."
          right={
            <Button variant="light" onClick={loadAll} size="sm">
              Refresh
            </Button>
          }
        >
          {timeline.length === 0 ? (
            <Text c="dimmed">No timeline events yet.</Text>
          ) : (
            <Stack gap="xs">
              {timeline.map((ev, idx) => (
                <GlassCard key={`${ev.kind}:${ev.ref_id ?? "x"}:${idx}`} p="md">
                  <Group justify="space-between" align="flex-start">
                    <Stack gap={2}>
                      <Group gap="sm">
                        <Badge color={eventBadgeColor(ev.kind)} variant="light">
                          {ev.kind}
                        </Badge>
                        <Text fw={700}>{ev.label}</Text>
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
                </GlassCard>
              ))}
            </Stack>
          )}
        </GlassSection>

        <GlassSection
          title="Logs"
          description="Operator notes and system logs for this run."
          right={
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
              <Button variant="light" onClick={loadAll} size="sm">
                Refresh
              </Button>
            </Group>
          }
        >
          <Stack gap="sm">
            <Divider />

            <Text fw={700}>Add log (member+)</Text>
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
                disabled={!canMutate}
              />
              <TextInput label="Message" value={logMessage} onChange={(e) => setLogMessage(e.currentTarget.value)} disabled={!canMutate} />
            </Group>

            <Textarea label="Meta (JSON)" autosize minRows={2} value={logMetaJson} onChange={(e) => setLogMetaJson(e.currentTarget.value)} disabled={!canMutate} />

            <MutateTooltip canMutate={canMutate}>
              <Button onClick={createLog} loading={creatingLog} disabled={!canMutate} size="sm">
                Add log
              </Button>
            </MutateTooltip>

            <Divider />

            {filteredLogs.length === 0 ? (
              <Text c="dimmed">No logs yet.</Text>
            ) : (
              <Stack gap="xs">
                {filteredLogs.map((l) => (
                  <GlassCard key={l.id} p="md">
                    <Stack gap={4}>
                      <Group gap="sm">
                        <Badge color={logBadgeColor(l.level)} variant="light">
                          {l.level}
                        </Badge>
                        <Text fw={700}>{l.message}</Text>
                      </Group>
                      <Text size="xs" c="dimmed">
                        {new Date(l.created_at).toLocaleString()} · {l.id}
                      </Text>
                      {l.meta && Object.keys(l.meta).length > 0 ? <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{JSON.stringify(l.meta, null, 2)}</pre> : null}
                    </Stack>
                  </GlassCard>
                ))}
              </Stack>
            )}
          </Stack>
        </GlassSection>

        <GlassSection title="Auto-add evidence" description="Attach retrieval evidence directly (member/admin)." right={<Badge variant="light">Advanced</Badge>}>
          <Stack gap="sm">
            <Text size="sm" c="dimmed">
              Viewer can preview retrieval above. Member/Admin can attach evidence here.
            </Text>

            <TextInput
              label="Query"
              value={autoQuery}
              onChange={(e) => setAutoQuery(e.currentTarget.value)}
              placeholder='e.g., "refresh tokens"'
              disabled={!canMutate}
            />

            <Group grow>
              <NumberInput label="Top K" value={autoK} min={1} max={20} onChange={(v) => setAutoK(Number(v) || 6)} disabled={!canMutate} />
              <Group gap="xs" align="end">
                <NumberInput
                  label="Alpha"
                  value={autoAlpha}
                  min={0}
                  max={1}
                  step={0.05}
                  onChange={(v) => setAutoAlpha(Number(v) || 0.65)}
                  disabled={!canMutate}
                />
                <HelpTip label="Hybrid weighting for auto evidence retrieval." />
              </Group>
            </Group>

            <MutateTooltip canMutate={canMutate}>
              <Button onClick={autoAddEvidence} loading={autoLoading} disabled={!canMutate} size="sm">
                Fetch & attach evidence
              </Button>
            </MutateTooltip>
          </Stack>
        </GlassSection>

        <GlassSection title="Create artifact" description="Create a manual artifact version (member+)." right={<Badge variant="light">Manual</Badge>}>
          <Stack gap="sm">
            <Select label="Type" data={artifactTypeOptions} value={atype} onChange={setAtype} disabled={!canMutate} />
            <Group grow>
              <TextInput label="Title" value={title} onChange={(e) => setTitle(e.currentTarget.value)} disabled={!canMutate} />
              <Tooltip withArrow label="Logical key groups versions (e.g., prd, tracking_spec).">
                <div style={{ width: "100%" }}>
                  <TextInput label="Logical key" value={logicalKey} onChange={(e) => setLogicalKey(e.currentTarget.value)} disabled={!canMutate} />
                </div>
              </Tooltip>
            </Group>
            <Textarea label="Content (Markdown)" autosize minRows={6} value={contentMd} onChange={(e) => setContentMd(e.currentTarget.value)} disabled={!canMutate} />

            <MutateTooltip canMutate={canMutate}>
              <Button onClick={createArtifact} loading={creatingArtifact} disabled={!canMutate} size="sm">
                Create
              </Button>
            </MutateTooltip>
          </Stack>
        </GlassSection>

        <GlassSection title="Add evidence" description="Attach evidence snippets/metrics/links to support regeneration (member+)." right={<Badge variant="light">Manual</Badge>}>
          <Stack gap="sm">
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
                disabled={!canMutate}
              />
              <TextInput label="Source name" value={sourceName} onChange={(e) => setSourceName(e.currentTarget.value)} disabled={!canMutate} />
            </Group>

            <TextInput
              label="Source ref (URL/id)"
              value={sourceRef}
              onChange={(e) => setSourceRef(e.currentTarget.value)}
              placeholder="optional"
              disabled={!canMutate}
            />
            <Textarea label="Excerpt" autosize minRows={3} value={excerpt} onChange={(e) => setExcerpt(e.currentTarget.value)} disabled={!canMutate} />
            <Textarea label="Meta (JSON)" autosize minRows={3} value={metaJson} onChange={(e) => setMetaJson(e.currentTarget.value)} disabled={!canMutate} />

            <MutateTooltip canMutate={canMutate}>
              <Button onClick={addEvidence} loading={creatingEvidence} disabled={!canMutate} size="sm">
                Add evidence
              </Button>
            </MutateTooltip>
          </Stack>
        </GlassSection>
      </Stack>
    </GlassPage>
  );
}