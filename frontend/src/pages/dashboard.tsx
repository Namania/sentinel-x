import { AlertsCard } from "@/features/alerts/alerts-card";
import { SirenBar } from "@/features/alerts/siren-bar";
import { useAlerts } from "@/features/alerts/use-alerts";
import { CameraCard } from "@/features/camera/camera-card";
import { MetricsSection } from "@/features/metrics/metrics-section";
import { ServerHealthCard } from "@/features/server/server-health-card";
import { useDocumentTitle } from "@/lib/use-document-title";

/** Wall screen for the infra team: everything at a glance, each card opens its detail page. */
export function DashboardPage() {
  useDocumentTitle("Dashboard · sentinel-x");
  // Mounted once here and shared by the alerts card and the sensor tiles.
  const alerts = useAlerts();
  return (
    <div className="flex flex-1 flex-col gap-6 p-6">
      {/* The top bar already shows the title; keep it for the document outline only. */}
      <h1 className="sr-only">Dashboard</h1>
      <div className="grid items-stretch gap-4 lg:grid-cols-3">
        <CameraCard className="lg:col-span-2" />
        <ServerHealthCard />
      </div>
      {/* Outside the card: the card is one link, and a link cannot hold the mute button. */}
      <SirenBar />
      <AlertsCard status={alerts.status} alerts={alerts.alerts} />
      <MetricsSection openAlerts={alerts.open} />
    </div>
  );
}
