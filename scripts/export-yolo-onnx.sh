#!/usr/bin/env sh
# Regenerates backend/models/yolov8n.onnx (YOLOv8n converted to ONNX at 320px), in a throwaway
# container: the conversion needs PyTorch, which never goes into the API image. Run it on a PC,
# not on the Raspberry Pi (it downloads ~1 GB), then commit the new file.
# Usage: scripts/export-yolo-onnx.sh
set -eu
cd "$(dirname "$0")/../backend/models"
exec docker run --rm -v "$PWD:/out" -w /tmp python:3.12-slim sh -c '
  pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision \
  && pip install --no-cache-dir "ultralytics==8.4.174" "onnx>=1.12" onnxslim \
  && pip uninstall -y opencv-python && pip install --no-cache-dir opencv-python-headless \
  && python -c "from ultralytics import YOLO; YOLO(\"yolov8n.pt\").export(format=\"onnx\", imgsz=320, opset=12, simplify=True)" \
  && cp yolov8n.onnx /out/yolov8n.onnx && chown "$(stat -c %u:%g /out)" /out/yolov8n.onnx'
