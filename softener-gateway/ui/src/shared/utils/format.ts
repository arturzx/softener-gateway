import { ApiError } from "../../api/errors";

export const missingValue = "—";

export function formatNumber(value: number | null | undefined, unit?: string, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return missingValue;
  }

  const formatted = new Intl.NumberFormat("en-GB", {
    maximumFractionDigits: digits,
    minimumFractionDigits: Number.isInteger(value) ? 0 : Math.min(digits, 1),
  }).format(value);

  return unit ? `${formatted} ${unit}` : formatted;
}

export function formatInteger(value: number | null | undefined, unit?: string): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return missingValue;
  }
  const formatted = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 }).format(value);
  return unit ? `${formatted} ${unit}` : formatted;
}

export function formatBoolean(value: boolean | null | undefined): string {
  if (value === null || value === undefined) {
    return missingValue;
  }
  return value ? "Yes" : "No";
}

export function formatEnum(value: string | null | undefined): string {
  if (!value) {
    return missingValue;
  }
  return value.replaceAll("_", " ");
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return missingValue;
  }
  if (typeof value === "boolean") {
    return formatBoolean(value);
  }
  if (typeof value === "number") {
    return formatNumber(value, undefined, 3);
  }
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value);
}

export function formatUpdatedAt(value: string | null | undefined): string {
  if (!value) {
    return missingValue;
  }

  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "unknown error";
}

export function secondsToShortDuration(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return missingValue;
  }
  if (value < 60) {
    return `${value}s`;
  }
  const minutes = Math.floor(value / 60);
  const seconds = value % 60;
  if (minutes < 60) {
    return seconds ? `${minutes}m ${seconds}s` : `${minutes}m`;
  }
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return restMinutes ? `${hours}h ${restMinutes}m` : `${hours}h`;
}
