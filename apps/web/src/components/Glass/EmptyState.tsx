// apps/web/src/components/Glass/EmptyState.tsx
import { Button, Group, Stack, Text, Title } from "@mantine/core";
import { Link } from "react-router-dom";
import GlassCard from "./GlassCard";

export default function EmptyState({
  title,
  description,
  primaryLabel,
  primaryTo,
  secondaryLabel,
  secondaryTo,
}: {
  title: string;
  description?: string;
  primaryLabel?: string;
  primaryTo?: string;
  secondaryLabel?: string;
  secondaryTo?: string;
}) {
  return (
    <GlassCard p="md">
      <Stack gap="sm">
        <Title order={4}>{title}</Title>
        {description ? (
          <Text c="dimmed" size="sm">
            {description}
          </Text>
        ) : null}

        {(primaryLabel && primaryTo) || (secondaryLabel && secondaryTo) ? (
          <Group>
            {primaryLabel && primaryTo ? (
              <Button component={Link} to={primaryTo} size="sm">
                {primaryLabel}
              </Button>
            ) : null}
            {secondaryLabel && secondaryTo ? (
              <Button component={Link} to={secondaryTo} size="sm" variant="light">
                {secondaryLabel}
              </Button>
            ) : null}
          </Group>
        ) : null}
      </Stack>
    </GlassCard>
  );
}