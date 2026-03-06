// apps/web/src/components/Glass/GlassCard.tsx
import { Card, type CardProps } from "@mantine/core";

export default function GlassCard(props: CardProps) {
  const { className, ...rest } = props;

  return (
    <Card
      className={["glass-surface", className].filter(Boolean).join(" ")}
      p="md"
      radius="md"
      {...rest}
    />
  );
}