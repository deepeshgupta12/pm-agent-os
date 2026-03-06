// apps/web/src/pages/PolicyCenterPage.tsx
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Code,
  Group,
  MultiSelect,
  NumberInput,
  Select,
  Stack,
  Switch,
  Text,
  Title,
  Divider,
} from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { WorkspacePolicyOut, WorkspacePolicyPurgeOut, WorkspaceRole } from "../types";

type PiiMode = "none" | "write_time" | "export_time" | "both";

function safeJson(v: any): string {
  try {
    return JSON.stringify(v ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

function normalizeLocalPolicy(raw: any): Record<string, any> {
  // Keep local normalization aligned with backend intent (defensive).
  const r = raw && typeof raw === "object" ? raw : {};
  const retrieval = r.retrieval && typeof r.retrieval === "object" ? r.retrieval : {};
  const privacy = r.privacy && typeof r.privacy === "object" ? r.privacy : {};
  const pii = privacy.pii_masking && typeof privacy.pii_masking === "object" ? privacy.pii_masking : {};

  const ast = Array.isArray(retrieval.allowed_source_types) ? retrieval.allowed_source_types : [];
  const cleanAst = ast
    .map((x: any) => String(x ?? "").trim().toLowerCase())
    .filter((s: string) => !!s);
  const allowed_source_types = Array.from(new Set(cleanAst));

  const rdRaw = retrieval.retention_days;
  let retention_days: number | null = null;
  if (rdRaw === null || rdRaw === undefined || rdRaw === "") {
    retention_days = null;
  } else {
    const n = Number(rdRaw);
    retention_days = Number.isFinite(n) && n > 0 ? Math.floor(n) : null;
  }

  const block_external_links = !!retrieval.block_external_links;

  const enabled = !!pii.enabled;
  const modeRaw = String(pii.mode ?? "none").trim().toLowerCase();
  const mode: PiiMode = (["none", "write_time", "export_time", "both"] as const).includes(modeRaw as any)
    ? (modeRaw as PiiMode)
    : "none";

  const internal_only = !!r.internal_only;

  return {
    internal_only,
    retrieval: {
      allowed_source_types,
      retention_days,
      block_external_links,
    },
    privacy: {
      pii_masking: {
        enabled,
        mode,
      },
    },
  };
}

export default function PolicyCenterPage() {
  const { workspaceId } = useParams();
  const wid = workspaceId || "";

  const [err, setErr] = useState<string | null>(null);

  // role
  const [myRole, setMyRole] = useState<WorkspaceRole | null>(null);
  const isAdmin = (myRole?.role || "").toLowerCase() === "admin";

  // policy payload
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const [policy, setPolicy] = useState<Record<string, any> | null>(null);
  const [dirty, setDirty] = useState(false);

  // purge
  const [purging, setPurging] = useState(false);
  const [purgeResult, setPurgeResult] = useState<WorkspacePolicyPurgeOut | null>(null);

  // form fields
  const [internalOnly, setInternalOnly] = useState(false);

  const [allowedSourceTypes, setAllowedSourceTypes] = useState<string[]>([]);
  const [retentionDays, setRetentionDays] = useState<number | null>(null);
  const [blockExternalLinks, setBlockExternalLinks] = useState(false);

  const [piiEnabled, setPiiEnabled] = useState(false);
  const [piiMode, setPiiMode] = useState<PiiMode>("none");

  const sourceOptions = useMemo(
    () => [
      { value: "docs", label: "docs" },
      { value: "github", label: "github" },
      { value: "slack", label: "slack" },
      { value: "jira", label: "jira" },
      { value: "support", label: "support" },
      { value: "analytics", label: "analytics" },
      { value: "manual", label: "manual" },
    ],
    []
  );

  const effectiveJson = useMemo(() => {
    const obj = normalizeLocalPolicy({
      internal_only: internalOnly,
      retrieval: {
        allowed_source_types: allowedSourceTypes,
        retention_days: retentionDays,
        block_external_links: blockExternalLinks,
      },
      privacy: {
        pii_masking: {
          enabled: piiEnabled,
          mode: piiMode,
        },
      },
    });
    return obj;
  }, [internalOnly, allowedSourceTypes, retentionDays, blockExternalLinks, piiEnabled, piiMode]);

  async function loadRole() {
    if (!wid) return;
    const roleRes = await apiFetch<WorkspaceRole>(`/workspaces/${wid}/my-role`, { method: "GET" });
    if (!roleRes.ok) {
      setMyRole(null);
      // don't hard fail page; show read-only by default
      return;
    }
    setMyRole(roleRes.data);
  }

  async function loadPolicy() {
    if (!wid) return;
    setErr(null);
    setLoading(true);
    setPurgeResult(null);

    const res = await apiFetch<WorkspacePolicyOut>(`/workspaces/${wid}/policy`, { method: "GET" });

    setLoading(false);

    if (!res.ok) {
      setPolicy(null);
      setErr(`Policy load failed: ${res.status} ${res.error}`);
      return;
    }

    const normalized = normalizeLocalPolicy(res.data.policy_json || {});
    setPolicy(normalized);

    // hydrate form state
    setInternalOnly(!!normalized.internal_only);

    setAllowedSourceTypes(
      Array.isArray(normalized?.retrieval?.allowed_source_types) ? normalized.retrieval.allowed_source_types : []
    );
    setRetentionDays(
      typeof normalized?.retrieval?.retention_days === "number" ? normalized.retrieval.retention_days : null
    );
    setBlockExternalLinks(!!normalized?.retrieval?.block_external_links);

    setPiiEnabled(!!normalized?.privacy?.pii_masking?.enabled);
    setPiiMode((normalized?.privacy?.pii_masking?.mode as PiiMode) || "none");

    setDirty(false);
  }

  async function savePolicy() {
    if (!wid) return;
    if (!isAdmin) {
      setErr("Only admins can update workspace policy.");
      return;
    }

    setErr(null);
    setSaving(true);
    setPurgeResult(null);

    const payload = { policy_json: effectiveJson };

    const res = await apiFetch<WorkspacePolicyOut>(`/workspaces/${wid}/policy`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });

    setSaving(false);

    if (!res.ok) {
      setErr(`Policy save failed: ${res.status} ${res.error}`);
      return;
    }

    const normalized = normalizeLocalPolicy(res.data.policy_json || {});
    setPolicy(normalized);

    // rehydrate from server (source of truth)
    setInternalOnly(!!normalized.internal_only);
    setAllowedSourceTypes(
      Array.isArray(normalized?.retrieval?.allowed_source_types) ? normalized.retrieval.allowed_source_types : []
    );
    setRetentionDays(
      typeof normalized?.retrieval?.retention_days === "number" ? normalized.retrieval.retention_days : null
    );
    setBlockExternalLinks(!!normalized?.retrieval?.block_external_links);

    setPiiEnabled(!!normalized?.privacy?.pii_masking?.enabled);
    setPiiMode((normalized?.privacy?.pii_masking?.mode as PiiMode) || "none");

    setDirty(false);
  }

  async function runPurge() {
    if (!wid) return;
    if (!isAdmin) {
      setErr("Only admins can run retention purge.");
      return;
    }

    setErr(null);
    setPurging(true);

    const res = await apiFetch<WorkspacePolicyPurgeOut>(`/workspaces/${wid}/policy/purge`, {
      method: "POST",
      body: JSON.stringify({}),
    });

    setPurging(false);

    if (!res.ok) {
      setPurgeResult(null);
      setErr(`Purge failed: ${res.status} ${res.error}`);
      return;
    }

    setPurgeResult(res.data);
  }

  useEffect(() => {
    if (!wid) return;
    void loadRole();
    void loadPolicy();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid]);

  function markDirty() {
    setDirty(true);
    setErr(null);
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Policy Center</Title>
        <Group>
          <Button component={Link} to={`/workspaces/${wid}`} variant="light">
            Back
          </Button>
          <Button variant="light" onClick={loadPolicy} loading={loading}>
            Refresh
          </Button>
          <Button onClick={savePolicy} loading={saving} disabled={!isAdmin || !dirty || loading}>
            Save
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
              <Text fw={700}>Workspace Policy</Text>
              <Badge variant="light">V1</Badge>
              <Badge variant="light" color={isAdmin ? "grape" : "gray"}>
                {isAdmin ? "admin can edit" : "read-only"}
              </Badge>
            </Group>
            <Text size="xs" c="dimmed">
              writes to <Code>workspaces.policy_json</Code>
            </Text>
          </Group>

          <Divider />

          <Stack gap="xs">
            <Text fw={600}>Internal-only</Text>
            <Text size="sm" c="dimmed">
              If enabled: exports are blocked and connector operations are disabled.
            </Text>
            <Switch
              checked={internalOnly}
              onChange={(e) => {
                setInternalOnly(e.currentTarget.checked);
                markDirty();
              }}
              disabled={!isAdmin}
              label="internal_only"
            />
          </Stack>

          <Divider />

          <Stack gap="xs">
            <Text fw={600}>Retrieval Controls</Text>
            <Text size="sm" c="dimmed">
              Allowed source types acts as an allowlist. If empty, everything is allowed.
            </Text>

            <MultiSelect
              label="allowed_source_types"
              data={sourceOptions}
              value={allowedSourceTypes}
              onChange={(v) => {
                setAllowedSourceTypes(v);
                markDirty();
              }}
              disabled={!isAdmin}
              searchable
              clearable
              placeholder="Select allowed sources (leave empty to allow all)"
            />

            <NumberInput
              label="retention_days"
              description="Optional. If set (>0), you can run purge to delete evidence + run logs older than cutoff."
              value={retentionDays ?? undefined}
              onChange={(v) => {
                const n = typeof v === "number" && Number.isFinite(v) ? v : null;
                setRetentionDays(n && n > 0 ? Math.floor(n) : null);
                markDirty();
              }}
              disabled={!isAdmin}
              min={1}
              placeholder="e.g., 30"
            />

            <Switch
              checked={blockExternalLinks}
              onChange={(e) => {
                setBlockExternalLinks(e.currentTarget.checked);
                markDirty();
              }}
              disabled={!isAdmin}
              label="block_external_links"
              description="Stored in policy_json. Enforcement can be wired in later (V1 stores it)."
            />
          </Stack>

          <Divider />

          <Stack gap="xs">
            <Text fw={600}>PII Masking</Text>
            <Text size="sm" c="dimmed">
              Basic masking for email/phone/long IDs. Mode controls when masking is applied.
            </Text>

            <Switch
              checked={piiEnabled}
              onChange={(e) => {
                setPiiEnabled(e.currentTarget.checked);
                markDirty();
              }}
              disabled={!isAdmin}
              label="pii_masking.enabled"
            />

            <Select
              label="pii_masking.mode"
              data={[
                { value: "none", label: "none" },
                { value: "write_time", label: "write_time" },
                { value: "export_time", label: "export_time" },
                { value: "both", label: "both" },
              ]}
              value={piiMode}
              onChange={(v) => {
                const nv = (v as PiiMode) || "none";
                setPiiMode(nv);
                markDirty();
              }}
              disabled={!isAdmin || !piiEnabled}
            />
          </Stack>

          <Divider />

          <Stack gap="xs">
            <Group justify="space-between">
              <Text fw={600}>Retention Purge</Text>
              <Button onClick={runPurge} loading={purging} disabled={!isAdmin || purging || loading}>
                Run purge now
              </Button>
            </Group>

            <Text size="sm" c="dimmed">
              Uses <Code>POST /workspaces/:id/policy/purge</Code>. Requires <Code>retention_days</Code> to be set.
            </Text>

            {purgeResult ? (
              <Card withBorder>
                <Stack gap={6}>
                  <Text fw={600}>Purge result</Text>
                  <Text size="sm">
                    cutoff: <Code>{purgeResult.cutoff}</Code>
                  </Text>
                  <Text size="sm">
                    deleted_evidence: <Code>{purgeResult.deleted_evidence}</Code> · deleted_logs:{" "}
                    <Code>{purgeResult.deleted_logs}</Code>
                  </Text>
                </Stack>
              </Card>
            ) : null}
          </Stack>

          <Divider />

          <Stack gap="xs">
            <Text fw={600}>Normalized Policy JSON (preview)</Text>
            <Text size="sm" c="dimmed">
              This is what will be sent to the backend on Save.
            </Text>
            <pre style={{ margin: 0, whiteSpace: "pre-wrap" }}>{safeJson(effectiveJson)}</pre>

            {policy ? (
              <Text size="xs" c="dimmed">
                Loaded from server: <Code>{wid}</Code>
              </Text>
            ) : null}
          </Stack>
        </Stack>
      </Card>
    </Stack>
  );
}