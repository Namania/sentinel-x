import { fireEvent, screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderWithProviders } from "@/test/render";
import { fakeJpeg, mjpegResponse, sensorsLink, VALID_REFRESH, server } from "@/test/server";
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

  it("opens the relayed stream with the access token and shows frames as blobs", async () => {
    const tokens: (string | null)[] = [];
    server.use(
      http.get("/api/camera/stream", ({ request }) => {
        tokens.push(request.headers.get("Authorization"));
        return mjpegResponse([fakeJpeg("first")]);
      }),
    );
    renderAuthenticated();
    expect(screen.getByRole("status")).toHaveTextContent("Connexion à la caméra…");
    const img = await screen.findByAltText(ALT);
    await waitFor(() => expect(img.getAttribute("src")).toMatch(/^blob:/));
    expect(tokens[0]).toMatch(/^Bearer [^.]+\.[^.]+\.[^.]+$/);
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

  it("reconnects after the relay fails, waiting before each attempt", async () => {
    let requests = 0;
    server.use(
      http.get("/api/camera/stream", () => {
        requests += 1;
        return requests === 1
          ? new HttpResponse(null, { status: 503 })
          : mjpegResponse([fakeJpeg("later")]);
      }),
    );
  it("shows the intruder badge when the vision worker reports an unrecognised face", async () => {
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        client.send(
          JSON.stringify({
            type: "vision.detection",
            data: {
              analyzed_at: "2026-10-06T12:00:00Z",
              has_intruder: true,
              people: [
                {
                  box: { x: 10, y: 20, width: 30, height: 40 },
                  confidence: 0.8,
                  identity: null,
                  identity_confidence: null,
                  is_intruder: true,
                },
              ],
            },
          }),
        );
      }),
    );
    renderAuthenticated();
    const img = await screen.findByAltText(ALT);
    fireEvent.load(img);
    expect(await screen.findByText("INTRUS DÉTECTÉ")).toBeInTheDocument();
  });

  it("does not show the intruder badge once every detected face is known", async () => {
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        client.send(
          JSON.stringify({
            type: "vision.detection",
            data: {
              analyzed_at: "2026-10-06T12:00:00Z",
              has_intruder: false,
              people: [
                {
                  box: { x: 10, y: 20, width: 30, height: 40 },
                  confidence: 0.8,
                  identity: "kevan",
                  identity_confidence: 0.9,
                },
              ],
            },
          }),
        );
      }),
    );
    renderAuthenticated();
    const img = await screen.findByAltText(ALT);
    fireEvent.load(img);
    await screen.findByText("EN DIRECT");
    expect(screen.queryByText("INTRUS DÉTECTÉ")).not.toBeInTheDocument();
  });

  it("reconnects once with a fresh url after a burst of errors", async () => {
    renderAuthenticated();
    expect(screen.getByRole("status")).toHaveTextContent("Connexion à la caméra…");
    const img = await screen.findByAltText(ALT, {}, { timeout: 4000 });
    await waitFor(() => expect(img.getAttribute("src")).toMatch(/^blob:/));
    expect(requests).toBe(2);
  }, 6000);

  it("releases the stream on unmount", async () => {
    // MSW does not propagate the client's abort to the handler: watch the controller itself.
    const abort = vi.spyOn(AbortController.prototype, "abort");
    const view = renderAuthenticated();
    const img = await screen.findByAltText(ALT);
    await waitFor(() => expect(img.getAttribute("src")).toMatch(/^blob:/));
    const before = abort.mock.calls.length;
    view.unmount();
    expect(abort.mock.calls.length).toBeGreaterThan(before);
    abort.mockRestore();
  });

  describe("fullscreen shortcut", () => {
    afterEach(() => {
      Reflect.deleteProperty(HTMLElement.prototype, "requestFullscreen");
      Reflect.deleteProperty(document, "fullscreenEnabled");
    });

    it("ignores f with a modifier key and reacts to a plain f", async () => {
      const requestFullscreen = vi.fn();
      HTMLElement.prototype.requestFullscreen = requestFullscreen;
      Object.defineProperty(document, "fullscreenEnabled", { value: true, configurable: true });
      renderAuthenticated();
      await screen.findByAltText(ALT);
      fireEvent.keyDown(document, { key: "f", metaKey: true });
      expect(requestFullscreen).not.toHaveBeenCalled();
      fireEvent.keyDown(document, { key: "f" });
      expect(requestFullscreen).toHaveBeenCalledTimes(1);
    });

    it("hides the fullscreen button when the browser has no fullscreen support", async () => {
      renderAuthenticated();
      await screen.findByAltText(ALT);
      expect(screen.queryByRole("button", { name: "Plein écran" })).not.toBeInTheDocument();
    });
  });
});
