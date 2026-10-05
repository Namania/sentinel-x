import { LayoutDashboard, LogOut, Video, type LucideIcon } from "lucide-react";
import { NavLink, useLocation } from "react-router";
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
} from "@/components/ui/sidebar";
import { useAuth } from "@/features/auth/use-auth";
import { formatLongDate } from "@/lib/format-date";
import { initials } from "@/lib/initials";

type NavItem = { to: string; label: string; icon: LucideIcon; end: boolean };

const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/camera", label: "Caméra", icon: Video, end: false },
];

function isCurrent(item: NavItem, pathname: string): boolean {
  return item.end ? pathname === item.to : pathname.startsWith(item.to);
}

export function AppSidebar() {
  const { user, logout } = useAuth();
  const { pathname } = useLocation();

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-4 py-3">
        <span className="text-sm font-bold tracking-[0.18em] group-data-[collapsible=icon]:hidden">
          SENTINEL-X
        </span>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Navigation</SidebarGroupLabel>
          <SidebarGroupContent>
            <nav aria-label="Navigation principale">
              <SidebarMenu>
                {NAV_ITEMS.map((item) => (
                  <SidebarMenuItem key={item.to}>
                    <SidebarMenuButton
                      asChild
                      isActive={isCurrent(item, pathname)}
                      tooltip={item.label}
                    >
                      <NavLink to={item.to} end={item.end}>
                        <item.icon />
                        <span>{item.label}</span>
                      </NavLink>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                ))}
              </SidebarMenu>
            </nav>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter role="contentinfo">
        {user && (
          <div className="flex items-center gap-2 px-1 py-1">
            <Avatar className="size-8">
              <AvatarFallback className="text-xs">{initials(user.email)}</AvatarFallback>
            </Avatar>
            <div className="min-w-0 flex-1 text-xs group-data-[collapsible=icon]:hidden">
              <p className="truncate font-medium">{user.email}</p>
              <p className="text-muted-foreground truncate">
                Compte créé le {formatLongDate(user.created_at)}
              </p>
            </div>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Se déconnecter"
              onClick={logout}
              className="group-data-[collapsible=icon]:hidden"
            >
              <LogOut />
            </Button>
          </div>
        )}
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  );
}
