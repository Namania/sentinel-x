import { render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "@/features/auth/auth-provider";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { makeReading } from "@/test/sensors";
import { sensorsLink, server, VALID_REFRESH } from "@/test/server";
import type { Reading } from "./metrics-api";
import { RECONNECT_DELAYS_MS, useSensorStream } from "./use-sensor-stream";

function Probe({ enabled }: { enabled: boolean }) {
  const [last, setLast] = useState<Reading | null>(null);
  const { connected } = useSensorStream(enabled, setLast);
  return (
    <div>
      <p>connected:{String(connected)}</p>
      <p>last:{last?.gas_level ?? "-"}</p>
    </div>
  );
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

describe("useSensorStream", () => {
  it("connects with the access token and delivers sensor.reading events", async () => {
    const tokens: string[] = [];
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        tokens.push(new URL(client.url).searchParams.get("token") ?? "");
        client.send(
          JSON.stringify({ type: "sensor.reading", data: makeReading({ gas_level: 777 }) }),
        );
        client.send(JSON.stringify({ type: "pong" }));
      }),
    );
    renderProbe();
    expect(await screen.findByText("connected:true")).toBeInTheDocument();
    expect(await screen.findByText("last:777")).toBeInTheDocument();
    expect(tokens[0]!.split(".")).toHaveLength(3);
  });

  it("does not connect when disabled", async () => {
    let connections = 0;
    server.use(sensorsLink.addEventListener("connection", () => void connections++));
    renderProbe(false);
    await wait(200);
    expect(connections).toBe(0);
    expect(screen.getByText("connected:false")).toBeInTheDocument();
  });

  it("reconnects after the server closes, waiting before each attempt", async () => {
    const times: number[] = [];
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        times.push(Date.now());
        if (times.length === 1) client.close();
      }),
    );
    renderProbe();
    await waitFor(() => expect(times).toHaveLength(2), { timeout: 4000 });
    expect(times[1]! - times[0]!).toBeGreaterThanOrEqual(RECONNECT_DELAYS_MS[0] - 50);
  });

  it("waits longer before each further reconnection attempt", async () => {
    const times: number[] = [];
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        times.push(Date.now());
        if (times.length < 3) client.close();
      }),
    );
    renderProbe();
    await waitFor(() => expect(times).toHaveLength(3), { timeout: 6000 });
    const [first, second] = [times[1]! - times[0]!, times[2]! - times[1]!];
    expect(first).toBeGreaterThanOrEqual(RECONNECT_DELAYS_MS[0] - 50);
    expect(second).toBeGreaterThanOrEqual(RECONNECT_DELAYS_MS[1] - 50);
  }, 8000);

  it("closes the socket on unmount and stops reconnecting", async () => {
    let connections = 0;
    server.use(sensorsLink.addEventListener("connection", () => void connections++));
    const view = renderProbe();
    await screen.findByText("connected:true");
    view.unmount();
    await wait(1300);
    expect(connections).toBe(1);
  });
});
