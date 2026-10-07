import { fireEvent, screen, waitFor } from "@testing-library/react";
import { http } from "msw";
import { describe, expect, it } from "vitest";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderWithProviders } from "@/test/render";
import { fakeJpeg, mjpegResponse, server, VALID_REFRESH } from "@/test/server";
import { CameraStream } from "./camera-stream";

const ALT = "Flux vidéo de la caméra";

function renderStream(stallMs = 10_000) {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderWithProviders(<CameraStream stallMs={stallMs} />);
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

describe("CameraStream", () => {
  it("shows the latest frame only: frames that arrive while one is decoding are skipped", async () => {
    server.use(
      http.get("/api/camera/stream", () =>
        mjpegResponse([fakeJpeg("one"), fakeJpeg("two"), fakeJpeg("three")]),
      ),
    );
    renderStream();
    const img = await screen.findByAltText(ALT);
    await waitFor(() => expect(img.getAttribute("src")).toMatch(/^blob:/));
    await wait(50);
    const shownWhileBusy = img.getAttribute("src");
    // The first frame is still "decoding" (jsdom never fires load by itself): nothing replaced it.
    expect(shownWhileBusy).toBe(img.getAttribute("src"));
    fireEvent.load(img);
    // Once decoded, the newest pending frame is shown — the middle one was dropped.
    await waitFor(() => expect(img.getAttribute("src")).not.toBe(shownWhileBusy));
    const afterLoad = img.getAttribute("src");
    fireEvent.load(img);
    await wait(30);
    expect(img.getAttribute("src")).toBe(afterLoad);
  });

  it("reopens the stream when no frame arrived for a while", async () => {
    let requests = 0;
    server.use(
      http.get("/api/camera/stream", () => {
        requests += 1;
        return mjpegResponse([fakeJpeg(`r${requests}`)]);
      }),
    );
    renderStream(120);
    const img = await screen.findByAltText(ALT);
    await waitFor(() => expect(img.getAttribute("src")).toMatch(/^blob:/));
    fireEvent.load(img);
    await waitFor(() => expect(requests).toBeGreaterThanOrEqual(2), { timeout: 4000 });
  }, 6000);

  it("shows the live state once a frame is displayed and goes back to connecting on failure", async () => {
    let requests = 0;
    server.use(
      http.get("/api/camera/stream", () => {
        requests += 1;
        return requests === 1
          ? mjpegResponse([fakeJpeg("a")], 0, true) // ends cleanly after one frame
          : mjpegResponse([fakeJpeg("b")]);
      }),
    );
    renderStream();
    const img = await screen.findByAltText(ALT);
    await waitFor(() => expect(img.getAttribute("src")).toMatch(/^blob:/));
    fireEvent.load(img);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    await waitFor(() => expect(requests).toBe(2), { timeout: 4000 });
  }, 6000);
});
