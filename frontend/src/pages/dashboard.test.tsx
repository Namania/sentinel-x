import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { routes } from "@/app/router";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderRoutes } from "@/test/render";
import { TEST_USER, VALID_REFRESH, server } from "@/test/server";

function renderDashboard() {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderRoutes(routes, "/");
}

async function card(name: string) {
  return within(await screen.findByRole("region", { name }));
}

describe("DashboardPage", () => {
  it("shows the camera status with a link to the camera", async () => {
    server.use(
      http.get("/api/camera/status", () => HttpResponse.json({ configured: true, viewers: 2 })),
    );
    renderDashboard();
    const camera = await card("Caméra");
    expect(await camera.findByText("Configurée")).toBeInTheDocument();
    expect(camera.getByText("2 spectateurs")).toBeInTheDocument();
    expect(camera.getByRole("link", { name: "Voir la caméra" })).toHaveAttribute("href", "/camera");
  });

  it("tells when no camera is configured", async () => {
    server.use(
      http.get("/api/camera/status", () => HttpResponse.json({ configured: false, viewers: 0 })),
    );
    renderDashboard();
    const camera = await card("Caméra");
    expect(await camera.findByText("Non configurée")).toBeInTheDocument();
  });

  it("shows the API health", async () => {
    renderDashboard();
    const api = await card("API");
    expect(await api.findByText("En ligne")).toBeInTheDocument();
  });

  it("reports an unreachable API", async () => {
    server.use(http.get("/api/health", () => HttpResponse.error()));
    renderDashboard();
    const api = await card("API");
    expect(await api.findByText("Indisponible")).toBeInTheDocument();
  });

  it("shows the account", async () => {
    renderDashboard();
    const account = await card("Compte");
    expect(account.getByText(TEST_USER.email)).toBeInTheDocument();
    expect(account.getByText("Créé le 5 octobre 2026")).toBeInTheDocument();
  });
});
