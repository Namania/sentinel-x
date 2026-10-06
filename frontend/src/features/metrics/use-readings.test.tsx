import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderWithProviders } from "@/test/render";
import { makeReading, NOW_MS } from "@/test/sensors";
import { server, VALID_REFRESH } from "@/test/server";
import type { Range } from "./metrics-api";
import { useReadings } from "./use-readings";

function Probe({ range }: { range: Range }) {
  const { status, points, latest, previous, push } = useReadings("esp-interieur", range);
  return (
    <div>
      <p>status:{status}</p>
      <p>points:{points.length}</p>
      <p>latest:{latest?.temperature_c ?? "-"}</p>
      <p>previous:{previous?.temperature_c ?? "-"}</p>
      <button
        onClick={() =>
          push(
            makeReading({
              recorded_at: new Date(NOW_MS + 60_000).toISOString(),
              temperature_c: 30,
            }),
          )
        }
      >
        push
      </button>
      <button onClick={() => push(makeReading({ device_id: "esp-ext", temperature_c: 99 }))}>
        push-other
      </button>
    </div>
  );
}

function renderProbe(range: Range) {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderWithProviders(<Probe range={range} />);
}

function recordReadingUrls(): string[] {
  const urls: string[] = [];
  server.events.on("request:start", ({ request }) => {
    if (request.url.includes("/sensors/readings")) urls.push(request.url);
  });
  return urls;
}

describe("useReadings", () => {
  it("loads raw readings for 15 minutes and derives latest and previous", async () => {
    const urls = recordReadingUrls();
    renderProbe("15m");
    expect(await screen.findByText("status:ready")).toBeInTheDocument();
    expect(screen.getByText("points:5")).toBeInTheDocument();
    expect(screen.getByText("latest:22")).toBeInTheDocument();
    expect(screen.getByText("previous:21.5")).toBeInTheDocument();
    expect(urls[0]).not.toContain("bucket=");
  });

  it("requests buckets for an hour", async () => {
    const urls = recordReadingUrls();
    renderProbe("1h");
    await screen.findByText("status:ready");
    expect(urls[0]).toContain("bucket=1m");
    expect(screen.getByText("points:4")).toBeInTheDocument();
  });

  it("pushes a live reading of the same device and ignores other devices", async () => {
    const user = userEvent.setup();
    renderProbe("15m");
    await screen.findByText("status:ready");
    await user.click(screen.getByRole("button", { name: "push-other" }));
    expect(screen.getByText("points:5")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "push" }));
    expect(screen.getByText("points:6")).toBeInTheDocument();
    expect(screen.getByText("latest:30")).toBeInTheDocument();
    expect(screen.getByText("previous:22")).toBeInTheDocument();
  });

  it("reports an error when the API fails", async () => {
    server.use(http.get("/api/sensors/readings", () => HttpResponse.json({}, { status: 500 })));
    renderProbe("15m");
    expect(await screen.findByText("status:error")).toBeInTheDocument();
  });
});
