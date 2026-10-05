import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

function Picker() {
  const [value, setValue] = useState("dark");
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" aria-label="Choisir">
          {value}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuRadioGroup value={value} onValueChange={setValue}>
          <DropdownMenuRadioItem value="light">Clair</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">Sombre</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

describe("toolchain", () => {
  it("merges tailwind classes", () => {
    expect(cn("p-2", "p-4")).toBe("p-4");
  });

  it("renders a shadcn button", () => {
    render(<Button>Se connecter</Button>);
    expect(screen.getByRole("button", { name: "Se connecter" })).toBeInTheDocument();
  });

  it("drives a radix dropdown with user-event under jsdom", async () => {
    const user = userEvent.setup();
    render(<Picker />);
    await user.click(screen.getByRole("button", { name: "Choisir" }));
    await user.click(await screen.findByRole("menuitemradio", { name: "Clair" }));
    expect(screen.getByRole("button", { name: "Choisir" })).toHaveTextContent("light");
  });
});
