import { ServerDetail } from "@/features/server/server-detail";
import { useDocumentTitle } from "@/lib/use-document-title";

export function ServerPage() {
  useDocumentTitle("Serveur · sentinel-x");
  return (
    <div className="flex flex-1 flex-col p-6">
      <ServerDetail />
    </div>
  );
}
