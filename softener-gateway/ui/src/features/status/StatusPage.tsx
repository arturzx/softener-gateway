import { SimpleGrid, Stack } from "@mantine/core";
import {
  IconDroplet,
  IconHourglass,
  IconRefresh,
  IconDroplets,
  IconWaterpolo,
} from "@tabler/icons-react";

import { useSoftenerSnapshotQuery } from "../../api/softenerApi";
import { ErrorState } from "../../shared/components/ErrorState";
import { LoadingState } from "../../shared/components/LoadingState";
import { displayMetricValue } from "../../shared/utils/normalize";
import { formatInteger, secondsToShortDuration } from "../../shared/utils/format";
import { SoftenerHeroCard } from "./SoftenerHeroCard";
import { StatusMetricCard } from "./StatusMetricCard";

export function StatusPage() {
  const snapshotQuery = useSoftenerSnapshotQuery();

  if (snapshotQuery.isLoading) {
    return <LoadingState rows={6} />;
  }
  if (snapshotQuery.isError) {
    return <ErrorState error={snapshotQuery.error} />;
  }
  if (!snapshotQuery.data) {
    return <LoadingState rows={4} />;
  }

  const snapshot = snapshotQuery.data;
  const regenerationValue = snapshot.state.regeneration.active
    ? `Active, ${secondsToShortDuration(snapshot.state.regeneration.remaining)}`
    : "Inactive";
  const saltRemainingValue = formatInteger(snapshot.state.salt.remaining_estimate, "days");

  return (
    <Stack gap="lg">
      <SoftenerHeroCard snapshot={snapshot} />
      <SimpleGrid cols={{ base: 1, sm: 2, lg: 5 }} spacing="md">
        <StatusMetricCard
          icon={<IconDroplet size={20} />}
          label="Flow"
          value={displayMetricValue(snapshot, "current_flow")}
        />
        <StatusMetricCard
          icon={<IconWaterpolo size={20} />}
          label="Today usage"
          value={displayMetricValue(snapshot, "water_used_today")}
        />
        <StatusMetricCard
          icon={<IconDroplets size={20} />}
          label="Available water"
          value={displayMetricValue(snapshot, "treated_water_available")}
        />
        <StatusMetricCard
          icon={<IconHourglass size={20} />}
          label="Salt remaining"
          tone={
            snapshot.state.salt.remaining_estimate !== null &&
            snapshot.state.salt.remaining_estimate !== undefined &&
            snapshot.state.salt.remaining_estimate <= 14
              ? "orange"
              : "blue"
          }
          value={saltRemainingValue}
        />
        <StatusMetricCard
          icon={<IconRefresh size={20} />}
          label="Regeneration"
          tone={snapshot.state.regeneration.active ? "orange" : "green"}
          value={regenerationValue}
        />
      </SimpleGrid>
    </Stack>
  );
}
