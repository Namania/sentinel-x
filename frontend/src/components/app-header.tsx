import { Link } from "react-router";
import { ThemeToggle } from "@/features/theme/theme-toggle";

export function AppHeader() {
  return (
    <header className="flex items-center justify-between border-b px-4 py-2">
      <Link to="/" className="text-sm font-bold tracking-[0.18em]">
        SENTINEL-X
      </Link>
      <div className="flex items-center gap-2">
        <ThemeToggle />
      </div>
    </header>
  );
}
