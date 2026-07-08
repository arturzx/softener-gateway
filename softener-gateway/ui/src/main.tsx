import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import "./styles.css";

import { MantineProvider } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { HashRouter } from "react-router-dom";

import App from "./App";
import { queryClient } from "./app/queryClient";
import { theme } from "./app/theme";

const root = document.getElementById("root");

if (root === null) {
  throw new Error("Missing root element");
}

createRoot(root).render(
  <StrictMode>
    <MantineProvider defaultColorScheme="light" forceColorScheme="light" theme={theme}>
      <QueryClientProvider client={queryClient}>
        <HashRouter>
          <App />
        </HashRouter>
      </QueryClientProvider>
      <Notifications position="bottom-center" />
    </MantineProvider>
  </StrictMode>,
);
