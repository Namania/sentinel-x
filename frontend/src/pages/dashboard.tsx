import { CameraCard } from "@/features/camera/camera-card";
import { MetricsSection } from "@/features/metrics/metrics-section";
import { ServerHealthCard } from "@/features/server/server-health-card";
import { useDocumentTitle } from "@/lib/use-document-title";

/** Wall screen for the infra team: everything at a glance, each card opens its detail page. */
export function DashboardPage() {
  useDocumentTitle("Dashboard · sentinel-x");
  return (
    <div className="flex flex-1 flex-col gap-6 p-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <div className="grid items-stretch gap-4 lg:grid-cols-3">
        <CameraCard className="lg:col-span-2" />
        <ServerHealthCard />
      </div>
      <MetricsSection />
    </div>
  );
}
