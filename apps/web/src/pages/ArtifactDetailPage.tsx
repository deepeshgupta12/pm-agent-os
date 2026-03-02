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
import type { Artifact, ArtifactDiff, ArtifactReview, Run, WorkspaceRole } from "../types";

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

  // Role (derived)
  const [myRole, setMyRole] = useState<WorkspaceRole | null>(null);

  // Approvals
  const [reviews, setReviews] = useState<ArtifactReview[]>([]);
  const [submitComment, setSubmitComment] = useState("");
  const [decisionComment, setDecisionComment] = useState("");
  const [submitLoading, setSubmitLoading] = useState(false);
  const [approveLoading, setApproveLoading] = useState(false);
  const [rejectLoading, setRejectLoading] = useState(false);

  // Diff (V0 basic)
  const [siblings, setSiblings] = useState<Artifact[]>([]);
  const [otherId, setOtherId] = useState<string | null>(null);
  const [diffText, setDiffText] = useState<string>("");
  const [diffLoading, setDiffLoading] = useState(false);

  const isFinal = status === "final";
  const isInReview = status === "in_review";
  const role = (myRole?.role || "").toLowerCase();
  const canWrite = role === "admin" || role === "member";
  const isAdmin = role === "admin";
  const isViewer = role === "viewer";

  const latestReview = useMemo(() => (reviews.length > 0 ? reviews[0] : null), [reviews]);
  const latestReviewState = (latestReview?.state || "").toLowerCase();

  const diffOptions = useMemo(() => {
    return siblings.map((a) => ({
      value: a.id,
      label: `v${a.version} · ${a.title} (${a.status})`,
    }));
  }, [siblings]);

  async function loadRoleForArtifact(loaded: Artifact) {
    // fetch run → workspace_id → my-role
    const runRes = await apiFetch<Run>(`/runs/${loaded.run_id}`, { method: "GET" });
    if (!runRes.ok) return;

    const wid = runRes.data.workspace_id;
    const roleRes = await apiFetch<WorkspaceRole>(`/workspaces/${wid}/my-role`, { method: "GET" });
    if (!roleRes.ok) return;

    setMyRole(roleRes.data);
  }

  async function loadReviews() {
    const rr = await apiFetch<ArtifactReview[]>(`/artifacts/${aid}/reviews`, { method: "GET" });
    if (!rr.ok) {
      setReviews([]);
      return;
    }
    setReviews(rr.data || []);
  }

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

    await loadRoleForArtifact(loaded);
    await loadReviews();

    // Load artifacts for same run, then filter to same logical_key (versions)
    const sibRes = await apiFetch<Artifact[]>(`/runs/${loaded.run_id}/artifacts`, { method: "GET" });
    if (!sibRes.ok) {
      setSiblings([]);
      setOtherId(null);
      return;
    }

    const sameKey = (sibRes.data || [])
      .filter((x) => x.logical_key === loaded.logical_key)
      .filter((x) => x.id !== loaded.id)
      .sort((a, b) => (b.version ?? 0) - (a.version ?? 0));

    setSiblings(sameKey);
    setOtherId(sameKey.length > 0 ? sameKey[0].id : null);
  }

  async function saveInPlace() {
    if (isFinal || isInReview || !canWrite) return;

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
    setTitle(res.data.title);
    setContentMd(res.data.content_md);
    setStatus(res.data.status);
  }

  async function saveNewVersion() {
    if (!art || isFinal || isInReview || !canWrite) return;

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
    await loadReviews(); // new artifact id => different review list
  }

  async function submitForReview() {
    if (!canWrite || isFinal || isInReview) return;
    setSubmitLoading(true);
    setErr(null);

    const res = await apiFetch<ArtifactReview>(`/artifacts/${aid}/submit-review`, {
      method: "POST",
      body: JSON.stringify({ comment: submitComment.trim() || null }),
    });

    setSubmitLoading(false);

    if (!res.ok) {
      setErr(`Submit for review failed: ${res.status} ${res.error}`);
      return;
    }

    setSubmitComment("");
    await load();
  }

  async function approve() {
    if (!isAdmin || !isInReview) return;
    setApproveLoading(true);
    setErr(null);

    const res = await apiFetch<ArtifactReview>(`/artifacts/${aid}/approve`, {
      method: "POST",
      body: JSON.stringify({ comment: decisionComment.trim() || null }),
    });

    setApproveLoading(false);

    if (!res.ok) {
      setErr(`Approve failed: ${res.status} ${res.error}`);
      return;
    }

    setDecisionComment("");
    await loadReviews();
  }

  async function reject() {
    if (!isAdmin || !isInReview) return;
    setRejectLoading(true);
    setErr(null);

    const res = await apiFetch<ArtifactReview>(`/artifacts/${aid}/reject`, {
      method: "POST",
      body: JSON.stringify({ comment: decisionComment.trim() || null }),
    });

    setRejectLoading(false);

    if (!res.ok) {
      setErr(`Reject failed: ${res.status} ${res.error}`);
      return;
    }

    setDecisionComment("");
    await load(); // artifact status becomes draft
  }

  async function publish() {
    if (!canWrite) return;

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
    await loadReviews();
  }

  async function unpublish() {
    if (!canWrite) return;

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
    await loadReviews();
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

  function exportDocx() {
    window.open(`${API_BASE}/artifacts/${aid}/export/docx`, "_blank");
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

  const publishDisabledReason = useMemo(() => {
    if (!canWrite) return "Read-only role";
    if (isFinal) return "Already published (final)";
    if (!isInReview) return "Submit for review first";
    if (latestReviewState !== "approved") return "Needs admin approval";
    return null;
  }, [canWrite, isFinal, isInReview, latestReviewState]);

  const viewerHint = useMemo(() => {
    if (!myRole) return null;
    if (!isViewer) return null;
    return "You have viewer access. You can export and copy, but cannot edit, version, submit for review, or publish.";
  }, [myRole, isViewer]);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Artifact</Title>
        <Button component={Link} to="/workspaces" variant="light">
          Back
        </Button>
      </Group>

      {viewerHint ? (
        <Card withBorder>
          <Text c="dimmed">{viewerHint}</Text>
        </Card>
      ) : null}

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
                {myRole ? <Badge variant="light">role: {myRole.role}</Badge> : null}
              </Group>
              <Text size="xs" c="dimmed">
                {art.id}
              </Text>
            </Group>

            {/* Approvals banner */}
            <Card withBorder>
              <Stack gap="xs">
                <Group justify="space-between">
                  <Text fw={700}>Approvals</Text>
                  <Badge variant="light">{isFinal ? "final" : isInReview ? "in_review" : "draft"}</Badge>
                </Group>

                {latestReview ? (
                  <Text size="sm" c="dimmed">
                    Latest review: <b>{latestReview.state}</b> · requested_at {latestReview.requested_at}
                    {latestReview.decided_at ? ` · decided_at ${latestReview.decided_at}` : ""}
                  </Text>
                ) : (
                  <Text size="sm" c="dimmed">
                    No review history yet.
                  </Text>
                )}

                {!isFinal && !isInReview ? (
                  <Group align="end">
                    <TextInput
                      label="Submit comment (optional)"
                      value={submitComment}
                      onChange={(e) => setSubmitComment(e.currentTarget.value)}
                      style={{ flex: 1 }}
                      disabled={!canWrite}
                    />
                    <Button onClick={submitForReview} loading={submitLoading} disabled={!canWrite}>
                      Submit for review
                    </Button>
                  </Group>
                ) : null}

                {isInReview ? (
                  <Group align="end">
                    <TextInput
                      label="Decision comment (optional)"
                      value={decisionComment}
                      onChange={(e) => setDecisionComment(e.currentTarget.value)}
                      style={{ flex: 1 }}
                      disabled={!isAdmin}
                    />
                    <Button onClick={approve} loading={approveLoading} disabled={!isAdmin}>
                      Approve
                    </Button>
                    <Button color="red" onClick={reject} loading={rejectLoading} disabled={!isAdmin}>
                      Reject
                    </Button>
                  </Group>
                ) : null}

                {/* Review history */}
                {reviews.length > 0 ? (
                  <Card withBorder>
                    <Stack gap="xs">
                      <Text fw={600}>Review history</Text>
                      {reviews.map((r) => (
                        <Card key={r.id} withBorder>
                          <Stack gap={2}>
                            <Group gap="sm">
                              <Badge variant="light">{r.state}</Badge>
                              <Text size="sm" c="dimmed">
                                requested_at {r.requested_at} · requested_by {r.requested_by_user_id}
                              </Text>
                            </Group>
                            {r.request_comment ? <Text size="sm">request: {r.request_comment}</Text> : null}
                            {r.decided_at ? (
                              <Text size="sm" c="dimmed">
                                decided_at {r.decided_at} · decided_by {r.decided_by_user_id}
                              </Text>
                            ) : null}
                            {r.decision_comment ? <Text size="sm">decision: {r.decision_comment}</Text> : null}
                          </Stack>
                        </Card>
                      ))}
                    </Stack>
                  </Card>
                ) : null}
              </Stack>
            </Card>

            <Group grow>
              <TextInput
                label="Title"
                value={title}
                onChange={(e) => setTitle(e.currentTarget.value)}
                disabled={isFinal || isInReview || !canWrite}
              />
              <TextInput label="Status" value={status} disabled />
            </Group>

            <Group>
              <Button onClick={saveInPlace} loading={saving} disabled={isFinal || isInReview || !canWrite}>
                Save (same version)
              </Button>
              <Button
                variant="light"
                onClick={saveNewVersion}
                loading={newVerLoading}
                disabled={isFinal || isInReview || !canWrite}
              >
                Save as new version
              </Button>
              <Button variant="default" onClick={copyMarkdown}>
                Copy Markdown
              </Button>
              <Button variant="default" onClick={exportPdf}>
                Export PDF
              </Button>
              <Button variant="default" onClick={exportDocx}>
                Export DOCX
              </Button>

              {!isFinal ? (
                <Button
                  color="green"
                  onClick={publish}
                  loading={publishing}
                  disabled={!!publishDisabledReason}
                  title={publishDisabledReason ?? undefined}
                >
                  Publish (final)
                </Button>
              ) : (
                <Button color="yellow" onClick={unpublish} loading={unpublishing} disabled={!canWrite}>
                  Unpublish (back to draft)
                </Button>
              )}

              {publishDisabledReason ? (
                <Text size="sm" c="dimmed">
                  Publish blocked: {publishDisabledReason}
                </Text>
              ) : null}

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
                  disabled={isFinal || isInReview || !canWrite}
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

            {isInReview ? (
              <Text size="sm" c="dimmed">
                This artifact is in review and locked. Admin must approve/reject.
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