import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "@/features/auth/auth-provider";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { sensorsLink, server, VALID_REFRESH } from "@/test/server";
import { healthFixture, makeHealth, SERVER_NOW_MS } from "@/test/server-health";
import { useServerHealth } from "./use-server-health";

function Probe() {
  const { status, latest, history, connected } = useServerHealth();
  return (
    <div>
      <p>status:{status}</p>
      <p>connected:{String(connected)}</p>
      <p>count:{history.length}</p>
      <p>uptime:{latest?.uptime_s ?? "-"}</p>
    </div>
  );
}

function renderProbe() {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return render(
    <AuthProvider>
      <Probe />
    </AuthProvider>,
  );
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

describe("useServerHealth", () => {
  it("loads the history then applies server.health events", async () => {
    let send: ((data: string) => void) | null = null;
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        send = (data) => client.send(data);
      }),
    );
    renderProbe();
    expect(await screen.findByText("status:ready")).toBeInTheDocument();
    expect(screen.getByText("count:4")).toBeInTheDocument();
    await screen.findByText("connected:true");
    send!(
      JSON.stringify({
        type: "server.health",
        data: makeHealth({
          recorded_at: new Date(SERVER_NOW_MS + 5000).toISOString(),
          uptime_s: 999,
        }),
      }),
    );
    expect(await screen.findByText("uptime:999")).toBeInTheDocument();
    expect(screen.getByText("count:5")).toBeInTheDocument();
  });

  it("keeps an event received while the history is loading", async () => {
    server.use(
      http.get("/api/server/health", async () => {
        await wait(150);
        const history = healthFixture(4, SERVER_NOW_MS);
        return HttpResponse.json({ latest: history.at(-1), history });
      }),
      sensorsLink.addEventListener("connection", ({ client }) => {
        client.send(
          JSON.stringify({
            type: "server.health",
            data: makeHealth({
              recorded_at: new Date(SERVER_NOW_MS + 5000).toISOString(),
              uptime_s: 777,
            }),
          }),
        );
      }),
    );
    renderProbe();
    expect(await screen.findByText("status:ready")).toBeInTheDocument();
    expect(await screen.findByText("uptime:777")).toBeInTheDocument();
    expect(screen.getByText("count:5")).toBeInTheDocument();
  });

  it("ignores other event types", async () => {
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        client.send(JSON.stringify({ type: "sensor.reading", data: { uptime_s: 1 } }));
      }),
    );
    renderProbe();
    expect(await screen.findByText("status:ready")).toBeInTheDocument();
    await wait(100);
    expect(screen.getByText("count:4")).toBeInTheDocument();
  });

  it("reports an error when the history cannot be loaded", async () => {
    server.use(http.get("/api/server/health", () => HttpResponse.error()));
    renderProbe();
    expect(await screen.findByText("status:error")).toBeInTheDocument();
    expect(screen.getByText("uptime:-")).toBeInTheDocument();
  });
});
