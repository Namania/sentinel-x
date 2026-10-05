export type CameraStatus = { configured: boolean; viewers: number };

export const CAMERA_STATUS_PATH = "/camera/status";

/** Relayed MJPEG url. `attempt` makes every reconnection a distinct url so the browser re-fetches. */
export function streamUrl(token: string, attempt: number): string {
  return `/api/camera/stream?token=${encodeURIComponent(token)}&t=${Date.now()}-${attempt}`;
}
