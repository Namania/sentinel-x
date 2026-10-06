import { BellRing, LayoutDashboard, LogOut, Server, Video, type LucideIcon } from "lucide-react";
import { NavLink, useMatch } from "react-router";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import { useAlertCount } from "@/features/alerts/use-alert-count";
import { useAuth } from "@/features/auth/use-auth";
import { initials } from "@/lib/initials";

type NavItemProps = {
  to: string;
  label: string;
  icon: LucideIcon;
  end: boolean;
  /** Open alert count shown as a red badge; hidden when 0 or unknown. */
  badge?: number | null;
};

const NAV_ITEMS: NavItemProps[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/camera", label: "Caméra", icon: Video, end: false },
  { to: "/serveur", label: "Serveur", icon: Server, end: false },
  { to: "/alertes", label: "Alertes", icon: BellRing, end: false },
];

function NavItem({ to, label, icon: Icon, end, badge }: NavItemProps) {
  const active = useMatch({ path: to, end }) !== null;
  const { isMobile, setOpenMobile } = useSidebar();
  return (
    <SidebarMenuItem>
      <SidebarMenuButton asChild isActive={active} tooltip={label}>
        <NavLink
          to={to}
          end={end}
          className="relative"
          onClick={() => {
            // On a phone the menu is a sheet: close it once the destination is chosen.
            if (isMobile) setOpenMobile(false);
          }}
        >
          <Icon />
          <span>{label}</span>
          {badge ? (
            <span
              aria-label={`${badge} ${badge > 1 ? "alertes ouvertes" : "alerte ouverte"}`}
              className="bg-destructive ml-auto min-w-4 rounded-full px-1 text-center text-[10px] leading-4 font-semibold text-white tabular-nums group-data-[collapsible=icon]:absolute group-data-[collapsible=icon]:-top-0.5 group-data-[collapsible=icon]:-right-0.5 group-data-[collapsible=icon]:ml-0"
            >
              {badge}
            </span>
          ) : null}
        </NavLink>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}

export function AppSidebar() {
  const { user, logout } = useAuth();
  const collapsed = useSidebar().state === "collapsed";
  const openAlerts = useAlertCount();

  return (
    <Sidebar collapsible="icon">
      {/* Same height as the top bar of the page (h-12) so both bottom borders line up. */}
      <SidebarHeader className="h-12 flex-row items-center justify-center border-b p-0">
        <span className="text-sm font-bold tracking-[0.18em]">
          {collapsed ? "S" : "SENTINEL-X"}
        </span>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Navigation</SidebarGroupLabel>
          <SidebarGroupContent>
            <nav aria-label="Navigation principale">
              <SidebarMenu className="gap-px">
                {NAV_ITEMS.map((item) => (
                  <NavItem
                    key={item.to}
                    {...item}
                    badge={item.to === "/alertes" ? openAlerts : null}
                  />
                ))}
              </SidebarMenu>
            </nav>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter>
        {user && (
          <section
            aria-label="Mon compte"
            className="flex items-center gap-2 px-1 py-1 group-data-[collapsible=icon]:flex-col group-data-[collapsible=icon]:px-0"
          >
            <Avatar className="size-8">
              <AvatarFallback className="text-xs">{initials(user.email)}</AvatarFallback>
            </Avatar>
            {collapsed ? (
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Déconnexion"
                onClick={logout}
                className="text-destructive hover:text-destructive"
              >
                <LogOut />
              </Button>
            ) : (
              <div className="min-w-0 flex-1 text-xs">
                <p className="truncate font-medium">{user.email}</p>
                <button
                  type="button"
                  onClick={logout}
                  className="text-destructive flex items-center gap-1 underline-offset-2 hover:underline"
                >
                  <LogOut className="size-3" aria-hidden="true" />
                  Déconnexion
                </button>
              </div>
            )}
          </section>
        )}
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
