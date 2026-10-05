import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { installMatchMedia } from "@/test/match-media";
import { THEME_STORAGE_KEY } from "./theme-context";
import { ThemeProvider } from "./theme-provider";
import { useTheme } from "./use-theme";

function Probe() {
  const { theme, setTheme } = useTheme();
  return (
    <div>
      <p>theme:{theme}</p>
      <button onClick={() => setTheme("light")}>light</button>
      <button onClick={() => setTheme("system")}>system</button>
    </div>
  );
}

const root = () => document.documentElement;

describe("ThemeProvider", () => {
  it("defaults to dark", () => {
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(screen.getByText("theme:dark")).toBeInTheDocument();
    expect(root()).toHaveClass("dark");
  });

  it("restores the stored theme", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(root()).toHaveClass("light");
    expect(root()).not.toHaveClass("dark");
  });

  it("falls back to dark when the stored value is invalid", () => {
    localStorage.setItem(THEME_STORAGE_KEY, "blue");
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(screen.getByText("theme:dark")).toBeInTheDocument();
    expect(root()).toHaveClass("dark");
  });

  it("persists the chosen theme", async () => {
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    await user.click(screen.getByRole("button", { name: "light" }));
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(root()).toHaveClass("light");
  });

  it("follows the OS preference in system mode", async () => {
    const media = installMatchMedia(true);
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    await user.click(screen.getByRole("button", { name: "system" }));
    expect(root()).toHaveClass("dark");
    act(() => media.setMatches(false));
    expect(root()).toHaveClass("light");
  });
});
