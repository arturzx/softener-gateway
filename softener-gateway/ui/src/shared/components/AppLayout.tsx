import {
  ActionIcon,
  AppShell,
  Box,
  Burger,
  Container,
  Group,
  SegmentedControl,
  Stack,
  Text,
  ThemeIcon,
  Title,
  Tooltip,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconActivityHeartbeat, IconDroplet } from "@tabler/icons-react";
import type { ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { diagnosticsRoute, primaryRoutes } from "../../app/router";
import { useSoftenerSnapshotQuery } from "../../api/softenerApi";
import { StateBadge } from "./StateBadge";

type AppLayoutProps = {
  children: ReactNode;
};

export function AppLayout({ children }: AppLayoutProps) {
  const [opened, { toggle }] = useDisclosure(false);
  const location = useLocation();
  const navigate = useNavigate();
  const snapshotQuery = useSoftenerSnapshotQuery();
  const modelName = snapshotQuery.data?.device.model_description?.trim();

  const currentRoute = primaryRoutes.find((route) => location.pathname === route.path);
  const diagnosticsActive = location.pathname === diagnosticsRoute.path;
  const deviceConnectionStatus = deviceConnectionBadge(snapshotQuery.data?.state.device_connected);

  return (
    <AppShell className="app-shell" header={{ height: { base: 116, md: 78 } }} padding={0}>
      <AppShell.Header className="app-header">
        <Container h="100%" maw={1180} px={{ base: "md", md: "xl" }}>
          <Stack gap="xs" h="100%" justify="center">
            <Group className="app-header__row" justify="space-between" wrap="nowrap">
              <Group gap="sm" wrap="nowrap">
                <Burger hiddenFrom="md" opened={opened} size="sm" onClick={toggle} />
                <ThemeIcon aria-hidden="true" className="app-brand__mark" radius="lg" size={44} variant="light">
                  <IconDroplet size={24} stroke={1.8} />
                </ThemeIcon>
                <Box miw={0}>
                  <Title order={1} size="h3">
                    Water softener
                  </Title>
                  {modelName ? (
                    <Text c="dimmed" className="app-brand__subtitle" fw={400} lh={1.05} size="xs" title={modelName}>
                      {modelName}
                    </Text>
                  ) : null}
                </Box>
              </Group>

              <Group className="top-navigation" visibleFrom="md">
                {primaryRoutes.map((route) => {
                  const IconComponent = route.icon;

                  return (
                    <NavLink
                      className={({ isActive }) =>
                        `top-navigation__item${isActive ? " top-navigation__item--active" : ""}`
                      }
                      key={route.path}
                      to={route.path}
                    >
                      <IconComponent size={17} stroke={1.8} />
                      <span>{route.label}</span>
                    </NavLink>
                  );
                })}
              </Group>

              <Group className="app-status-bar" gap="sm" wrap="nowrap">
                <Stack align="center" gap={2}>
                  <StateBadge label={deviceConnectionStatus.label} status={deviceConnectionStatus.status} />
                  <Text c="dimmed" lh={1.2} size="xs">
                    © AZX
                  </Text>
                </Stack>
                <Tooltip label="Diagnostics">
                  <ActionIcon
                    aria-label="Open diagnostics"
                    className={`diagnostics-nav${diagnosticsActive ? " diagnostics-nav--active" : ""}`}
                    component={NavLink}
                    size="sm"
                    to={diagnosticsRoute.path}
                    variant="subtle"
                  >
                    <IconActivityHeartbeat size={16} stroke={1.8} />
                  </ActionIcon>
                </Tooltip>
              </Group>
            </Group>

            <SegmentedControl
              className="mobile-nav"
              data={primaryRoutes.map((route) => ({ label: route.label, value: route.path }))}
              hiddenFrom="md"
              onChange={(value) => {
                navigate(value);
              }}
              radius="lg"
              value={currentRoute?.path ?? ""}
            />
          </Stack>
        </Container>
      </AppShell.Header>
      <AppShell.Main className="app-main">
        <Box className="app-content">{children}</Box>
      </AppShell.Main>
    </AppShell>
  );
}

function deviceConnectionBadge(deviceConnected: boolean | null | undefined) {
  if (deviceConnected === true) {
    return { label: "Connected", status: "online" as const };
  }
  if (deviceConnected === false) {
    return { label: "Disconnected", status: "offline" as const };
  }

  return { label: "No data", status: "unknown" as const };
}
