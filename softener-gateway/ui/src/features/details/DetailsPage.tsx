import { SimpleGrid, Stack } from "@mantine/core";

import { useSoftenerSnapshotQuery } from "../../api/softenerApi";
import { ErrorState } from "../../shared/components/ErrorState";
import { LoadingState } from "../../shared/components/LoadingState";
import { formatBoolean, formatNumber } from "../../shared/utils/format";
import {
  displayMetricValue,
  normalizeSnapshot,
} from "../../shared/utils/normalize";
import { DailyUsageChart } from "./DailyUsageChart";
import { DataGroupCard } from "./DataGroupCard";

export function DetailsPage() {
  const snapshotQuery = useSoftenerSnapshotQuery();

  if (snapshotQuery.isLoading) {
    return <LoadingState rows={7} />;
  }
  if (snapshotQuery.isError) {
    return <ErrorState error={snapshotQuery.error} />;
  }
  if (!snapshotQuery.data) {
    return <LoadingState rows={4} />;
  }

  const snapshot = snapshotQuery.data;
  const normalized = normalizeSnapshot(snapshot);
  const saltWeightUnit = normalized.weightUnit;
  const hardnessRemovedUnit = normalized.weightUnit === "kg" ? "g" : "lb";
  const hardnessRemovedDailyUnit = `${hardnessRemovedUnit}/day`;
  const saltEfficiencyUnit = normalized.weightUnit === "kg" ? "g/kg" : "grains/lb";
  const capacityUnit = normalized.weightUnit === "kg" ? "g" : "grains";

  return (
    <Stack gap="lg">
      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
        <DataGroupCard
          items={[
            {
              label: "Model",
              value:
                snapshot.device.model_description && snapshot.device.model_id !== null
                  ? `${snapshot.device.model_description} (${snapshot.device.model_id})`
                  : snapshot.device.model_description ?? snapshot.device.model_id,
            },
            { label: "Serial", value: snapshot.device.serial_number },
            { label: "Product serial number", value: snapshot.device.product_serial_number },
            { label: "Software version", value: snapshot.device.software_version },
            { label: "Build date", value: snapshot.device.build_date },
            { label: "Device time", value: snapshot.state.time },
            {
              label: "Operation time",
              value:
                snapshot.device.operation_time === null || snapshot.device.operation_time === undefined
                  ? null
                  : `${snapshot.device.operation_time} days`,
            },
          ]}
          title="Device"
        />
        <DataGroupCard
          items={[
            { label: "Active", value: formatBoolean(snapshot.state.regeneration.active) },
            { label: "Trigger", value: snapshot.state.regeneration.trigger },
            {
              label: "Stage",
              value: formatStage(snapshot.state.regeneration.stage, snapshot.state.regeneration.stage_remaining),
            },
            { label: "Remaining", value: formatNumber(snapshot.state.regeneration.remaining, "s", 0) },
            { label: "Time", value: snapshot.settings.regen_time },
            {
              label: "Since last / average interval",
              value: `${formatNumber(snapshot.state.regeneration.since_last, "days", 0)} / ${formatNumber(
                snapshot.state.regeneration.average_interval,
                "days",
              )}`,
            },
            { label: "Total count", value: formatNumber(snapshot.state.regeneration.total_count, undefined, 0) },
            { label: "Manual count", value: formatNumber(snapshot.state.regeneration.manual_count, undefined, 0) },
          ]}
          title="Regeneration"
        />
        <DataGroupCard
          items={[
            { label: "Flow", value: displayMetricValue(snapshot, "current_flow") },
            { label: "Today", value: displayMetricValue(snapshot, "water_used_today") },
            { label: "Daily average", value: formatNumber(snapshot.state.average_daily_usage, normalized.volumeUnit) },
            { label: "Available soft water", value: displayMetricValue(snapshot, "treated_water_available") },
            { label: "Total outlet", value: displayMetricValue(snapshot, "total_outlet_water") },
            { label: "Peak flow", value: displayMetricValue(snapshot, "peak_flow") },
          ]}
          title="Counters and usage"
        />
        <DataGroupCard
          items={[
            { label: "Current level", value: formatSaltLevel(snapshot.state.salt.level) },
            { label: "Low", value: formatBoolean(snapshot.state.salt.low) },
            {
              label: "Remaining estimate",
              value: formatNumber(snapshot.state.salt.remaining_estimate, "days", 0),
            },
            { label: "Total used", value: formatNumber(snapshot.state.salt.total_used, saltWeightUnit) },
            {
              label: "Average per regeneration",
              value: formatNumber(snapshot.state.salt.average_per_regeneration, saltWeightUnit),
            },
            { label: "Efficiency", value: formatNumber(snapshot.state.salt.efficiency, saltEfficiencyUnit) },
          ]}
          title="Salt"
        />
        <DataGroupCard
          items={[
            {
              label: "Since regeneration",
              value: formatNumber(snapshot.state.hardness_removed.since_regeneration, hardnessRemovedUnit),
            },
            {
              label: "Daily average",
              value: formatNumber(snapshot.state.hardness_removed.daily_average, hardnessRemovedDailyUnit),
            },
            { label: "Total", value: formatNumber(snapshot.state.hardness_removed.total, hardnessRemovedUnit) },
          ]}
          title="Hardness removed"
        />
        <DataGroupCard
          items={[
            { label: "Operating", value: formatNumber(snapshot.state.capacity.operating, capacityUnit) },
            { label: "Remaining", value: formatNumber(snapshot.state.capacity.remaining, "%") },
            {
              label: "Average exhaustion",
              value: formatNumber(snapshot.state.capacity.average_exhaustion, "%"),
            },
          ]}
          title="Capacity"
        />
        <div className="details-wide-panel">
          <DailyUsageChart profile={snapshot.state.daily_usage_profile} unit={normalized.volumeUnit} />
        </div>
      </SimpleGrid>
    </Stack>
  );
}

function formatStage(stage: string | null | undefined, remaining: number | null | undefined): string | null {
  if (!stage) {
    return null;
  }
  if (remaining === null || remaining === undefined) {
    return stage;
  }

  return `${stage} (${formatNumber(remaining, "s", 0)} remaining)`;
}

function formatSaltLevel(value: number | null | undefined): string | null {
  if (value === null || value === undefined) {
    return null;
  }

  return `${formatNumber(value)}/8`;
}
