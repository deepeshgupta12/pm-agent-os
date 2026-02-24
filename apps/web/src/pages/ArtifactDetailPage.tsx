import { useEffect, useState } from "react";
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
} from "@mantine/core";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { apiFetch } from "../apiClient";
import type { Artifact } from "../types";

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

  async function load() {
    setErr(null);
    const res = await apiFetch<Artifact>(`/artifacts/${aid}`, { method: "GET" });
    if (!res.ok) {
      setErr(`Load failed: ${res.status} ${res.error}`);
      return;
    }
    setArt(res.data);
    setTitle(res.data.title);
    setContentMd(res.data.content_md);
    setStatus(res.data.status);
  }

  async function saveInPlace() {
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
    if (!art) return;
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

    // update URL to new artifact id
    window.history.replaceState({}, "", `/artifacts/${res.data.id}`);
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
              <Text fw={700}>
                {art.type} · v{art.version} · {art.logical_key}
              </Text>
              <Text size="xs" c="dimmed">
                {art.id}
              </Text>
            </Group>

            <Group grow>
              <TextInput label="Title" value={title} onChange={(e) => setTitle(e.currentTarget.value)} />
              <TextInput label="Status" value={status} onChange={(e) => setStatus(e.currentTarget.value)} />
            </Group>

            <Group>
              <Button onClick={saveInPlace} loading={saving}>
                Save (same version)
              </Button>
              <Button variant="light" onClick={saveNewVersion} loading={newVerLoading}>
                Save as new version
              </Button>
              <Button variant="default" onClick={copyMarkdown}>
                Copy Markdown
              </Button>
              {copyMsg ? <Text size="sm" c="dimmed">{copyMsg}</Text> : null}
            </Group>

            <Divider />

            <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
              <div>
                <Textarea
                  label="Content (Markdown)"
                  autosize
                  minRows={18}
                  value={contentMd}
                  onChange={(e) => setContentMd(e.currentTarget.value)}
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
          </Stack>
        </Card>
      ) : (
        <Text c="dimmed">Loading artifact…</Text>
      )}
    </Stack>
  );
}