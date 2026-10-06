import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderRoutes } from "@/test/render";
import { server, VALID_REFRESH } from "@/test/server";
import { CameraCard } from "./camera-card";

const ALT = "Flux vidéo de la caméra";

function renderCard() {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderRoutes([
    { path: "/", element: <CameraCard /> },
    { path: "/camera", element: <h1>Caméra</h1> },
  ]);
}

describe("CameraCard", () => {
  it("opens the stream and shows the live badge once frames arrive", async () => {
    renderCard();
    const img = await screen.findByAltText(ALT);
    expect(img.getAttribute("src")).toMatch(/^\/api\/camera\/stream\?token=/);
    expect(screen.queryByText("EN DIRECT")).not.toBeInTheDocument();
    fireEvent.load(img);
    expect(screen.getByText("EN DIRECT")).toBeInTheDocument();
  });

  it("navigates to the camera page when clicked", async () => {
    const user = userEvent.setup();
    const { router } = renderCard();
    await user.click(await screen.findByRole("link", { name: "Caméra, voir en grand" }));
    expect(router.state.location.pathname).toBe("/camera");
  });

  it("says so when no camera is configured", async () => {
    server.use(
      http.get("/api/camera/status", () => HttpResponse.json({ configured: false, viewers: 0 })),
    );
    renderCard();
    expect(await screen.findByText("Aucune caméra configurée")).toBeInTheDocument();
    expect(screen.queryByAltText(ALT)).not.toBeInTheDocument();
  });

  it("releases the stream on unmount", async () => {
    const view = renderCard();
    const img = await screen.findByAltText(ALT);
    view.unmount();
    expect(img.getAttribute("src")).toBe("");
  });
});
