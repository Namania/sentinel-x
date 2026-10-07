import { fireEvent, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderWithProviders } from "@/test/render";
import { server, VALID_REFRESH } from "@/test/server";
import { CameraStream } from "./camera-stream";

const ALT = "Flux vidéo de la caméra";

function renderStream() {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderWithProviders(<CameraStream stallCheckMs={40} />);
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

describe("CameraStream stall watchdog", () => {
  it("reopens the stream when the relay stops receiving frames", async () => {
    server.use(
      http.get("/api/camera/status", () =>
        HttpResponse.json({ configured: true, viewers: 1, frames: 1200 }),
      ),
    );
    renderStream();
    const img = await screen.findByAltText(ALT);
    fireEvent.load(img);
    const first = img.getAttribute("src");
    await waitFor(() => expect(img.getAttribute("src")).not.toBe(first), { timeout: 2000 });
    expect(img.getAttribute("src")).toMatch(/&t=\d+-2$/);
    expect(screen.getByRole("status")).toHaveTextContent("Connexion à la caméra…");
  });

  it("leaves a healthy stream alone", async () => {
    let frames = 1000;
    server.use(
      http.get("/api/camera/status", () =>
        HttpResponse.json({ configured: true, viewers: 1, frames: (frames += 60) }),
      ),
    );
    renderStream();
    const img = await screen.findByAltText(ALT);
    fireEvent.load(img);
    const first = img.getAttribute("src");
    await wait(250);
    expect(img.getAttribute("src")).toBe(first);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("does not guess when the API reports no frame counter", async () => {
    server.use(
      http.get("/api/camera/status", () => HttpResponse.json({ configured: true, viewers: 1 })),
    );
    renderStream();
    const img = await screen.findByAltText(ALT);
    fireEvent.load(img);
    const first = img.getAttribute("src");
    await wait(250);
    expect(img.getAttribute("src")).toBe(first);
  });
});
