import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { ALERTS_NOW_MS, makeAlert } from "@/test/alerts";
import { renderRoutes } from "@/test/render";
import { server, VALID_REFRESH } from "@/test/server";
import { AlertsPageContent } from "./alerts-page-content";

function renderPage() {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  server.use(
    http.get("/api/alerts", () =>
      HttpResponse.json([
        makeAlert({ id: "open-temp" }),
        makeAlert({
          id: "open-ssh",
          metric: "ssh",
          device_id: "ip:203.0.113.5",
          threshold: 0,
          opened_value: 1,
          peak_value: 3,
        }),
        makeAlert({
          id: "done-hum",
          device_id: "esp-exterieur",
          metric: "humidity",
          threshold: 70,
          peak_value: 74,
          opened_at: new Date(ALERTS_NOW_MS - 30 * 60_000).toISOString(),
          resolved_at: new Date(ALERTS_NOW_MS - 10 * 60_000).toISOString(),
          resolved_value: 67,
        }),
      ]),
    ),
    http.get("/api/sensors/devices", () =>
      HttpResponse.json([
        { device_id: "esp-interieur", last_seen: "2026-10-06T09:00:00Z" },
        { device_id: "esp-exterieur", last_seen: "2026-10-06T09:00:00Z" },
      ]),
    ),
  );
  return renderRoutes(
    [{ path: "/alertes", element: <AlertsPageContent nowMs={ALERTS_NOW_MS} /> }],
    "/alertes",
  );
}

describe("AlertsPageContent", () => {
  it("summarises, shows open alerts as tiles and the history as a timeline grouped by day", async () => {
    renderPage();
    expect(await screen.findByText("Ouvertes maintenant")).toBeInTheDocument();
    const open = within(screen.getByRole("heading", { name: "En cours" }).parentElement!);
    expect(open.getAllByRole("listitem")).toHaveLength(2);
    expect(open.getByText("31,2 °C")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Historique" })).toBeInTheDocument();
    const today = within(screen.getByRole("list", { name: "Alertes résolues, Aujourd'hui" }));
    const rows = today.getAllByRole("listitem");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("Humidité 74 % > 70 %");
    expect(rows[0]).toHaveTextContent("esp-exterieur");
    expect(rows[0]).toHaveTextContent("20 min");
  });

  it("filters by state, metric and device", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "Historique" });
    await user.click(screen.getByRole("radio", { name: "Ouvertes" }));
    expect(screen.queryByRole("heading", { name: "Historique" })).toBeNull();
    expect(screen.getByRole("heading", { name: "En cours" })).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Toutes" }));
    await user.click(screen.getByRole("radio", { name: "Humidité" }));
    expect(screen.queryByRole("heading", { name: "En cours" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Historique" })).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "SSH" }));
    expect(screen.getByRole("heading", { name: "En cours" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Historique" })).toBeNull();
    await user.click(screen.getByRole("radio", { name: "Toutes les métriques" }));
    await user.click(screen.getByRole("combobox", { name: "Appareil" }));
    await user.click(await screen.findByRole("option", { name: "esp-exterieur" }));
    expect(screen.queryByRole("heading", { name: "En cours" })).toBeNull();
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });

  it("says so when nothing matches", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "Historique" });
    await user.click(screen.getByRole("combobox", { name: "Appareil" }));
    await user.click(await screen.findByRole("option", { name: "esp-exterieur" }));
    await user.click(screen.getByRole("radio", { name: "Ouvertes" }));
    expect(screen.getByText("Aucune alerte")).toBeInTheDocument();
  });

  it("says when the history is truncated to the newest alerts", async () => {
    localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
    server.use(
      http.get("/api/alerts", ({ request }) => {
        const limit = Number(new URL(request.url).searchParams.get("limit"));
        expect(limit).toBe(500);
        return HttpResponse.json(
          Array.from({ length: limit }, (_, i) =>
            makeAlert({
              id: `a${i}`,
              opened_at: new Date(ALERTS_NOW_MS - (i + 2) * 60_000).toISOString(),
              resolved_at: new Date(ALERTS_NOW_MS - (i + 1) * 60_000).toISOString(),
              resolved_value: 29,
            }),
          ),
        );
      }),
    );
    renderRoutes(
      [{ path: "/alertes", element: <AlertsPageContent nowMs={ALERTS_NOW_MS} /> }],
      "/alertes",
    );
    await screen.findByRole("heading", { name: "Historique" });
    expect(
      screen.getByText("Seules les 500 alertes les plus récentes sont affichées."),
    ).toBeInTheDocument();
  });

  it("closes an ssh alert by hand and moves it to the history", async () => {
    const user = userEvent.setup();
    renderPage();
    const open = within((await screen.findByRole("heading", { name: "En cours" })).parentElement!);
    const tiles = open.getAllByRole("listitem");
    expect(within(tiles[0]).queryByRole("button", { name: "Clôturer" })).toBeNull(); // température
    const close = within(tiles[1]).getByRole("button", { name: "Clôturer" });
    await user.click(close);
    const history = within(
      await screen.findByRole("list", { name: "Alertes résolues, Aujourd'hui" }),
    );
    expect(history.getAllByRole("listitem")).toHaveLength(2);
    expect(history.getByText("SSH : 3 tentatives refusées depuis 203.0.113.5")).toBeInTheDocument();
    expect(open.getAllByRole("listitem")).toHaveLength(1);
  });
});
