import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router";
import { ThemeProvider } from "@/features/theme/theme-provider";

export function renderWithProviders(ui: ReactElement) {
  return render(<ThemeProvider>{ui}</ThemeProvider>);
}

export function renderRoutes(routes: RouteObject[], initialPath = "/") {
  const router = createMemoryRouter(routes, { initialEntries: [initialPath] });
  return {
    router,
    ...render(
      <ThemeProvider>
        <RouterProvider router={router} />
      </ThemeProvider>,
    ),
  };
}
