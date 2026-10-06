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
  it("lists every alert in a table, open ones first", async () => {
    renderPage();
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1); // skip the header
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Ouverte");
    expect(rows[0]).toHaveTextContent("Température");
    expect(rows[0]).toHaveTextContent("31,2 °C > 30 °C");
    expect(rows[1]).toHaveTextContent("Résolue");
    expect(rows[1]).toHaveTextContent("20 min");
  });

  it("filters by state and by device", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");
    await user.click(screen.getByRole("radio", { name: "Ouvertes" }));
    expect(screen.getAllByRole("row")).toHaveLength(2);
    await user.click(screen.getByRole("radio", { name: "Toutes" }));
    await user.click(screen.getByRole("combobox", { name: "Appareil" }));
    await user.click(await screen.findByRole("option", { name: "esp-exterieur" }));
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("esp-exterieur");
  });

  it("says so when nothing matches", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("table");
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
    await screen.findByRole("table");
    expect(
      screen.getByText("Seules les 500 alertes les plus récentes sont affichées."),
    ).toBeInTheDocument();
  });
});
