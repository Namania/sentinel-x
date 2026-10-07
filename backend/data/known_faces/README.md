# Known faces whitelist

Drop reference photos here. The file name without its extension and trailing number is the name
shown in the dashboard: `kevan.jpg`, `kevan1.jpg` and `kevan_2.jpg` are all "kevan".

- 2-3 clear, front-facing photos per person work best; photos taken by the camera itself, at
  the distance people will stand from it, match best of all.
- Photos in profile, or with a face too small to use, are skipped at startup (see the API logs).
- Supported formats: `.jpg`, `.jpeg`, `.png`.
- Loaded once at API startup (`VISION_IDENTIFY_FACES=true`); restart the API after adding or
  changing a photo.
- Anyone whose face doesn't match a photo here is reported as an intruder, and so is anyone
  whose face can't be read (turned away, in profile, too far) before being recognised once.
  Once recognised, a person keeps their name while they are followed, even turned away.

This directory's photos are personal data - do not commit real teammate photos to a public
repository. Add real photos locally or via `.env`/deploy-time file transfer instead.
