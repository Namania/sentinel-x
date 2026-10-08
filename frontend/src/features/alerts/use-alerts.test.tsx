import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "@/features/auth/auth-provider";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { makeAlert } from "@/test/alerts";
import { sensorsLink, server, VALID_REFRESH } from "@/test/server";
import { useAlertCount } from "./use-alert-count";
import { useAlerts } from "./use-alerts";

function Probe() {
  const { status, alerts, open } = useAlerts();
  const count = useAlertCount();
  return (
    <div>
      <p>status:{status}</p>
      <p>total:{alerts.length}</p>
      <p>open:{open.length}</p>
      <p>ids:{alerts.map((a) => a.id).join(",")}</p>
      <p>peak:{open[0]?.peak_value ?? "-"}</p>
      <p>count:{count ?? "-"}</p>
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

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

describe("useAlerts / useAlertCount", () => {
  it("loads the list and the count", async () => {
    renderProbe();
    expect(await screen.findByText("status:ready")).toBeInTheDocument();
    expect(screen.getByText("total:1")).toBeInTheDocument();
    expect(screen.getByText("open:0")).toBeInTheDocument();
    expect(await screen.findByText("count:0")).toBeInTheDocument();
  });

  it("adds on alert.opened, replaces on alert.resolved, keeps the count in step", async () => {
    // Two hooks → two sockets: every connected client must receive each event.
    const clients: { send(data: string): void }[] = [];
    const send = (data: string) => clients.forEach((c) => c.send(data));
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        clients.push(client);
      }),
    );
    renderProbe();
    await screen.findByText("status:ready");
    await screen.findByText("count:0");
    await wait(50);
    const opened = makeAlert({ id: "new" });
    send(JSON.stringify({ type: "alert.opened", data: opened }));
    expect(await screen.findByText("open:1")).toBeInTheDocument();
    expect(screen.getByText("ids:new,alert-resolved")).toBeInTheDocument();
    expect(screen.getByText("count:1")).toBeInTheDocument();
    send(
      JSON.stringify({
        type: "alert.resolved",
        data: { ...opened, resolved_at: "2026-10-06T09:05:00Z", resolved_value: 29 },
      }),
    );
    expect(await screen.findByText("open:0")).toBeInTheDocument();
    expect(screen.getByText("total:2")).toBeInTheDocument();
    expect(screen.getByText("count:0")).toBeInTheDocument();
  });

  it("recovers from a failed list request on the first event", async () => {
    server.use(
      http.get("/api/alerts", () => HttpResponse.error()),
      sensorsLink.addEventListener("connection", ({ client }) => {
        client.send(JSON.stringify({ type: "alert.opened", data: makeAlert({ id: "late" }) }));
      }),
    );
    renderProbe();
    expect(await screen.findByText("status:ready")).toBeInTheDocument();
    expect(screen.getByText("ids:late")).toBeInTheDocument();
  });

  it("reloads the list and the count after the socket reconnects", async () => {
    let connections = 0;
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        connections += 1;
        // Both hooks open a socket; the first round drops shortly after opening, and the
        // events emitted meanwhile are lost by design.
        if (connections <= 2) setTimeout(() => client.close(), 50);
      }),
    );
    renderProbe();
    await screen.findByText("status:ready");
    await screen.findByText("count:0");
    // What the API knows by the time the client comes back (1 s later).
    server.use(
      http.get("/api/alerts", () => HttpResponse.json([makeAlert({ id: "missed" })])),
      http.get("/api/alerts/summary", () => HttpResponse.json({ open: 1 })),
    );
    expect(await screen.findByText("ids:missed", {}, { timeout: 4000 })).toBeInTheDocument();
    expect(await screen.findByText("count:1")).toBeInTheDocument();
    expect(screen.getByText("status:ready")).toBeInTheDocument();
  }, 8000);

  it("replaces the alert on alert.updated without changing the count", async () => {
    const clients: { send(data: string): void }[] = [];
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        clients.push(client);
      }),
    );
    renderProbe();
    await screen.findByText("status:ready");
    await screen.findByText("count:0");
    await wait(50);
    const opened = makeAlert({
      id: "ssh",
      metric: "ssh",
      device_id: "ip:203.0.113.5",
      peak_value: 1,
    });
    clients.forEach((c) => c.send(JSON.stringify({ type: "alert.opened", data: opened })));
    expect(await screen.findByText("open:1")).toBeInTheDocument();
    clients.forEach((c) =>
      c.send(JSON.stringify({ type: "alert.updated", data: { ...opened, peak_value: 2 } })),
    );
    expect(await screen.findByText("peak:2")).toBeInTheDocument();
    expect(screen.getByText("total:2")).toBeInTheDocument();
    expect(screen.getByText("open:1")).toBeInTheDocument();
    expect(screen.getByText("count:1")).toBeInTheDocument();
  });
});
