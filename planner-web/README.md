# Planner (web)

A Python/FastAPI + HTMX rewrite of the native Swift Planner app (`../planner/`): an hourly-grid daily planner with day navigation and recurring tasks. This is a **core-scope port** — voice entry, native push notifications, and drag-to-resize on the grid are intentionally not included (see "Not included" below).

## Stack

- **FastAPI** — backend, routing, HTML rendering
- **SQLAlchemy + SQLite** — storage (`planner.db`, created automatically on first run)
- **Jinja2** — server-rendered HTML templates
- **HTMX** (via CDN) — partial page updates (day navigation, add/edit/delete/toggle) without a JS build step or a separate frontend app

## Running it

```bash
cd planner-web
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000 (or whatever port `uvicorn` prints). `planner.db` is created next to this README on first run — delete it any time to start fresh.

## What's here

- **Hourly grid** (7 AM–7 PM by default, see `app/grid_config.py`) with a live current-time indicator and current-hour highlight.
- **Day navigation** — prev/next arrows, a date-jump input, and a "Today" shortcut. All navigation is an HTMX partial swap of `#day-view`, no full page reload.
- **Manual add/edit/delete**, plus tap-to-toggle-complete on a task block.
- **Recurring tasks** — daily / weekdays / weekly / custom-weekday patterns, with an optional end date. Occurrences are materialized as independent rows sharing a `series_id` (same design as the Swift app, for the same reason: a Monday's completion needs to be independent of Tuesday's). A lightweight top-up (`app/main.py: _top_up_series`) extends a series' materialized occurrences on each day-view load, so an old series doesn't just run out.
- **Edit/delete scope** — "this occurrence only" vs. "this and future occurrences," matching the original app's semantics.
- **Overlap layout** — concurrent tasks get side-by-side columns (`app/layout.py`, ported from the Swift `TaskLayoutEngine`'s interval-graph-coloring approach).
- **Compact block rendering** — a short task (e.g. 15–30 min) collapses to a single-line title+time layout instead of the normal two-line one. This directly carries forward a real bug found in the Swift app (see its `CLAUDE.md`): a short block's slot isn't tall enough for a two-line layout, and nothing clips overflow, so it visually bleeds into the next slot. Ported the fix rather than the bug.

## Not included (by design, for this first pass)

- **Voice entry** — would need the Web Speech API (Chrome-only, needs HTTPS in production) or a server-side speech service; deferred.
- **Notifications** (reminders / completion check-ins) — the Swift app used real local notifications; a web port would need the Web Notifications API plus a service worker, and only works while a tab is open (no native push without a backend push service). Deferred.
- **Drag-to-move/resize on the grid** — the Swift app's nicest interaction, but meaningfully more frontend work (pointer events, live preview, snap-to-grid) than a core pass warranted. Tasks are edited via the form instead.

All three are natural next passes if you want to extend this.

## Project layout

```
app/
  main.py            FastAPI app + all routes
  models.py           SQLAlchemy Task model
  database.py          engine/session setup
  recurrence.py        pure date-generation logic for recurring series
  layout.py            overlap/column layout algorithm
  grid_config.py       grid constants + label/format helpers (shared with templates)
  templates/
    index.html          full-page shell
    partials/
      day_view.html       the grid + toolbar (also returned directly by HTMX nav requests)
      task_form.html       the add/edit modal
  static/style.css      all styling
```

## Notes on how mutations work

Every create/edit/delete/toggle POST/PUT/DELETE returns two out-of-band HTMX swaps in one response: a refreshed `#day-view` and an emptied `#modal-container` (see `_oob_day_view` in `app/main.py`). That's why the buttons that trigger them use `hx-swap="none"` — the real updates happen via the OOB fragments, not the triggering element's own target.
