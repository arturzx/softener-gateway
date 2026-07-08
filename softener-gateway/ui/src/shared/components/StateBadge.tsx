import { Badge } from "@mantine/core";

import type { DeviceStatus } from "../types/softener";

type StateBadgeProps = {
  label: string;
  status?: DeviceStatus | "online" | "unknown";
};

export function StateBadge({ label, status = "unknown" }: StateBadgeProps) {
  return (
    <Badge className={`status-badge--${status}`} radius="md" variant="light">
      {label}
    </Badge>
  );
}
