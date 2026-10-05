import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/api";
import { TEST_USER, VALID_PASSWORD, VALID_REFRESH, server, tokenPair } from "@/test/server";
import { AuthProvider } from "./auth-provider";
import { REFRESH_TOKEN_KEY } from "./token-storage";
import { useAuth } from "./use-auth";

function Probe({ password = VALID_PASSWORD }: { password?: string }) {
  const { status, user, login, logout, authFetch } = useAuth();
  const [message, setMessage] = useState("");
  return (
    <div>
      <p>status:{status}</p>
      <p>user:{user?.email ?? "-"}</p>
      <p>message:{message}</p>
      <button
        onClick={() =>
          login(TEST_USER.email, password).catch((e: unknown) =>
            setMessage(e instanceof ApiError ? `api:${e.status}` : "network"),
          )
        }
      >
        login
      </button>
      <button onClick={logout}>logout</button>
      <button
        onClick={() =>
          authFetch<{ email: string }>("/users/me")
            .then((me) => setMessage(`me:${me.email}`))
            .catch(() => setMessage("fetch-failed"))
        }
      >
        fetch
      </button>
    </div>
  );
}

function renderProbe(props: { password?: string } = {}) {
  return render(
    <AuthProvider>
      <Probe {...props} />
    </AuthProvider>,
  );
}

describe("AuthProvider", () => {
  it("is anonymous right away without a stored refresh token", () => {
    renderProbe();
    expect(screen.getByText("status:anonymous")).toBeInTheDocument();
  });

  it("restores the session from a stored refresh token", async () => {
    localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
    renderProbe();
    expect(screen.getByText("status:restoring")).toBeInTheDocument();
    expect(await screen.findByText("status:authenticated")).toBeInTheDocument();
    expect(screen.getByText(`user:${TEST_USER.email}`)).toBeInTheDocument();
  });

  it("drops an invalid stored refresh token", async () => {
    localStorage.setItem(REFRESH_TOKEN_KEY, "stale");
    renderProbe();
    expect(await screen.findByText("status:anonymous")).toBeInTheDocument();
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBeNull();
  });

  it("ends anonymous when the server is unreachable at startup", async () => {
    server.use(http.post("/api/auth/refresh", () => HttpResponse.error()));
    localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
    renderProbe();
    expect(await screen.findByText("status:anonymous")).toBeInTheDocument();
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBeNull();
  });

  it("logs in and stores the refresh token", async () => {
    const user = userEvent.setup();
    renderProbe();
    await user.click(screen.getByRole("button", { name: "login" }));
    expect(await screen.findByText("status:authenticated")).toBeInTheDocument();
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBe(VALID_REFRESH);
  });

  it("surfaces a 401 on wrong credentials and stays anonymous", async () => {
    const user = userEvent.setup();
    renderProbe({ password: "wrong" });
    await user.click(screen.getByRole("button", { name: "login" }));
    expect(await screen.findByText("message:api:401")).toBeInTheDocument();
    expect(screen.getByText("status:anonymous")).toBeInTheDocument();
  });

  it("logs out and clears the storage", async () => {
    const user = userEvent.setup();
    localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
    renderProbe();
    await screen.findByText("status:authenticated");
    await user.click(screen.getByRole("button", { name: "logout" }));
    expect(screen.getByText("status:anonymous")).toBeInTheDocument();
    expect(screen.getByText("user:-")).toBeInTheDocument();
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBeNull();
  });

  it("refreshes proactively shortly before the access token expires", async () => {
    let refreshCalls = 0;
    server.use(
      http.post("/api/auth/login", () => HttpResponse.json(tokenPair(61))),
      http.post("/api/auth/refresh", () => {
        refreshCalls += 1;
        return HttpResponse.json(tokenPair(900));
      }),
    );
    const user = userEvent.setup();
    renderProbe();
    await user.click(screen.getByRole("button", { name: "login" }));
    await screen.findByText("status:authenticated");
    await waitFor(() => expect(refreshCalls).toBe(1), { timeout: 3000 });
    expect(screen.getByText("status:authenticated")).toBeInTheDocument();
  });

  it("retries an authenticated call once after refreshing on 401", async () => {
    const user = userEvent.setup();
    localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
    renderProbe();
    await screen.findByText("status:authenticated");
    let meCalls = 0;
    let refreshCalls = 0;
    server.use(
      http.get("/api/users/me", () => {
        meCalls += 1;
        return meCalls === 1
          ? HttpResponse.json({ detail: "Invalid or expired token" }, { status: 401 })
          : HttpResponse.json(TEST_USER);
      }),
      http.post("/api/auth/refresh", () => {
        refreshCalls += 1;
        return HttpResponse.json(tokenPair());
      }),
    );
    await user.click(screen.getByRole("button", { name: "fetch" }));
    expect(await screen.findByText(`message:me:${TEST_USER.email}`)).toBeInTheDocument();
    expect(meCalls).toBe(2);
    expect(refreshCalls).toBe(1);
  });

  it("logs out when the refresh after a 401 fails too", async () => {
    const user = userEvent.setup();
    localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
    renderProbe();
    await screen.findByText("status:authenticated");
    server.use(
      http.get("/api/users/me", () =>
        HttpResponse.json({ detail: "Invalid or expired token" }, { status: 401 }),
      ),
      http.post("/api/auth/refresh", () =>
        HttpResponse.json({ detail: "Invalid credentials" }, { status: 401 }),
      ),
    );
    await user.click(screen.getByRole("button", { name: "fetch" }));
    expect(await screen.findByText("message:fetch-failed")).toBeInTheDocument();
    expect(screen.getByText("status:anonymous")).toBeInTheDocument();
  });
});
