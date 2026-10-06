import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { routes } from "@/app/router";
import { REFRESH_TOKEN_KEY } from "@/features/auth/token-storage";
import { renderRoutes } from "@/test/render";
import { makeReading, NOW_MS } from "@/test/sensors";
import { sensorsLink, server, VALID_REFRESH } from "@/test/server";

function renderDashboard() {
  localStorage.setItem(REFRESH_TOKEN_KEY, VALID_REFRESH);
  return renderRoutes(routes, "/");
}

async function metrics() {
  return within(await screen.findByRole("region", { name: "Capteurs" }));
}

describe("Sensors section of the Dashboard", () => {
  it("is a level-2 section under the page's single level-1 heading, without status cards", async () => {
    renderDashboard();
    const section = await metrics();
    expect(section.getByRole("heading", { level: 2, name: "Capteurs" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.queryByRole("region", { name: "Caméra" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "API" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Compte" })).not.toBeInTheDocument();
  });

  it("shows the latest values in the tiles with their variation", async () => {
    renderDashboard();
    const section = await metrics();
    const temperature = within(await section.findByRole("group", { name: "Température" }));
    expect(await temperature.findByText("22,0")).toBeInTheDocument(); // last raw fixture
    expect(temperature.getByText(/\+0,5/)).toBeInTheDocument();
    expect(
      within(section.getByRole("group", { name: "Humidité" })).getByText("44"),
    ).toBeInTheDocument();
    expect(
      within(section.getByRole("group", { name: "Gaz" })).getByText("440"),
    ).toBeInTheDocument();
    expect(section.queryByText("Alerte gaz")).not.toBeInTheDocument();
  });

  it("flags a gas alert on the gas tile", async () => {
    server.use(
      http.get("/api/sensors/readings", () =>
        HttpResponse.json([
          makeReading({
            gas_level: 1800,
            gas_alert: true,
            recorded_at: new Date(NOW_MS).toISOString(),
          }),
        ]),
      ),
    );
    renderDashboard();
    const section = await metrics();
    expect(await section.findByText("Alerte gaz")).toBeInTheDocument();
  });

  it("switches to the table view and lists the readings", async () => {
    const user = userEvent.setup();
    renderDashboard();
    const section = await metrics();
    await section.findByRole("group", { name: "Température" });
    await user.click(section.getByRole("radio", { name: "Tableau" }));
    const table = section.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(6); // header + 5 readings
    expect(within(table).getByText("22,0")).toBeInTheDocument();
  });

  it("reloads with buckets when the range changes", async () => {
    const urls: string[] = [];
    server.events.on("request:start", ({ request }) => {
      if (request.url.includes("/sensors/readings")) urls.push(request.url);
    });
    const user = userEvent.setup();
    renderDashboard();
    const section = await metrics();
    await section.findByRole("group", { name: "Température" });
    await user.click(section.getByRole("radio", { name: "6 h" }));
    await waitFor(() => expect(urls.some((u) => u.includes("bucket=5m"))).toBe(true));
  });

  it("updates the tiles when a live reading arrives", async () => {
    server.use(
      sensorsLink.addEventListener("connection", ({ client }) => {
        setTimeout(() => {
          client.send(
            JSON.stringify({
              type: "sensor.reading",
              data: makeReading({
                temperature_c: 31.4,
                recorded_at: new Date(NOW_MS + 60_000).toISOString(),
              }),
            }),
          );
          client.send(
            JSON.stringify({
              type: "sensor.reading",
              data: makeReading({
                device_id: "esp-ext",
                temperature_c: 5,
                recorded_at: new Date(NOW_MS + 61_000).toISOString(),
              }),
            }),
          );
        }, 50);
      }),
    );
    renderDashboard();
    const section = await metrics();
    const temperature = within(await section.findByRole("group", { name: "Température" }));
    expect(await temperature.findByText("31,4")).toBeInTheDocument();
    expect(temperature.queryByText("5,0")).not.toBeInTheDocument();
  });

  it("explains when there is no data", async () => {
    server.use(http.get("/api/sensors/readings", () => HttpResponse.json([])));
    renderDashboard();
    const section = await metrics();
    expect(
      await section.findByText("Aucune mesure pour cet appareil sur la plage choisie."),
    ).toBeInTheDocument();
  });

  it("explains when no device has reported yet instead of loading forever", async () => {
    server.use(http.get("/api/sensors/devices", () => HttpResponse.json([])));
    renderDashboard();
    const section = await metrics();
    expect(
      await section.findByText("Aucun appareil n'a encore envoyé de mesure."),
    ).toBeInTheDocument();
    expect(
      section.queryByRole("status", { name: "Chargement des mesures" }),
    ).not.toBeInTheDocument();
  });

  it("marks gas alert buckets with a symbol, not colour alone", async () => {
    const user = userEvent.setup();
    renderDashboard();
    const section = await metrics();
    await section.findByRole("group", { name: "Température" });
    await user.click(section.getByRole("radio", { name: "6 h" }));
    // bucketsFixture flags only the last of four buckets.
    expect(await section.findAllByRole("img", { name: "Alerte gaz" })).toHaveLength(1);
  });
});
