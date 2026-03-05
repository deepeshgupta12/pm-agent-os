import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Divider,
  Group,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
  Code,
} from "@mantine/core";
import { apiFetch } from "../apiClient";
import type {
  AgentBase,
  AgentBuilderMeta,
  CustomAgentPreviewIn,
  CustomAgentPreviewOut,
  CustomAgentPublished,
  Run,
} from "../types";

function safeJson(v: any): string {
  try {
    return JSON.stringify(v ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

function safeJsonParse(s: string): { ok: boolean; value: any; error?: string } {
  try {
    const v = s.trim() ? JSON.parse(s) : {};
    return { ok: true, value: v };
  } catch (e: any) {
    return { ok: false, value: null, error: e?.message || "Invalid JSON" };
  }
}

export default function AgentBuilderPage() {
  const { workspaceId } = useParams();
  const wid = workspaceId || "";
  const nav = useNavigate();

  const [err, setErr] = useState<string | null>(null);

  const [meta, setMeta] = useState<AgentBuilderMeta | null>(null);
  const [bases, setBases] = useState<AgentBase[]>([]);
  const [loadingMeta, setLoadingMeta] = useState(false);
  const [loadingBases, setLoadingBases] = useState(false);

  const [baseId, setBaseId] = useState<string | null>(null);
  const selectedBase = useMemo(() => bases.find((b) => b.id === baseId) || null, [bases, baseId]);

  const [published, setPublished] = useState<CustomAgentPublished | null>(null);
  const [loadingPublished, setLoadingPublished] = useState(false);

  // Preview
  const [previewInputJson, setPreviewInputJson] = useState<string>(
    JSON.stringify({ goal: "Write a PRD for X", context: "", constraints: "" }, null, 2)
  );
  const [retrievalOverrideJson, setRetrievalOverrideJson] = useState<string>("{}");
  const [previewOut, setPreviewOut] = useState<CustomAgentPreviewOut | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  // Run
  const [runLoading, setRunLoading] = useState(false);

  const baseOptions = useMemo(
    () =>
      bases.map((b) => ({
        value: b.id,
        label: `${b.name} (${b.key})`,
      })),
    [bases]
  );

  async function loadMeta() {
    if (!wid) return;
    setErr(null);
    setLoadingMeta(true);

    const res = await apiFetch<AgentBuilderMeta>(`/workspaces/${wid}/agent-builder/meta`, { method: "GET" });

    setLoadingMeta(false);

    if (!res.ok) {
      setMeta(null);
      setErr(`Agent Builder meta load failed: ${res.status} ${res.error}`);
      return;
    }

    setMeta(res.data);
  }

  async function loadBases() {
    if (!wid) return;
    setErr(null);
    setLoadingBases(true);

    const res = await apiFetch<AgentBase[]>(`/workspaces/${wid}/agent-bases`, { method: "GET" });

    setLoadingBases(false);

    if (!res.ok) {
      setBases([]);
      setErr(`Agent bases load failed: ${res.status} ${res.error}`);
      return;
    }

    setBases(res.data || []);
    if (!baseId && (res.data || []).length > 0) setBaseId(res.data[0].id);
  }

  async function loadPublished(bid: string) {
    if (!wid || !bid) return;
    setErr(null);
    setLoadingPublished(true);

    const res = await apiFetch<CustomAgentPublished>(`/workspaces/${wid}/agent-bases/${bid}/published`, {
      method: "GET",
    });

    setLoadingPublished(false);

    if (!res.ok) {
      setPublished(null);
      setErr(`Published version load failed: ${res.status} ${res.error}`);
      return;
    }

    setPublished(res.data);
  }

  async function loadAll() {
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
      setPreviewOut(null);
      return;
    }
    void loadPublished(baseId);
    setPreviewOut(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseId]);

  async function preview() {
    if (!wid || !baseId) return;

    setErr(null);
    setPreviewLoading(true);

    const ip = safeJsonParse(previewInputJson);
    if (!ip.ok) {
      setPreviewLoading(false);
      setErr(`Preview input JSON invalid: ${ip.error}`);
      return;
    }

    const ro = safeJsonParse(retrievalOverrideJson);
    if (!ro.ok) {
      setPreviewLoading(false);
      setErr(`Retrieval override JSON invalid: ${ro.error}`);
      return;
    }

    // retrieval override is optional; if empty object => send null
    const retrievalOverride = ro.value && Object.keys(ro.value || {}).length > 0 ? ro.value : null;

    const payload: CustomAgentPreviewIn = {
      input_payload: ip.value || {},
      retrieval: retrievalOverride,
    };

    const res = await apiFetch<CustomAgentPreviewOut>(`/workspaces/${wid}/agent-bases/${baseId}/preview`, {
      method: "POST",
      body: JSON.stringify(payload),
    });

    setPreviewLoading(false);

    if (!res.ok) {
      setPreviewOut(null);
      setErr(`Preview failed: ${res.status} ${res.error}`);
      return;
    }

    setPreviewOut(res.data);
  }

  async function runNow() {
    if (!wid || !baseId) return;

    setErr(null);
    setRunLoading(true);

    const ip = safeJsonParse(previewInputJson);
    if (!ip.ok) {
      setRunLoading(false);
      setErr(`Run input JSON invalid: ${ip.error}`);
      return;
    }

    const ro = safeJsonParse(retrievalOverrideJson);
    if (!ro.ok) {
      setRunLoading(false);
      setErr(`Retrieval override JSON invalid: ${ro.error}`);
      return;
    }
    const retrievalOverride = ro.value && Object.keys(ro.value || {}).length > 0 ? ro.value : null;

    const payload = {
      input_payload: ip.value || {},
      retrieval: retrievalOverride,
    };

    const res = await apiFetch<Run>(`/workspaces/${wid}/agent-bases/${baseId}/runs`, {
      method: "POST",
      body: JSON.stringify(payload),
    });

    setRunLoading(false);

    if (!res.ok) {
      setErr(`Run failed: ${res.status} ${res.error}`);
      return;
    }

    nav(`/runs/${res.data.id}`);
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Agent Builder</Title>
        <Group>
          <Button component={Link} to={`/workspaces/${wid}`} variant="light">
            Back to Workspace
          </Button>
          <Button variant="light" onClick={loadAll} loading={loadingMeta || loadingBases}>
            Refresh
          </Button>
        </Group>
      </Group>

      {err ? (
        <Card withBorder>
          <Text c="red">{err}</Text>
        </Card>
      ) : null}

      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Group gap="sm">
              <Text fw={700}>Builder Meta</Text>
              <Badge variant="light">from API</Badge>
            </Group>
            <Button variant="light" onClick={loadMeta} loading={loadingMeta}>
              Refresh meta
            </Button>
          </Group>

          {meta ? (
            <Stack gap={4}>
              <Text size="sm">
                allowed_source_types: <Code>{(meta.allowed_source_types || []).join(", ") || "(none)"}</Code>
              </Text>
              <Text size="sm">
                timeframe_presets: <Code>{(meta.timeframe_presets || []).join(", ") || "(none)"}</Code>
              </Text>
              <Text size="sm">
                artifact_types: <Code>{(meta.artifact_types || []).join(", ") || "(none)"}</Code>
              </Text>
              <Textarea label="retrieval_knobs (json)" autosize minRows={6} value={safeJson(meta.retrieval_knobs)} readOnly />
            </Stack>
          ) : (
            <Text size="sm" c="dimmed">
              Meta not loaded yet.
            </Text>
          )}
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Group gap="sm">
              <Text fw={700}>Agent Bases</Text>
              <Badge variant="light">{bases.length} items</Badge>
            </Group>
            <Button variant="light" onClick={loadBases} loading={loadingBases}>
              Refresh bases
            </Button>
          </Group>

          <Select
            label="Select agent base"
            data={baseOptions}
            value={baseId}
            onChange={setBaseId}
            searchable
            nothingFoundMessage="No agent bases"
          />

          {selectedBase ? (
            <Card withBorder>
              <Stack gap={4}>
                <Group gap="sm">
                  <Badge variant="light">{selectedBase.key}</Badge>
                  <Text fw={700}>{selectedBase.name}</Text>
                </Group>
                <Text size="sm" c="dimmed">
                  {selectedBase.description || "(no description)"}
                </Text>
                <Text size="xs" c="dimmed">
                  id={selectedBase.id}
                </Text>
              </Stack>
            </Card>
          ) : (
            <Text size="sm" c="dimmed">
              Pick a base to continue.
            </Text>
          )}
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Group gap="sm">
              <Text fw={700}>Published Definition</Text>
              <Badge variant="light">latest published</Badge>
            </Group>
            <Button
              variant="light"
              onClick={() => baseId && loadPublished(baseId)}
              loading={loadingPublished}
              disabled={!baseId}
            >
              Refresh published
            </Button>
          </Group>

          {published ? (
            <Stack gap="xs">
              <Text size="sm">
                version: <Code>{published.published_version}</Code> · version_id:{" "}
                <Code>{published.published_version_id}</Code>
              </Text>
              <Textarea
                label="definition_json"
                autosize
                minRows={10}
                value={safeJson(published.definition_json)}
                readOnly
              />
            </Stack>
          ) : (
            <Text size="sm" c="dimmed">
              No published version loaded (or it may not exist).
            </Text>
          )}
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Text fw={700}>Preview + Run</Text>
          <Text size="sm" c="dimmed">
            Preview calls <Code>POST /workspaces/:id/agent-bases/:baseId/preview</Code>. Run calls{" "}
            <Code>POST /workspaces/:id/agent-bases/:baseId/runs</Code>.
          </Text>

          <Divider />

          <Textarea
            label="input_payload (JSON)"
            autosize
            minRows={8}
            value={previewInputJson}
            onChange={(e) => setPreviewInputJson(e.currentTarget.value)}
          />

          <Textarea
            label="retrieval override (JSON, optional)"
            description='If empty {}, the published definition retrieval defaults are used. Example: {"enabled":true,"query":"...","k":6,"alpha":0.65,"source_types":["docs"],"timeframe":{"preset":"30d"},"min_score":0.15,"overfetch_k":3,"rerank":false}'
            autosize
            minRows={6}
            value={retrievalOverrideJson}
            onChange={(e) => setRetrievalOverrideJson(e.currentTarget.value)}
          />

          <Group>
            <Button onClick={preview} loading={previewLoading} disabled={!baseId}>
              Preview prompts
            </Button>
            <Button onClick={runNow} loading={runLoading} disabled={!baseId}>
              Run custom agent
            </Button>
          </Group>

          {previewOut ? (
            <Card withBorder>
              <Stack gap="sm">
                <Group gap="sm">
                  <Badge variant="light">artifact_type: {previewOut.artifact_type}</Badge>
                  <Badge variant="light" color={previewOut.llm_enabled ? "green" : "gray"}>
                    llm_enabled: {String(previewOut.llm_enabled)}
                  </Badge>
                  <Badge variant="light">published_version: {previewOut.published_version}</Badge>
                </Group>

                {previewOut.notes?.length ? (
                  <Card withBorder>
                    <Text fw={600}>Notes</Text>
                    <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{previewOut.notes.join("\n")}</pre>
                  </Card>
                ) : null}

                <Textarea label="system_prompt" autosize minRows={6} value={previewOut.system_prompt || ""} readOnly />
                <Textarea label="user_prompt" autosize minRows={12} value={previewOut.user_prompt || ""} readOnly />

                <Textarea
                  label="retrieval_resolved (json)"
                  autosize
                  minRows={6}
                  value={safeJson(previewOut.retrieval_resolved)}
                  readOnly
                />
              </Stack>
            </Card>
          ) : (
            <Text size="sm" c="dimmed">
              Run preview to see prompts.
            </Text>
          )}
        </Stack>
      </Card>
    </Stack>
  );
}