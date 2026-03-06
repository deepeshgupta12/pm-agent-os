// apps/web/src/layout/HeaderBar.tsx
import { Anchor, Badge, Group, Text } from "@mantine/core";
import { Link } from "react-router-dom";

export default function HeaderBar({ workspaceId }: { workspaceId: string | null }) {
  const wsShort = workspaceId ? workspaceId.slice(0, 8) : null;

  return (
    <Group justify="space-between" px="md" h="100%" className="glass-surface-strong">
      <Group gap="sm">
        <Text fw={700}>PM Agent OS</Text>
        {wsShort ? <Badge variant="light">WS: {wsShort}…</Badge> : null}
      </Group>

      <Group gap="md">
        <Anchor component={Link} to="/workspaces">
          Workspaces
        </Anchor>
        <Anchor component={Link} to="/me">
          Me
        </Anchor>
      </Group>
    </Group>
  );
}