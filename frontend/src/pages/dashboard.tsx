import { AccountCard, ApiCard, CameraCard } from "@/features/dashboard/status-cards";
import { MetricsSection } from "@/features/metrics/metrics-section";
import { useDocumentTitle } from "@/lib/use-document-title";

export function DashboardPage() {
  useDocumentTitle("Dashboard · sentinel-x");
  return (
    <section className="flex flex-1 flex-col gap-6 p-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <CameraCard />
        <ApiCard />
        <AccountCard />
      </div>
      <MetricsSection />
    </section>
  );
}
