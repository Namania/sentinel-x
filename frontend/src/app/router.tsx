import { createBrowserRouter, type RouteObject } from "react-router";
import { AlertsPage } from "@/pages/alerts";
import { CameraPage } from "@/pages/camera";
import { DashboardPage } from "@/pages/dashboard";
import { LoginPage } from "@/pages/login";
import { NotFoundPage } from "@/pages/not-found";
import { ServerPage } from "@/pages/server";
import { AppShell } from "./app-shell";
import { RequireAuth } from "./require-auth";
import { RootLayout } from "./root-layout";

export const routes: RouteObject[] = [
  {
    // Public pages: plain header, no sidebar.
    element: <RootLayout />,
    children: [
      { path: "/login", element: <LoginPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
  {
    // Authenticated area: sidebar shell.
    element: <RequireAuth />,
    children: [
      {
        element: <AppShell />,
        children: [
          { index: true, element: <DashboardPage /> },
          { path: "/camera", element: <CameraPage /> },
          { path: "/serveur", element: <ServerPage /> },
          { path: "/alertes", element: <AlertsPage /> },
        ],
      },
    ],
  },
];

export function createAppRouter() {
  return createBrowserRouter(routes);
}
