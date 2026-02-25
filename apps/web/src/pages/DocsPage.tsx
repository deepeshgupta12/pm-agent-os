import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Divider,
  Group,
  NumberInput,
  Stack,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import { apiFetch } from "../apiClient";

type WorkspaceRole = {
  workspace_id: string;
  role: "admin" | "member" | "viewer";
};

type SourceOut = {
  id: string;
  workspace_id: string;
  type: string; // "docs"
  name: string;
  config: Record<string, unknown>;
};

type IngestDocIn = {
  title: string;
  text: string;
  external_id?: string | null;
};

type IngestResult = {
  document: {
    id: string;
    workspace_id: string;
    source_id: string;
    title: string;
    external_id?: string | null;
    meta: Record<string, unknown>;
  };
  chunks_created: number;
};

type RetrieveItem = {
  chunk_id: string;
  document_id: string;
  source_id: string;
  document_title: string;
  chunk_index: number;
  snippet: string;
  meta: Record<string, unknown>;
  score_fts: number;
  score_vec: number;
  score_hybrid: number;
};

type RetrieveResponse = {
  ok: boolean;
  q: string;
  k: number;
  alpha: number;
  items: RetrieveItem[];
};

export default function DocsPage() {
  const { workspaceId } = useParams();
  const wid = workspaceId || "";

  const [err, setErr] = useState<string | null>(null);

  // Role
  const [myRole, setMyRole] = useState<WorkspaceRole | null>(null);
  const canWrite = (myRole?.role || "").toLowerCase() !== "viewer";

  // Create docs source
  const [sourceName, setSourceName] = useState("Team Docs");
  const [creatingSource, setCreatingSource] = useState(false);
  const [docsSource, setDocsSource] = useState<SourceOut | null>(null);

  // Ingest doc
  const [docTitle, setDocTitle] = useState("PRD Notes");
  const [docExternalId, setDocExternalId] = useState("doc-123");
  const [docText, setDocText] = useState("This is a docs ingestion test.\nWe need retrieval later.");
  const [ingesting, setIngesting] = useState(false);
  const [lastIngest, setLastIngest] = useState<IngestResult | null>(null);

  // Retrieve
  const [query, setQuery] = useState("retrieval later");
  const [k, setK] = useState<number>(5);
  const [alpha, setAlpha] = useState<number>(0.65);
  const [onlyDocs, setOnlyDocs] = useState(true);
  const [searching, setSearching] = useState(false);
  const [results, setResults] = useState<RetrieveResponse | null>(null);

  const canIngest = useMemo(() => {
    // UI requirement: force explicit docs source creation before ingest (makes “source shell” visible + named).
    return Boolean(docsSource?.id) && canWrite;
  }, [docsSource, canWrite]);

  async function loadMyRole() {
    if (!wid) return;
    const res = await apiFetch<WorkspaceRole>(`/workspaces/${wid}/my-role`, { method: "GET" });
    if (!res.ok) {
      // If role fetch fails, treat as no-write to avoid exposing write actions.
      setMyRole(null);
      setErr(`Role load failed: ${res.status} ${res.error}`);
      return;
    }
    setMyRole(res.data);
  }

  async function createDocsSource() {
    if (!wid) return;
    if (!canWrite) {
      setErr("You are a viewer. Docs source creation is disabled.");
      return;
    }

    setErr(null);
    setCreatingSource(true);

    const res = await apiFetch<SourceOut>(`/workspaces/${wid}/sources/docs`, {
      method: "POST",
      body: JSON.stringify({ name: sourceName.trim() || "Team Docs" }),
    });

    setCreatingSource(false);

    if (!res.ok) {
      setErr(`Create docs source failed: ${res.status} ${res.error}`);
      return;
    }

    setDocsSource(res.data);
  }

  async function ingestDoc() {
    if (!wid) return;
    if (!canWrite) {
      setErr("You are a viewer. Docs ingestion is disabled.");
      return;
    }
    if (!docsSource?.id) {
      setErr("Create a Docs source first.");
      return;
    }

    setErr(null);
    setIngesting(true);

    const payload: IngestDocIn = {
      title: docTitle.trim() || "Untitled",
      text: docText,
      external_id: docExternalId.trim() ? docExternalId.trim() : null,
    };

    const res = await apiFetch<IngestResult>(`/workspaces/${wid}/documents/docs`, {
      method: "POST",
      body: JSON.stringify(payload),
    });

    setIngesting(false);

    if (!res.ok) {
      setErr(`Docs ingest failed: ${res.status} ${res.error}`);
      return;
    }

    setLastIngest(res.data);
  }

  async function retrieve() {
    if (!wid) return;
    if (!query.trim()) {
      setErr("Enter a query.");
      return;
    }

    setErr(null);
    setSearching(true);

    const params = new URLSearchParams();
    params.set("q", query.trim());
    params.set("k", String(k || 5));
    params.set("alpha", String(alpha ?? 0.65));
    if (onlyDocs) params.set("source_types", "docs");

    const res = await apiFetch<RetrieveResponse>(`/workspaces/${wid}/retrieve?${params.toString()}`, {
      method: "GET",
    });

    setSearching(false);

    if (!res.ok) {
      setErr(`Retrieve failed: ${res.status} ${res.error}`);
      setResults(null);
      return;
    }

    setResults(res.data);
  }

  useEffect(() => {
    setErr(null);
    setDocsSource(null);
    setLastIngest(null);
    setResults(null);
    setMyRole(null);

    if (!wid) return;
    void loadMyRole();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid]);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Docs</Title>
        <Group>
          <Button component={Link} to={`/workspaces/${wid}`} variant="light">
            Back to Workspace
          </Button>
          <Button component={Link} to={`/run-builder/${wid}`} variant="default">
            Run Builder
          </Button>
        </Group>
      </Group>

      {!wid ? (
        <Card withBorder>
          <Text c="red">Missing workspaceId in route.</Text>
        </Card>
      ) : null}

      {myRole ? (
        <Card withBorder>
          <Group justify="space-between">
            <Text fw={700}>Workspace role</Text>
            <Badge variant="light">{myRole.role}</Badge>
          </Group>
          <Text size="sm" c="dimmed">
            Viewer can retrieve/search. Member/Admin can create sources + ingest docs.
          </Text>
        </Card>
      ) : null}

      {err ? (
        <Card withBorder>
          <Text c="red">{err}</Text>
        </Card>
      ) : null}

      <Card withBorder>
        <Stack gap="sm">
          <Text fw={700}>1) Create Docs Source</Text>
          <Text size="sm" c="dimmed">
            V0 “Docs integration” = a docs source shell + ability to ingest text into retrieval store.
          </Text>

          <Group align="end">
            <TextInput
              label="Source name"
              value={sourceName}
              onChange={(e) => setSourceName(e.currentTarget.value)}
              placeholder="e.g., Team Docs"
              style={{ flex: 1 }}
              disabled={!canWrite}
            />
            <Button onClick={createDocsSource} loading={creatingSource} disabled={!wid || !canWrite}>
              Create source
            </Button>
          </Group>

          {!canWrite ? (
            <Text size="sm" c="dimmed">
              You are a viewer — source creation is disabled.
            </Text>
          ) : null}

          {docsSource ? (
            <Group gap="sm">
              <Badge variant="light">type: {docsSource.type}</Badge>
              <Badge variant="light">source_id: {docsSource.id}</Badge>
              <Text size="sm" c="dimmed">
                {docsSource.name}
              </Text>
            </Group>
          ) : (
            <Text size="sm" c="dimmed">
              No docs source created yet.
            </Text>
          )}
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Text fw={700}>2) Ingest a Doc (text)</Text>
          <Text size="sm" c="dimmed">
            This creates a Document + chunks. (Embeddings are optional; hybrid currently works with FTS even if vec=0.)
          </Text>

          <Group grow>
            <TextInput
              label="Title"
              value={docTitle}
              onChange={(e) => setDocTitle(e.currentTarget.value)}
              disabled={!canWrite}
            />
            <TextInput
              label="External ID (optional)"
              value={docExternalId}
              onChange={(e) => setDocExternalId(e.currentTarget.value)}
              placeholder="doc-123"
              disabled={!canWrite}
            />
          </Group>

          <Textarea
            label="Doc text"
            autosize
            minRows={6}
            value={docText}
            onChange={(e) => setDocText(e.currentTarget.value)}
            disabled={!canWrite}
          />

          <Button onClick={ingestDoc} loading={ingesting} disabled={!canIngest}>
            Ingest doc
          </Button>

          {!canWrite ? (
            <Text size="sm" c="dimmed">
              You are a viewer — ingestion is disabled.
            </Text>
          ) : !docsSource?.id ? (
            <Text size="sm" c="dimmed">
              Create a Docs source first to enable ingestion.
            </Text>
          ) : null}

          {lastIngest ? (
            <Card withBorder>
              <Stack gap={6}>
                <Text fw={600}>Ingest result</Text>
                <Text size="sm">document_id: {lastIngest.document.id}</Text>
                <Text size="sm">source_id: {lastIngest.document.source_id}</Text>
                <Text size="sm">chunks_created: {lastIngest.chunks_created}</Text>
                <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>
                  {JSON.stringify(lastIngest.document.meta, null, 2)}
                </pre>
              </Stack>
            </Card>
          ) : null}
        </Stack>
      </Card>

      <Card withBorder>
        <Stack gap="sm">
          <Text fw={700}>3) Retrieve (viewer+)</Text>
          <Text size="sm" c="dimmed">
            This tests that docs ingestion is searchable. Toggle “Docs only” to pass source_types=docs.
          </Text>

          <Divider />

          <TextInput
            label="Query"
            value={query}
            onChange={(e) => setQuery(e.currentTarget.value)}
            placeholder='e.g., "retrieval later"'
          />

          <Group grow>
            <NumberInput label="Top K" value={k} min={1} max={50} onChange={(v) => setK(Number(v) || 5)} />
            <NumberInput
              label="Alpha (vector weight)"
              value={alpha}
              min={0}
              max={1}
              step={0.05}
              onChange={(v) => setAlpha(Number(v) || 0.65)}
            />
          </Group>

          <Group>
            <Button variant={onlyDocs ? "filled" : "light"} onClick={() => setOnlyDocs((x) => !x)}>
              {onlyDocs ? "Docs only: ON" : "Docs only: OFF"}
            </Button>

            <Button onClick={retrieve} loading={searching}>
              Search
            </Button>
          </Group>

          {results ? (
            <Card withBorder>
              <Stack gap="xs">
                <Group justify="space-between">
                  <Text fw={600}>Results</Text>
                  <Badge variant="light">items: {results.items?.length ?? 0}</Badge>
                </Group>

                {(results.items || []).length === 0 ? (
                  <Text size="sm" c="dimmed">
                    No matches.
                  </Text>
                ) : (
                  <Stack gap="xs">
                    {results.items.map((it) => (
                      <Card key={it.chunk_id} withBorder>
                        <Stack gap={4}>
                          <Group gap="sm">
                            <Badge variant="light">score: {it.score_hybrid.toFixed(3)}</Badge>
                            <Text fw={600}>{it.document_title}</Text>
                          </Group>
                          <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
                            {it.snippet}
                          </Text>
                          <Text size="xs" c="dimmed">
                            doc={it.document_id} · chunk={it.chunk_id} · source={it.source_id}
                          </Text>
                        </Stack>
                      </Card>
                    ))}
                  </Stack>
                )}
              </Stack>
            </Card>
          ) : (
            <Text size="sm" c="dimmed">
              Run a search to see results.
            </Text>
          )}
        </Stack>
      </Card>
    </Stack>
  );
}