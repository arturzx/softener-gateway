import { Alert, Stack, Text, Title } from "@mantine/core";
import { IconInfoCircle } from "@tabler/icons-react";

type EmptyStateProps = {
  description: string;
  title: string;
};

export function EmptyState({ description, title }: EmptyStateProps) {
  return (
    <Alert color="blue" icon={<IconInfoCircle size={18} />} radius="lg" variant="light">
      <Stack gap={4}>
        <Title order={3} size="h4">
          {title}
        </Title>
        <Text size="sm">{description}</Text>
      </Stack>
    </Alert>
  );
}
