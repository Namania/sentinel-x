import { Navigate, Outlet, useLocation } from "react-router";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/features/auth/use-auth";

export function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "restoring") {
    return (
      <div className="flex flex-1 flex-col p-4" aria-busy="true">
        <span className="sr-only">Chargement de la session…</span>
        <Skeleton className="min-h-64 flex-1" />
      </div>
    );
  }
  if (status === "anonymous") {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  return <Outlet />;
}
