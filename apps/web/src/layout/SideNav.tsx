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
    <div className="sidenav-item" data-active={active ? "true" : "false"}>
      <Button
        component={Link}
        to={to}
        variant="subtle"
        size="sm"
        justify="flex-start"
        fullWidth
        disabled={disabled}
        styles={{
          root: {
            height: 36,
            borderRadius: 10,
            paddingLeft: 18,
            paddingRight: 12,
            opacity: disabled ? 0.55 : 1,
            background: active ? "rgba(255,255,255,0.06)" : "transparent",
            border: active ? "1px solid rgba(255,255,255,0.12)" : "1px solid transparent",
          },
          label: {
            fontWeight: active ? 700 : 600,
          },
        }}
      >
        {label}
      </Button>
    </div>
  );
}

export default function SideNav({ workspaceId }: { workspaceId: string | null }) {
  const loc = useLocation();
  const hasWs = !!workspaceId;
  const wid = workspaceId || "";

  const isActive = (prefix: string) => loc.pathname.startsWith(prefix);

  const wsBase = hasWs ? `/workspaces/${wid}` : "/workspaces";
  const runBuilder = hasWs ? `/run-builder/${wid}` : "/workspaces";

  return (
    <div style={{ height: "100%" }} className="glass-surface-strong">
      <Stack gap="sm" p="md">
        <Stack gap={6}>
          <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
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
          <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
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