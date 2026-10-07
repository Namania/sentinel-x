# µStreamer: serves a V4L2 webcam as an MJPEG stream (http://webcam:8080/stream), which the API
# relays exactly like the ESP32 camera. With a webcam that outputs MJPEG natively the frames are
# passed through untouched: almost no CPU on the Pi.
FROM debian:bookworm-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends ustreamer \
    && rm -rf /var/lib/apt/lists/*
EXPOSE 8080
ENTRYPOINT ["ustreamer"]
