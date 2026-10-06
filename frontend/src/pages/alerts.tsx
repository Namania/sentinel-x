import { AlertsPageContent } from "@/features/alerts/alerts-page-content";
import { useDocumentTitle } from "@/lib/use-document-title";

export function AlertsPage() {
  useDocumentTitle("Alertes · sentinel-x");
  return (
    <div className="flex flex-1 flex-col p-6">
      <AlertsPageContent />
    </div>
  );
}
