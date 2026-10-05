import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { routes } from "@/app/router";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderRoutes } from "@/test/render";
import { TEST_USER, VALID_PASSWORD, VALID_REFRESH, server } from "@/test/server";

async function fillAndSubmit(email: string, password: string) {
  const user = userEvent.setup();
  if (email) await user.type(screen.getByLabelText("Email"), email);
  if (password) await user.type(screen.getByLabelText("Mot de passe"), password);
  await user.click(screen.getByRole("button", { name: "Se connecter" }));
}

describe("LoginPage", () => {
  it("validates the form before calling the API", async () => {
    renderRoutes(routes, "/login");
    await fillAndSubmit("", "");
    expect(await screen.findByText("Adresse email invalide")).toBeInTheDocument();
    expect(screen.getByText("Mot de passe requis")).toBeInTheDocument();
  });

  it("reports wrong credentials", async () => {
    renderRoutes(routes, "/login");
    await fillAndSubmit(TEST_USER.email, "wrong");
    expect(await screen.findByRole("alert")).toHaveTextContent("Email ou mot de passe incorrect");
  });

  it("reports an unreachable server", async () => {
    server.use(http.post("/api/auth/login", () => HttpResponse.error()));
    renderRoutes(routes, "/login");
    await fillAndSubmit(TEST_USER.email, VALID_PASSWORD);
    expect(await screen.findByRole("alert")).toHaveTextContent("Serveur injoignable");
  });

  it("logs in, stores the refresh token and lands on the dashboard", async () => {
    renderRoutes(routes, "/login");
    await fillAndSubmit(TEST_USER.email, VALID_PASSWORD);
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBe(VALID_REFRESH);
  });

  it("accepts an email with spaces and capitals", async () => {
    renderRoutes(routes, "/login");
    await fillAndSubmit("  Alice@Example.com ", VALID_PASSWORD);
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("returns to the page the visitor came from", async () => {
    renderRoutes(routes, "/camera");
    await screen.findByRole("heading", { name: "Connexion" });
    await fillAndSubmit(TEST_USER.email, VALID_PASSWORD);
    expect(await screen.findByRole("heading", { name: "Caméra" })).toBeInTheDocument();
  });
});
