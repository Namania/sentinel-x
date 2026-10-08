import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { AuthProvider } from "@/features/auth/auth-provider";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { makeAlert } from "@/test/alerts";
import { server, VALID_REFRESH } from "@/test/server";
import type { Alert } from "./alerts-api";
import { CloseAlertButton } from "./close-alert-button";

const SSH = makeAlert({
  id: "ssh-open",
  metric: "ssh",
  device_id: "ip:203.0.113.5",
  threshold: 0,
  opened_value: 1,
  peak_value: 3,
});

function renderButton(alert: Alert, onResolved = vi.fn()) {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  render(
    <AuthProvider>
      <CloseAlertButton alert={alert} onResolved={onResolved} />
    </AuthProvider>,
  );
  return onResolved;
}

describe("CloseAlertButton", () => {
  it("posts the resolution and hands the closed alert back", async () => {
    const user = userEvent.setup();
    let posted: string | null = null;
    server.use(
      http.post("/api/alerts/:id/resolve", ({ params }) => {
        posted = String(params.id);
        return HttpResponse.json({
          ...SSH,
          resolved_at: "2026-10-06T09:05:00Z",
          resolved_value: 3,
        });
      }),
    );
    const onResolved = renderButton(SSH);
    await user.click(await screen.findByRole("button", { name: "Clôturer" }));
    expect(await screen.findByRole("button", { name: "Clôturer" })).toBeEnabled();
    expect(posted).toBe("ssh-open");
    expect(onResolved).toHaveBeenCalledWith(
      expect.objectContaining({ id: "ssh-open", resolved_value: 3 }),
    );
  });

  it("shows the pending state while the request runs", async () => {
    const user = userEvent.setup();
    server.use(
      http.post("/api/alerts/:id/resolve", async () => {
        await new Promise((r) => setTimeout(r, 150));
        return HttpResponse.json({
          ...SSH,
          resolved_at: "2026-10-06T09:05:00Z",
          resolved_value: 3,
        });
      }),
    );
    renderButton(SSH);
    await user.click(await screen.findByRole("button", { name: "Clôturer" }));
    expect(screen.getByRole("button", { name: "Clôture…" })).toBeDisabled();
    expect(await screen.findByRole("button", { name: "Clôturer" })).toBeEnabled();
  });

  it("reports a refusal from the API", async () => {
    const user = userEvent.setup();
    const onResolved = renderButton({ ...SSH, id: "closed" });
    await user.click(await screen.findByRole("button", { name: "Clôturer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only an open SSH alert can be closed by hand",
    );
    expect(onResolved).not.toHaveBeenCalled();
  });
});
