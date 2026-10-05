import { CameraView } from "@/features/camera/camera-view";
import { useDocumentTitle } from "@/lib/use-document-title";

export function CameraPage() {
  useDocumentTitle("Caméra · sentinel-x");
  return (
    <>
      <h1 className="sr-only">Caméra</h1>
      <CameraView />
    </>
  );
}
