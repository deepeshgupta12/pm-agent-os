import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  Group,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { apiFetch } from "../apiClient";
import type { PipelineRun, PipelineTemplate } from "../types";

type TemplateListResponse = PipelineTemplate[] | { items: PipelineTemplate[] };

function normalizeTemplates(res: TemplateListResponse): PipelineTemplate[] {
  if (Array.isArray(res)) return res;
  return res.items ?? [];
}

export default function PipelinesPage() {
  const { workspaceId } = useParams();
  const wid = workspaceId || "";
  const nav = useNavigate();

  const [templates, setTemplates] = useState<PipelineTemplate[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [loadingTemplates, setLoadingTemplates] = useState(false);

  // Create pipeline run form
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [goal, setGoal] = useState("Improve onboarding conversion");
  const [context, setContext] = useState("Mobile web");
  const [constraints, setConstraints] = useState("");
  const [creating, setCreating] = useState(false);

  const templateOptions = useMemo(
    () => templates.map((t) => ({ value: t.id, label: `${t.name}` })),
    [templates]
  );

  async function loadTemplates() {
    if (!wid) return;
    setErr(null);
    setLoadingTemplates(true);

    // Expected endpoint:
    // GET /workspaces/{workspace_id}/pipelines/templates
    const res = await apiFetch<TemplateListResponse>(`/workspaces/${wid}/pipelines/templates`, {
      method: "GET",
    });

    setLoadingTemplates(false);

    if (!res.ok) {
      // Not fatal: allow manual template id entry
      setTemplates([]);
      setErr(
        `Templates load failed (${res.status}). You can still start a pipeline by pasting template_id manually.`
      );
      return;
    }

    const items = normalizeTemplates(res.data);
    setTemplates(items);
    if (!templateId && items.length > 0) setTemplateId(items[0].id);
  }

  async function createPipelineRun() {
    if (!wid) return;
    if (!templateId) {
      setErr("Select a template (or paste template_id).");
      return;
    }

    setErr(null);
    setCreating(true);

    // Expected endpoint:
    // POST /workspaces/{workspace_id}/pipelines/runs
    const res = await apiFetch<PipelineRun>(`/workspaces/${wid}/pipelines/runs`, {
      method: "POST",
      body: JSON.stringify({
        template_id: templateId,
        input_payload: {
          goal: goal.trim(),
          context: context.trim(),
          constraints: constraints.trim(),
        },
      }),
    });

    setCreating(false);

    if (!res.ok) {
      setErr(`Create pipeline run failed: ${res.status} ${res.error}`);
      return;
    }

    nav(`/pipelines/runs/${res.data.id}`);
  }

  useEffect(() => {
    void loadTemplates();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wid]);

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Pipelines</Title>
        <Button component={Link} to={`/workspaces/${wid}`} variant="light">
          Back to Workspace
        </Button>
      </Group>

      {!wid ? (
        <Card withBorder>
          <Text c="red">Missing workspaceId in route.</Text>
        </Card>
      ) : null}

      {err ? (
        <Card withBorder>
          <Text c="red">{err}</Text>
        </Card>
      ) : null}

      <Card withBorder>
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={700}>Start a pipeline run</Text>
            <Button variant="light" onClick={loadTemplates} loading={loadingTemplates}>
              Refresh templates
            </Button>
          </Group>

          <Group gap="sm" align="flex-end">
            <Select
              label="Template"
              data={templateOptions}
              value={templateId}
              onChange={setTemplateId}
              placeholder={loadingTemplates ? "Loading…" : "Select template"}
              style={{ flex: 1 }}
              searchable
              nothingFoundMessage="No templates loaded"
            />
            <Badge variant="light">workspace: {wid.slice(0, 8)}…</Badge>
          </Group>

          {/* Manual override if templates endpoint isn't present */}
          {templates.length === 0 ? (
            <TextInput
              label="Template ID (manual)"
              value={templateId ?? ""}
              onChange={(e) => setTemplateId(e.currentTarget.value)}
              placeholder="Paste template UUID"
            />
          ) : null}

          <Group grow>
            <TextInput
              label="Goal"
              value={goal}
              onChange={(e) => setGoal(e.currentTarget.value)}
              placeholder="What outcome are you trying to drive?"
            />
            <TextInput
              label="Context"
              value={context}
              onChange={(e) => setContext(e.currentTarget.value)}
              placeholder="e.g., Mobile web / iOS / B2B admin"
            />
          </Group>
          <TextInput
            label="Constraints (optional)"
            value={constraints}
            onChange={(e) => setConstraints(e.currentTarget.value)}
            placeholder="e.g., ship in 2 weeks, no backend changes"
          />

          <Button onClick={createPipelineRun} loading={creating}>
            Create pipeline run
          </Button>

          <Text size="sm" c="dimmed">
            After creation, you’ll execute steps one-by-one. Each step creates a normal <b>Run</b> and an initial
            draft <b>Artifact</b>.
          </Text>
        </Stack>
      </Card>
    </Stack>
  );
}