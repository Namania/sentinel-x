import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { routes } from "@/app/router";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderRoutes } from "@/test/render";
import { sensorsLink, server, VALID_REFRESH } from "@/test/server";

function renderDashboard() {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderRoutes(routes, "/");
}

describe("Dashboard (wall screen)", () => {
  it("shows the camera card, the server card and the sensors section under one heading", async () => {
    renderDashboard();
    expect(await screen.findByRole("heading", { level: 1, name: "Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Caméra, voir en grand" })).toHaveAttribute(
      "href",
      "/camera",
    );
    expect(screen.getByRole("link", { name: "Santé du serveur, voir le détail" })).toHaveAttribute(
      "href",
      "/serveur",
    );
    const sensors = within(await screen.findByRole("region", { name: "Capteurs" }));
    expect(sensors.getByRole("heading", { level: 2, name: "Capteurs" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("opens the camera page when the camera card is clicked", async () => {
    const user = userEvent.setup();
    const { router } = renderDashboard();
    await user.click(await screen.findByRole("link", { name: "Caméra, voir en grand" }));
    expect(router.state.location.pathname).toBe("/camera");
    expect(await screen.findByRole("heading", { name: "Caméra" })).toBeInTheDocument();
  });

  it("shows the alerts card between the top row and the sensors, linking to /alertes", async () => {
    const user = userEvent.setup();
    const { router } = renderDashboard();
    const card = await screen.findByRole("link", { name: "Alertes, voir l'historique" });
    expect(card).toHaveAttribute("href", "/alertes");
    await user.click(card);
    expect(router.state.location.pathname).toBe("/alertes");
  });

  it("shares one WebSocket between the sensors, the server card, the alerts and the nav", async () => {
    let connections = 0;
    server.use(sensorsLink.addEventListener("connection", () => void connections++));
    renderDashboard();
    await screen.findByRole("link", { name: "Alertes, voir l'historique" });
    await screen.findByRole("group", { name: "CPU" });
    await new Promise((r) => setTimeout(r, 300));
    expect(connections).toBe(1);
  });
});
