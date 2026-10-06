import { useCallback, useEffect, useState } from "react";
import { useAuth } from "@/features/auth/use-auth";
import {
  appendLive,
  BUCKET_MS,
  bucketFor,
  readingsPath,
  toPoints,
  type Bucket,
  type MetricPoint,
  type Range,
  type Reading,
} from "./metrics-api";

type State = {
  status: "loading" | "ready" | "error";
  points: MetricPoint[];
  latest: Reading | null;
  previous: Reading | null;
};

const EMPTY: State = { status: "loading", points: [], latest: null, previous: null };

/** History of one device over a range, plus live readings pushed through `push`. */
export function useReadings(deviceId: string | null, range: Range) {
  const { authFetch } = useAuth();
  const [state, setState] = useState<State>(EMPTY);

  useEffect(() => {
    if (!deviceId) return;
    let cancelled = false;
    const bucket = bucketFor(range);
    authFetch<Reading[] | Bucket[]>(readingsPath(deviceId, range, Date.now()))
      .then((rows) => {
        if (cancelled) return;
        const raw = bucket === null ? (rows as Reading[]) : [];
        setState({
          status: "ready",
          points: toPoints(rows, bucket !== null),
          latest: raw.at(-1) ?? null,
          previous: raw.at(-2) ?? null,
        });
      })
      .catch(() => {
        if (!cancelled) setState({ ...EMPTY, status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch, deviceId, range]);

  const push = useCallback(
    (reading: Reading) => {
      if (reading.device_id !== deviceId) return;
      const bucket = bucketFor(range);
      setState((current) => ({
        ...current,
        points: appendLive(current.points, reading, range, bucket ? BUCKET_MS[bucket] : null),
        latest: reading,
        previous: current.latest,
      }));
    },
    [deviceId, range],
  );

  return { ...state, push };
}
