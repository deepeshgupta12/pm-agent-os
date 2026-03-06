// apps/web/src/pages/SettingsHomePage.tsx
import { Button, Group, Stack, Text } from "@mantine/core";
import { Link } from "react-router-dom";

import GlassPage from "../components/Glass/GlassPage";
import GlassSection from "../components/Glass/GlassSection";
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

export default function SettingsHomePage() {
  const wid = readLastWorkspaceId();

  return (
    <GlassPage
      title="Settings"
      subtitle="Global settings and workspace settings shortcuts."
      right={
        <Group>
          <Button component={Link} to="/workspaces" variant="light" size="sm">
            Workspaces
          </Button>
        </Group>
      }
    >
      <Stack gap="md">
        <GlassSection title="Global settings" description="Global configuration (placeholder).">
          <Text c="dimmed" size="sm">
            Global settings will live here later (account defaults, UI preferences, connector defaults).
          </Text>
        </GlassSection>

        {!wid ? (
          <EmptyState
            title="Workspace settings"
            description="Select a workspace to access workspace rules, audit logs, and advanced tools."
            primaryLabel="Go to Workspaces"
            primaryTo="/workspaces"
          />
        ) : (
          <GlassSection title="Workspace settings" description="Shortcuts for the active workspace.">
            <Group>
              <Button component={Link} to={`/workspaces/${wid}`} size="sm">
                Workspace overview
              </Button>
              <Button component={Link} to={`/workspaces/${wid}/policy`} size="sm" variant="light">
                Workspace rules
              </Button>
              <Button component={Link} to={`/workspaces/${wid}/governance`} size="sm" variant="light">
                Audit log
              </Button>
              <Button component={Link} to={`/workspaces/${wid}/agent-builder`} size="sm" variant="light">
                Agent builder
              </Button>
            </Group>
          </GlassSection>
        )}
      </Stack>
    </GlassPage>
  );
}