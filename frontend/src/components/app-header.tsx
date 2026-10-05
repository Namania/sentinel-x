import { LogOut } from "lucide-react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/use-auth";
import { ThemeToggle } from "@/features/theme/theme-toggle";

export function AppHeader() {
  const { status, user, logout } = useAuth();
  return (
    <header className="flex items-center justify-between border-b px-4 py-2">
      <Link to="/" className="text-sm font-bold tracking-[0.18em]">
        SENTINEL-X
      </Link>
      <div className="flex items-center gap-2">
        {status === "authenticated" && (
          <>
            <span className="text-muted-foreground text-sm">{user?.email}</span>
            <Button variant="ghost" size="icon" aria-label="Se déconnecter" onClick={logout}>
              <LogOut className="size-5" />
            </Button>
          </>
        )}
        <ThemeToggle />
      </div>
    </header>
  );
}
