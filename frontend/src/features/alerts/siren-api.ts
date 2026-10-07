import { formatTime } from "@/lib/format-number";
import type { Metric } from "./alerts-api";

export type SirenState = {
  on: boolean;
  reason: Metric | null;
  open: number;
  muted_until: string | null;
};

export const SIREN_PATH = "/alerts/siren";
export const SIREN_MUTE_PATH = "/alerts/siren/mute";

const REASONS: Record<Metric, string> = {
  gas: "gaz",
  temperature: "température",
  humidity: "humidité",
  intruder: "intrus",
};

/** « Sirène active : gaz », « Sirène coupée jusqu'à 09:27 », « Sirène au repos ». */
export function sirenLabel(state: SirenState): string {
  if (state.muted_until) {
    return `Sirène coupée jusqu'à ${formatTime(Date.parse(state.muted_until))}`;
  }
  if (state.on && state.reason) return `Sirène active : ${REASONS[state.reason]}`;
  return "Sirène au repos";
}
