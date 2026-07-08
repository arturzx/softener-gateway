import { Card, Group, Stack, Text } from "@mantine/core";
import type { ReactNode } from "react";

type SectionCardProps = {
  actions?: ReactNode;
  children?: ReactNode;
  description?: string;
  title: string;
};

export function SectionCard({ actions, children, description, title }: SectionCardProps) {
  return (
    <Card className="section-card" padding="lg" radius="xl" withBorder>
      <Stack gap="md">
        <Group align="flex-start" justify="space-between">
          <Stack gap={2}>
            <Text className="section-card__title">{title}</Text>
            {description ? (
              <Text c="dimmed" size="sm">
                {description}
              </Text>
            ) : null}
          </Stack>
          {actions}
        </Group>
        {children}
      </Stack>
    </Card>
  );
}
