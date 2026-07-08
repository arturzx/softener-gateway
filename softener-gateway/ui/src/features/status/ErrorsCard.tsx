import { Alert, List, Stack, Text } from "@mantine/core";
import { IconAlertTriangle, IconCircleCheck } from "@tabler/icons-react";

import { SectionCard } from "../../shared/components/SectionCard";

type ErrorsCardProps = {
  errors: { key: string; label: string }[];
};

export function ErrorsCard({ errors }: ErrorsCardProps) {
  return (
    <SectionCard title="Errors">
      {errors.length === 0 ? (
        <Alert color="green" icon={<IconCircleCheck size={18} />} radius="lg" variant="light">
          No active errors
        </Alert>
      ) : (
        <Alert color="red" icon={<IconAlertTriangle size={18} />} radius="lg" variant="light">
          <Stack gap="xs">
            <Text fw={700}>Active errors</Text>
            <List spacing={4}>
              {errors.map((error) => (
                <List.Item key={error.key}>{error.label}</List.Item>
              ))}
            </List>
          </Stack>
        </Alert>
      )}
    </SectionCard>
  );
}
