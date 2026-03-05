// apps/web/src/pages/AgentBuilderPage.tsx
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Code,
  Group,
  Select,
  Stack,
  Text,
  Textarea,
  Title,
  Divider,
  TextInput,
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

  // versions
  const [versions, setVersions] = useState<AgentVersionOut[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [versionId, setVersionId] = useState<string | null>(null);

  // create version (draft)
  const defaultDefinition = useMemo(() => {
    // keep consistent with what you tested via curl
    return {
      artifact: { type: "prd" },
      retrieval: {
        enabled: true,
        query: "demo",
        k: 6,
        alpha: 0.65,
        source_types: ["manual"],
        timeframe: { preset: "30d" },
        min_score: 0.15,
        overfetch_k: 3,
        rerank: false,
      },
      prompt_blocks: [{ kind: "instruction", text: "Write a clean PRD. Be specific. Do not invent facts." }],
    };
  }, []);

  const [definitionJson, setDefinitionJson] = useState<string>(stableJsonStringify(defaultDefinition));
  const [creatingVersion, setCreatingVersion] = useState(false);

  // publish/archive
  const [publishing, setPublishing] = useState(false);
  const [archiving, setArchiving] = useState(false);

  // published def
  const [published, setPublished] = useState<CustomAgentPublishedOut | null>(null);
  const [publishedLoading, setPublishedLoading] = useState(false);

  // input payload + retrieval override
  const [inputJson, setInputJson] = useState<string>(
    stableJsonStringify({ goal: "Write a PRD for X", context: "", constraints: "" })
  );
  const [retrievalOverrideJson, setRetrievalOverrideJson] = useState<string>("{}");

  // preview
  const [preview, setPreview] = useState<CustomAgentPreviewOut | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // run
  const [running, setRunning] = useState(false);

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

  // RBAC effective roles from meta (fallback to safe defaults)
  const rbacAgentBuilder = (meta?.rbac_effective as any)?.agent_builder || {};
  const canCreateBase = isRoleAllowed(roleStr, rbacAgentBuilder?.can_create_agent_base_roles || ["admin", "member"]);
  const canPublish = isRoleAllowed(roleStr, rbacAgentBuilder?.can_publish_agent_roles || ["admin"]);
  const canArchive = isRoleAllowed(roleStr, rbacAgentBuilder?.can_archive_agent_roles || ["admin"]);
  const canPreview = isRoleAllowed(roleStr, rbacAgentBuilder?.can_preview_agent_roles || ["admin", "member"]);
  const canRun = isRoleAllowed(roleStr, rbacAgentBuilder?.can_run_agent_roles || ["admin", "member"]);

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

    // preserve existing selection if possible
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

    // select latest draft first, else latest
    const latestDraft = list.find((x) => (x.status || "").toLowerCase() === "draft");
    const pick = latestDraft || list[0] || null;
    setVersionId(pick ? pick.id : null);

    // also update the editor with selected version definition (nice UX)
    if (pick?.definition_json) setDefinitionJson(stableJsonStringify(pick.definition_json));
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
      // 409 is expected when none exists; don’t hard-error the page
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

    // reload + select new base
    await loadBases();
    setBaseId(res.data.id);
  }

  async function createVersion() {
    if (!wid || !baseId) return;

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

  async function publishSelected() {
    if (!wid || !versionId) return;
    if (!canPublish) {
      setErr("Not allowed by RBAC to publish agent version.");
      return;
    }

    setErr(null);
    setPublishing(true);

    const res = await apiFetch<any>(`/workspaces/${wid}/agent-versions/${versionId}/publish`, {
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

    const res = await apiFetch<any>(`/workspaces/${wid}/agent-versions/${versionId}/archive`, {
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

  useEffect(() => {
    if (!wid) return;
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid]);

  useEffect(() => {
    if (!baseId) {
      setPublished(null);
      setPreview(null);
      setVersions([]);
      setVersionId(null);
      return;
    }
    void loadVersions(baseId);
    void loadPublished(baseId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseId]);

  useEffect(() => {
    if (!versionId) return;
    const v = versions.find((x) => x.id === versionId);
    if (v?.definition_json) setDefinitionJson(stableJsonStringify(v.definition_json));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versionId]);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Agent Builder</Title>
        <Group>
          <Button component={Link} to={`/workspaces/${wid}`} variant="light">
            Back
          </Button>
          <Button onClick={loadAll} loading={metaLoading || basesLoading}>
            Refresh
          </Button>
        </Group>
      </Group>

      {myRole ? (
        <Card withBorder>
          <Group justify="space-between">
            <Text fw={700}>Workspace role</Text>
            <Badge color={roleBadgeColor(roleStr)} variant="light">
              {myRole.role}
            </Badge>
          </Group>
          <Text size="sm" c="dimmed">
            RBAC is enforced by backend; UI buttons are disabled based on effective RBAC + your role.
          </Text>
        </Card>
      ) : null}

      {err ? (
        <Card withBorder>
          <Text c="red">{err}</Text>
        </Card>
      ) : null}

      {/* Meta */}
      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Group gap="sm">
              <Text fw={700}>Builder Meta</Text>
              <Badge variant="light">governance-aware</Badge>
            </Group>
            <Button variant="light" onClick={loadMeta} loading={metaLoading}>
              Refresh meta
            </Button>
          </Group>

          {!meta ? (
            <Text c="dimmed">{metaLoading ? "Loading…" : "No meta loaded."}</Text>
          ) : (
            <>
              <Text size="sm" c="dimmed">
                allowed_source_types:{" "}
                <Code>{(meta.allowed_source_types || []).length ? meta.allowed_source_types.join(",") : "none"}</Code>
              </Text>
              <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{stableJsonStringify(meta)}</pre>
            </>
          )}
        </Stack>
      </Card>

      {/* Create base */}
      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Group gap="sm">
              <Text fw={700}>Create Agent Base</Text>
              <Badge variant="light" color={canCreateBase ? "blue" : "gray"}>
                {canCreateBase ? "allowed" : "blocked by RBAC"}
              </Badge>
            </Group>
          </Group>

          <Group grow>
            <TextInput
              label="key"
              value={newKey}
              onChange={(e) => setNewKey(e.currentTarget.value)}
              placeholder="e.g. demo_prd"
              disabled={!canCreateBase}
            />
            <TextInput
              label="name"
              value={newName}
              onChange={(e) => setNewName(e.currentTarget.value)}
              placeholder="e.g. Demo PRD Agent"
              disabled={!canCreateBase}
            />
          </Group>
          <TextInput
            label="description"
            value={newDesc}
            onChange={(e) => setNewDesc(e.currentTarget.value)}
            placeholder="Short description"
            disabled={!canCreateBase}
          />
          <Group>
            <Button onClick={createBase} loading={creatingBase} disabled={!canCreateBase}>
              Create base
            </Button>
            <Button variant="light" onClick={loadBases} loading={basesLoading}>
              Refresh bases
            </Button>
          </Group>
        </Stack>
      </Card>

      {/* Bases */}
      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Group gap="sm">
              <Text fw={700}>Agent Bases</Text>
              <Badge variant="light">{bases.length} items</Badge>
            </Group>
            <Button variant="light" onClick={loadBases} loading={basesLoading}>
              Refresh
            </Button>
          </Group>

          {bases.length === 0 ? (
            <Text c="dimmed">No agent bases in this workspace yet.</Text>
          ) : (
            <Select
              label="Select agent base"
              data={baseOptions}
              value={baseId}
              onChange={(v) => setBaseId(v)}
              searchable
              nothingFoundMessage="No agent bases"
            />
          )}
        </Stack>
      </Card>

      {/* Versions */}
      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Group gap="sm">
              <Text fw={700}>Versions</Text>
              <Badge variant="light">{versions.length} items</Badge>
            </Group>
            <Button
              variant="light"
              onClick={() => (baseId ? loadVersions(baseId) : null)}
              loading={versionsLoading}
              disabled={!baseId}
            >
              Refresh versions
            </Button>
          </Group>

          {!baseId ? (
            <Text c="dimmed">Pick an agent base to manage versions.</Text>
          ) : (
            <>
              <Select
                label="Select version"
                data={versionOptions}
                value={versionId}
                onChange={(v) => setVersionId(v)}
                searchable
                nothingFoundMessage="No versions"
              />

              <Textarea
                label="definition_json (for new draft version)"
                description="POST /workspaces/:wid/agent-bases/:baseId/versions"
                autosize
                minRows={10}
                value={definitionJson}
                onChange={(e) => setDefinitionJson(e.currentTarget.value)}
              />

              <Group>
                <Button onClick={createVersion} loading={creatingVersion} disabled={!baseId}>
                  Create draft version
                </Button>

                <Button
                  onClick={publishSelected}
                  loading={publishing}
                  disabled={!versionId || !canPublish}
                  color={canPublish ? undefined : "gray"}
                >
                  Publish selected
                </Button>

                <Button
                  onClick={archiveSelected}
                  loading={archiving}
                  disabled={!versionId || !canArchive}
                  variant="light"
                  color="red"
                >
                  Archive selected
                </Button>
              </Group>

              <Text size="xs" c="dimmed">
                Publish requires RBAC: <Code>can_publish_agent_roles</Code>. Archive requires{" "}
                <Code>can_archive_agent_roles</Code>.
              </Text>
            </>
          )}
        </Stack>
      </Card>

      {/* Published */}
      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Group gap="sm">
              <Text fw={700}>Published Definition</Text>
              <Badge variant="light">latest published</Badge>
            </Group>
            <Button
              variant="light"
              onClick={() => (baseId ? loadPublished(baseId) : null)}
              loading={publishedLoading}
              disabled={!baseId}
            >
              Refresh published
            </Button>
          </Group>

          {!baseId ? (
            <Text c="dimmed">Pick an agent base first.</Text>
          ) : !published ? (
            <Text c="dimmed">No published version exists (or not loaded).</Text>
          ) : (
            <>
              <Text size="sm" c="dimmed">
                base_id: <Code>{published.agent_base_id}</Code> · published_version:{" "}
                <Code>{published.published_version}</Code>
              </Text>
              <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{stableJsonStringify(published.definition_json)}</pre>
            </>
          )}
        </Stack>
      </Card>

      {/* Preview + Run */}
      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Group gap="sm">
              <Text fw={700}>Preview + Run</Text>
              <Badge variant="light">policy enforced</Badge>
            </Group>
            <Badge variant="light" color={canPreview ? "blue" : "gray"}>
              preview: {canPreview ? "allowed" : "blocked"}
            </Badge>
          </Group>

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

          <Textarea
            label="retrieval override (JSON, optional)"
            description='If empty {}, published definition retrieval defaults are used.'
            autosize
            minRows={4}
            value={retrievalOverrideJson}
            onChange={(e) => setRetrievalOverrideJson(e.currentTarget.value)}
          />

          <Group>
            <Button onClick={doPreview} loading={previewLoading} disabled={!baseId || !canPreview}>
              Preview
            </Button>
            <Button onClick={doRun} loading={running} disabled={!baseId || !canRun}>
              Run
            </Button>
          </Group>

          {preview ? (
            <Card withBorder>
              <Stack gap="xs">
                <Group justify="space-between">
                  <Text fw={700}>Preview Output</Text>
                  <Badge variant="light">{preview.llm_enabled ? "LLM enabled" : "LLM disabled"}</Badge>
                </Group>

                <Text size="sm" c="dimmed">
                  artifact_type: <Code>{preview.artifact_type}</Code> · published_version:{" "}
                  <Code>{preview.published_version}</Code>
                </Text>

                <Text fw={600}>retrieval_resolved</Text>
                <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                  {stableJsonStringify(preview.retrieval_resolved)}
                </pre>

                <Text fw={600}>system_prompt</Text>
                <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{preview.system_prompt}</pre>

                <Text fw={600}>user_prompt</Text>
                <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{preview.user_prompt}</pre>

                {preview.notes?.length ? (
                  <>
                    <Text fw={600}>notes</Text>
                    <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{stableJsonStringify(preview.notes)}</pre>
                  </>
                ) : null}
              </Stack>
            </Card>
          ) : (
            <Text size="sm" c="dimmed">
              Run preview to validate prompt wiring and policy enforcement.
            </Text>
          )}
        </Stack>
      </Card>
    </Stack>
  );
}