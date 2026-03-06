// apps/web/src/pages/AgentBuilderPage.tsx
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Badge,
  Button,
  Code,
  Group,
  Select,
  Stack,
  Text,
  Textarea,
  Divider,
  TextInput,
  NumberInput,
  Checkbox,
  MultiSelect,
  Collapse,
  Tooltip,
} from "@mantine/core";
import { apiFetch } from "../apiClient";
import type {
  AgentBuilderMetaOut,
  AgentBaseOut,
  AgentVersionOut,
  CustomAgentPublishedOut,
  CustomAgentPreviewOut,
  Run,
  WorkspaceRole,
  AgentPublishOut,
  AgentArchiveOut,
  AgentDefinitionJson,
  PromptBlock,
} from "../types";

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

function roleBadgeColor(role: string | null): string {
  if (role === "admin") return "grape";
  if (role === "member") return "blue";
  if (role === "viewer") return "gray";
  return "dark";
}

function isRoleAllowed(myRole: string | null, allowed: string[]): boolean {
  const r = (myRole || "").toLowerCase();
  if (!r) return false;
  const set = new Set((allowed || []).map((x) => String(x || "").toLowerCase()).filter(Boolean));
  return set.has(r);
}

function HelpPill({ label }: { label: string }) {
  return (
    <Tooltip label={label} withArrow>
      <Badge variant="light">?</Badge>
    </Tooltip>
  );
}

type TimeframePreset = "7d" | "30d" | "90d" | "custom";

type DefinitionForm = {
  artifactType: string;

  retrievalEnabled: boolean;
  retrievalQuery: string;
  k: number;
  alpha: number;
  minScore: number;
  overfetchK: number;
  rerank: boolean;

  sourceTypes: string[];

  preset: TimeframePreset;
  startDate: string;
  endDate: string;

  promptBlocks: PromptBlock[];
};

const DEFAULT_PROMPT_BLOCKS: PromptBlock[] = [
  { kind: "instruction", text: "Write a clean PRD. Be specific. Do not invent facts." },
];

function clamp(n: number, min: number, max: number): number {
  if (!Number.isFinite(n)) return min;
  return Math.max(min, Math.min(max, n));
}

function formToDefinitionJson(f: DefinitionForm): AgentDefinitionJson {
  const timeframe: Record<string, unknown> =
    f.preset === "custom"
      ? {
          preset: "custom",
          ...(f.startDate ? { start_date: f.startDate } : {}),
          ...(f.endDate ? { end_date: f.endDate } : {}),
        }
      : { preset: f.preset };

  const out: AgentDefinitionJson = {
    artifact: { type: f.artifactType || "strategy_memo" },
    retrieval: {
      enabled: Boolean(f.retrievalEnabled),
      query: String(f.retrievalQuery || ""),
      k: Number(f.k),
      alpha: Number(f.alpha),
      source_types: Array.isArray(f.sourceTypes) ? f.sourceTypes : [],
      timeframe,
      min_score: Number(f.minScore),
      overfetch_k: Number(f.overfetchK),
      rerank: Boolean(f.rerank),
    },
    prompt_blocks: Array.isArray(f.promptBlocks) ? f.promptBlocks : [],
  };

  return out;
}

function definitionJsonToForm(dj: AgentDefinitionJson, fallbackArtifactTypes: string[]): DefinitionForm {
  const artType =
    String((dj as any)?.artifact?.type || "").trim() || (fallbackArtifactTypes[0] || "strategy_memo");

  const r: any = (dj as any)?.retrieval || {};
  const tf: any = r?.timeframe || {};

  const presetRaw = String(tf?.preset || "30d").toLowerCase();
  const preset: TimeframePreset =
    presetRaw === "7d" || presetRaw === "30d" || presetRaw === "90d" || presetRaw === "custom"
      ? (presetRaw as TimeframePreset)
      : "30d";

  const pb: PromptBlock[] = Array.isArray((dj as any)?.prompt_blocks)
    ? (dj as any).prompt_blocks
        .map((x: any) => ({
          kind: String(x?.kind || "instruction"),
          text: String(x?.text || ""),
        }))
        .filter((x: any) => x.kind.trim() || x.text.trim())
    : [];

  return {
    artifactType: artType,

    retrievalEnabled: Boolean(r?.enabled ?? true),
    retrievalQuery: String(r?.query || ""),
    k: Number(r?.k ?? 6),
    alpha: Number(r?.alpha ?? 0.65),
    minScore: Number(r?.min_score ?? r?.minScore ?? 0.15),
    overfetchK: Number(r?.overfetch_k ?? r?.overfetchK ?? 3),
    rerank: Boolean(r?.rerank ?? false),

    sourceTypes: Array.isArray(r?.source_types)
      ? r.source_types.map((x: any) => String(x).trim()).filter(Boolean)
      : [],

    preset,
    startDate: String(tf?.start_date || ""),
    endDate: String(tf?.end_date || ""),

    promptBlocks: pb.length ? pb : DEFAULT_PROMPT_BLOCKS,
  };
}

export default function AgentBuilderPage() {
  const { workspaceId } = useParams();
  const wid = workspaceId || "";
  const nav = useNavigate();

  const [err, setErr] = useState<string | null>(null);

  // role
  const [myRole, setMyRole] = useState<WorkspaceRole | null>(null);
  const roleStr = (myRole?.role || "").toLowerCase() || null;

  // meta
  const [meta, setMeta] = useState<AgentBuilderMetaOut | null>(null);
  const [metaLoading, setMetaLoading] = useState(false);

  // bases
  const [bases, setBases] = useState<AgentBaseOut[]>([]);
  const [basesLoading, setBasesLoading] = useState(false);
  const [baseId, setBaseId] = useState<string | null>(null);

  // create base
  const [newKey, setNewKey] = useState("demo_prd");
  const [newName, setNewName] = useState("Demo PRD Agent");
  const [newDesc, setNewDesc] = useState("Demo custom agent");
  const [creatingBase, setCreatingBase] = useState(false);

  // edit selected base
  const selectedBase = useMemo(() => bases.find((b) => b.id === baseId) || null, [bases, baseId]);
  const [editBaseName, setEditBaseName] = useState("");
  const [editBaseDesc, setEditBaseDesc] = useState("");
  const [savingBase, setSavingBase] = useState(false);

  // versions
  const [versions, setVersions] = useState<AgentVersionOut[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [versionId, setVersionId] = useState<string | null>(null);

  const selectedVersion = useMemo(() => versions.find((v) => v.id === versionId) || null, [versions, versionId]);
  const selectedVersionStatus = (selectedVersion?.status || "").toLowerCase();
  const canEditSelectedVersion = selectedVersionStatus === "draft";

  // published def
  const [published, setPublished] = useState<CustomAgentPublishedOut | null>(null);
  const [publishedLoading, setPublishedLoading] = useState(false);

  // preview/run input
  const [inputJson, setInputJson] = useState<string>(
    stableJsonStringify({ goal: "Write a PRD for X", context: "", constraints: "" })
  );
  const [retrievalOverrideJson, setRetrievalOverrideJson] = useState<string>("{}");

  // preview
  const [preview, setPreview] = useState<CustomAgentPreviewOut | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // run
  const [running, setRunning] = useState(false);

  // publish/archive
  const [publishing, setPublishing] = useState(false);
  const [archiving, setArchiving] = useState(false);

  // create version
  const [creatingVersion, setCreatingVersion] = useState(false);

  // save version
  const [savingVersion, setSavingVersion] = useState(false);

  // definition editor: guided form + advanced json
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [definitionJson, setDefinitionJson] = useState<string>(stableJsonStringify({}));
  const [defDirty, setDefDirty] = useState(false);

  const artifactTypes = useMemo(() => {
    const at = meta?.artifact_types || [];
    return at.length ? at : ["strategy_memo", "prd"];
  }, [meta?.artifact_types]);

  const timeframePresets = useMemo(() => {
    const p = meta?.timeframe_presets || [];
    return p.length ? p : ["7d", "30d", "90d", "custom"];
  }, [meta?.timeframe_presets]);

  // knobs bounds/defaults from meta.retrieval_knobs
  const knobDefaults = useMemo(() => {
    const d: any = (meta?.retrieval_knobs as any)?.defaults || {};
    return {
      k: Number(d.k ?? 6),
      alpha: Number(d.alpha ?? 0.65),
      minScore: Number(d.min_score ?? d.minScore ?? 0.15),
      overfetchK: Number(d.overfetch_k ?? d.overfetchK ?? 3),
      rerank: Boolean(d.rerank ?? false),
    };
  }, [meta?.retrieval_knobs]);

  const knobBounds = useMemo(() => {
    const b: any = (meta?.retrieval_knobs as any)?.bounds || {};
    const kb: any = b.k || {};
    const ab: any = b.alpha || {};
    const ms: any = b.min_score || b.minScore || {};
    const ofk: any = b.overfetch_k || b.overfetchK || {};
    return {
      kMin: Number(kb.min ?? 1),
      kMax: Number(kb.max ?? 50),
      aMin: Number(ab.min ?? 0.0),
      aMax: Number(ab.max ?? 1.0),
      msMin: Number(ms.min ?? 0.0),
      msMax: Number(ms.max ?? 1.0),
      ofkMin: Number(ofk.min ?? 1),
      ofkMax: Number(ofk.max ?? 10),
    };
  }, [meta?.retrieval_knobs]);

  // policy allowlist from meta
  const policyAllowedSourceTypes = useMemo(() => {
    const st = meta?.allowed_source_types || [];
    return st.map((x) => String(x).trim().toLowerCase()).filter(Boolean);
  }, [meta?.allowed_source_types]);

  const commonSourceTypes = useMemo(() => ["manual", "docs", "github", "jira", "slack"], []);
  const sourceTypeOptions = useMemo(() => {
    const allowed = policyAllowedSourceTypes;
    const list = allowed.length ? allowed : commonSourceTypes;
    return list.map((x) => ({ value: x, label: x }));
  }, [policyAllowedSourceTypes, commonSourceTypes]);

  // RBAC from meta
  const rbacAgentBuilder = (meta?.rbac_effective as any)?.agent_builder || {};
  const canCreateBase = isRoleAllowed(roleStr, rbacAgentBuilder?.can_create_agent_base_roles || ["admin", "member"]);
  const canPublish = isRoleAllowed(roleStr, rbacAgentBuilder?.can_publish_agent_roles || ["admin"]);
  const canArchive = isRoleAllowed(roleStr, rbacAgentBuilder?.can_archive_agent_roles || ["admin"]);
  const canPreview = isRoleAllowed(roleStr, rbacAgentBuilder?.can_preview_agent_roles || ["admin", "member"]);
  const canRun = isRoleAllowed(roleStr, rbacAgentBuilder?.can_run_agent_roles || ["admin", "member"]);
  const canEditBase = canCreateBase;
  const canEditVersion = canCreateBase;

  // Guided form state
  const [form, setForm] = useState<DefinitionForm>(() => definitionJsonToForm({}, ["prd", "strategy_memo"]));

  // Validate: if policy allowlist exists, selected sources must be subset
  const policyViolation = useMemo(() => {
    if (!policyAllowedSourceTypes.length) return null;
    const bad = (form.sourceTypes || []).filter((x) => !policyAllowedSourceTypes.includes(String(x).toLowerCase()));
    if (!bad.length) return null;
    return `Source types not allowed by policy: ${bad.join(", ")}`;
  }, [form.sourceTypes, policyAllowedSourceTypes]);

  const baseOptions = useMemo(
    () =>
      bases.map((b) => ({
        value: b.id,
        label: `${b.name} · ${b.key}`,
      })),
    [bases]
  );

  const versionOptions = useMemo(
    () =>
      versions.map((v) => ({
        value: v.id,
        label: `v${v.version} · ${v.status} · ${v.id.slice(0, 8)}`,
      })),
    [versions]
  );

  function syncFormToJson(nextForm: DefinitionForm) {
    const dj = formToDefinitionJson(nextForm);
    setDefinitionJson(stableJsonStringify(dj));
    setDefDirty(true);
  }

  function setFormAndSync(patch: Partial<DefinitionForm>) {
    setForm((prev) => {
      const next = { ...prev, ...patch };
      syncFormToJson(next);
      return next;
    });
  }

  async function loadMyRole() {
    if (!wid) return;
    const res = await apiFetch<WorkspaceRole>(`/workspaces/${wid}/my-role`, { method: "GET" });
    if (!res.ok) {
      setMyRole(null);
      return;
    }
    setMyRole(res.data);
  }

  async function loadMeta() {
    if (!wid) return;
    setErr(null);
    setMetaLoading(true);

    const res = await apiFetch<AgentBuilderMetaOut>(`/workspaces/${wid}/agent-builder/meta`, { method: "GET" });

    setMetaLoading(false);

    if (!res.ok) {
      setMeta(null);
      setErr(`Agent builder meta load failed: ${res.status} ${res.error}`);
      return;
    }

    setMeta(res.data);
  }

  async function loadBases() {
    if (!wid) return;
    setErr(null);
    setBasesLoading(true);

    const res = await apiFetch<AgentBaseOut[]>(`/workspaces/${wid}/agent-bases`, { method: "GET" });

    setBasesLoading(false);

    if (!res.ok) {
      setBases([]);
      setBaseId(null);
      setVersions([]);
      setVersionId(null);
      setErr(`Agent bases load failed: ${res.status} ${res.error}`);
      return;
    }

    const list = res.data || [];
    setBases(list);

    if (list.length === 0) {
      setBaseId(null);
      setVersions([]);
      setVersionId(null);
      return;
    }

    if (!baseId || !list.find((b) => b.id === baseId)) {
      setBaseId(list[0].id);
    }
  }

  async function loadVersions(bid: string) {
    if (!wid || !bid) return;
    setErr(null);
    setVersionsLoading(true);

    const res = await apiFetch<AgentVersionOut[]>(`/workspaces/${wid}/agent-bases/${bid}/versions`, { method: "GET" });

    setVersionsLoading(false);

    if (!res.ok) {
      setVersions([]);
      setVersionId(null);
      setErr(`Agent versions load failed: ${res.status} ${res.error}`);
      return;
    }

    const list = res.data || [];
    setVersions(list);

    const latestDraft = list.find((x) => (x.status || "").toLowerCase() === "draft");
    const pick = latestDraft || list[0] || null;
    setVersionId(pick ? pick.id : null);

    // initialize editor from picked version or default
    const dj = (pick?.definition_json || {}) as AgentDefinitionJson;
    const nextForm = definitionJsonToForm(dj, artifactTypes);
    setForm(nextForm);
    setDefinitionJson(stableJsonStringify(formToDefinitionJson(nextForm)));
    setDefDirty(false);
  }

  async function loadPublished(bid: string) {
    if (!wid || !bid) return;
    setErr(null);
    setPublishedLoading(true);

    const res = await apiFetch<CustomAgentPublishedOut>(`/workspaces/${wid}/agent-bases/${bid}/published`, {
      method: "GET",
    });

    setPublishedLoading(false);

    if (!res.ok) {
      setPublished(null);
      return;
    }

    setPublished(res.data);
  }

  async function createBase() {
    if (!wid) return;
    if (!canCreateBase) {
      setErr("Not allowed by RBAC to create agent base.");
      return;
    }

    const key = newKey.trim();
    const name = newName.trim();
    const description = newDesc.trim();

    if (!key || !name) {
      setErr("Key and name are required.");
      return;
    }

    setErr(null);
    setCreatingBase(true);

    const res = await apiFetch<AgentBaseOut>(`/workspaces/${wid}/agent-bases`, {
      method: "POST",
      body: JSON.stringify({ key, name, description }),
    });

    setCreatingBase(false);

    if (!res.ok) {
      setErr(`Create agent base failed: ${res.status} ${res.error}`);
      return;
    }

    await loadBases();
    setBaseId(res.data.id);
  }

  async function saveBaseEdits() {
    if (!wid || !baseId) return;
    if (!canEditBase) {
      setErr("Not allowed by RBAC to edit agent base.");
      return;
    }

    const name = editBaseName.trim();
    const description = editBaseDesc.trim();

    if (!name) {
      setErr("Base name cannot be empty.");
      return;
    }

    setErr(null);
    setSavingBase(true);

    const res = await apiFetch<AgentBaseOut>(`/workspaces/${wid}/agent-bases/${baseId}`, {
      method: "PATCH",
      body: JSON.stringify({ name, description }),
    });

    setSavingBase(false);

    if (!res.ok) {
      setErr(`Update agent base failed: ${res.status} ${res.error}`);
      return;
    }

    await loadBases();
  }

  async function createVersion() {
    if (!wid || !baseId) return;

    if (policyViolation) {
      setErr(policyViolation);
      return;
    }

    const parsed = safeJsonParse(definitionJson);
    if (!parsed.ok) {
      setErr(`definition_json invalid: ${parsed.error}`);
      return;
    }

    setErr(null);
    setCreatingVersion(true);

    const res = await apiFetch<AgentVersionOut>(`/workspaces/${wid}/agent-bases/${baseId}/versions`, {
      method: "POST",
      body: JSON.stringify({ definition_json: parsed.value || {} }),
    });

    setCreatingVersion(false);

    if (!res.ok) {
      setErr(`Create agent version failed: ${res.status} ${res.error}`);
      return;
    }

    await loadVersions(baseId);
    setVersionId(res.data.id);
  }

  async function saveSelectedVersion() {
    if (!wid || !versionId) return;
    if (!canEditVersion) {
      setErr("Not allowed by RBAC to edit agent versions.");
      return;
    }
    if (!canEditSelectedVersion) {
      setErr("Only draft versions can be edited.");
      return;
    }
    if (policyViolation) {
      setErr(policyViolation);
      return;
    }

    const parsed = safeJsonParse(definitionJson);
    if (!parsed.ok) {
      setErr(`definition_json invalid: ${parsed.error}`);
      return;
    }

    setErr(null);
    setSavingVersion(true);

    const res = await apiFetch<AgentVersionOut>(`/workspaces/${wid}/agent-versions/${versionId}`, {
      method: "PATCH",
      body: JSON.stringify({ definition_json: parsed.value || {} }),
    });

    setSavingVersion(false);

    if (!res.ok) {
      setErr(`Save draft failed: ${res.status} ${res.error}`);
      return;
    }

    if (baseId) {
      await loadVersions(baseId);
      setVersionId(res.data.id);
    }
    setDefDirty(false);
  }

  async function publishSelected() {
    if (!wid || !versionId) return;
    if (!canPublish) {
      setErr("Not allowed by RBAC to publish agent version.");
      return;
    }
    if (policyViolation) {
      setErr(policyViolation);
      return;
    }

    setErr(null);
    setPublishing(true);

    const res = await apiFetch<AgentPublishOut>(`/workspaces/${wid}/agent-versions/${versionId}/publish`, {
      method: "POST",
      body: JSON.stringify({}),
    });

    setPublishing(false);

    if (!res.ok) {
      setErr(`Publish failed: ${res.status} ${res.error}`);
      return;
    }

    if (baseId) {
      await loadVersions(baseId);
      await loadPublished(baseId);
    }
  }

  async function archiveSelected() {
    if (!wid || !versionId) return;
    if (!canArchive) {
      setErr("Not allowed by RBAC to archive agent version.");
      return;
    }

    setErr(null);
    setArchiving(true);

    const res = await apiFetch<AgentArchiveOut>(`/workspaces/${wid}/agent-versions/${versionId}/archive`, {
      method: "POST",
      body: JSON.stringify({}),
    });

    setArchiving(false);

    if (!res.ok) {
      setErr(`Archive failed: ${res.status} ${res.error}`);
      return;
    }

    if (baseId) await loadVersions(baseId);
  }

  async function doPreview() {
    if (!wid || !baseId) return;
    if (!canPreview) {
      setErr("Not allowed by RBAC to preview.");
      return;
    }

    const inputParsed = safeJsonParse(inputJson);
    if (!inputParsed.ok) {
      setErr(`input_payload JSON invalid: ${inputParsed.error}`);
      return;
    }

    const retrievalParsed = safeJsonParse(retrievalOverrideJson);
    if (!retrievalParsed.ok) {
      setErr(`retrieval override JSON invalid: ${retrievalParsed.error}`);
      return;
    }

    const payload: any = {
      input_payload: inputParsed.value || {},
      retrieval: Object.keys(retrievalParsed.value || {}).length ? retrievalParsed.value : null,
    };

    setErr(null);
    setPreviewLoading(true);

    const res = await apiFetch<CustomAgentPreviewOut>(`/workspaces/${wid}/agent-bases/${baseId}/preview`, {
      method: "POST",
      body: JSON.stringify(payload),
    });

    setPreviewLoading(false);

    if (!res.ok) {
      setPreview(null);
      setErr(`Preview failed: ${res.status} ${res.error}`);
      return;
    }

    setPreview(res.data);
  }

  async function doRun() {
    if (!wid || !baseId) return;
    if (!canRun) {
      setErr("Not allowed by RBAC to run.");
      return;
    }

    const inputParsed = safeJsonParse(inputJson);
    if (!inputParsed.ok) {
      setErr(`input_payload JSON invalid: ${inputParsed.error}`);
      return;
    }

    const retrievalParsed = safeJsonParse(retrievalOverrideJson);
    if (!retrievalParsed.ok) {
      setErr(`retrieval override JSON invalid: ${retrievalParsed.error}`);
      return;
    }

    const payload: any = {
      input_payload: inputParsed.value || {},
      retrieval: Object.keys(retrievalParsed.value || {}).length ? retrievalParsed.value : null,
    };

    setErr(null);
    setRunning(true);

    const res = await apiFetch<Run>(`/workspaces/${wid}/agent-bases/${baseId}/runs`, {
      method: "POST",
      body: JSON.stringify(payload),
    });

    setRunning(false);

    if (!res.ok) {
      setErr(`Run failed: ${res.status} ${res.error}`);
      return;
    }

    nav(`/runs/${res.data.id}`);
  }

  async function loadAll() {
    await loadMyRole();
    await loadMeta();
    await loadBases();
  }

  // initial load
  useEffect(() => {
    if (!wid) return;
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid]);

  // base changes -> versions + published + base edit fields
  useEffect(() => {
    if (!baseId) {
      setPublished(null);
      setPreview(null);
      setVersions([]);
      setVersionId(null);
      return;
    }

    const b = bases.find((x) => x.id === baseId);
    setEditBaseName(b?.name || "");
    setEditBaseDesc(b?.description || "");

    void loadVersions(baseId);
    void loadPublished(baseId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseId]);

  // version selection -> load into guided form/editor (but don’t destroy edits if dirty)
  useEffect(() => {
    if (!versionId) return;
    const v = versions.find((x) => x.id === versionId);
    if (!v?.definition_json) return;

    if (defDirty) return;

    const dj = (v.definition_json || {}) as AgentDefinitionJson;
    const nextForm = definitionJsonToForm(dj, artifactTypes);
    setForm(nextForm);
    setDefinitionJson(stableJsonStringify(formToDefinitionJson(nextForm)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versionId]);

  // build-friendly defaults for new draft when there’s no selected version
  useEffect(() => {
    if (versions.length === 0 && artifactTypes.length) {
      const next = definitionJsonToForm({}, artifactTypes);
      setForm(next);
      setDefinitionJson(stableJsonStringify(formToDefinitionJson(next)));
      setDefDirty(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versions.length, artifactTypes.join("|")]);

  const headerRight = (
    <Group>
      <Button component={Link} to={`/workspaces/${wid}`} variant="light" size="sm">
        Back
      </Button>
      <Button onClick={loadAll} loading={metaLoading || basesLoading} size="sm" variant="light">
        Refresh
      </Button>
    </Group>
  );

  const roleRight = myRole ? (
    <Group gap="sm" wrap="wrap">
      <Badge color={roleBadgeColor(roleStr)} variant="light">
        {myRole.role}
      </Badge>
      <GlassStat label="Bases" value={bases.length} />
      <GlassStat label="Versions" value={versions.length} />
    </Group>
  ) : undefined;

  return (
    <GlassPage
      title="Agent Builder"
      subtitle="Create agent bases, draft versions, and publish governed definitions."
      right={headerRight}
    >
      <Stack gap="md">
        {err ? (
          <GlassCard>
            <Text c="red">{err}</Text>
          </GlassCard>
        ) : null}

        <GlassSection
          title="Access"
          description="RBAC is enforced by backend; UI controls are disabled based on effective RBAC."
          right={roleRight}
        >
          <Stack gap="xs">
            <Text size="sm" c="dimmed">
              Your role controls whether you can create bases, edit drafts, publish, or run agents.
            </Text>
          </Stack>
        </GlassSection>

        <GlassSection
          title="Builder meta"
          description="Policy + RBAC metadata used to render allowed options."
          right={
            <Group gap="sm">
              <Button variant="light" onClick={loadMeta} loading={metaLoading} size="sm">
                Refresh meta
              </Button>
              <Badge variant="light">governance-aware</Badge>
            </Group>
          }
        >
          {!meta ? (
            <Text c="dimmed">{metaLoading ? "Loading…" : "No meta loaded."}</Text>
          ) : (
            <Stack gap="xs">
              <Text size="sm" c="dimmed">
                policy allowlist (source_types):{" "}
                <Code>{policyAllowedSourceTypes.length ? policyAllowedSourceTypes.join(",") : "none (no allowlist)"}</Code>
              </Text>
              <Text size="sm" c="dimmed">
                artifact types: <Code>{artifactTypes.join(",")}</Code>
              </Text>
              <Text size="sm" c="dimmed">
                timeframe presets: <Code>{timeframePresets.join(",")}</Code>
              </Text>
            </Stack>
          )}
        </GlassSection>

        <GlassSection
          title="Create agent base"
          description="A base is a logical agent (key + name). Versions store the governed prompt + retrieval config."
          right={
            <Group gap="sm" wrap="wrap">
              <Badge variant="light" color={canCreateBase ? "blue" : "gray"}>
                {canCreateBase ? "allowed" : "blocked by RBAC"}
              </Badge>
            </Group>
          }
        >
          <Stack gap="sm">
            <Group grow>
              <TextInput
                label="Key"
                value={newKey}
                onChange={(e) => setNewKey(e.currentTarget.value)}
                placeholder="e.g. demo_prd"
                disabled={!canCreateBase}
              />
              <TextInput
                label="Name"
                value={newName}
                onChange={(e) => setNewName(e.currentTarget.value)}
                placeholder="e.g. Demo PRD Agent"
                disabled={!canCreateBase}
              />
            </Group>

            <TextInput
              label="Description"
              value={newDesc}
              onChange={(e) => setNewDesc(e.currentTarget.value)}
              placeholder="Short description"
              disabled={!canCreateBase}
            />

            <Group>
              <Button onClick={createBase} loading={creatingBase} disabled={!canCreateBase} size="sm">
                Create base
              </Button>
              <Button variant="light" onClick={loadBases} loading={basesLoading} size="sm">
                Refresh bases
              </Button>
            </Group>
          </Stack>
        </GlassSection>

        <GlassSection
          title="Agent bases"
          description="Select a base to manage versions, publishing, and runs."
          right={<GlassStat label="Total" value={bases.length} />}
        >
          {bases.length === 0 ? (
            <Text c="dimmed">No agent bases in this workspace yet.</Text>
          ) : (
            <Stack gap="sm">
              <Select
                label="Select agent base"
                data={baseOptions}
                value={baseId}
                onChange={(v) => setBaseId(v)}
                searchable
                nothingFoundMessage="No agent bases"
              />

              {selectedBase ? (
                <GlassCard p="md">
                  <Stack gap="sm">
                    <Group justify="space-between" align="center">
                      <Text fw={700}>Edit base</Text>
                      <Badge variant="light" color={canEditBase ? "blue" : "gray"}>
                        {canEditBase ? "editable" : "read-only"}
                      </Badge>
                    </Group>

                    <Group grow>
                      <TextInput
                        label="Name"
                        value={editBaseName}
                        onChange={(e) => setEditBaseName(e.currentTarget.value)}
                        disabled={!canEditBase}
                      />
                      <TextInput
                        label="Description"
                        value={editBaseDesc}
                        onChange={(e) => setEditBaseDesc(e.currentTarget.value)}
                        disabled={!canEditBase}
                      />
                    </Group>

                    <Group>
                      <Button onClick={saveBaseEdits} loading={savingBase} disabled={!canEditBase || !baseId} size="sm">
                        Save base
                      </Button>
                    </Group>
                  </Stack>
                </GlassCard>
              ) : null}
            </Stack>
          )}
        </GlassSection>

        <GlassSection
          title="Versions"
          description="Draft versions are editable. Publish locks a definition as the active version."
          right={
            <Group gap="sm">
              <GlassStat label="Count" value={versions.length} />
              <Button
                variant="light"
                onClick={() => (baseId ? loadVersions(baseId) : null)}
                loading={versionsLoading}
                disabled={!baseId}
                size="sm"
              >
                Refresh
              </Button>
            </Group>
          }
        >
          {!baseId ? (
            <Text c="dimmed">Pick an agent base to manage versions.</Text>
          ) : (
            <Stack gap="sm">
              <Select
                label="Select version"
                data={versionOptions}
                value={versionId}
                onChange={(v) => setVersionId(v)}
                searchable
                nothingFoundMessage="No versions"
              />

              <Group justify="space-between" align="center">
                <Group gap="sm">
                  <Badge variant="light" color={canEditSelectedVersion ? "blue" : "gray"}>
                    selected: {selectedVersionStatus || "none"}
                  </Badge>
                  {defDirty ? <Badge variant="light" color="yellow">unsaved changes</Badge> : null}
                </Group>

                <Button variant="light" size="xs" onClick={() => setAdvancedOpen((x) => !x)}>
                  {advancedOpen ? "Hide advanced JSON" : "Show advanced JSON"}
                </Button>
              </Group>

              {policyViolation ? (
                <GlassCard>
                  <Text c="red">{policyViolation}</Text>
                  <Text size="sm" c="dimmed">
                    Fix your source types to match the workspace policy allowlist (from meta).
                  </Text>
                </GlassCard>
              ) : null}

              <Divider />

              <Text fw={700}>Guided builder</Text>

              <Group grow>
                <Select
                  label="Artifact type"
                  data={artifactTypes.map((t) => ({ value: t, label: t }))}
                  value={form.artifactType}
                  onChange={(v) => setFormAndSync({ artifactType: v || artifactTypes[0] || "strategy_memo" })}
                />
                <Group gap="xs" align="end" style={{ width: "100%" }}>
                  <Select
                    label="Timeframe preset"
                    data={timeframePresets.map((p) => ({ value: p, label: p }))}
                    value={form.preset}
                    onChange={(v) => setFormAndSync({ preset: (v as any) || "30d" })}
                  />
                  <HelpPill label="Controls what time window retrieval should prioritize." />
                </Group>
              </Group>

              {form.preset === "custom" ? (
                <Group grow>
                  <TextInput
                    label="Start date (YYYY-MM-DD)"
                    value={form.startDate}
                    onChange={(e) => setFormAndSync({ startDate: e.currentTarget.value })}
                  />
                  <TextInput
                    label="End date (YYYY-MM-DD)"
                    value={form.endDate}
                    onChange={(e) => setFormAndSync({ endDate: e.currentTarget.value })}
                  />
                </Group>
              ) : null}

              <Divider />

              <Group justify="space-between" align="center">
                <Group gap="sm">
                  <Text fw={700}>Retrieval</Text>
                  <HelpPill label="Retrieval pulls evidence into the agent context. Disable if you want pure prompting." />
                </Group>

                <Checkbox
                  label="enabled"
                  checked={form.retrievalEnabled}
                  onChange={(e) => setFormAndSync({ retrievalEnabled: e.currentTarget.checked })}
                />
              </Group>

              <TextInput
                label="Query"
                value={form.retrievalQuery}
                onChange={(e) => setFormAndSync({ retrievalQuery: e.currentTarget.value })}
                placeholder='e.g., "pricing page events"'
              />

              <Group gap="xs" align="end">
                <MultiSelect
                  label="source_types"
                  data={sourceTypeOptions}
                  value={form.sourceTypes}
                  onChange={(v) => setFormAndSync({ sourceTypes: v })}
                  searchable
                  nothingFoundMessage="No options"
                  description={
                    policyAllowedSourceTypes.length
                      ? `Policy allowlist enforced: ${policyAllowedSourceTypes.join(", ")}`
                      : "No policy allowlist set."
                  }
                />
                <HelpPill label="If policy allowlist exists, only those sources can be used." />
              </Group>

              <Group grow>
                <Group gap="xs" align="end" style={{ width: "100%" }}>
                  <NumberInput
                    label="k"
                    value={form.k}
                    min={knobBounds.kMin}
                    max={knobBounds.kMax}
                    onChange={(v) =>
                      setFormAndSync({ k: clamp(Number(v) || knobDefaults.k, knobBounds.kMin, knobBounds.kMax) })
                    }
                  />
                  <HelpPill label="How many chunks to fetch before scoring/filtering." />
                </Group>

                <Group gap="xs" align="end" style={{ width: "100%" }}>
                  <NumberInput
                    label="alpha"
                    value={form.alpha}
                    min={knobBounds.aMin}
                    max={knobBounds.aMax}
                    step={0.05}
                    onChange={(v) =>
                      setFormAndSync({ alpha: clamp(Number(v) || knobDefaults.alpha, knobBounds.aMin, knobBounds.aMax) })
                    }
                  />
                  <HelpPill label="Hybrid weight: 0=keyword heavy, 1=vector heavy (implementation dependent)." />
                </Group>
              </Group>

              <Group grow>
                <Group gap="xs" align="end" style={{ width: "100%" }}>
                  <NumberInput
                    label="min_score"
                    value={form.minScore}
                    min={knobBounds.msMin}
                    max={knobBounds.msMax}
                    step={0.05}
                    onChange={(v) =>
                      setFormAndSync({
                        minScore: clamp(Number(v) || knobDefaults.minScore, knobBounds.msMin, knobBounds.msMax),
                      })
                    }
                  />
                  <HelpPill label="Filters weak matches. Raise to improve precision; lower to improve recall." />
                </Group>

                <Group gap="xs" align="end" style={{ width: "100%" }}>
                  <NumberInput
                    label="overfetch_k"
                    value={form.overfetchK}
                    min={knobBounds.ofkMin}
                    max={knobBounds.ofkMax}
                    onChange={(v) =>
                      setFormAndSync({
                        overfetchK: clamp(Number(v) || knobDefaults.overfetchK, knobBounds.ofkMin, knobBounds.ofkMax),
                      })
                    }
                  />
                  <HelpPill label="Fetch extra candidates to improve final selection (useful with rerank)." />
                </Group>
              </Group>

              <Group gap="xs" align="center">
                <Checkbox label="rerank" checked={form.rerank} onChange={(e) => setFormAndSync({ rerank: e.currentTarget.checked })} />
                <HelpPill label="When enabled, applies an extra reranking step (if available) to improve ordering." />
              </Group>

              <Divider />

              <Group gap="sm" align="center">
                <Text fw={700}>Prompt blocks</Text>
                <HelpPill label="Blocks are applied in order. Use instruction/constraint/checklist/style to shape the agent." />
              </Group>

              <Text size="sm" c="dimmed">
                Minimal editor: add/remove blocks, pick a kind, and write text.
              </Text>

              <Stack gap="xs">
                {form.promptBlocks.map((b, idx) => (
                  <GlassCard key={idx} p="md">
                    <Stack gap="xs">
                      <Group grow align="end">
                        <Select
                          label="kind"
                          data={[
                            { value: "instruction", label: "instruction" },
                            { value: "constraint", label: "constraint" },
                            { value: "checklist", label: "checklist" },
                            { value: "style", label: "style" },
                          ]}
                          value={b.kind}
                          onChange={(v) => {
                            const next = [...form.promptBlocks];
                            next[idx] = { ...next[idx], kind: v || "instruction" };
                            setFormAndSync({ promptBlocks: next });
                          }}
                        />
                        <Button
                          variant="light"
                          color="red"
                          size="sm"
                          onClick={() => {
                            const next = form.promptBlocks.filter((_, i) => i !== idx);
                            setFormAndSync({ promptBlocks: next.length ? next : DEFAULT_PROMPT_BLOCKS });
                          }}
                        >
                          Remove
                        </Button>
                      </Group>

                      <Textarea
                        label="text"
                        autosize
                        minRows={3}
                        value={b.text}
                        onChange={(e) => {
                          const next = [...form.promptBlocks];
                          next[idx] = { ...next[idx], text: e.currentTarget.value };
                          setFormAndSync({ promptBlocks: next });
                        }}
                      />
                    </Stack>
                  </GlassCard>
                ))}
              </Stack>

              <Group>
                <Button
                  variant="light"
                  size="sm"
                  onClick={() => setFormAndSync({ promptBlocks: [...form.promptBlocks, { kind: "instruction", text: "" }] })}
                >
                  Add prompt block
                </Button>
              </Group>

              <Divider />

              <Collapse in={advancedOpen}>
                <Group gap="sm" align="center" mb="xs">
                  <Text fw={700}>definition_json (advanced)</Text>
                  <HelpPill label="Advanced mode is for last-mile tweaks. Guided form does not auto-sync back from arbitrary JSON edits." />
                </Group>

                <Textarea
                  label="definition_json"
                  autosize
                  minRows={10}
                  value={definitionJson}
                  onChange={(e) => {
                    setDefinitionJson(e.currentTarget.value);
                    setDefDirty(true);
                  }}
                />
              </Collapse>

              <Group>
                <Button onClick={createVersion} loading={creatingVersion} disabled={!baseId || !!policyViolation} size="sm">
                  Create draft
                </Button>

                <Button
                  onClick={saveSelectedVersion}
                  loading={savingVersion}
                  disabled={!versionId || !canEditVersion || !canEditSelectedVersion || !defDirty || !!policyViolation}
                  size="sm"
                  variant="light"
                >
                  Save draft
                </Button>

                <Tooltip withArrow label={canPublish ? "Publish makes this the active version for the base." : "Admin only."}>
                  <span>
                    <Button onClick={publishSelected} loading={publishing} disabled={!versionId || !canPublish || !!policyViolation} size="sm">
                      Publish
                    </Button>
                  </span>
                </Tooltip>

                <Tooltip withArrow label={canArchive ? "Archive hides the version from normal selection." : "Admin only."}>
                  <span>
                    <Button
                      onClick={archiveSelected}
                      loading={archiving}
                      disabled={!versionId || !canArchive}
                      variant="light"
                      color="red"
                      size="sm"
                    >
                      Archive
                    </Button>
                  </span>
                </Tooltip>
              </Group>

              <Text size="xs" c="dimmed">
                Publish requires <Code>can_publish_agent_roles</Code>. Archive requires <Code>can_archive_agent_roles</Code>. Draft edits only work for{" "}
                <Code>draft</Code> versions.
              </Text>
            </Stack>
          )}
        </GlassSection>

        <GlassSection
          title="Published definition"
          description="The latest published definition is what runs will use by default."
          right={
            <Group gap="sm">
              <Button
                variant="light"
                onClick={() => (baseId ? loadPublished(baseId) : null)}
                loading={publishedLoading}
                disabled={!baseId}
                size="sm"
              >
                Refresh
              </Button>
              <Badge variant="light">latest</Badge>
            </Group>
          }
        >
          {!baseId ? (
            <Text c="dimmed">Pick an agent base first.</Text>
          ) : !published ? (
            <Text c="dimmed">No published version exists (or not loaded).</Text>
          ) : (
            <Stack gap="xs">
              <Text size="sm" c="dimmed">
                base_id: <Code>{published.agent_base_id}</Code> · published_version: <Code>{published.published_version}</Code>
              </Text>
              <GlassCard p="md">
                <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{stableJsonStringify(published.definition_json)}</pre>
              </GlassCard>
            </Stack>
          )}
        </GlassSection>

        <GlassSection
          title="Preview + run"
          description="Validate prompt wiring and policy enforcement. Then run to create a real execution."
          right={
            <Group gap="sm" wrap="wrap">
              <Badge variant="light" color={canPreview ? "blue" : "gray"}>
                preview: {canPreview ? "allowed" : "blocked"}
              </Badge>
              <Badge variant="light" color={canRun ? "blue" : "gray"}>
                run: {canRun ? "allowed" : "blocked"}
              </Badge>
            </Group>
          }
        >
          <Stack gap="sm">
            <Text size="sm" c="dimmed">
              Preview: <Code>POST /workspaces/:id/agent-bases/:baseId/preview</Code> · Run:{" "}
              <Code>POST /workspaces/:id/agent-bases/:baseId/runs</Code>
            </Text>

            <Divider />

            <Textarea
              label="input_payload (JSON)"
              autosize
              minRows={6}
              value={inputJson}
              onChange={(e) => setInputJson(e.currentTarget.value)}
            />

            <Group gap="xs" align="end">
              <Textarea
                label="retrieval override (JSON, optional)"
                description='If empty {}, published definition retrieval defaults are used.'
                autosize
                minRows={4}
                value={retrievalOverrideJson}
                onChange={(e) => setRetrievalOverrideJson(e.currentTarget.value)}
              />
              <HelpPill label="Use this to override retrieval knobs for preview/run without changing the published definition." />
            </Group>

            <Group>
              <Tooltip withArrow label={canPreview ? "Preview renders the resolved prompts without running." : "Blocked by RBAC."}>
                <span>
                  <Button onClick={doPreview} loading={previewLoading} disabled={!baseId || !canPreview} size="sm">
                    Preview
                  </Button>
                </span>
              </Tooltip>

              <Tooltip withArrow label={canRun ? "Run executes and creates a new run record." : "Blocked by RBAC."}>
                <span>
                  <Button onClick={doRun} loading={running} disabled={!baseId || !canRun} size="sm">
                    Run
                  </Button>
                </span>
              </Tooltip>
            </Group>

            {preview ? (
              <GlassCard p="md">
                <Stack gap="xs">
                  <Group justify="space-between">
                    <Text fw={700}>Preview output</Text>
                    <Badge variant="light">{preview.llm_enabled ? "LLM enabled" : "LLM disabled"}</Badge>
                  </Group>

                  <Text size="sm" c="dimmed">
                    artifact_type: <Code>{preview.artifact_type}</Code> · published_version: <Code>{preview.published_version}</Code>
                  </Text>

                  <Divider />

                  <Text fw={700}>retrieval_resolved</Text>
                  <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{stableJsonStringify(preview.retrieval_resolved)}</pre>

                  <Divider />

                  <Text fw={700}>system_prompt</Text>
                  <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{preview.system_prompt}</pre>

                  <Divider />

                  <Text fw={700}>user_prompt</Text>
                  <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{preview.user_prompt}</pre>

                  {preview.notes?.length ? (
                    <>
                      <Divider />
                      <Text fw={700}>notes</Text>
                      <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{stableJsonStringify(preview.notes)}</pre>
                    </>
                  ) : null}
                </Stack>
              </GlassCard>
            ) : (
              <Text size="sm" c="dimmed">
                Run preview to validate prompt wiring and policy enforcement.
              </Text>
            )}
          </Stack>
        </GlassSection>
      </Stack>
    </GlassPage>
  );
}