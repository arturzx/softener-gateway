import type { Icon } from "@tabler/icons-react";
import {
  IconActivityHeartbeat,
  IconGauge,
  IconInfoCircle,
  IconSettings,
} from "@tabler/icons-react";
import type { ReactElement } from "react";
import { Navigate } from "react-router-dom";

import { DetailsPage } from "../features/details/DetailsPage";
import { DiagnosticsPage } from "../features/diagnostics/DiagnosticsPage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { StatusPage } from "../features/status/StatusPage";

export type AppRoute = {
  icon: Icon;
  label: string;
  path: string;
  element: ReactElement;
};

export const primaryRoutes: AppRoute[] = [
  { icon: IconGauge, label: "Status", path: "/status", element: <StatusPage /> },
  { icon: IconInfoCircle, label: "Details", path: "/details", element: <DetailsPage /> },
  { icon: IconSettings, label: "Settings", path: "/settings", element: <SettingsPage /> },
];

export const diagnosticsRoute: AppRoute = {
  icon: IconActivityHeartbeat,
  label: "Diagnostics",
  path: "/diagnostics",
  element: <DiagnosticsPage />,
};

export const appRoutes: AppRoute[] = [...primaryRoutes, diagnosticsRoute];

export const defaultRoute = <Navigate replace to="/status" />;
