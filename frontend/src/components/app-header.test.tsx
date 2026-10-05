import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { routes } from "@/app/router";
import { renderRoutes } from "@/test/render";

describe("AppHeader (public pages)", () => {
  it("shows the title link and the theme toggle, never a logout button", async () => {
    renderRoutes(routes, "/login");
    await screen.findByRole("heading", { name: "Connexion" });
    expect(screen.getByRole("link", { name: "SENTINEL-X" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("button", { name: "Changer de thème" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Se déconnecter" })).not.toBeInTheDocument();
  });
});
