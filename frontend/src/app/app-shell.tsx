import { Outlet, useLocation } from "react-router";
import { AppSidebar } from "@/components/app-sidebar";
import { SidebarInset, SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeToggle } from "@/features/theme/theme-toggle";

const TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/camera": "Caméra",
  "/serveur": "Serveur",
};

/** Layout of the authenticated area: sidebar + a thin top bar above the page. */
export function AppShell() {
  const { pathname } = useLocation();
  return (
    <TooltipProvider>
      {/* Wall screen first: collapsed on load, the user can still open it for the session. */}
      <SidebarProvider defaultOpen={false}>
        <AppSidebar />
        <SidebarInset className="bg-background text-foreground">
          <header className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
            <SidebarTrigger aria-label="Afficher ou masquer le menu" />
            <span className="text-sm font-medium">{TITLES[pathname] ?? "sentinel-x"}</span>
            <div className="ml-auto">
              <ThemeToggle />
            </div>
          </header>
          <div className="flex flex-1 flex-col">
            <Outlet />
          </div>
        </SidebarInset>
      </SidebarProvider>
    </TooltipProvider>
  );
}
