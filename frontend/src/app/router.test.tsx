import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderRoutes } from "@/test/render";
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
});
