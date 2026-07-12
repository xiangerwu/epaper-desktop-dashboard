# Project memory

- Target: HyRead Gaze Note Plus, Android 11, 1404×1872, DPR 2.
- Data flow: collectors → last-success SQLite cache → Jinja2 live HTML → Fully Kiosk.
- A source failure must keep the last successful cache value.
- `/health` stays live with top-level `ok`; each enabled source reports `available`, `age_seconds`, and `stale`.
- A source is stale only after twice its collection interval; missing data is stale.
- Startup collectors run concurrently. Scheduled intervals remain independent.
- OpenRouter code and configuration are reserved but disabled until it has a visible UI.
- Do not auto-refresh Claude/Codex OAuth tokens. Do not add image rendering or browser automation.
- Gate: `.venv/Scripts/python -m unittest discover -s tests -v`.
- Periodic hardware eval: `.venv/Scripts/python -m evals.device_screen`.
