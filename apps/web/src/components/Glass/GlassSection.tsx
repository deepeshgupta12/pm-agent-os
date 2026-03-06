// apps/web/src/components/Glass/GlassSection.tsx
import { Group, Stack, Text } from "@mantine/core";
import GlassCard from "./GlassCard";

export default function GlassSection({
  title,
  description,
  right,
  children,
  p = "md",
}: {
  title: string;
  description?: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  p?: "sm" | "md" | "lg" | number;
}) {
  return (
    <GlassCard p={p}>
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Stack gap={2}>
            <Text fw={700}>{title}</Text>
            {description ? (
              <Text size="sm" c="dimmed">
                {description}
              </Text>
            ) : null}
          </Stack>

          {right ? <Group gap="sm">{right}</Group> : null}
        </Group>

        {children}
      </Stack>
    </GlassCard>
  );
}