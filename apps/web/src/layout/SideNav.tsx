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

  const isActive = (prefix: string) => loc.pathname === prefix || loc.pathname.startsWith(`${prefix}/`);

  const wsBase = hasWs ? `/workspaces/${wid}` : "/workspaces";
  const runBuilder = hasWs ? `/run-builder/${wid}` : "/workspaces";

  return (
    <div style={{ height: "100%" }} className="glass-surface-strong">
      <Stack gap="sm" p="md">
        {/* Global navigation */}
        <Stack gap={6}>
          <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
            Global
          </Text>
          <NavItem label="Workspaces" to="/workspaces" active={isActive("/workspaces") && !loc.pathname.match(/^\/workspaces\/[0-9a-fA-F-]{36}/)} />
          <NavItem label="Runs" to="/runs" active={isActive("/runs")} />
          <NavItem label="Outputs" to="/outputs" active={isActive("/outputs")} />
          <NavItem label="Approvals" to="/approvals" active={isActive("/approvals")} />
          <NavItem label="Docs" to="/docs" active={isActive("/docs")} />
          <NavItem label="Schedules" to="/schedules" active={isActive("/schedules")} />
          <NavItem label="Settings" to="/settings" active={isActive("/settings")} />
        </Stack>

        <Divider />

        {/* Workspace navigation */}
        <Stack gap={6}>
          <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
            Workspace
          </Text>

          <NavItem label="Overview" to={wsBase} disabled={!hasWs} active={hasWs && isActive(wsBase)} />
          <NavItem label="Create Run" to={runBuilder} disabled={!hasWs} active={hasWs && isActive(`/run-builder/${wid}`)} />
          <NavItem label="Outputs" to="/outputs" disabled={!hasWs} active={hasWs && isActive("/outputs")} />
          <NavItem label="Approvals" to="/approvals" disabled={!hasWs} active={hasWs && isActive("/approvals")} />
          <NavItem label="Docs" to="/docs" disabled={!hasWs} active={hasWs && isActive("/docs")} />
          <NavItem label="Schedules" to="/schedules" disabled={!hasWs} active={hasWs && isActive("/schedules")} />
        </Stack>

        <Divider />

        {/* Workspace Settings grouping */}
        <Stack gap={6}>
          <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
            Workspace Settings
          </Text>

          <NavItem
            label="Workspace Rules"
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
          <NavItem
            label="Members (Legacy)"
            to={`${wsBase}/_legacy`}
            disabled={!hasWs}
            active={hasWs && isActive(`${wsBase}/_legacy`)}
          />
        </Stack>

        {!hasWs ? (
          <>
            <Divider />
            <Group>
              <Text size="sm" c="dimmed">
                Select a workspace to unlock workspace tools.
              </Text>
            </Group>
          </>
        ) : null}
      </Stack>
    </div>
  );
}