import { Link } from "react-router";
import { Button } from "@/components/ui/button";
import { useDocumentTitle } from "@/lib/use-document-title";

export function NotFoundPage() {
  useDocumentTitle("404 · sentinel-x");
  return (
    <section className="flex flex-1 flex-col items-center justify-center gap-4 px-4 text-center">
      <p className="text-muted-foreground text-7xl font-black tracking-tight">404</p>
      <h1 className="text-2xl font-semibold">Cette page n'existe pas</h1>
      <p className="text-muted-foreground max-w-md">
        L'adresse demandée ne correspond à aucune page de sentinel-x.
      </p>
      <Button asChild>
        <Link to="/">Retour à l'accueil</Link>
      </Button>
    </section>
  );
}
