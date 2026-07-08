import { Button, Card, Group, Text } from "@mantine/core";
import { IconDeviceFloppy, IconX } from "@tabler/icons-react";

type PendingChangesBarProps = {
  count: number;
  saving: boolean;
  onDiscard: () => void;
  onSave: () => void;
};

export function PendingChangesBar({ count, saving, onDiscard, onSave }: PendingChangesBarProps) {
  if (count === 0) {
    return null;
  }

  return (
    <Card className="settings-bottom-bar" padding="md" radius="xl" shadow="md" withBorder>
      <Group justify="space-between">
        <Text fw={700}>Unsaved changes: {count}</Text>
        <Group gap="sm">
          <Button
            leftSection={<IconX size={16} />}
            onClick={onDiscard}
            variant="subtle"
          >
            Discard
          </Button>
          <Button
            leftSection={<IconDeviceFloppy size={16} />}
            loading={saving}
            onClick={onSave}
          >
            Save changes
          </Button>
        </Group>
      </Group>
    </Card>
  );
}
