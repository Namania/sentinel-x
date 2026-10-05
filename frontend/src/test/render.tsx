import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router";
import { AuthProvider } from "@/features/auth/auth-provider";
import { ThemeProvider } from "@/features/theme/theme-provider";

export function renderWithProviders(ui: ReactElement) {
  return render(
    <ThemeProvider>
      <AuthProvider>{ui}</AuthProvider>
    </ThemeProvider>,
  );
}

export function renderRoutes(routes: RouteObject[], initialPath = "/") {
  const router = createMemoryRouter(routes, { initialEntries: [initialPath] });
  return {
    router,
    ...render(
      <ThemeProvider>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </ThemeProvider>,
    ),
  };
}
