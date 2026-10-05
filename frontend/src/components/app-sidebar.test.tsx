import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { routes } from "@/app/router";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderRoutes } from "@/test/render";
import { TEST_USER, VALID_REFRESH } from "@/test/server";

function renderAuthenticated(path: string) {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderRoutes(routes, path);
}

async function sidebar() {
  return within(await screen.findByRole("navigation", { name: "Navigation principale" }));
}

describe("AppSidebar", () => {
  it("links to the dashboard and the camera", async () => {
    renderAuthenticated("/");
    const nav = await sidebar();
    expect(nav.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
    expect(nav.getByRole("link", { name: "Caméra" })).toHaveAttribute("href", "/camera");
  });

  it("marks the current page", async () => {
    renderAuthenticated("/camera");
    const nav = await sidebar();
    expect(nav.getByRole("link", { name: "Caméra" })).toHaveAttribute("aria-current", "page");
    expect(nav.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute("aria-current");
  });

  it("shows the account in the footer and logs out", async () => {
    const user = userEvent.setup();
    renderAuthenticated("/");
    const footer = within(await screen.findByRole("region", { name: "Mon compte" }));
    expect(footer.getByText(TEST_USER.email)).toBeInTheDocument();
    expect(footer.getByText("AL")).toBeInTheDocument();
    expect(footer.queryByText(/créé le/i)).not.toBeInTheDocument();
    await user.click(footer.getByRole("button", { name: "Déconnexion" }));
    expect(await screen.findByRole("heading", { name: "Connexion" })).toBeInTheDocument();
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBeNull();
  });

  it("marks the dashboard link as current on /", async () => {
    renderAuthenticated("/");
    const nav = await sidebar();
    expect(nav.getByRole("link", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
  });

  describe("on a phone", () => {
    const desktopWidth = window.innerWidth;
    afterEach(() => {
      window.innerWidth = desktopWidth;
    });

    it("closes the menu sheet after navigating", async () => {
      window.innerWidth = 500;
      const user = userEvent.setup();
      renderAuthenticated("/");
      await screen.findByRole("heading", { name: "Dashboard" });
      await act(async () => {
        await user.click(screen.getByRole("button", { name: "Afficher ou masquer le menu" }));
      });
      const sheet = within(await screen.findByRole("dialog"));
      await user.click(sheet.getByRole("link", { name: "Caméra" }));
      expect(await screen.findByRole("heading", { name: "Caméra" })).toBeInTheDocument();
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });
});
