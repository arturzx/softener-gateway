import { NumberInput, Select, Stack, Switch, Text, TextInput } from "@mantine/core";

import type { ControlField, SoftenerSnapshot } from "../../shared/types/softener";
import { formatValue } from "../../shared/utils/format";

export type PendingValue = boolean | number | string;

type SettingFieldProps = {
  field: ControlField;
  onChange: (command: string, value: PendingValue) => void;
  pendingValue?: PendingValue;
  snapshot: SoftenerSnapshot;
};

export function SettingField({ field, onChange, pendingValue, snapshot }: SettingFieldProps) {
  const currentValue = field.currentValue(snapshot);
  const value = pendingValue ?? normalizeCurrentValue(currentValue);
  const description = `${field.description} Current: ${formatValue(currentValue)}`;
  const options = typeof field.options === "function" ? field.options(snapshot) : field.options;

  if (field.type === "boolean") {
    return (
      <Switch
        checked={Boolean(value)}
        description={description}
        label={field.label}
        onChange={(event) => onChange(field.command, event.currentTarget.checked)}
      />
    );
  }

  if (field.type === "select") {
    return (
      <Select
        clearable={false}
        data={options ?? []}
        description={description}
        label={field.label}
        onChange={(nextValue) => {
          if (nextValue !== null) {
            onChange(field.command, nextValue);
          }
        }}
        value={String(value ?? "")}
      />
    );
  }

  if (field.type === "time") {
    return (
      <TextInput
        description={description}
        label={field.label}
        onChange={(event) => onChange(field.command, event.currentTarget.value)}
        type="time"
        value={String(value ?? "")}
      />
    );
  }

  return (
    <Stack gap={4}>
      <NumberInput
        decimalScale={field.step && field.step < 1 ? 2 : 0}
        description={description}
        label={field.label}
        max={field.max}
        min={field.min}
        onChange={(nextValue) => {
          if (typeof nextValue === "number") {
            onChange(field.command, nextValue);
          }
          if (typeof nextValue === "string" && nextValue.trim()) {
            onChange(field.command, Number(nextValue));
          }
        }}
        rightSection={field.unit ? <Text size="xs">{field.unit}</Text> : undefined}
        step={field.step}
        value={typeof value === "number" ? value : Number(value)}
      />
    </Stack>
  );
}

function normalizeCurrentValue(value: unknown): PendingValue | undefined {
  if (typeof value === "boolean" || typeof value === "number" || typeof value === "string") {
    return value;
  }
  return undefined;
}
