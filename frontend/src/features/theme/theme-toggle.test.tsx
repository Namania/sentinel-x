import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { THEME_STORAGE_KEY } from "./theme-context";
import { ThemeProvider } from "./theme-provider";
import { ThemeToggle } from "./theme-toggle";

it("lets the user pick a theme from the menu", async () => {
  const user = userEvent.setup();
  render(
    <ThemeProvider>
      <ThemeToggle />
    </ThemeProvider>,
  );
  await user.click(screen.getByRole("button", { name: "Changer de thème" }));
  expect(await screen.findByRole("menuitemradio", { name: "Sombre" })).toBeChecked();
  await user.click(screen.getByRole("menuitemradio", { name: "Clair" }));
  expect(document.documentElement).toHaveClass("light");
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
});
