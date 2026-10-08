import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "@/features/auth/auth-provider";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { sensorsLink, server, VALID_REFRESH } from "@/test/server";
import { makeSshEvent } from "@/test/ssh";
import { useSshEvents } from "./use-ssh-events";

function Probe() {
  const { status, events } = useSshEvents();
  return (
    <div>
      <p>status:{status}</p>
      <p>ids:{events.map((e) => e.id).join(",")}</p>
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

describe("useSshEvents", () => {
  it("loads the list newest first", async () => {
    renderProbe();
    expect(await screen.findByText("status:ready")).toBeInTheDocument();
    expect(screen.getByText("ids:ssh-1,ssh-refused")).toBeInTheDocument();
  });

  it("prepends ssh.event events", async () => {
    const clients: { send(data: string): void }[] = [];
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        clients.push(client);
      }),
    );
    renderProbe();
    await screen.findByText("status:ready");
    await wait(50);
    const live = makeSshEvent({ id: "live", occurred_at: "2026-10-08T09:00:00Z" });
    clients.forEach((c) => c.send(JSON.stringify({ type: "ssh.event", data: live })));
    expect(await screen.findByText("ids:live,ssh-1,ssh-refused")).toBeInTheDocument();
  });

  it("keeps an event that arrives before the list", async () => {
    server.use(
      http.get("/api/ssh/events", async () => {
        await wait(100);
        return HttpResponse.json([makeSshEvent()]);
      }),
      sensorsLink.addEventListener("connection", ({ client }) => {
        const early = makeSshEvent({ id: "early", occurred_at: "2026-10-08T09:00:00Z" });
        client.send(JSON.stringify({ type: "ssh.event", data: early }));
      }),
    );
    renderProbe();
    expect(await screen.findByText("ids:early,ssh-1")).toBeInTheDocument();
  });

  it("recovers from a failed list request on the first event", async () => {
    server.use(
      http.get("/api/ssh/events", () => HttpResponse.error()),
      sensorsLink.addEventListener("connection", ({ client }) => {
        client.send(JSON.stringify({ type: "ssh.event", data: makeSshEvent({ id: "late" }) }));
      }),
    );
    renderProbe();
    expect(await screen.findByText("status:ready")).toBeInTheDocument();
    expect(screen.getByText("ids:late")).toBeInTheDocument();
  });

  it("reports an error when the list fails and nothing arrives", async () => {
    server.use(http.get("/api/ssh/events", () => HttpResponse.error()));
    renderProbe();
    expect(await screen.findByText("status:error")).toBeInTheDocument();
  });
});
