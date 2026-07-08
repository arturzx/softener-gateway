import { Alert, Button, SimpleGrid, Stack, Tabs, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { IconAlertTriangle, IconPlayerPlay } from "@tabler/icons-react";
import { useState } from "react";

import { useControlMutation } from "../../api/softenerApi";
import { SectionCard } from "../../shared/components/SectionCard";
import type { ControlField, SoftenerSnapshot } from "../../shared/types/softener";
import { availableControlFields, hardnessControlValue } from "../../shared/utils/normalize";
import { SettingField, type PendingValue } from "./SettingField";
import { PendingChangesBar } from "./PendingChangesBar";

type SettingsTabsProps = {
  commands: { name: string; requiresValue: boolean }[] | undefined;
  snapshot: SoftenerSnapshot;
};

type PendingChanges = Record<string, PendingValue>;

export function SettingsTabs({ commands, snapshot }: SettingsTabsProps) {
  const fields = availableControlFields(commands);
  const editableFields = fields.filter((field) => field.command !== "start_regeneration");
  const hasStartRegeneration = fields.some((field) => field.command === "start_regeneration");
  const controlMutation = useControlMutation();
  const [pending, setPending] = useState<PendingChanges>({});

  const setPendingValue = (command: string, value: PendingValue) => {
    setPending((current) => ({
      ...current,
      [command]: value,
    }));
  };

  const save = async () => {
    const entries = Object.entries(pending);
    try {
      for (const [command, value] of entries) {
        await controlMutation.mutateAsync({
          command,
          payload: { value: normalizeControlValue(command, value) },
        });
      }
      setPending({});
      notifications.show({
        color: "green",
        message: "Settings have been sent to the device.",
        title: "Changes saved",
      });
    } catch (error) {
      notifications.show({
        color: "red",
        message: error instanceof Error ? error.message : "Unknown error",
        title: "Could not save changes",
      });
    }
  };

  const startRegeneration = async () => {
    try {
      await controlMutation.mutateAsync({ command: "start_regeneration", payload: {} });
      notifications.show({
        color: "green",
        message: "Regeneration command has been sent.",
        title: "Regeneration",
      });
    } catch (error) {
      notifications.show({
        color: "red",
        message: error instanceof Error ? error.message : "Unknown error",
        title: "Could not start regeneration",
      });
    }
  };

  return (
    <Stack gap="lg">
      <Tabs defaultValue="general" keepMounted={false} variant="pills">
        <Tabs.List>
          <Tabs.Tab value="general">General</Tabs.Tab>
          <Tabs.Tab value="regeneration">Regeneration</Tabs.Tab>
          <Tabs.Tab value="units">Units</Tabs.Tab>
          <Tabs.Tab value="features">Features</Tabs.Tab>
          <Tabs.Tab value="advanced">Advanced</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel pt="lg" value="general">
          <SettingsSection fields={editableFields} pending={pending} section="general" setPendingValue={setPendingValue} snapshot={snapshot} />
        </Tabs.Panel>
        <Tabs.Panel pt="lg" value="regeneration">
          <Stack gap="lg">
            <SettingsSection
              fields={editableFields}
              pending={pending}
              section="regeneration"
              setPendingValue={setPendingValue}
              snapshot={snapshot}
            />
            {hasStartRegeneration ? (
              <SectionCard
                description="Manual regeneration is the only public control action exposed right now."
                title="Action"
              >
                <Button
                  color="orange"
                  leftSection={<IconPlayerPlay size={18} />}
                  loading={controlMutation.isPending}
                  onClick={startRegeneration}
                >
                  Start regeneration
                </Button>
              </SectionCard>
            ) : null}
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel pt="lg" value="units">
          <SettingsSection fields={editableFields} pending={pending} section="units" setPendingValue={setPendingValue} snapshot={snapshot} />
        </Tabs.Panel>
        <Tabs.Panel pt="lg" value="features">
          <SettingsSection fields={editableFields} pending={pending} section="features" setPendingValue={setPendingValue} snapshot={snapshot} />
        </Tabs.Panel>
        <Tabs.Panel pt="lg" value="advanced">
          <SettingsSection fields={editableFields} pending={pending} section="advanced" setPendingValue={setPendingValue} snapshot={snapshot} />
        </Tabs.Panel>
      </Tabs>

      {editableFields.length === 0 ? (
        <Alert color="orange" icon={<IconAlertTriangle size={18} />} radius="lg" variant="light">
          The API did not return any writable commands. Settings are read-only.
        </Alert>
      ) : null}

      <PendingChangesBar
        count={Object.keys(pending).length}
        onDiscard={() => setPending({})}
        onSave={save}
        saving={controlMutation.isPending}
      />
    </Stack>
  );
}

function SettingsSection({
  fields,
  pending,
  section,
  setPendingValue,
  snapshot,
}: {
  fields: ControlField[];
  pending: PendingChanges;
  section: ControlField["section"];
  setPendingValue: (command: string, value: PendingValue) => void;
  snapshot: SoftenerSnapshot;
}) {
  const sectionFields = fields.filter((field) => field.section === section);

  if (sectionFields.length === 0) {
    return (
      <SectionCard title="No settings">
        <Text c="dimmed" size="sm">
          There are no writable fields in this section.
        </Text>
      </SectionCard>
    );
  }

  return (
    <SectionCard title={sectionTitle(section)}>
      <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
        {sectionFields.map((field) => (
          <SettingField
            field={field}
            key={field.command}
            onChange={setPendingValue}
            pendingValue={pending[field.command]}
            snapshot={snapshot}
          />
        ))}
      </SimpleGrid>
    </SectionCard>
  );
}

function sectionTitle(section: ControlField["section"]): string {
  switch (section) {
    case "advanced":
      return "Advanced";
    case "app":
      return "App / communication";
    case "features":
      return "Features";
    case "general":
      return "General";
    case "regeneration":
      return "Regeneration";
    case "units":
      return "Units";
  }
}

function normalizeControlValue(command: string, value: PendingValue): PendingValue {
  if (command === "set_hardness" && typeof value === "string") {
    return hardnessControlValue(value);
  }
  if (command === "set_max_days_between_regenerations" && typeof value === "string") {
    return value === "auto" ? value : Number(value);
  }
  if (command === "set_feature_97_percent" && typeof value === "string") {
    return value === "enabled";
  }
  if (
    command.startsWith("set_regeneration_") &&
    command !== "set_regeneration_time" &&
    typeof value === "number"
  ) {
    return Math.round(value);
  }
  return value;
}
