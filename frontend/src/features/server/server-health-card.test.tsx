import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderRoutes } from "@/test/render";
import { sensorsLink, server, VALID_REFRESH } from "@/test/server";
import { healthFixture, makeHealth, SERVER_NOW_MS } from "@/test/server-health";
import { ServerHealthCard } from "./server-health-card";

const LINK = "Santé du serveur, voir le détail";

function renderCard() {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderRoutes([
    { path: "/", element: <ServerHealthCard /> },
    { path: "/serveur", element: <h1>Serveur</h1> },
  ]);
}

async function card() {
  renderCard();
  return within(await screen.findByRole("link", { name: LINK }));
}

describe("ServerHealthCard", () => {
  it("links to the server page and shows the four gauges with their values", async () => {
    const link = await card();
    expect(screen.getByRole("link", { name: LINK })).toHaveAttribute("href", "/serveur");
    const cpu = within(await link.findByRole("group", { name: "CPU" }));
    expect(cpu.getByText("13 %")).toBeInTheDocument();
    expect(within(link.getByRole("group", { name: "Mémoire" })).getByText("2,0 / 8,0 Gio"));
    expect(within(link.getByRole("group", { name: "Disque" })).getByText("20,0 / 64,0 Gio"));
    expect(within(link.getByRole("group", { name: "Température SoC" })).getByText("48,2 °C"));
    expect(link.getByText("Charge 0,42 · 0,38 · 0,31")).toBeInTheDocument();
    expect(link.getByText("Démarré depuis 3 j 4 h")).toBeInTheDocument();
  });

  it("shows dashes when CPU and temperature are unknown", async () => {
    server.use(
      http.get("/api/server/health", () => {
        const history = [makeHealth({ cpu_pct: null, temperature_c: null })];
        return HttpResponse.json({ latest: history[0], history });
      }),
    );
    const link = await card();
    expect(within(await link.findByRole("group", { name: "CPU" })).getByText("–"));
    expect(within(link.getByRole("group", { name: "Température SoC" })).getByText("–"));
  });

  it("marks a gauge above its threshold without hiding the value", async () => {
    server.use(
      http.get("/api/server/health", () => {
        const history = healthFixture(2, SERVER_NOW_MS).map((h) => ({ ...h, cpu_pct: 92 }));
        return HttpResponse.json({ latest: history.at(-1), history });
      }),
    );
    const link = await card();
    const cpu = within(await link.findByRole("group", { name: "CPU" }));
    expect(cpu.getByText("92 %")).toBeInTheDocument();
    expect(cpu.getByRole("meter")).toHaveAttribute("data-warn", "true");
    expect(cpu.getByRole("meter")).toHaveAttribute("aria-valuenow", "92");
  });

  it("shows a skeleton while loading and a message on error", async () => {
    server.use(http.get("/api/server/health", () => HttpResponse.error()));
    renderCard();
    expect(await screen.findByRole("status", { name: "Chargement de la santé du serveur" }));
    expect(await screen.findByText("Santé du serveur indisponible")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: LINK })).toHaveAttribute("href", "/serveur");
  });

  it("keeps the card a single tab stop: no focusable element inside the link", async () => {
    const link = await card();
    await link.findByRole("group", { name: "CPU" });
    const anchor = screen.getByRole("link", { name: LINK });
    expect(anchor.querySelectorAll('[tabindex]:not([tabindex="-1"]), a, button')).toHaveLength(0);
    expect(link.queryAllByRole("application")).toHaveLength(0);
  });

  it("says how old the data is while the live stream is down", async () => {
    // The socket drops at once and every time: the card must not pretend to be live.
    server.use(sensorsLink.addEventListener("connection", ({ client }) => client.close()));
    const link = await card();
    await link.findByRole("group", { name: "CPU" });
    expect(await link.findByText(/^il y a /)).toBeInTheDocument();
    expect(link.getByText("temps réel interrompu")).toBeInTheDocument();
  });
});
