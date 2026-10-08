import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/use-auth";
import { resolveAlertPath, type Alert } from "./alerts-api";

type Props = { alert: Alert; onResolved?: (alert: Alert) => void };

/** « Clôturer » an open ssh alert now, instead of waiting for the quiet minutes. */
export function CloseAlertButton({ alert, onResolved }: Props) {
  const { authFetch } = useAuth();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function close() {
    setPending(true);
    setError(null);
    try {
      const closed = await authFetch<Alert>(resolveAlertPath(alert.id), { method: "POST" });
      onResolved?.(closed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Clôture impossible");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <Button variant="outline" size="sm" disabled={pending} onClick={close}>
        {pending ? "Clôture…" : "Clôturer"}
      </Button>
      {error && (
        <p role="alert" className="text-destructive text-xs">
          {error}
        </p>
      )}
    </div>
  );
}
