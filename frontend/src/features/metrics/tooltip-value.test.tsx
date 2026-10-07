import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { valueFormatter } from "./tooltip-value";

type Item = Parameters<ReturnType<typeof valueFormatter>>[2];
const item = (color: string) => ({ color }) as unknown as Item;

describe("valueFormatter", () => {
  it("renders the series label and the value in French with the right precision", () => {
    const format = valueFormatter({ label: "Température (°C)", digits: 1 });
    render(<div>{format(22.456, "temperature", item("#d9541e"), 0, [])}</div>);
    expect(screen.getByText("Température (°C)")).toBeInTheDocument();
    expect(screen.getByText("22,5")).toBeInTheDocument();
  });

  it("appends a unit when given one", () => {
    const format = valueFormatter({ label: "Mémoire utilisée", digits: 1, unit: "Gio" });
    render(<div>{format(0.7221, "memGib", item("#000"), 0, [])}</div>);
    expect(screen.getByText("0,7 Gio")).toBeInTheDocument();
  });
});
