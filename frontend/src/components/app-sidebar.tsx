import { LayoutDashboard, LogOut, Video, type LucideIcon } from "lucide-react";
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
  SidebarSeparator,
  useSidebar,
} from "@/components/ui/sidebar";
import { useAuth } from "@/features/auth/use-auth";
import { initials } from "@/lib/initials";

type NavItemProps = { to: string; label: string; icon: LucideIcon; end: boolean };

const NAV_ITEMS: NavItemProps[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/camera", label: "Caméra", icon: Video, end: false },
];

function NavItem({ to, label, icon: Icon, end }: NavItemProps) {
  const active = useMatch({ path: to, end }) !== null;
  const { isMobile, setOpenMobile } = useSidebar();
  return (
    <SidebarMenuItem>
      <SidebarMenuButton asChild isActive={active} tooltip={label}>
        <NavLink
          to={to}
          end={end}
          onClick={() => {
            // On a phone the menu is a sheet: close it once the destination is chosen.
            if (isMobile) setOpenMobile(false);
          }}
        >
          <Icon />
          <span>{label}</span>
        </NavLink>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}

export function AppSidebar() {
  const { user, logout } = useAuth();
  const collapsed = useSidebar().state === "collapsed";

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-3">
        <span className="text-sm font-bold tracking-[0.18em] group-data-[collapsible=icon]:hidden">
          SENTINEL-X
        </span>
      </SidebarHeader>
      <SidebarSeparator className="mx-0" />
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Navigation</SidebarGroupLabel>
          <SidebarGroupContent>
            <nav aria-label="Navigation principale">
              <SidebarMenu>
                {NAV_ITEMS.map((item) => (
                  <NavItem key={item.to} {...item} />
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
              <Button variant="ghost" size="icon-sm" aria-label="Déconnexion" onClick={logout}>
                <LogOut />
              </Button>
            ) : (
              <div className="min-w-0 flex-1 text-xs">
                <p className="truncate font-medium">{user.email}</p>
                <button
                  type="button"
                  onClick={logout}
                  className="text-muted-foreground hover:text-foreground flex items-center gap-1 underline-offset-2 hover:underline"
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
