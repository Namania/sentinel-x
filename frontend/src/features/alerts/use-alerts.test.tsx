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
});
