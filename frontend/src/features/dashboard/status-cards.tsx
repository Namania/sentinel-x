import { useId, type ReactNode } from "react";
import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/features/auth/use-auth";
import { CAMERA_STATUS_PATH, viewersLabel, type CameraStatus } from "@/features/camera/camera-api";
import { formatLongDate } from "@/lib/format-date";
import { useApiResource } from "./use-api-resource";

function StatusCard({
  title,
  children,
  footer,
}: {
  title: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const id = useId();
  return (
    <Card role="region" aria-labelledby={id}>
      <CardHeader>
        <CardTitle id={id}>{title}</CardTitle>
      </CardHeader>
      <CardContent>{children}</CardContent>
      {footer && <CardFooter>{footer}</CardFooter>}
    </Card>
  );
}

const Unavailable = () => <p className="text-destructive font-medium">Indisponible</p>;
const Loading = () => <Skeleton className="h-5 w-32" />;

export function CameraCard() {
  const resource = useApiResource<CameraStatus>(CAMERA_STATUS_PATH);
  return (
    <StatusCard
      title="Caméra"
      footer={
        <Button asChild variant="outline" size="sm">
          <Link to="/camera">Voir la caméra</Link>
        </Button>
      }
    >
      {resource.status === "loading" && <Loading />}
      {resource.status === "error" && <Unavailable />}
      {resource.status === "ready" && (
        <div className="space-y-1">
          <p className="font-medium">
            {resource.data.configured ? "Configurée" : "Non configurée"}
          </p>
          <p className="text-muted-foreground text-sm">{viewersLabel(resource.data.viewers)}</p>
        </div>
      )}
    </StatusCard>
  );
}

export function ApiCard() {
  const resource = useApiResource<{ status: string }>("/health");
  return (
    <StatusCard title="API">
      {resource.status === "loading" && <Loading />}
      {resource.status === "error" && <Unavailable />}
      {resource.status === "ready" &&
        (resource.data.status === "ok" ? <p className="font-medium">En ligne</p> : <Unavailable />)}
    </StatusCard>
  );
}

export function AccountCard() {
  const { user } = useAuth();
  return (
    <StatusCard title="Compte">
      {user && (
        <div className="space-y-1">
          <p className="truncate font-medium">{user.email}</p>
          <p className="text-muted-foreground text-sm">Créé le {formatLongDate(user.created_at)}</p>
        </div>
      )}
    </StatusCard>
  );
}
