"""One-off export of YOLOv8n to NCNN, the fast CPU format for the Pi (see yolo_face_analyzer.py).

Run once after installing the "vision" extra (export is slow - tens of seconds - so it must not
happen on every API startup):

    uv run --extra vision yolo-export-ncnn

Produces yolov8n_ncnn_model/ next to yolov8n.pt in the working directory; YoloFaceAnalyzer picks
it up automatically on the next start.
"""

from __future__ import annotations

import sys

from ultralytics import YOLO

MODEL = "yolov8n.pt"


def main() -> None:
    print(f"Exporting {MODEL} to NCNN (this can take a minute)...")
    model = YOLO(MODEL)
    exported_path = model.export(format="ncnn", imgsz=640)
    print(f"Done: {exported_path}")


def export_ncnn_command() -> None:
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator running the command
        print(f"NCNN export failed: {exc}", file=sys.stderr)
        sys.exit(1)
