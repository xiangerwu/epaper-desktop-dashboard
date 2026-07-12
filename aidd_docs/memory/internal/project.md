# Project memory

- Target: HyRead Gaze Note Plus, Android 11, 1404×1872, DPR 2.
- Data flow: collectors → last-success SQLite cache → Jinja2 live HTML → Fully Kiosk.
- A source failure must keep the last successful cache value.
- `/health` stays live with top-level `ok`; each enabled source reports `available`, `age_seconds`, and `stale`.
- A source is stale only after twice its collection interval; missing data is stale.
- Startup collectors run concurrently. Scheduled intervals remain independent.
- Weather and AQI use an exact hourly cron at minute 0. Claude, Codex, and routine use 600-second intervals.
- Routine is a right-side card driven only by local time and cached state.
- Routine schedule: 00–02/22–24 night, 02–07 deep night, 07–09 breakfast, 09–12 work, 12–13 lunch, 13–18 work, 18–19 dinner, 19–22 work.
- Each work segment and day change resets the cycle. Updates 1–3 are focus/countdown; update 4 is a five-minute water/stretch reminder; the next update wraps to 1. At 600 seconds per update the nominal cycle is 40 minutes.
- GET `/refresh` runs collectors and advances routine. GET `/` and ADB page reload do not.
- Never pass `next_run_time=None` to scheduled interval collectors: APScheduler treats it as a permanently paused job. Startup collection belongs to lifespan; interval scheduling supplies the next run.
- OpenRouter code and configuration are reserved but disabled until it has a visible UI.
- Do not auto-refresh Claude/Codex OAuth tokens. Do not add image rendering or browser automation.
- Gate: `.venv/Scripts/python -m unittest discover -s tests -v`.
- Periodic hardware eval: `.venv/Scripts/python -m evals.device_screen`.
