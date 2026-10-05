import { Link } from "react-router";
import { ThemeToggle } from "@/features/theme/theme-toggle";

/** Header of the public pages (login, 404). Authenticated pages use the sidebar shell. */
export function AppHeader() {
  return (
    <header className="flex items-center justify-between border-b px-4 py-2">
      <Link to="/" className="text-sm font-bold tracking-[0.18em]">
        SENTINEL-X
      </Link>
      <ThemeToggle />
    </header>
  );
}
