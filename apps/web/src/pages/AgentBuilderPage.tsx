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
} from "@mantine/core";
import { apiFetch } from "../apiClient";
import type {
  AgentBuilderMetaOut,
  AgentBaseOut,
  CustomAgentPublishedOut,
  CustomAgentPreviewOut,
  Run,
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

export default function AgentBuilderPage() {
  const { workspaceId } = useParams();
  const wid = workspaceId || "";
  const nav = useNavigate();

  const [err, setErr] = useState<string | null>(null);

  // meta
  const [meta, setMeta] = useState<AgentBuilderMetaOut | null>(null);
  const [metaLoading, setMetaLoading] = useState(false);

  // bases
  const [bases, setBases] = useState<AgentBaseOut[]>([]);
  const [basesLoading, setBasesLoading] = useState(false);
  const [baseId, setBaseId] = useState<string | null>(null);

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
      setErr(`Agent bases load failed: ${res.status} ${res.error}`);
      return;
    }

    setBases(res.data || []);
    if (!baseId && (res.data || []).length > 0) setBaseId(res.data[0].id);
    if ((res.data || []).length === 0) setBaseId(null);
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
      // Not fatal: show "no published"
      setPublished(null);
      return;
    }

    setPublished(res.data);
  }

  async function doPreview() {
    if (!wid || !baseId) return;

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
    await loadMeta();
    await loadBases();
  }

  useEffect(() => {
    if (!wid) return;
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid]);

  useEffect(() => {
    // whenever base changes, try load published
    if (!baseId) {
      setPublished(null);
      setPreview(null);
      return;
    }
    void loadPublished(baseId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseId]);

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
              <Badge variant="light">governance-aware</Badge>
            </Group>
            <Button variant="light" onClick={loadMeta} loading={metaLoading}>
              Refresh meta
            </Button>
          </Group>

          {!meta ? (
            <Text c="dimmed">{metaLoading ? "Loading…" : "No meta loaded."}</Text>
          ) : (
            <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{stableJsonStringify(meta)}</pre>
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
            <Button variant="light" onClick={loadBases} loading={basesLoading}>
              Refresh bases
            </Button>
          </Group>

          {bases.length === 0 ? (
            <Text c="dimmed">
              No agent bases in this workspace yet. Create one via API first (Commit 6 step is UI-only).
            </Text>
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
            <Text c="dimmed">No published version loaded (or it may not exist).</Text>
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

      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Group gap="sm">
              <Text fw={700}>Preview + Run</Text>
              <Badge variant="light">no side effects in preview</Badge>
            </Group>
            <Text size="sm" c="dimmed">
              Preview: <Code>POST /workspaces/:id/agent-bases/:baseId/preview</Code> · Run:{" "}
              <Code>POST /workspaces/:id/agent-bases/:baseId/runs</Code>
            </Text>
          </Group>

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
            description='If empty {}, published definition retrieval defaults are used. Example: {"enabled":true,"query":"...","k":6,"alpha":0.65,"source_types":["docs"],"timeframe":{"preset":"30d"},"min_score":0.15,"overfetch_k":3,"rerank":false}'
            autosize
            minRows={4}
            value={retrievalOverrideJson}
            onChange={(e) => setRetrievalOverrideJson(e.currentTarget.value)}
          />

          <Group>
            <Button onClick={doPreview} loading={previewLoading} disabled={!baseId}>
              Preview
            </Button>
            <Button onClick={doRun} loading={running} disabled={!baseId}>
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
                <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{stableJsonStringify(preview.retrieval_resolved)}</pre>

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