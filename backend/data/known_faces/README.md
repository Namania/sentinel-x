# Known faces whitelist

Drop one reference photo per person here. The file name (without extension) is the name shown
in the dashboard, e.g. `kevan.jpg` -> "kevan".

- One clear, front-facing photo per person is enough.
- Supported formats: `.jpg`, `.jpeg`, `.png`.
- Loaded once at API startup (`VISION_ENABLED=true`); restart the API after adding or changing a
  photo.
- Anyone whose face doesn't match a photo here is reported as an intruder.

This directory's photos are personal data - do not commit real teammate photos to a public
repository. Add real photos locally or via `.env`/deploy-time file transfer instead.
