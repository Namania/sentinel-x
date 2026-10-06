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
  /** Which (device, range) this state belongs to; another key means "not loaded yet". */
  key: string;
  status: "loading" | "ready" | "error";
  points: MetricPoint[];
  latest: Reading | null;
  previous: Reading | null;
};

const EMPTY: Omit<State, "key"> = { status: "loading", points: [], latest: null, previous: null };
const requestKey = (deviceId: string | null, range: Range) => `${deviceId ?? ""}|${range}`;

/** History of one device over a range, plus live readings pushed through `push`. */
export function useReadings(deviceId: string | null, range: Range) {
  const { authFetch } = useAuth();
  const key = requestKey(deviceId, range);
  const [state, setState] = useState<State>({ key, ...EMPTY });

  useEffect(() => {
    if (!deviceId) return;
    let cancelled = false;
    const bucket = bucketFor(range);
    authFetch<Reading[] | Bucket[]>(readingsPath(deviceId, range, Date.now()))
      .then((rows) => {
        if (cancelled) return;
        const raw = bucket === null ? (rows as Reading[]) : [];
        setState({
          key,
          status: "ready",
          points: toPoints(rows, bucket !== null),
          latest: raw.at(-1) ?? null,
          previous: raw.at(-2) ?? null,
        });
      })
      .catch(() => {
        if (!cancelled) setState({ key, ...EMPTY, status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [authFetch, deviceId, range, key]);

  const push = useCallback(
    (reading: Reading) => {
      if (reading.device_id !== deviceId) return;
      const bucket = bucketFor(range);
      setState((current) =>
        current.key !== key
          ? current // history for this key is still loading; it will include the reading
          : {
              ...current,
              points: appendLive(current.points, reading, range, bucket ? BUCKET_MS[bucket] : null),
              latest: reading,
              previous: current.latest,
            },
      );
    },
    [deviceId, range, key],
  );

  // A state from another (device, range) is stale: show the loading state instead.
  const visible = state.key === key ? state : { key, ...EMPTY };
  const { key: _key, ...rest } = visible;
  void _key;
  return { ...rest, push };
}
