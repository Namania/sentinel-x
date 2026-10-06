import { MetricsSection } from "@/features/metrics/metrics-section";
import { useDocumentTitle } from "@/lib/use-document-title";

export function DashboardPage() {
  useDocumentTitle("Dashboard · sentinel-x");
  return (
    <div className="flex flex-1 flex-col p-6">
      <MetricsSection />
    </div>
  );
}
