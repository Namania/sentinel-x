import { Outlet } from "react-router";
import { AppHeader } from "@/components/app-header";

export function RootLayout() {
  return (
    <div className="bg-background text-foreground flex min-h-svh flex-col">
      <AppHeader />
      <main className="flex flex-1 flex-col">
        <Outlet />
      </main>
    </div>
  );
}
