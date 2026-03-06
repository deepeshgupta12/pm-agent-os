// apps/web/src/components/Glass/GlassPage.tsx
import { Group, Stack, Text, Title } from "@mantine/core";

export default function GlassPage({
  title,
  subtitle,
  right,
  children,
}: {
  title?: string;
  subtitle?: string;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="page-wrap">
      {(title || subtitle || right) && (
        <Group justify="space-between" align="flex-start" mb="md">
          <Stack gap={2}>
            {title ? <Title order={2}>{title}</Title> : null}
            {subtitle ? (
              <Text size="sm" c="dimmed">
                {subtitle}
              </Text>
            ) : null}
          </Stack>

          {right ? <Group>{right}</Group> : null}
        </Group>
      )}

      <Stack gap="md">{children}</Stack>
    </div>
  );
}