#!/bin/sh
# Apply optional V4L2 controls, then hand over to µStreamer.
# WEBCAM_FPS: optional --desired-fps; WEBCAM_CONTROLS: comma-separated name=value pairs, e.g. "exposure_auto_priority=0,power_line_frequency=1".
# A control the camera does not expose is skipped with a note (names differ between kernels).
set -eu
DEVICE="${WEBCAM_DEVICE_IN_CONTAINER:-/dev/video0}"
if [ -n "${WEBCAM_CONTROLS:-}" ]; then
  OLD_IFS=$IFS; IFS=,
  for control in $WEBCAM_CONTROLS; do
    IFS=$OLD_IFS
    [ -n "$control" ] || continue
    if v4l2-ctl -d "$DEVICE" -c "$control" 2>/dev/null; then
      echo "-- INFO  [entrypoint] -- applied $control"
    else
      echo "-- INFO  [entrypoint] -- control not available on this camera: $control"
    fi
  done
  IFS=$OLD_IFS
fi
# Frame-rate cap only when asked for: some cameras reject the request and never capture.
if [ -n "${WEBCAM_FPS:-}" ]; then
  set -- "$@" "--desired-fps=$WEBCAM_FPS"
fi
exec ustreamer "$@"
