from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    scheduled_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_hour: Mapped[int] = mapped_column(Integer, nullable=False)
    start_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    is_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    # Recurrence: every occurrence is an independent row sharing a series_id,
    # not one row with a rule - same design as the Swift app (see CLAUDE.md:
    # completion/notes need to vary per-occurrence, e.g. a daily standup's
    # Monday completion is independent of Tuesday's). Flat primitive fields
    # rather than a nested structure, for simplicity.
    series_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    recurrence_frequency: Mapped[str | None] = mapped_column(String, nullable=True)  # daily|weekly|weekdays|custom
    recurrence_custom_days: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "0,2,4" (Mon=0..Sun=6)
    recurrence_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    @property
    def custom_days(self) -> list[int]:
        if not self.recurrence_custom_days:
            return []
        return [int(d) for d in self.recurrence_custom_days.split(",") if d != ""]

    @property
    def end_minutes(self) -> int:
        return self.start_hour * 60 + self.start_minute + self.duration_minutes

    @property
    def start_minutes(self) -> int:
        return self.start_hour * 60 + self.start_minute
