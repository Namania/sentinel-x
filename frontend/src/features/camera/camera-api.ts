/** `frames` counts what the relay received since start; two equal readings mean a stalled source. */
export type CameraStatus = { configured: boolean; viewers: number; frames?: number };

export const CAMERA_STATUS_PATH = "/camera/status";

export function viewersLabel(count: number): string {
  return `${count} ${count > 1 ? "spectateurs" : "spectateur"}`;
}
