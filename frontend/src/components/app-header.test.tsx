import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { routes } from "@/app/router";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderRoutes } from "@/test/render";
import { TEST_USER, VALID_REFRESH } from "@/test/server";

describe("AppHeader", () => {
  it("hides the logout button for anonymous visitors", async () => {
    renderRoutes(routes, "/login");
    await screen.findByRole("heading", { name: "Connexion" });
    expect(screen.queryByRole("button", { name: "Se déconnecter" })).not.toBeInTheDocument();
  });

  it("shows the user and logs out", async () => {
    const user = userEvent.setup();
    localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
    renderRoutes(routes, "/");
    await screen.findByRole("heading", { name: "Caméra" });
    expect(screen.getByText(TEST_USER.email)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Se déconnecter" }));
    expect(await screen.findByRole("heading", { name: "Connexion" })).toBeInTheDocument();
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBeNull();
  });
});
