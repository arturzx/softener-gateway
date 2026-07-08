import { Route, Routes } from "react-router-dom";

import { appRoutes, defaultRoute } from "./app/router";
import { AppLayout } from "./shared/components/AppLayout";
import { EmptyState } from "./shared/components/EmptyState";

export default function App() {
  return (
    <AppLayout>
      <Routes>
        <Route element={defaultRoute} path="/" />
        {appRoutes.map((route) => (
          <Route element={route.element} key={route.path} path={route.path} />
        ))}
        <Route
          element={
            <EmptyState
              description="This view does not exist or has been moved."
              title="Page not found"
            />
          }
          path="*"
        />
      </Routes>
    </AppLayout>
  );
}
