import { SshPageContent } from "@/features/ssh/ssh-page-content";
import { useDocumentTitle } from "@/lib/use-document-title";

export function SshPage() {
  useDocumentTitle("Accès SSH · sentinel-x");
  return (
    <div className="flex flex-1 flex-col p-6">
      <SshPageContent />
    </div>
  );
}
