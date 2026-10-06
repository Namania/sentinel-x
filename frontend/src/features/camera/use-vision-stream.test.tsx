import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "@/features/auth/auth-provider";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { sensorsLink, server, VALID_REFRESH } from "@/test/server";
import { useVisionStream } from "./use-vision-stream";

const SNAPSHOT = {
  analyzed_at: "2026-10-06T12:00:00Z",
  has_intruder: true,
  people: [
    {
      box: { x: 1, y: 2, width: 3, height: 4 },
      confidence: 0.9,
      identity: null,
      identity_confidence: null,
      is_intruder: true,
    },
  ],
};

function Probe({ enabled }: { enabled: boolean }) {
  const snapshot = useVisionStream(enabled);
  return <p>has_intruder:{String(snapshot?.has_intruder ?? "-")}</p>;
}

function renderProbe(enabled = true) {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return render(
    <AuthProvider>
      <Probe enabled={enabled} />
    </AuthProvider>,
  );
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

describe("useVisionStream", () => {
  it("delivers vision.detection events", async () => {
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        client.send(JSON.stringify({ type: "vision.detection", data: SNAPSHOT }));
      }),
    );
    renderProbe();
    expect(await screen.findByText("has_intruder:true")).toBeInTheDocument();
  });

  it("does not connect when disabled", async () => {
    let connections = 0;
    server.use(sensorsLink.addEventListener("connection", () => void connections++));
    renderProbe(false);
    await wait(200);
    expect(connections).toBe(0);
    expect(screen.getByText("has_intruder:-")).toBeInTheDocument();
  });

  it("clears the snapshot when disabled after being connected", async () => {
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        client.send(JSON.stringify({ type: "vision.detection", data: SNAPSHOT }));
      }),
    );
    const view = renderProbe(true);
    await screen.findByText("has_intruder:true");
    view.rerender(
      <AuthProvider>
        <Probe enabled={false} />
      </AuthProvider>,
    );
    expect(await screen.findByText("has_intruder:-")).toBeInTheDocument();
  });
});
