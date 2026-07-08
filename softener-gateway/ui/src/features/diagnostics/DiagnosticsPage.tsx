import { SegmentedControl, Stack } from "@mantine/core";
import { useEffect, useMemo, useRef, useState } from "react";

import { useControlCommandsQuery, useSoftenerSnapshotQuery } from "../../api/softenerApi";
import { ErrorState } from "../../shared/components/ErrorState";
import { LoadingState } from "../../shared/components/LoadingState";
import { SectionCard } from "../../shared/components/SectionCard";
import { buildDiagnosticRows, snapshotValueMap } from "../../shared/utils/normalize";
import { RawDataTable } from "./RawDataTable";

type DiagnosticsFilter = "all" | "changed" | "errors" | "writable";

export function DiagnosticsPage() {
  const snapshotQuery = useSoftenerSnapshotQuery();
  const commandsQuery = useControlCommandsQuery();
  const [filter, setFilter] = useState<DiagnosticsFilter>("all");
  const previousMapRef = useRef<Map<string, string> | null>(null);
  const [changedKeys, setChangedKeys] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!snapshotQuery.data) {
      return;
    }

    const currentMap = snapshotValueMap(snapshotQuery.data);
    const previousMap = previousMapRef.current;
    if (previousMap) {
      const changed = new Set<string>();
      for (const [key, value] of currentMap) {
        if (previousMap.get(key) !== value) {
          changed.add(key);
        }
      }
      setChangedKeys(changed);
    }
    previousMapRef.current = currentMap;
  }, [snapshotQuery.data]);

  const rows = useMemo(() => {
    if (!snapshotQuery.data) {
      return [];
    }

    const allRows = buildDiagnosticRows(snapshotQuery.data, commandsQuery.data, changedKeys);
    switch (filter) {
      case "all":
        return allRows;
      case "changed":
        return allRows.filter((row) => row.changed);
      case "errors":
        return allRows.filter((row) => row.key.includes(".errors.") && row.active);
      case "writable":
        return allRows.filter((row) => row.writable);
    }
  }, [changedKeys, commandsQuery.data, filter, snapshotQuery.data]);

  if (snapshotQuery.isLoading) {
    return <LoadingState rows={7} />;
  }
  if (snapshotQuery.isError) {
    return <ErrorState error={snapshotQuery.error} />;
  }
  if (!snapshotQuery.data) {
    return <LoadingState rows={4} />;
  }

  return (
    <Stack gap="lg">
      <SectionCard
        actions={
          <SegmentedControl
            data={[
              { label: "All", value: "all" },
              { label: "Writable", value: "writable" },
              { label: "Errors", value: "errors" },
              { label: "Changed", value: "changed" },
            ]}
            onChange={(value) => setFilter(value as DiagnosticsFilter)}
            value={filter}
          />
        }
        title="Raw data and diagnostics"
      >
        <RawDataTable rows={rows} updatedAt={snapshotQuery.data.updatedAt} />
      </SectionCard>
    </Stack>
  );
}
