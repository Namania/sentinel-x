import { act, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import { routes } from "@/app/router";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderRoutes } from "@/test/render";
import { server, TEST_USER, VALID_REFRESH } from "@/test/server";

function renderAuthenticated(path: string) {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderRoutes(routes, path);
}

async function sidebar() {
  return within(await screen.findByRole("navigation", { name: "Navigation principale" }));
}

describe("AppSidebar", () => {
  it("links to the dashboard, the camera, the server, the alerts and the SSH log", async () => {
    renderAuthenticated("/");
    const nav = await sidebar();
    expect(nav.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
    expect(nav.getByRole("link", { name: "Caméra" })).toHaveAttribute("href", "/camera");
    expect(nav.getByRole("link", { name: "Serveur" })).toHaveAttribute("href", "/serveur");
    expect(nav.getByRole("link", { name: /^Alertes/ })).toHaveAttribute("href", "/alertes");
    expect(nav.getByRole("link", { name: "Accès SSH" })).toHaveAttribute("href", "/ssh");
  });

  it("shows the number of open alerts on the Alertes entry", async () => {
    server.use(http.get("/api/alerts/summary", () => HttpResponse.json({ open: 2 })));
    renderAuthenticated("/");
    const nav = await sidebar();
    expect(await nav.findByText("2 alertes ouvertes")).toBeInTheDocument();
    expect(nav.getByText("2", { selector: "[aria-hidden]" })).toBeInTheDocument();
    // The menu button clips its content; the badge sits on the icon's corner, so it must not.
    expect(nav.getByRole("link", { name: /^Alertes/ })).toHaveClass("overflow-visible");
  });

  it("starts collapsed so the wall screen keeps the room for the content", async () => {
    renderAuthenticated("/");
    await sidebar();
    expect(document.querySelector('[data-slot="sidebar"]')).toHaveAttribute(
      "data-state",
      "collapsed",
    );
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
    // Collapsed by default: open the sidebar to see the account details.
    await user.click(await screen.findByRole("button", { name: "Afficher ou masquer le menu" }));
    const footer = within(await screen.findByRole("region", { name: "Mon compte" }));
    expect(footer.getByText(TEST_USER.email)).toBeInTheDocument();
    expect(footer.getByText("AL")).toBeInTheDocument();
    expect(footer.queryByText(/créé le/i)).not.toBeInTheDocument();
    await user.click(footer.getByRole("button", { name: "Déconnexion" }));
    expect(await screen.findByRole("heading", { name: "Connexion" })).toBeInTheDocument();
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBeNull();
  });

  it("shows the logo while collapsed, the full name once opened", async () => {
    const user = userEvent.setup();
    renderAuthenticated("/");
    await screen.findByRole("heading", { name: "Dashboard" });
    expect(screen.getByRole("img", { name: "SENTINEL-X" })).toHaveAttribute("src", "/favicon.svg");
    expect(screen.queryByText("S")).not.toBeInTheDocument();
    expect(screen.queryByText("SENTINEL-X")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Afficher ou masquer le menu" }));
    expect(screen.getByText("SENTINEL-X")).toBeInTheDocument();
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
      const sheet = within(await screen.findByRole("dialog", { name: "Menu" }));
      await user.click(sheet.getByRole("link", { name: "Caméra" }));
      expect(await screen.findByRole("heading", { name: "Caméra" })).toBeInTheDocument();
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });
});
