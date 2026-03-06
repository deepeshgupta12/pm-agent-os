// apps/web/src/pages/DocsHomePage.tsx
import { Button, Group } from "@mantine/core";
import { Link } from "react-router-dom";

import GlassPage from "../components/Glass/GlassPage";
import EmptyState from "../components/Glass/EmptyState";

const LAST_WS_KEY = "pmos:lastWorkspaceId";

function readLastWorkspaceId(): string | null {
  try {
    const v = window.localStorage.getItem(LAST_WS_KEY);
    if (!v) return null;
    return /^[0-9a-fA-F-]{36}$/.test(v) ? v : null;
  } catch {
    return null;
  }
}

export default function DocsHomePage() {
  const wid = readLastWorkspaceId();

  return (
    <GlassPage
      title="Docs"
      subtitle="Ingest and search workspace knowledge."
      right={
        <Group>
          <Button component={Link} to="/workspaces" variant="light" size="sm">
            Workspaces
          </Button>
        </Group>
      }
    >
      {!wid ? (
        <EmptyState
          title="No workspace selected"
          description="Choose a workspace to open Docs."
          primaryLabel="Go to Workspaces"
          primaryTo="/workspaces"
        />
      ) : (
        <EmptyState
          title="Open workspace docs"
          description="Docs are workspace-scoped."
          primaryLabel="Open Docs"
          primaryTo={`/workspaces/${wid}/docs`}
          secondaryLabel="Switch workspace"
          secondaryTo="/workspaces"
        />
      )}
    </GlassPage>
  );
}