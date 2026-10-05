import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { routes } from "@/app/router";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderRoutes } from "@/test/render";
import { TEST_USER, VALID_REFRESH } from "@/test/server";

function renderAuthenticated(path: string) {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderRoutes(routes, path);
}

async function sidebar() {
  return within(await screen.findByRole("navigation", { name: "Navigation principale" }));
}

describe("AppSidebar", () => {
  it("links to the dashboard and the camera", async () => {
    renderAuthenticated("/");
    const nav = await sidebar();
    expect(nav.getByRole("link", { name: "Dashboard" })).toHaveAttribute("href", "/");
    expect(nav.getByRole("link", { name: "Caméra" })).toHaveAttribute("href", "/camera");
  });

  it("marks the current page", async () => {
    renderAuthenticated("/camera");
    const nav = await sidebar();
    expect(nav.getByRole("link", { name: "Caméra" })).toHaveAttribute("aria-current", "page");
    expect(nav.getByRole("link", { name: "Dashboard" })).not.toHaveAttribute("aria-current");
  });

  it("shows the account in the footer and logs out", async () => {
    const user = userEvent.setup();
    renderAuthenticated("/");
    const footer = within(await screen.findByRole("contentinfo"));
    expect(footer.getByText(TEST_USER.email)).toBeInTheDocument();
    expect(footer.getByText("AL")).toBeInTheDocument();
    await user.click(footer.getByRole("button", { name: "Se déconnecter" }));
    expect(await screen.findByRole("heading", { name: "Connexion" })).toBeInTheDocument();
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBeNull();
  });
});
