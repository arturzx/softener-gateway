import { Badge, Box } from "@mantine/core";

import type { DeviceStatus } from "../../shared/types/softener";
import softenerImageUrl from "../../../../images/softener.png";

type SoftenerIllustrationProps = {
  capacityRemaining?: number;
  saltLevel?: number;
  status: DeviceStatus;
};

const SALT_LEVEL_MAX = 8;

export function SoftenerIllustration({
  capacityRemaining,
  saltLevel,
  status,
}: SoftenerIllustrationProps) {
  const badge = statusLabel(status);

  return (
    <Box className="softener-illustration">
      <Box className={`softener-illustration__halo softener-illustration__halo--${status}`} />
      <Box className="softener-illustration__frame">
        <img
          alt="Water softener"
          className={`softener-illustration__image${
            status === "offline" ? " softener-illustration__image--offline" : ""
          }`}
          src={softenerImageUrl}
        />
        <CapacityRemainingOverlay capacityRemaining={capacityRemaining} />
        <SaltLevelOverlay saltLevel={saltLevel} />
      </Box>
      <Badge
        className="softener-illustration__badge"
        color={badgeColor(status)}
        radius="md"
        variant="filled"
      >
        {badge}
      </Badge>
    </Box>
  );
}

function CapacityRemainingOverlay({ capacityRemaining }: { capacityRemaining?: number }) {
  if (capacityRemaining === undefined || Number.isNaN(capacityRemaining)) {
    return null;
  }

  const normalized = Math.max(0, Math.min(100, capacityRemaining));
  const low = normalized <= 10;

  return (
    <div
      aria-label={`Remaining capacity ${Math.round(normalized)} percent`}
      className="softener-illustration__capacity-overlay"
    >
      <span
        className={`softener-illustration__capacity-fill${
          low ? " softener-illustration__capacity-fill--low" : ""
        }`}
        style={{ height: `${normalized}%` }}
      />
    </div>
  );
}

function SaltLevelOverlay({ saltLevel }: { saltLevel?: number }) {
  const normalized =
    saltLevel === undefined ? undefined : Math.max(1, Math.min(SALT_LEVEL_MAX, saltLevel));

  return (
    <div className="softener-illustration__salt-overlay" aria-label="Salt level overlay">
      <div className="softener-illustration__marker-cover" />
      {Array.from({ length: SALT_LEVEL_MAX }, (_, index) => {
        const value = SALT_LEVEL_MAX - index;
        const current = normalized === value;
        const filled = normalized !== undefined && value <= normalized;
        const classes = [
          "softener-illustration__salt-pill",
          filled ? "softener-illustration__salt-pill--filled" : "",
          current ? "softener-illustration__salt-pill--current" : "",
          current && value === 1 ? "softener-illustration__salt-pill--low" : "",
        ]
          .filter(Boolean)
          .join(" ");

        return (
          <span className={classes} key={value}>
            {current ? <span className="softener-illustration__salt-marker" /> : null}
          </span>
        );
      })}
    </div>
  );
}

function statusLabel(status: DeviceStatus): string {
  switch (status) {
    case "error":
      return "Needs attention";
    case "flowing":
      return "All good";
    case "offline":
      return "Offline";
    case "ok":
      return "All good";
    case "regeneration":
      return "Regeneration";
  }
}

function badgeColor(status: DeviceStatus): string {
  switch (status) {
    case "error":
      return "red";
    case "flowing":
      return "waterBlue";
    case "offline":
      return "gray";
    case "ok":
      return "waterBlue";
    case "regeneration":
      return "orange";
  }
}
