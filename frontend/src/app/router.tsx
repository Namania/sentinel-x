import { createBrowserRouter, type RouteObject } from "react-router";
import { CameraPage } from "@/pages/camera";
import { LoginPage } from "@/pages/login";
import { NotFoundPage } from "@/pages/not-found";
import { RequireAuth } from "./require-auth";
import { RootLayout } from "./root-layout";

export const routes: RouteObject[] = [
  {
    element: <RootLayout />,
    children: [
      { path: "/login", element: <LoginPage /> },
      {
        element: <RequireAuth />,
        children: [{ index: true, element: <CameraPage /> }],
      },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export function createAppRouter() {
  return createBrowserRouter(routes);
}
