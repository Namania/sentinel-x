import { useEffect, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";

export type Resource<T> =
  { status: "loading" } | { status: "ready"; data: T } | { status: "error"; error: Error };

/** Load one API resource once, through the authenticated fetch. */
export function useApiResource<T>(path: string): Resource<T> {
  const { authFetch } = useAuth();
  const [resource, setResource] = useState<Resource<T>>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    authFetch<T>(path)
      .then((data) => {
        if (!cancelled) setResource({ status: "ready", data });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setResource({
            status: "error",
            error: error instanceof Error ? error : new Error(String(error)),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch, path]);

  return resource;
}
