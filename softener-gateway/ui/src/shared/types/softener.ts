export type DeviceStatus = "error" | "flowing" | "offline" | "ok" | "regeneration";

export type JsonObject = Record<string, unknown>;

export type DeviceInfo = {
  system_type?: string | null;
  model_id?: number | null;
  model_description?: string | null;
  serial_number?: string | null;
  product_serial_number?: string | null;
  software_version?: string | null;
  esp_software_part_number?: string | null;
  ota_status?: number | null;
  pwa_number?: string | null;
  build_date_code?: string | null;
  build_year?: number | null;
  build_day?: number | null;
  build_date?: string | null;
  operation_time?: number | null;
  power_outage_count?: number | null;
  time_loss_count?: number | null;
};

export type RegenerationState = {
  active?: boolean | null;
  trigger?: string | null;
  stage?: string | null;
  remaining?: number | null;
  stage_remaining?: number | null;
  since_last?: number | null;
  total_count?: number | null;
  manual_count?: number | null;
  average_interval?: number | null;
};

export type SaltState = {
  level?: number | null;
  low?: boolean | null;
  remaining_estimate?: number | null;
  total_used?: number | null;
  average_per_regeneration?: number | null;
  efficiency?: number | null;
};

export type CapacityState = {
  operating?: number | null;
  remaining?: number | null;
  average_exhaustion?: number | null;
};

export type HardnessRemovedState = {
  since_regeneration?: number | null;
  daily_average?: number | null;
  total?: number | null;
};

export type DailyUsageProfileDay = {
  average?: number | null;
  deviation?: number | null;
};

export type DailyUsageProfile = {
  day_1?: DailyUsageProfileDay | null;
  day_2?: DailyUsageProfileDay | null;
  day_3?: DailyUsageProfileDay | null;
  day_4?: DailyUsageProfileDay | null;
  day_5?: DailyUsageProfileDay | null;
  day_6?: DailyUsageProfileDay | null;
  day_7?: DailyUsageProfileDay | null;
};

export type State = {
  online: boolean;
  module_connected?: boolean | null;
  device_connected?: boolean | null;
  time?: string | null;
  current_flow?: number | null;
  peak_flow?: number | null;
  water_used_today?: number | null;
  average_daily_usage?: number | null;
  treated_water_available?: number | null;
  total_outlet_water?: number | null;
  total_untreated_water?: number | null;
  regeneration: RegenerationState;
  salt: SaltState;
  capacity: CapacityState;
  hardness_removed: HardnessRemovedState;
  daily_usage_profile: DailyUsageProfile;
  errors: Record<string, boolean>;
  wifi_signal_strength?: number | null;
  unmapped: JsonObject;
};

export type SaltType = "kcl" | "nacl";
export type VolumeUnit = "gallons" | "liters";
export type WeightUnit = "kilograms" | "lbs";
export type HardnessUnit = "gpg" | "ppm";
export type DateFormat = "dd/mm/yyyy" | "mm/dd/yyyy";
export type TimeFormat = "12h" | "24h";
export type EfficiencyMode = "auto" | "salt_saving";
export type AuxOutputMode =
  | "bypass"
  | "chemical_feed"
  | "chlorine_generator"
  | "fast_rinse"
  | "off"
  | "on"
  | "water_flow";

export type Settings = {
  timezone?: string | null;
  hardness?: number | null;
  regen_time?: string | null;
  salt: {
    type?: SaltType | null;
    level?: number | null;
  };
  flow_alert: {
    min_rate?: number | null;
    duration?: number | null;
  };
  display: {
    volume_unit?: VolumeUnit | null;
    weight_unit?: WeightUnit | null;
    hardness_unit?: HardnessUnit | null;
    date_format?: DateFormat | null;
    time_format?: TimeFormat | null;
  };
  aux_output: {
    mode?: AuxOutputMode | null;
    chemical_feed_amount?: number | null;
  };
  regeneration: {
    fill?: number | null;
    draw?: number | null;
    backwash?: number | null;
    fast_rinse?: number | null;
    second_backwash?: number | null;
    rinse_type?: number | null;
  };
  feature_97_percent?: boolean | null;
  efficiency_mode?: EfficiencyMode | null;
  max_days_between_regenerations?: "auto" | number | null;
  unmapped: JsonObject;
};

export type SoftenerSnapshot = {
  device: DeviceInfo;
  state: State;
  settings: Settings;
  updatedAt: string;
};

export type ControlCommand = {
  name: string;
  requiresValue: boolean;
};

export type ControlFieldType = "boolean" | "number" | "select" | "time";

export type ControlField = {
  command: string;
  currentValue: (snapshot: SoftenerSnapshot) => boolean | number | string | null | undefined;
  description: string;
  label: string;
  max?: number;
  min?: number;
  options?: { label: string; value: string }[] | ((snapshot: SoftenerSnapshot) => { label: string; value: string }[]);
  path: string;
  section: "advanced" | "app" | "features" | "general" | "regeneration" | "units";
  step?: number;
  type: ControlFieldType;
  unit?: string;
};

export type DiagnosticRow = {
  active: boolean;
  changed: boolean;
  description: string;
  key: string;
  label: string;
  source: "device" | "settings" | "state";
  timestamp?: string;
  value: unknown;
  writable: boolean;
};
