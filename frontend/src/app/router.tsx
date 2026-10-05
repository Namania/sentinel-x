import { createBrowserRouter, type RouteObject } from "react-router";
import { CameraPage } from "@/pages/camera";
import { NotFoundPage } from "@/pages/not-found";
import { RootLayout } from "./root-layout";

export const routes: RouteObject[] = [
  {
    element: <RootLayout />,
    children: [
      { index: true, element: <CameraPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
];

export function createAppRouter() {
  return createBrowserRouter(routes);
}
