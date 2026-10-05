import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderRoutes } from "@/test/render";
import { VALID_REFRESH } from "@/test/server";
import { routes } from "./router";

describe("routing", () => {
  it("renders the 404 page for an unknown url", async () => {
    renderRoutes(routes, "/une/route/inconnue");
    expect(
      await screen.findByRole("heading", { name: "Cette page n'existe pas" }),
    ).toBeInTheDocument();
    expect(screen.getByText("404")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Retour à l'accueil" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "SENTINEL-X" })).toHaveAttribute("href", "/");
    expect(document.title).toBe("404 · sentinel-x");
  });

  it("sends an anonymous visitor from / to the login page", async () => {
    renderRoutes(routes, "/");
    expect(await screen.findByRole("heading", { name: "Connexion" })).toBeInTheDocument();
    expect(document.title).toBe("Connexion · sentinel-x");
  });

  it("shows a loading state while restoring, then the camera page", async () => {
    localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
    renderRoutes(routes, "/");
    expect(screen.getByText("Chargement de la session…")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Caméra" })).toBeInTheDocument();
  });

  it("sends an authenticated visitor from /login to /", async () => {
    localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
    renderRoutes(routes, "/login");
    expect(await screen.findByRole("heading", { name: "Caméra" })).toBeInTheDocument();
  });
});
