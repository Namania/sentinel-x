import { fireEvent, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderWithProviders } from "@/test/render";
import { VALID_REFRESH, server } from "@/test/server";
import { CameraView } from "./camera-view";

const ALT = "Flux vidéo de la caméra";

function renderAuthenticated() {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderWithProviders(<CameraView />);
}

describe("CameraView", () => {
  it("explains when no camera is configured", async () => {
    server.use(
      http.get("/api/camera/status", () => HttpResponse.json({ configured: false, viewers: 0 })),
    );
    renderAuthenticated();
    expect(
      await screen.findByRole("heading", { name: "Aucune caméra configurée" }),
    ).toBeInTheDocument();
    expect(screen.queryByAltText(ALT)).not.toBeInTheDocument();
  });

  it("opens the relayed stream with the access token", async () => {
    renderAuthenticated();
    const img = await screen.findByAltText(ALT);
    expect(img.getAttribute("src")).toMatch(/^\/api\/camera\/stream\?token=[^&]+&t=\d+-1$/);
    expect(screen.getByRole("status")).toHaveTextContent("Connexion à la caméra…");
  });

  it("shows the live badge and the viewer count once frames arrive", async () => {
    server.use(
      http.get("/api/camera/status", () => HttpResponse.json({ configured: true, viewers: 2 })),
    );
    renderAuthenticated();
    const img = await screen.findByAltText(ALT);
    fireEvent.load(img);
    expect(screen.getByText("EN DIRECT")).toBeInTheDocument();
    expect(screen.getByText("3 spectateurs")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("reconnects once with a fresh url after a burst of errors", async () => {
    renderAuthenticated();
    const img = await screen.findByAltText(ALT);
    fireEvent.load(img);
    const first = img.getAttribute("src");
    fireEvent.error(img);
    fireEvent.error(img);
    expect(screen.getByRole("status")).toHaveTextContent("Connexion à la caméra…");
    await waitFor(() => expect(img.getAttribute("src")).not.toBe(first), { timeout: 3000 });
    expect(img.getAttribute("src")).toMatch(/&t=\d+-2$/);
  }, 5000);

  it("releases the stream on unmount", async () => {
    const view = renderAuthenticated();
    const img = await screen.findByAltText(ALT);
    view.unmount();
    expect(img.getAttribute("src")).toBe("");
  });
});
