# Known faces: whitelist and blacklist

Drop reference photos directly in this folder for the **whitelist** (people the dashboard reports
by name instead of "INTRUS"). Drop them in `blacklist/` for the **blacklist** (people who must
raise an alert the moment the camera sees them - the same kind of alert as a gas spike or an
over-temperature, visible in `/alertes` and able to trigger the buzzer).

In both folders, the file name without its extension and trailing number is the name shown in the
dashboard: `kevan.jpg`, `kevan1.jpg`, `kevan_2.jpg` and `kevan (2).jpg` are all "kevan".

- 2-3 clear, front-facing photos per person work best; photos taken by the camera itself, at
  the distance people will stand from it, match best of all.
- Photos in profile, or with a face too small to use, are skipped at startup (see the API logs).
- Supported formats: `.jpg`, `.jpeg`, `.png`.
- Loaded once at API startup (`VISION_IDENTIFY_FACES=true`); restart the API after adding or
  changing a photo, in either folder.
- Whitelist: anyone whose face doesn't match a photo here is reported as an intruder, and so is
  anyone whose face can't be read (turned away, in profile, too far) before being recognised once.
  Once recognised, a person keeps their name while they are followed, even turned away.
- Blacklist: a match opens an "intruder" alert for that person (`/alertes`, and the buzzer if
  `BUZZER_TRIGGERS` includes `intruder`, which it does by default); the alert resolves itself once
  they leave the frame. The same person can be in both lists - the blacklist alert does not
  depend on whether they also match the whitelist.

This directory's photos are personal data - do not commit real teammate photos to a public
repository. Add real photos locally or via `.env`/deploy-time file transfer instead.
