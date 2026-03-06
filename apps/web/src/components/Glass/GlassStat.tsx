// apps/web/src/components/Glass/GlassStat.tsx
import { Group, Text } from "@mantine/core";

export default function GlassStat({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <Group gap={8} className="glass-stat" wrap="nowrap">
      <Text size="xs" c="dimmed" fw={600} tt="uppercase">
        {label}
      </Text>
      <Text size="sm" fw={700}>
        {value}
      </Text>
    </Group>
  );
}