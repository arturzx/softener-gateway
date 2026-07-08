import { Stack } from "@mantine/core";

import { useControlCommandsQuery, useSoftenerSnapshotQuery } from "../../api/softenerApi";
import { ErrorState } from "../../shared/components/ErrorState";
import { LoadingState } from "../../shared/components/LoadingState";
import { SettingsTabs } from "./SettingsTabs";

export function SettingsPage() {
  const snapshotQuery = useSoftenerSnapshotQuery();
  const commandsQuery = useControlCommandsQuery();

  if (snapshotQuery.isLoading || commandsQuery.isLoading) {
    return <LoadingState rows={7} />;
  }
  if (snapshotQuery.isError) {
    return <ErrorState error={snapshotQuery.error} />;
  }
  if (commandsQuery.isError) {
    return <ErrorState error={commandsQuery.error} />;
  }
  if (!snapshotQuery.data) {
    return <LoadingState rows={4} />;
  }

  return (
    <Stack gap="lg">
      <SettingsTabs commands={commandsQuery.data} snapshot={snapshotQuery.data} />
    </Stack>
  );
}
