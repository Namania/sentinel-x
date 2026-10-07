import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ALERTS_NOW_MS, makeAlert } from "@/test/alerts";
import { renderRoutes } from "@/test/render";
import type { Alert } from "./alerts-api";
import { AlertsCard } from "./alerts-card";

const LINK = "Alertes, voir l'historique";

function renderCard(alerts: Alert[], status: "loading" | "ready" | "error" = "ready") {
  return renderRoutes([
    { path: "/", element: <AlertsCard status={status} alerts={alerts} nowMs={ALERTS_NOW_MS} /> },
    { path: "/alertes", element: <h1>Alertes</h1> },
  ]);
}

const resolvedAt = (minutesAgo: number, lastedS: number) =>
  makeAlert({
    opened_at: new Date(ALERTS_NOW_MS - minutesAgo * 60_000 - lastedS * 1000).toISOString(),
    resolved_at: new Date(ALERTS_NOW_MS - minutesAgo * 60_000).toISOString(),
    resolved_value: 29,
  });

describe("AlertsCard", () => {
  it("links to the alerts page and shows open alerts as tiles with peak, bound and excess", async () => {
    renderCard([makeAlert({ id: "a" }), makeAlert({ id: "b", metric: "gas", threshold: 0 })]);
    const link = screen.getByRole("link", { name: LINK });
    expect(link).toHaveAttribute("href", "/alertes");
    expect(within(link).getByText("2 ouvertes")).toBeInTheDocument();
    const tiles = within(within(link).getByRole("list", { name: "Alertes ouvertes" })).getAllByRole(
      "listitem",
    );
    expect(tiles).toHaveLength(2);
    expect(tiles[0]).toHaveTextContent("Température");
    expect(tiles[0]).toHaveTextContent("esp-interieur");
    expect(tiles[0]).toHaveTextContent("31,2 °C");
    expect(tiles[0]).toHaveTextContent("dépasse la borne de 30 °C");
    expect(tiles[0]).toHaveTextContent("+1,2 °C");
    expect(tiles[0]).toHaveTextContent("Ouverte");
    expect(tiles[0]).toHaveTextContent("depuis 4 min");
    expect(tiles[1]).toHaveTextContent("alerte signalée par l'ESP");
  });

  it("says everything is within bounds and lists at most three resolved ones", () => {
    const resolved = Array.from({ length: 5 }, (_, i) => ({
      ...resolvedAt(i + 1, 40),
      id: `r${i}`,
    }));
    renderCard(resolved);
    const link = screen.getByRole("link", { name: LINK });
    expect(within(link).getByText("Aucune ouverte")).toBeInTheDocument();
    expect(within(link).getByText("Tout est dans les bornes")).toBeInTheDocument();
    expect(within(link).getByText("5 résolues aujourd'hui")).toBeInTheDocument();
    const rows = within(
      within(link).getByRole("list", { name: "Dernières alertes résolues" }),
    ).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("Température 31,2 °C > 30 °C");
    expect(rows[0]).toHaveTextContent("→");
    expect(rows[0]).toHaveTextContent("40 s");
  });

  it("shows a skeleton while loading and a message on error", () => {
    const { unmount } = renderCard([], "loading");
    expect(screen.getByRole("status", { name: "Chargement des alertes" })).toBeInTheDocument();
    unmount();
    renderCard([], "error");
    expect(screen.getByText("Alertes indisponibles")).toBeInTheDocument();
  });
});
