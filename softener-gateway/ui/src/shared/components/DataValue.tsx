import { Stack, Text } from "@mantine/core";

import { missingValue } from "../utils/format";

type DataValueProps = {
  label: string;
  value?: string | number | boolean | null;
};

export function DataValue({ label, value }: DataValueProps) {
  return (
    <Stack gap={2}>
      <Text className="data-value__label">{label}</Text>
      <Text className="data-value__value">
        {value === undefined || value === null || value === "" ? missingValue : String(value)}
      </Text>
    </Stack>
  );
}
