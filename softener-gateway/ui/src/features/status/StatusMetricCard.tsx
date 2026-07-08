import { Card, Group, Stack, Text, ThemeIcon } from "@mantine/core";
import type { ReactNode } from "react";

type StatusMetricCardProps = {
  icon: ReactNode;
  label: string;
  tone?: "blue" | "green" | "orange" | "red";
  value: string;
};

export function StatusMetricCard({ icon, label, tone = "blue", value }: StatusMetricCardProps) {
  return (
    <Card className="metric-card" padding="md" radius="xl" withBorder>
      <Group align="center" gap="sm" wrap="nowrap">
        <ThemeIcon color={toneColor(tone)} radius="lg" size="lg" variant="light">
          {icon}
        </ThemeIcon>
        <Stack gap={1} miw={0}>
          <Text c="dimmed" size="xs">
            {label}
          </Text>
          <Text fw={650} truncate>
            {value}
          </Text>
        </Stack>
      </Group>
    </Card>
  );
}

function toneColor(tone: "blue" | "green" | "orange" | "red"): string {
  switch (tone) {
    case "blue":
      return "waterBlue";
    case "green":
      return "green";
    case "orange":
      return "orange";
    case "red":
      return "red";
  }
}
