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
} from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { Artifact, Evidence, Run } from "../types";

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

export default function RunDetailPage() {
  const { runId } = useParams();
  const rid = runId || "";

  const [run, setRun] = useState<Run | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [err, setErr] = useState<string | null>(null);

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

  const artifactTypeOptions = useMemo(
    () => ARTIFACT_TYPES.map((t) => ({ value: t, label: t })),
    []
  );

  const autoArtifact = useMemo(() => {
    if (artifacts.length === 0) return null;
    // heuristic: newest is first (we fetch desc), use first
    return artifacts[0];
  }, [artifacts]);

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

  useEffect(() => {
    if (!rid) return;
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rid]);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Run</Title>
        <Button component={Link} to="/workspaces" variant="light">
          Back to Workspaces
        </Button>
      </Group>

      {run ? (
        <Card withBorder>
          <Stack gap="xs">
            <Group justify="space-between">
              <Group gap="sm">
                <Badge>{run.status}</Badge>
                <Text fw={700}>{run.agent_id}</Text>
              </Group>
              <Text size="xs" c="dimmed">
                {run.id}
              </Text>
            </Group>

            {run.output_summary ? <Text c="dimmed">{run.output_summary}</Text> : null}

            <Card withBorder>
              <Text fw={600} mb={6}>
                Input payload
              </Text>
              <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                {JSON.stringify(run.input_payload, null, 2)}
              </pre>
            </Card>

            {autoArtifact ? (
              <Group>
                <Button component={Link} to={`/artifacts/${autoArtifact.id}`}>
                  Open latest artifact
                </Button>
              </Group>
            ) : null}
          </Stack>
        </Card>
      ) : (
        <Text c="dimmed">Loading run…</Text>
      )}

      {err && (
        <Card withBorder>
          <Text c="red">{err}</Text>
        </Card>
      )}

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

      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={700}>Artifacts</Text>
            <Button variant="light" onClick={loadAll}>
              Refresh
            </Button>
          </Group>

          {artifacts.length === 0 ? (
            <Text c="dimmed">No artifacts yet.</Text>
          ) : (
            <Stack gap="xs">
              {artifacts.map((a) => (
                <Card key={a.id} withBorder>
                  <Group justify="space-between" align="flex-start">
                    <Stack gap={2}>
                      <Group gap="sm">
                        <Badge variant="light">{a.type}</Badge>
                        <Badge>{a.status}</Badge>
                        <Text fw={600}>
                          v{a.version} · {a.title}
                        </Text>
                      </Group>
                      <Text size="xs" c="dimmed">
                        {a.id} · key={a.logical_key}
                      </Text>
                    </Stack>
                    <Button component={Link} to={`/artifacts/${a.id}`}>
                      Open
                    </Button>
                  </Group>
                </Card>
              ))}
            </Stack>
          )}
        </Stack>
      </Card>

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
            <TextInput label="Source name" value={sourceName} onChange={(e) => setSourceName(e.currentTarget.value)} />
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

      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={700}>Evidence</Text>
            <Button variant="light" onClick={loadAll}>
              Refresh
            </Button>
          </Group>

          {evidence.length === 0 ? (
            <Text c="dimmed">No evidence yet.</Text>
          ) : (
            <Stack gap="xs">
              {evidence.map((e) => (
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
        </Stack>
      </Card>
    </Stack>
  );
}