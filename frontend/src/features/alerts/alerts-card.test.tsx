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

describe("AlertsCard", () => {
  it("links to the alerts page and counts the open ones", async () => {
    renderCard([makeAlert({ id: "a" }), makeAlert({ id: "b", metric: "gas", threshold: 0 })]);
    const link = screen.getByRole("link", { name: LINK });
    expect(link).toHaveAttribute("href", "/alertes");
    expect(within(link).getByText("2 ouvertes")).toBeInTheDocument();
    const items = within(link).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Ouverte");
    expect(items[0]).toHaveTextContent("esp-interieur");
    expect(items[0]).toHaveTextContent("Température 31,2 °C > 30 °C");
    expect(items[0]).toHaveTextContent("depuis 4 min");
    expect(items[1]).toHaveTextContent("Gaz : alerte ESP");
  });

  it("shows « Aucune alerte » and at most five resolved ones", () => {
    const resolved = Array.from({ length: 7 }, (_, i) =>
      makeAlert({
        id: `r${i}`,
        opened_at: new Date(ALERTS_NOW_MS - (i + 2) * 60_000).toISOString(),
        resolved_at: new Date(ALERTS_NOW_MS - (i + 1) * 60_000).toISOString(),
        resolved_value: 29,
      }),
    );
    renderCard(resolved);
    const link = screen.getByRole("link", { name: LINK });
    expect(within(link).getByText("Aucune alerte")).toBeInTheDocument();
    const items = within(link).getAllByRole("listitem");
    expect(items).toHaveLength(5);
    expect(items[0]).toHaveTextContent("Résolue");
    expect(items[0]).toHaveTextContent("1 min");
  });

  it("shows a skeleton while loading and a message on error", () => {
    const { unmount } = renderCard([], "loading");
    expect(screen.getByRole("status", { name: "Chargement des alertes" })).toBeInTheDocument();
    unmount();
    renderCard([], "error");
    expect(screen.getByText("Alertes indisponibles")).toBeInTheDocument();
  });
});
