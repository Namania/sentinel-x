import { act, render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { AuthProvider } from "@/features/auth/auth-provider";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { sensorsLink, server, VALID_REFRESH } from "@/test/server";
import { makeSiren } from "@/test/siren";
import { useSiren } from "./use-siren";

function Probe() {
  const { status, state, mute, unmute } = useSiren();
  return (
    <div>
      <p>status:{status}</p>
      <p>on:{String(state?.on)}</p>
      <p>muted:{state?.muted_until ?? "-"}</p>
      <button onClick={() => void mute()}>mute</button>
      <button onClick={() => void unmute()}>unmute</button>
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

describe("useSiren", () => {
  it("loads the state and follows siren.state events", async () => {
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        client.send(
          JSON.stringify({
            type: "siren.state",
            data: makeSiren({ on: true, reason: "gas", open: 1 }),
          }),
        );
      }),
    );
    renderProbe();
    expect(await screen.findByText("status:ready")).toBeInTheDocument();
    expect(await screen.findByText("on:true")).toBeInTheDocument();
  });

  it("mutes and unmutes through the API and shows the response at once", async () => {
    const calls: string[] = [];
    server.use(
      http.post("/api/alerts/siren/mute", () => {
        calls.push("post");
        return HttpResponse.json(
          makeSiren({ reason: "gas", open: 1, muted_until: "2026-10-07T07:27:00Z" }),
        );
      }),
      http.delete("/api/alerts/siren/mute", () => {
        calls.push("delete");
        return HttpResponse.json(makeSiren({ on: true, reason: "gas", open: 1 }));
      }),
    );
    renderProbe();
    await screen.findByText("status:ready");
    await act(async () => screen.getByText("mute").click());
    expect(await screen.findByText("muted:2026-10-07T07:27:00Z")).toBeInTheDocument();
    await act(async () => screen.getByText("unmute").click());
    expect(await screen.findByText("on:true")).toBeInTheDocument();
    expect(calls).toEqual(["post", "delete"]);
  });
});
