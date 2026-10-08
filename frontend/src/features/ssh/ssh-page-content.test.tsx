import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderRoutes } from "@/test/render";
import { server, VALID_REFRESH } from "@/test/server";
import { makeSshEvent, SSH_NOW_MS } from "@/test/ssh";
import { SshPageContent } from "./ssh-page-content";

function renderPage() {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderRoutes([{ path: "/ssh", element: <SshPageContent nowMs={SSH_NOW_MS} /> }], "/ssh");
}

describe("SshPageContent", () => {
  it("summarises and lists the connections grouped by day", async () => {
    renderPage();
    expect(await screen.findByRole("heading", { name: "Accès SSH" })).toBeInTheDocument();
    expect(screen.getByText("Connexions 24 h").nextElementSibling).toHaveTextContent("1");
    expect(screen.getByText("Refus 24 h").nextElementSibling).toHaveTextContent("1");
    expect(screen.getByText("Dernière acceptée").nextElementSibling).toHaveTextContent(
      "mael.namania@gmail.com",
    );
    expect(screen.getByText("il y a 4 min")).toBeInTheDocument();
    const today = within(screen.getByRole("list", { name: "Connexions, Aujourd'hui" }));
    const rows = today.getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("mael.namania@gmail.com depuis 192.168.0.18 · clé");
    expect(rows[0]).toHaveTextContent("Acceptée");
    expect(rows[1]).toHaveTextContent("root depuis 203.0.113.5 · clé non acceptée");
    expect(rows[1]).toHaveTextContent("Refusée");
  });

  it("filters by outcome and by text", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByRole("heading", { name: "Accès SSH" });
    await user.click(screen.getByRole("radio", { name: "Refusées" }));
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    expect(screen.getByText(/root depuis/)).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Toutes" }));
    await user.type(screen.getByRole("searchbox", { name: "Rechercher" }), "MAEL");
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    // The « Dernière acceptée » stat carries the mail too: look at the list itself.
    expect(screen.getByRole("listitem")).toHaveTextContent(/mael\.namania/);
    await user.clear(screen.getByRole("searchbox", { name: "Rechercher" }));
    await user.type(screen.getByRole("searchbox", { name: "Rechercher" }), "203.0.113");
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
    await user.click(screen.getByRole("radio", { name: "Acceptées" }));
    expect(screen.getByText("Aucune connexion")).toBeInTheDocument();
  });

  it("shows the loading, error and truncated states", async () => {
    localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
    server.use(http.get("/api/ssh/events", () => HttpResponse.error()));
    renderRoutes([{ path: "/ssh", element: <SshPageContent nowMs={SSH_NOW_MS} /> }], "/ssh");
    expect(screen.getByRole("status", { name: "Chargement des connexions" })).toBeInTheDocument();
    expect(await screen.findByText("Journal SSH indisponible.")).toBeInTheDocument();
    server.use(
      http.get("/api/ssh/events", ({ request }) => {
        expect(Number(new URL(request.url).searchParams.get("limit"))).toBe(500);
        return HttpResponse.json(
          Array.from({ length: 500 }, (_, i) =>
            makeSshEvent({
              id: `e${i}`,
              occurred_at: new Date(SSH_NOW_MS - (i + 1) * 60_000).toISOString(),
            }),
          ),
        );
      }),
    );
    renderRoutes([{ path: "/ssh", element: <SshPageContent nowMs={SSH_NOW_MS} /> }], "/ssh");
    expect(
      await screen.findByText("Seules les 500 connexions les plus récentes sont affichées."),
    ).toBeInTheDocument();
  });
});
