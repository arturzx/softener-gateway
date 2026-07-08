import { Alert, Card, List, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { IconAlertTriangle } from "@tabler/icons-react";

import type { SoftenerSnapshot } from "../../shared/types/softener";
import { normalizeSnapshot } from "../../shared/utils/normalize";
import { SoftenerIllustration } from "./SoftenerIllustration";

type SoftenerHeroCardProps = {
  snapshot: SoftenerSnapshot;
};

export function SoftenerHeroCard({ snapshot }: SoftenerHeroCardProps) {
  const normalized = normalizeSnapshot(snapshot);

  return (
    <Card className="hero-card" padding="xl" radius="xl" withBorder>
      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="xl" verticalSpacing="xl">
        <div>
          <SoftenerIllustration
            capacityRemaining={snapshot.state.capacity.remaining ?? undefined}
            saltLevel={normalized.saltLevel}
            status={normalized.mainStatus}
          />
        </div>
        <div className="hero-card__content">
          <Stack className="hero-card__body" gap="lg">
            <Stack gap="xs">
              <Title order={2}>{normalized.statusTitle}</Title>
              {normalized.activeErrors.length > 0 ? (
                <ActiveErrorsAlert errors={normalized.activeErrors} />
              ) : (
                <Text c="dimmed">{normalized.statusSubtitle}</Text>
              )}
            </Stack>
          </Stack>
        </div>
      </SimpleGrid>
    </Card>
  );
}

function ActiveErrorsAlert({ errors }: { errors: { key: string; label: string }[] }) {
  return (
    <Alert color="red" icon={<IconAlertTriangle size={18} />} radius="lg" variant="light">
      <Stack gap="xs">
        <Text fw={500}>Active errors</Text>
        <List spacing={4}>
          {errors.map((error) => (
            <List.Item key={error.key}>{error.label}</List.Item>
          ))}
        </List>
      </Stack>
    </Alert>
  );
}
