import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderRoutes } from "@/test/render";
import { VALID_REFRESH } from "@/test/server";
import { healthFixture, SERVER_NOW_MS } from "@/test/server-health";
import { toServerPoints } from "./server-api";
import { ServerDetail } from "./server-detail";

describe("toServerPoints", () => {
  it("maps samples to chart points, keeping unknown CPU and temperature as null", () => {
    const points = toServerPoints(healthFixture(2, SERVER_NOW_MS));
    expect(points[0]).toEqual({ time: SERVER_NOW_MS - 5000, cpu: null, memGib: 2, temp: 48.2 });
    expect(points[1]!.cpu).toBe(11);
  });
});

describe("ServerDetail", () => {
  it("renders the three charts, the disk gauge and the load line", async () => {
    localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
    renderRoutes([{ path: "/serveur", element: <ServerDetail /> }], "/serveur");
    expect(await screen.findByRole("heading", { name: "CPU (%)" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Mémoire utilisée (Gio)" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Température (°C)" })).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Disque" })).getByText("20,0 / 64,0 Gio"));
    expect(screen.getByText("Charge 0,42 · 0,38 · 0,31")).toBeInTheDocument();
    expect(document.querySelectorAll(".recharts-surface").length).toBeGreaterThanOrEqual(3);
  });
});
