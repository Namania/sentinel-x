# µStreamer: serves a V4L2 webcam as an MJPEG stream (http://webcam:8080/stream), which the API
# relays exactly like the ESP32 camera. With a webcam that outputs MJPEG natively the frames are
# passed through untouched: almost no CPU on the Pi. v4l-utils lets the entrypoint pin camera
# controls (the Logitech C270 halves its frame rate in dim light unless told not to).
FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ustreamer v4l-utils \
    && rm -rf /var/lib/apt/lists/*
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
