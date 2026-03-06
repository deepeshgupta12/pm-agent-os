// apps/web/src/layout/SideNav.tsx
import { Button, Divider, Group, Stack, Text } from "@mantine/core";
import { Link, useLocation } from "react-router-dom";

function NavItem({
  label,
  to,
  disabled,
  active,
}: {
  label: string;
  to: string;
  disabled?: boolean;
  active?: boolean;
}) {
  return (
    <Button
      component={Link}
      to={to}
      variant="subtle"
      justify="flex-start"
      fullWidth
      disabled={disabled}
      className={`nav-item ${active ? "nav-item-active" : "nav-item-inactive"}`}
      styles={{
        root: {
          height: 38,
          borderRadius: 10,
        },
      }}
    >
      {label}
    </Button>
  );
}

export default function SideNav({ workspaceId }: { workspaceId: string | null }) {
  const loc = useLocation();
  const hasWs = !!workspaceId;
  const wid = workspaceId || "";

  const isActive = (prefix: string) => loc.pathname === prefix || loc.pathname.startsWith(prefix + "/");

  const wsBase = hasWs ? `/workspaces/${wid}` : "/workspaces";
  const runBuilder = hasWs ? `/run-builder/${wid}` : "/workspaces";

  return (
    <div style={{ height: "100%" }} className="glass-surface-strong">
      <Stack gap="sm" p="md">
        <Stack gap={6}>
          <Text size="xs" tt="uppercase" fw={700} className="nav-group-title">
            Workspace
          </Text>
          <NavItem label="Overview" to={wsBase} disabled={!hasWs} active={hasWs && isActive(wsBase)} />
          <NavItem
            label="Run Builder"
            to={runBuilder}
            disabled={!hasWs}
            active={hasWs && isActive(`/run-builder/${wid}`)}
          />
          <NavItem label="Docs" to={`${wsBase}/docs`} disabled={!hasWs} active={hasWs && isActive(`${wsBase}/docs`)} />
          <NavItem
            label="Pipelines"
            to={`${wsBase}/pipelines`}
            disabled={!hasWs}
            active={hasWs && isActive(`${wsBase}/pipelines`)}
          />
          <NavItem
            label="Schedules"
            to={`${wsBase}/schedules`}
            disabled={!hasWs}
            active={hasWs && isActive(`${wsBase}/schedules`)}
          />
        </Stack>

        <Divider />

        <Stack gap={6}>
          <Text size="xs" tt="uppercase" fw={700} className="nav-group-title">
            Governance
          </Text>
          <NavItem
            label="Approvals"
            to={`${wsBase}/actions`}
            disabled={!hasWs}
            active={hasWs && isActive(`${wsBase}/actions`)}
          />
          <NavItem
            label="Policy Center"
            to={`${wsBase}/policy`}
            disabled={!hasWs}
            active={hasWs && isActive(`${wsBase}/policy`)}
          />
          <NavItem
            label="Audit Log"
            to={`${wsBase}/governance`}
            disabled={!hasWs}
            active={hasWs && isActive(`${wsBase}/governance`)}
          />
          <NavItem
            label="Agent Builder"
            to={`${wsBase}/agent-builder`}
            disabled={!hasWs}
            active={hasWs && isActive(`${wsBase}/agent-builder`)}
          />
        </Stack>

        {!hasWs ? (
          <>
            <Divider />
            <Group>
              <Text size="sm" c="dimmed">
                Select a workspace to unlock navigation.
              </Text>
            </Group>
          </>
        ) : null}
      </Stack>
    </div>
  );
}