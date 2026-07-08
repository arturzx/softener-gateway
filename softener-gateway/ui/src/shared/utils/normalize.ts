import type {
  ControlField,
  ControlCommand,
  DeviceStatus,
  DiagnosticRow,
  JsonObject,
  SoftenerSnapshot,
} from "../types/softener";
import { formatBoolean, formatEnum, formatInteger, formatNumber, formatValue } from "./format";

export type NormalizedSoftener = {
  activeErrors: { key: string; label: string }[];
  flowUnit: string;
  hardnessUnit: string;
  headerStatus: { label: string; status: DeviceStatus | "online" | "unknown" };
  mainStatus: DeviceStatus;
  saltLevel?: number;
  statusSubtitle: string;
  statusTitle: string;
  updatedAt: string;
  volumeUnit: string;
  weightUnit: string;
};

const ERROR_LABELS: Record<string, string> = {
  depletion: "Depletion",
  error_code: "General error",
  excessive_water_use: "Excessive water use",
  flow_monitor: "Flow monitor",
  low_salt: "Low salt",
  resin: "Resin",
  service_reminder: "Service reminder",
  shutoff_valve: "Shutoff valve",
  shutoff_valve_error_code: "Shutoff valve error",
  shutoff_valve_manual_override: "Shutoff valve manual override",
};

const HARDNESS_MIN_GPG = 1;
const HARDNESS_MAX_GPG = 80;
const PPM_PER_GPG = 17.1;
const PPM_PER_DH = 17.848;
const PPM_PER_FH = 10;
const SALT_LEVEL_MAX = 8;

export function normalizeSnapshot(snapshot: SoftenerSnapshot): NormalizedSoftener {
  const activeErrors = Object.entries(snapshot.state.errors)
    .filter(([, active]) => active)
    .map(([key]) => ({ key, label: errorLabel(key) }));

  const flowing = (snapshot.state.current_flow ?? 0) > 0.05;
  const regeneration = snapshot.state.regeneration.active === true;
  const online = snapshot.state.online === true;
  const saltLow = snapshot.state.salt.low === true;

  const mainStatus: DeviceStatus = !online
    ? "offline"
    : activeErrors.length > 0 || saltLow
      ? "error"
      : regeneration
        ? "regeneration"
        : flowing
          ? "flowing"
          : "ok";

  return {
    activeErrors,
    flowUnit: snapshot.settings.display.volume_unit === "gallons" ? "gal/min" : "l/min",
    hardnessUnit: snapshot.settings.display.hardness_unit === "gpg" ? "gpg" : "ppm",
    headerStatus: headerStatus(mainStatus, online),
    mainStatus,
    saltLevel: normalizeSaltLevel(snapshot.state.salt.level ?? snapshot.settings.salt.level),
    statusSubtitle: statusSubtitle(mainStatus, activeErrors.length),
    statusTitle: statusTitle(mainStatus),
    updatedAt: snapshot.updatedAt,
    volumeUnit: snapshot.settings.display.volume_unit === "gallons" ? "gal" : "l",
    weightUnit: snapshot.settings.display.weight_unit === "lbs" ? "lb" : "kg",
  };
}

export function errorLabel(key: string): string {
  return ERROR_LABELS[key] ?? key.replaceAll("_", " ");
}

export function normalizeSaltLevel(value: number | null | undefined): number | undefined {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return undefined;
  }
  return Math.max(1, Math.min(SALT_LEVEL_MAX, Math.round(value)));
}

export const CONTROL_FIELDS: ControlField[] = [
  {
    command: "set_hardness",
    currentValue: (snapshot) => hardnessCurrentOption(snapshot),
    description: "Incoming water hardness.",
    label: "Water hardness",
    options: (snapshot) => hardnessOptions(snapshot),
    path: "settings.hardness",
    section: "general",
    type: "select",
  },
  {
    command: "set_salt_level",
    currentValue: (snapshot) => snapshot.settings.salt.level,
    description: "Configured salt level on the device scale. Writable range is limited to 1..8.",
    label: "Salt level",
    max: 8,
    min: 1,
    path: "settings.salt.level",
    section: "general",
    step: 1,
    type: "number",
  },
  {
    command: "set_salt_type",
    currentValue: (snapshot) => snapshot.settings.salt.type,
    description: "Salt type used by the softener.",
    label: "Salt type",
    options: [
      { label: "NaCl", value: "nacl" },
      { label: "KCl", value: "kcl" },
    ],
    path: "settings.salt.type",
    section: "general",
    type: "select",
  },
  {
    command: "set_flow_alert_min_rate",
    currentValue: (snapshot) => snapshot.settings.flow_alert.min_rate,
    description: "Minimum flow rate that triggers the alert.",
    label: "Flow alert threshold",
    min: 0,
    path: "settings.flow_alert.min_rate",
    section: "general",
    step: 0.1,
    type: "number",
  },
  {
    command: "set_flow_alert_duration",
    currentValue: (snapshot) => snapshot.settings.flow_alert.duration,
    description: "Flow duration required to trigger the alert.",
    label: "Flow alert duration",
    min: 0,
    path: "settings.flow_alert.duration",
    section: "general",
    step: 1,
    type: "number",
    unit: "min",
  },
  {
    command: "set_regen_time",
    currentValue: (snapshot) => snapshot.settings.regen_time,
    description: "Scheduled regeneration start time.",
    label: "Regeneration time",
    path: "settings.regen_time",
    section: "regeneration",
    type: "time",
  },
  {
    command: "start_regeneration",
    currentValue: () => null,
    description: "Start a manual regeneration.",
    label: "Start regeneration",
    path: "control.start_regeneration",
    section: "regeneration",
    type: "boolean",
  },
  {
    command: "set_regeneration_backwash",
    currentValue: (snapshot) => snapshot.settings.regeneration.backwash,
    description: "Backwash duration.",
    label: "Backwash",
    min: 0,
    path: "settings.regeneration.backwash",
    section: "regeneration",
    step: 1,
    type: "number",
    unit: "s",
  },
  {
    command: "set_regeneration_fast_rinse",
    currentValue: (snapshot) => snapshot.settings.regeneration.fast_rinse,
    description: "Fast rinse duration.",
    label: "Fast rinse",
    min: 0,
    path: "settings.regeneration.fast_rinse",
    section: "regeneration",
    step: 1,
    type: "number",
    unit: "s",
  },
  {
    command: "set_regeneration_second_backwash",
    currentValue: (snapshot) => snapshot.settings.regeneration.second_backwash,
    description: "Second backwash duration.",
    label: "Second backwash",
    min: 0,
    path: "settings.regeneration.second_backwash",
    section: "regeneration",
    step: 1,
    type: "number",
    unit: "s",
  },
  {
    command: "set_regeneration_rinse_type",
    currentValue: (snapshot) => snapshot.settings.regeneration.rinse_type,
    description: "Raw rinse type code.",
    label: "Rinse type",
    min: 0,
    path: "settings.regeneration.rinse_type",
    section: "regeneration",
    step: 1,
    type: "number",
  },
  {
    command: "set_volume_unit",
    currentValue: (snapshot) => snapshot.settings.display.volume_unit,
    description: "Volume unit shown on the device panel.",
    label: "Volume unit",
    options: [
      { label: "Liters", value: "liters" },
      { label: "US gallons", value: "gallons" },
    ],
    path: "settings.display.volume_unit",
    section: "units",
    type: "select",
  },
  {
    command: "set_weight_unit",
    currentValue: (snapshot) => snapshot.settings.display.weight_unit,
    description: "Weight unit shown on the device panel.",
    label: "Weight unit",
    options: [
      { label: "Kilograms", value: "kilograms" },
      { label: "Pounds", value: "lbs" },
    ],
    path: "settings.display.weight_unit",
    section: "units",
    type: "select",
  },
  {
    command: "set_hardness_unit",
    currentValue: (snapshot) => snapshot.settings.display.hardness_unit,
    description: "Hardness unit shown on the device panel.",
    label: "Hardness unit",
    options: [
      { label: "PPM", value: "ppm" },
      { label: "GPG", value: "gpg" },
    ],
    path: "settings.display.hardness_unit",
    section: "units",
    type: "select",
  },
  {
    command: "set_date_format",
    currentValue: (snapshot) => snapshot.settings.display.date_format,
    description: "Date format shown on the device panel.",
    label: "Date format",
    options: [
      { label: "DD/MM/YYYY", value: "dd/mm/yyyy" },
      { label: "MM/DD/YYYY", value: "mm/dd/yyyy" },
    ],
    path: "settings.display.date_format",
    section: "units",
    type: "select",
  },
  {
    command: "set_time_format",
    currentValue: (snapshot) => snapshot.settings.display.time_format,
    description: "Time format shown on the device panel.",
    label: "Time format",
    options: [
      { label: "24h", value: "24h" },
      { label: "12h", value: "12h" },
    ],
    path: "settings.display.time_format",
    section: "units",
    type: "select",
  },
  {
    command: "set_aux_output_mode",
    currentValue: (snapshot) => snapshot.settings.aux_output.mode,
    description: "Auxiliary output mode.",
    label: "AUX mode",
    options: [
      { label: "Off", value: "off" },
      { label: "Bypass", value: "bypass" },
      { label: "Chlorine generator", value: "chlorine_generator" },
      { label: "Water flow", value: "water_flow" },
      { label: "Chemical feed", value: "chemical_feed" },
      { label: "Fast rinse", value: "fast_rinse" },
      { label: "On", value: "on" },
    ],
    path: "settings.aux_output.mode",
    section: "advanced",
    type: "select",
  },
  {
    command: "set_aux_chemical_feed_amount",
    currentValue: (snapshot) => snapshot.settings.aux_output.chemical_feed_amount,
    description: "Chemical feed amount.",
    label: "Chemical feed amount",
    min: 0,
    path: "settings.aux_output.chemical_feed_amount",
    section: "advanced",
    step: 0.1,
    type: "number",
  },
  {
    command: "set_feature_97_percent",
    currentValue: (snapshot) => booleanSelectValue(snapshot.settings.feature_97_percent),
    description: "97 percent capacity feature.",
    label: "97 percent feature",
    options: [
      { label: "Enabled", value: "enabled" },
      { label: "Disabled", value: "disabled" },
    ],
    path: "settings.feature_97_percent",
    section: "features",
    type: "select",
  },
  {
    command: "set_efficiency_mode",
    currentValue: (snapshot) => snapshot.settings.efficiency_mode,
    description: "Regeneration efficiency mode.",
    label: "Efficiency mode",
    options: [
      { label: "Auto", value: "auto" },
      { label: "Salt saving", value: "salt_saving" },
    ],
    path: "settings.efficiency_mode",
    section: "features",
    type: "select",
  },
  {
    command: "set_max_days_between_regenerations",
    currentValue: (snapshot) => snapshot.settings.max_days_between_regenerations,
    description: "Maximum interval between regenerations.",
    label: "Max regeneration interval",
    options: [
      { label: "Auto", value: "auto" },
      ...Array.from({ length: 15 }, (_, index) => {
        const value = String(index + 1);
        return { label: `${value} d`, value };
      }),
    ],
    path: "settings.max_days_between_regenerations",
    section: "features",
    type: "select",
  },
];

export function availableControlFields(commands: ControlCommand[] | undefined): ControlField[] {
  if (!commands) {
    return [];
  }
  const commandNames = new Set(commands.map((command) => command.name));
  return CONTROL_FIELDS.filter((field) => commandNames.has(field.command));
}

export function writablePaths(commands: ControlCommand[] | undefined): Set<string> {
  return new Set(availableControlFields(commands).map((field) => field.path));
}

export function buildDiagnosticRows(
  snapshot: SoftenerSnapshot,
  commands: ControlCommand[] | undefined,
  changedKeys: Set<string>,
): DiagnosticRow[] {
  const writable = writablePaths(commands);
  const rows: DiagnosticRow[] = [];

  addRows(rows, "device", "device", snapshot.device, writable, changedKeys);
  addRows(rows, "state", "state", snapshot.state, writable, changedKeys);
  addRows(rows, "settings", "settings", snapshot.settings, writable, changedKeys);

  return rows;
}

export function snapshotValueMap(snapshot: SoftenerSnapshot): Map<string, string> {
  const map = new Map<string, string>();
  flattenObject("device", snapshot.device, map);
  flattenObject("state", snapshot.state, map);
  flattenObject("settings", snapshot.settings, map);
  return map;
}

export function displayMetricValue(snapshot: SoftenerSnapshot, key: string): string {
  const normalized = normalizeSnapshot(snapshot);
  switch (key) {
    case "current_flow":
      return formatNumber(snapshot.state.current_flow, normalized.flowUnit);
    case "peak_flow":
      return formatNumber(snapshot.state.peak_flow, normalized.flowUnit);
    case "water_used_today":
      return formatNumber(snapshot.state.water_used_today, normalized.volumeUnit);
    case "treated_water_available":
      return formatNumber(snapshot.state.treated_water_available, normalized.volumeUnit);
    case "total_outlet_water":
      return formatNumber(snapshot.state.total_outlet_water, normalized.volumeUnit === "gal" ? "gal" : "m³", 3);
    case "hardness":
      return formatNumber(snapshot.settings.hardness, normalized.hardnessUnit);
    case "regen_time":
      return snapshot.settings.regen_time ?? "—";
    case "salt_level":
      return normalized.saltLevel === undefined ? "—" : `${normalized.saltLevel}/${SALT_LEVEL_MAX}`;
    default:
      return "—";
  }
}

function headerStatus(
  status: DeviceStatus,
  online: boolean,
): { label: string; status: DeviceStatus | "online" | "unknown" } {
  if (!online) {
    return { label: "Offline", status: "offline" };
  }
  if (status === "error") {
    return { label: "Error", status: "error" };
  }
  if (status === "regeneration") {
    return { label: "Regeneration", status: "regeneration" };
  }
  return { label: "Online", status: "online" };
}

function statusTitle(status: DeviceStatus): string {
  switch (status) {
    case "error":
      return "Needs attention";
    case "flowing":
      return "Soft water";
    case "offline":
      return "No connection";
    case "ok":
      return "Soft water";
    case "regeneration":
      return "Regeneration in progress";
  }
}

function statusSubtitle(status: DeviceStatus, activeErrorCount: number): string {
  switch (status) {
    case "error":
      return activeErrorCount > 0
        ? `Active errors: ${activeErrorCount}`
        : "The device reports a low salt level";
    case "flowing":
      return "Water is flowing";
    case "offline":
      return "The gateway has no active device session";
    case "ok":
      return "Everything is working correctly";
    case "regeneration":
      return "The device is running a regeneration cycle";
  }
}

function addRows(
  rows: DiagnosticRow[],
  source: DiagnosticRow["source"],
  prefix: string,
  value: unknown,
  writable: Set<string>,
  changedKeys: Set<string>,
): void {
  if (!isRecord(value)) {
    return;
  }

  for (const [key, item] of Object.entries(value)) {
    const path = `${prefix}.${key}`;
    if (isRecord(item)) {
      addRows(rows, source, path, item, writable, changedKeys);
      continue;
    }

    rows.push({
      active: item === true || (typeof item === "number" && item > 0),
      changed: changedKeys.has(path),
      description: diagnosticDescription(path),
      key: path,
      label: diagnosticLabel(path),
      source,
      value: item,
      writable: writable.has(path),
    });
  }
}

function flattenObject(prefix: string, value: unknown, output: Map<string, string>): void {
  if (!isRecord(value)) {
    output.set(prefix, formatValue(value));
    return;
  }
  for (const [key, item] of Object.entries(value)) {
    flattenObject(`${prefix}.${key}`, item, output);
  }
}

function isRecord(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function diagnosticLabel(path: string): string {
  if (path.includes(".unmapped.")) {
    return path.split(".unmapped.")[1]?.replaceAll("_", " ") ?? path;
  }

  const publicPath = path
    .replace(/^state\./, "")
    .replace(/^settings\./, "")
    .replace(/^device\./, "");

  if (path.startsWith("state.errors.")) {
    return publicPath.replace(/^errors\./, "error - ").replaceAll(".", " - ").replaceAll("_", " ");
  }

  return publicPath
    .replaceAll(".", " - ")
    .replaceAll("_", " ");
}

function diagnosticDescription(path: string): string {
  if (path.includes("errors.")) {
    return "Active alert/error reported by the device.";
  }
  if (path.includes("unmapped.")) {
    return "Raw diagnostic value without a public mapping.";
  }
  if (path.includes("regeneration")) {
    return "Regeneration-related field.";
  }
  if (path.includes("salt")) {
    return "Salt-related field.";
  }
  if (path.includes("display")) {
    return "Device display preference.";
  }
  return "Public API model value.";
}

export function formatDiagnosticValue(row: DiagnosticRow): string {
  if (row.key.endsWith(".active") || typeof row.value === "boolean") {
    return formatBoolean(row.value as boolean | null | undefined);
  }
  if (typeof row.value === "string") {
    return formatEnum(row.value);
  }
  if (typeof row.value === "number" && Number.isInteger(row.value)) {
    return formatInteger(row.value);
  }
  return formatValue(row.value);
}

export function hardnessControlValue(value: string): number {
  return Number(value.split(" ")[0]);
}

function hardnessOptions(snapshot: SoftenerSnapshot): { label: string; value: string }[] {
  const formatter = isMetricHardness(snapshot) ? hardnessMetricOption : hardnessImperialOption;
  return Array.from({ length: HARDNESS_MAX_GPG - HARDNESS_MIN_GPG + 1 }, (_, index) => {
    const label = formatter(HARDNESS_MIN_GPG + index);
    return { label, value: label };
  });
}

function hardnessCurrentOption(snapshot: SoftenerSnapshot): string | undefined {
  const value = snapshot.settings.hardness;
  if (value === null || value === undefined || Number.isNaN(value)) {
    return undefined;
  }

  if (isMetricHardness(snapshot)) {
    return hardnessMetricValueOption(value);
  }

  return hardnessImperialOption(Math.round(value));
}

function isMetricHardness(snapshot: SoftenerSnapshot): boolean {
  const value = snapshot.settings.hardness;
  return snapshot.settings.display.hardness_unit !== "gpg" || (value !== null && value !== undefined && value > HARDNESS_MAX_GPG);
}

function hardnessMetricOption(grains: number): string {
  return hardnessMetricValueOption(roundToNearest10(grains * PPM_PER_GPG));
}

function hardnessMetricValueOption(ppmValue: number): string {
  const ppm = roundToNearest10(ppmValue);
  const dh = Math.round(ppm / PPM_PER_DH);
  const fh = Math.round(ppm / PPM_PER_FH);
  return `${ppm} PPM (${dh} dH/${fh} fH)`;
}

function hardnessImperialOption(grains: number): string {
  const unit = grains === 1 ? "grain" : "grains";
  return `${grains} ${unit}`;
}

function booleanSelectValue(value: boolean | null | undefined): string | undefined {
  if (value === null || value === undefined) {
    return undefined;
  }

  return value ? "enabled" : "disabled";
}

function roundToNearest10(value: number): number {
  return Math.floor((value + 5) / 10) * 10;
}
