import { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  Button,
  Card,
  Group,
  Stack,
  Text,
  TextInput,
  Textarea,
  Title,
  SimpleGrid,
  Divider,
  Badge,
  Select,
} from "@mantine/core";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { apiFetch } from "../apiClient";
import type { Artifact, ArtifactDiff } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL as string;

export default function ArtifactDetailPage() {
  const { artifactId } = useParams();
  const aid = artifactId || "";

  const [art, setArt] = useState<Artifact | null>(null);
  const [title, setTitle] = useState("");
  const [contentMd, setContentMd] = useState("");
  const [status, setStatus] = useState("draft");

  const [err, setErr] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [newVerLoading, setNewVerLoading] = useState(false);
  const [copyMsg, setCopyMsg] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [unpublishing, setUnpublishing] = useState(false);

  // Diff (V0 basic)
  const [siblings, setSiblings] = useState<Artifact[]>([]);
  const [otherId, setOtherId] = useState<string | null>(null);
  const [diffText, setDiffText] = useState<string>("");
  const [diffLoading, setDiffLoading] = useState(false);

  const isFinal = status === "final";

  const diffOptions = useMemo(() => {
    return siblings.map((a) => ({
      value: a.id,
      label: `v${a.version} · ${a.title} (${a.status})`,
    }));
  }, [siblings]);

  async function load() {
    setErr(null);
    setDiffText("");

    const res = await apiFetch<Artifact>(`/artifacts/${aid}`, { method: "GET" });
    if (!res.ok) {
      setErr(`Load failed: ${res.status} ${res.error}`);
      return;
    }

    const loaded = res.data;
    setArt(loaded);
    setTitle(loaded.title);
    setContentMd(loaded.content_md);
    setStatus(loaded.status);

    // Load artifacts for same run, then filter to same logical_key (versions)
    const sibRes = await apiFetch<Artifact[]>(`/runs/${loaded.run_id}/artifacts`, { method: "GET" });
    if (!sibRes.ok) {
      // Not fatal; artifact can still render
      setSiblings([]);
      setOtherId(null);
      return;
    }

    const sameKey = (sibRes.data || [])
      .filter((x) => x.logical_key === loaded.logical_key)
      .filter((x) => x.id !== loaded.id)
      .sort((a, b) => (b.version ?? 0) - (a.version ?? 0)); // higher version first

    setSiblings(sameKey);
    setOtherId(sameKey.length > 0 ? sameKey[0].id : null);
  }

  async function saveInPlace() {
    if (isFinal) return;
    setSaving(true);
    setErr(null);

    const res = await apiFetch<Artifact>(`/artifacts/${aid}`, {
      method: "PUT",
      body: JSON.stringify({ title, content_md: contentMd, status }),
    });

    setSaving(false);

    if (!res.ok) {
      setErr(`Save failed: ${res.status} ${res.error}`);
      return;
    }
    setArt(res.data);
  }

  async function saveNewVersion() {
    if (!art || isFinal) return;
    setNewVerLoading(true);
    setErr(null);

    const res = await apiFetch<Artifact>(`/artifacts/${aid}/versions`, {
      method: "POST",
      body: JSON.stringify({ title, content_md: contentMd, status }),
    });

    setNewVerLoading(false);

    if (!res.ok) {
      setErr(`New version failed: ${res.status} ${res.error}`);
      return;
    }

    setArt(res.data);
    setTitle(res.data.title);
    setContentMd(res.data.content_md);
    setStatus(res.data.status);

    window.history.replaceState({}, "", `/artifacts/${res.data.id}`);
  }

  async function publish() {
    setPublishing(true);
    setErr(null);

    const res = await apiFetch<Artifact>(`/artifacts/${aid}/publish`, {
      method: "POST",
      body: JSON.stringify({}),
    });

    setPublishing(false);

    if (!res.ok) {
      setErr(`Publish failed: ${res.status} ${res.error}`);
      return;
    }

    setArt(res.data);
    setTitle(res.data.title);
    setContentMd(res.data.content_md);
    setStatus(res.data.status);
  }

  async function unpublish() {
    setUnpublishing(true);
    setErr(null);

    const res = await apiFetch<Artifact>(`/artifacts/${aid}/unpublish`, {
      method: "POST",
      body: JSON.stringify({}),
    });

    setUnpublishing(false);

    if (!res.ok) {
      setErr(`Unpublish failed: ${res.status} ${res.error}`);
      return;
    }

    setArt(res.data);
    setTitle(res.data.title);
    setContentMd(res.data.content_md);
    setStatus(res.data.status);
  }

  async function copyMarkdown() {
    try {
      await navigator.clipboard.writeText(contentMd);
      setCopyMsg("Copied!");
      setTimeout(() => setCopyMsg(null), 1200);
    } catch {
      setCopyMsg("Copy failed");
      setTimeout(() => setCopyMsg(null), 1200);
    }
  }

  function exportPdf() {
    window.open(`${API_BASE}/artifacts/${aid}/export/pdf`, "_blank");
  }

  async function loadDiff() {
    if (!otherId) return;
    setDiffLoading(true);
    setErr(null);

    const res = await apiFetch<ArtifactDiff>(`/artifacts/${aid}/diff?other_id=${otherId}`, { method: "GET" });

    setDiffLoading(false);

    if (!res.ok) {
      setErr(`Diff failed: ${res.status} ${res.error}`);
      setDiffText("");
      return;
    }

    setDiffText(res.data.unified_diff || "(no diff)");
  }

  useEffect(() => {
    if (!aid) return;
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aid]);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Artifact</Title>
        <Button component={Link} to="/workspaces" variant="light">
          Back
        </Button>
      </Group>

      {err && (
        <Card withBorder>
          <Text c="red">{err}</Text>
        </Card>
      )}

      {art ? (
        <Card withBorder>
          <Stack gap="sm">
            <Group justify="space-between">
              <Group gap="sm">
                <Text fw={700}>
                  {art.type} · v{art.version} · {art.logical_key}
                </Text>
                <Badge>{status}</Badge>
                {isFinal ? <Badge color="green">locked</Badge> : null}
              </Group>
              <Text size="xs" c="dimmed">
                {art.id}
              </Text>
            </Group>

            <Group grow>
              <TextInput
                label="Title"
                value={title}
                onChange={(e) => setTitle(e.currentTarget.value)}
                disabled={isFinal}
              />
              <TextInput label="Status" value={status} onChange={(e) => setStatus(e.currentTarget.value)} disabled />
            </Group>

            <Group>
              <Button onClick={saveInPlace} loading={saving} disabled={isFinal}>
                Save (same version)
              </Button>
              <Button variant="light" onClick={saveNewVersion} loading={newVerLoading} disabled={isFinal}>
                Save as new version
              </Button>
              <Button variant="default" onClick={copyMarkdown}>
                Copy Markdown
              </Button>
              <Button variant="default" onClick={exportPdf}>
                Export PDF
              </Button>

              {!isFinal ? (
                <Button color="green" onClick={publish} loading={publishing}>
                  Publish (final)
                </Button>
              ) : (
                <Button color="yellow" onClick={unpublish} loading={unpublishing}>
                  Unpublish (back to draft)
                </Button>
              )}

              {copyMsg ? (
                <Text size="sm" c="dimmed">
                  {copyMsg}
                </Text>
              ) : null}
            </Group>

            <Divider />

            {/* V0: Basic Diff */}
            <Card withBorder>
              <Stack gap="sm">
                <Group justify="space-between" align="flex-end">
                  <Select
                    label="Compare with another version (same logical key)"
                    data={diffOptions}
                    value={otherId}
                    onChange={setOtherId}
                    placeholder={siblings.length === 0 ? "No other versions available" : "Pick a version"}
                    searchable
                    nothingFoundMessage="No versions"
                    disabled={siblings.length === 0}
                    style={{ flex: 1 }}
                  />
                  <Button onClick={loadDiff} loading={diffLoading} disabled={!otherId}>
                    Show Diff
                  </Button>
                </Group>

                {diffText ? (
                  <Card withBorder style={{ overflow: "auto" }}>
                    <Text fw={600} mb={6}>
                      Unified Diff
                    </Text>
                    <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{diffText}</pre>
                  </Card>
                ) : (
                  <Text size="sm" c="dimmed">
                    {siblings.length === 0
                      ? "Create another version to enable diff."
                      : "Pick a version and click “Show Diff”."}
                  </Text>
                )}
              </Stack>
            </Card>

            <Divider />

            <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
              <div>
                <Textarea
                  label="Content (Markdown)"
                  autosize
                  minRows={18}
                  value={contentMd}
                  onChange={(e) => setContentMd(e.currentTarget.value)}
                  disabled={isFinal}
                />
              </div>

              <div>
                <Text fw={600} mb={6}>
                  Preview
                </Text>
                <Card withBorder style={{ height: "100%", overflow: "auto" }}>
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{contentMd}</ReactMarkdown>
                </Card>
              </div>
            </SimpleGrid>

            {isFinal ? (
              <Text size="sm" c="dimmed">
                This artifact is published (final) and locked. Unpublish to edit.
              </Text>
            ) : null}
          </Stack>
        </Card>
      ) : (
        <Text c="dimmed">Loading artifact…</Text>
      )}
    </Stack>
  );
}