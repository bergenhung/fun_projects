import uuid
from datetime import date, datetime, timedelta

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import grid_config
from .database import get_db, init_db
from .layout import layout_tasks
from .models import Task
from .recurrence import generate_series_dates

app = FastAPI(title="Planner")

_here = __import__("pathlib").Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=_here / "static"), name="static")
templates = Jinja2Templates(directory=_here / "templates")
templates.env.globals.update(
    hour_label=grid_config.hour_label,
    time_label=grid_config.time_label,
    duration_label=grid_config.duration_label,
    GRID_START_HOUR=grid_config.GRID_START_HOUR,
    GRID_END_HOUR=grid_config.GRID_END_HOUR,
    HOUR_HEIGHT_PX=grid_config.HOUR_HEIGHT_PX,
    HOUR_GUTTER_PX=grid_config.HOUR_GUTTER_PX,
    DURATION_OPTIONS=grid_config.DURATION_OPTIONS,
    MINUTE_OPTIONS=grid_config.MINUTE_OPTIONS,
    TWO_LINE_MIN_HEIGHT_PX=grid_config.TWO_LINE_MIN_HEIGHT_PX,
)


@app.on_event("startup")
def _startup():
    init_db()


def parse_date(date_str: str) -> date:
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def _top_up_series(db: Session, horizon: date) -> None:
    """Extend any still-active recurring series whose materialized
    occurrences don't yet reach `horizon` - mirrors the Swift app's rolling
    top-up (SeriesEditor.topUpAllSeries) so a series created months ago
    doesn't just run out of future occurrences."""
    series_ids = db.scalars(
        select(Task.series_id).where(Task.series_id.isnot(None)).distinct()
    ).all()
    for series_id in series_ids:
        rows = db.scalars(select(Task).where(Task.series_id == series_id)).all()
        if not rows:
            continue
        template = max(rows, key=lambda t: t.scheduled_date)
        if template.recurrence_end_date and template.recurrence_end_date < horizon:
            continue  # series has already ended
        existing_dates = {r.scheduled_date for r in rows}
        needed = generate_series_dates(
            start_date=min(r.scheduled_date for r in rows),
            frequency=template.recurrence_frequency,
            custom_days=template.custom_days,
            end_date=template.recurrence_end_date,
            window_days=(horizon - min(r.scheduled_date for r in rows)).days + 1,
        )
        for d in needed:
            if d not in existing_dates and d >= date.today():
                db.add(
                    Task(
                        title=template.title,
                        notes=template.notes,
                        scheduled_date=d,
                        start_hour=template.start_hour,
                        start_minute=template.start_minute,
                        duration_minutes=template.duration_minutes,
                        series_id=series_id,
                        recurrence_frequency=template.recurrence_frequency,
                        recurrence_custom_days=template.recurrence_custom_days,
                        recurrence_end_date=template.recurrence_end_date,
                    )
                )
    db.commit()


def _day_view_context(request: Request, db: Session, the_date: date) -> dict:
    _top_up_series(db, the_date + timedelta(days=60))
    tasks = db.scalars(
        select(Task).where(Task.scheduled_date == the_date).order_by(Task.start_hour, Task.start_minute)
    ).all()
    layouts = layout_tasks(tasks)
    today = date.today()
    return {
        "request": request,
        "the_date": the_date,
        "date_str": the_date.isoformat(),
        "prev_date": (the_date - timedelta(days=1)).isoformat(),
        "next_date": (the_date + timedelta(days=1)).isoformat(),
        "today_str": today.isoformat(),
        "is_today": the_date == today,
        "title_text": _title_text(the_date, today),
        "hours": list(range(grid_config.GRID_START_HOUR, grid_config.GRID_END_HOUR)),
        "layouts": layouts,
        "now_hour": datetime.now().hour,
        "now_minute": datetime.now().minute,
    }


def _title_text(the_date: date, today: date) -> str:
    delta = (the_date - today).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    if delta == -1:
        return "Yesterday"
    return the_date.strftime("%a, %b %-d")


@app.get("/", response_class=RedirectResponse)
def root():
    return RedirectResponse(url=f"/day/{date.today().isoformat()}")


@app.get("/day/{date_str}", response_class=HTMLResponse)
def day_page(date_str: str, request: Request, db: Session = Depends(get_db)):
    ctx = _day_view_context(request, db, parse_date(date_str))
    return templates.TemplateResponse("index.html", ctx)


@app.get("/day/{date_str}/view", response_class=HTMLResponse)
def day_view_partial(date_str: str, request: Request, db: Session = Depends(get_db)):
    ctx = _day_view_context(request, db, parse_date(date_str))
    return templates.TemplateResponse("partials/day_view.html", ctx)


@app.get("/modal/close", response_class=HTMLResponse)
def modal_close():
    return HTMLResponse('<div id="modal-container"></div>')


@app.get("/tasks/new", response_class=HTMLResponse)
def new_task_form(request: Request, date_str: str, hour: int | None = None):
    return templates.TemplateResponse(
        "partials/task_form.html",
        {
            "request": request,
            "task": None,
            "date_str": date_str,
            "default_hour": hour if hour is not None else grid_config.GRID_START_HOUR,
        },
    )


@app.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
def edit_task_form(task_id: int, request: Request, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    return templates.TemplateResponse(
        "partials/task_form.html",
        {"request": request, "task": task, "date_str": task.scheduled_date.isoformat(), "default_hour": task.start_hour},
    )


def _oob_day_view(request: Request, db: Session, the_date: date) -> str:
    ctx = _day_view_context(request, db, the_date)
    html = templates.get_template("partials/day_view.html").render(ctx)
    return f'<div id="day-view" hx-swap-oob="true">{html}</div><div id="modal-container" hx-swap-oob="true"></div>'


@app.post("/tasks", response_class=HTMLResponse)
def create_task(
    request: Request,
    db: Session = Depends(get_db),
    title: str = Form(...),
    notes: str = Form(""),
    date_str: str = Form(..., alias="date"),
    hour: int = Form(...),
    minute: int = Form(0),
    duration: int = Form(60),
    frequency: str = Form("never"),
    custom_days: list[str] = Form([]),
    has_end_date: str | None = Form(None),
    end_date_str: str | None = Form(None, alias="end_date"),
):
    the_date = parse_date(date_str)
    title = title.strip()
    notes_val = notes.strip() or None

    if frequency == "never":
        db.add(
            Task(
                title=title,
                notes=notes_val,
                scheduled_date=the_date,
                start_hour=hour,
                start_minute=minute,
                duration_minutes=duration,
            )
        )
    else:
        end_date = parse_date(end_date_str) if (has_end_date and end_date_str) else None
        days = [int(d) for d in custom_days] if frequency == "custom" else []
        series_id = str(uuid.uuid4())
        for d in generate_series_dates(the_date, frequency, days, end_date):
            db.add(
                Task(
                    title=title,
                    notes=notes_val,
                    scheduled_date=d,
                    start_hour=hour,
                    start_minute=minute,
                    duration_minutes=duration,
                    series_id=series_id,
                    recurrence_frequency=frequency,
                    recurrence_custom_days=",".join(str(x) for x in days) if days else None,
                    recurrence_end_date=end_date,
                )
            )
    db.commit()
    return HTMLResponse(_oob_day_view(request, db, the_date))


@app.put("/tasks/{task_id}", response_class=HTMLResponse)
def update_task(
    task_id: int,
    request: Request,
    db: Session = Depends(get_db),
    title: str = Form(...),
    notes: str = Form(""),
    hour: int = Form(...),
    minute: int = Form(0),
    duration: int = Form(60),
    scope: str = Form("this"),
):
    task = db.get(Task, task_id)
    title = title.strip()
    notes_val = notes.strip() or None

    if scope == "future" and task.series_id:
        siblings = db.scalars(
            select(Task).where(Task.series_id == task.series_id, Task.scheduled_date >= task.scheduled_date)
        ).all()
        for t in siblings:
            t.title = title
            t.notes = notes_val
            t.start_hour = hour
            t.start_minute = minute
            t.duration_minutes = duration
    else:
        task.title = title
        task.notes = notes_val
        task.start_hour = hour
        task.start_minute = minute
        task.duration_minutes = duration

    db.commit()
    return HTMLResponse(_oob_day_view(request, db, task.scheduled_date))


@app.delete("/tasks/{task_id}", response_class=HTMLResponse)
def delete_task(task_id: int, request: Request, scope: str = "this", db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    the_date = task.scheduled_date

    if scope == "future" and task.series_id:
        siblings = db.scalars(
            select(Task).where(Task.series_id == task.series_id, Task.scheduled_date >= task.scheduled_date)
        ).all()
        for t in siblings:
            db.delete(t)
    else:
        db.delete(task)

    db.commit()
    return HTMLResponse(_oob_day_view(request, db, the_date))


@app.post("/tasks/{task_id}/toggle", response_class=HTMLResponse)
def toggle_task(task_id: int, request: Request, db: Session = Depends(get_db)):
    task = db.get(Task, task_id)
    task.is_completed = not task.is_completed
    db.commit()
    return HTMLResponse(_oob_day_view(request, db, task.scheduled_date))
