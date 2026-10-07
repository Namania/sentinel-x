import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderWithProviders } from "@/test/render";
import { server, VALID_REFRESH } from "@/test/server";
import { makeSiren } from "@/test/siren";
import { SirenBar } from "./siren-bar";

function renderBar() {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderWithProviders(<SirenBar />);
}

describe("SirenBar", () => {
  it("rests quietly with no button when nothing sounds", async () => {
    renderBar();
    const bar = within(await screen.findByRole("status", { name: "Sirène" }));
    expect(await bar.findByText("Sirène au repos")).toBeInTheDocument();
    expect(bar.queryByRole("button")).toBeNull();
  });

  it("offers to mute while sounding and shows the mute at once", async () => {
    const user = userEvent.setup();
    let resolvePost: (() => void) | null = null;
    server.use(
      http.get("/api/alerts/siren", () =>
        HttpResponse.json(makeSiren({ on: true, reason: "gas", open: 1 })),
      ),
      http.post("/api/alerts/siren/mute", async () => {
        await new Promise<void>((r) => (resolvePost = r));
        return HttpResponse.json(
          makeSiren({ reason: "gas", open: 1, muted_until: "2026-10-07T07:27:00Z" }),
        );
      }),
    );
    renderBar();
    const bar = within(await screen.findByRole("status", { name: "Sirène" }));
    expect(await bar.findByText("Sirène active : gaz")).toBeInTheDocument();
    const button = bar.getByRole("button", { name: "Couper 15 min" });
    await user.click(button);
    expect(button).toBeDisabled(); // a second click while the request is pending does nothing
    resolvePost!();
    expect(await bar.findByText("Sirène coupée jusqu'à 09:27")).toBeInTheDocument();
    expect(bar.getByRole("button", { name: "Réactiver" })).toBeInTheDocument();
  });

  it("re-arms the siren", async () => {
    const user = userEvent.setup();
    server.use(
      http.get("/api/alerts/siren", () =>
        HttpResponse.json(
          makeSiren({ reason: "gas", open: 1, muted_until: "2026-10-07T07:27:00Z" }),
        ),
      ),
      http.delete("/api/alerts/siren/mute", () =>
        HttpResponse.json(makeSiren({ on: true, reason: "gas", open: 1 })),
      ),
    );
    renderBar();
    const bar = within(await screen.findByRole("status", { name: "Sirène" }));
    await user.click(await bar.findByRole("button", { name: "Réactiver" }));
    await waitFor(() => expect(bar.getByText("Sirène active : gaz")).toBeInTheDocument());
  });
});
