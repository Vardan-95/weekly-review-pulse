"""ISO 8601 week helpers.

Built entirely on Python's stdlib date.isocalendar() / date.fromisocalendar(),
so year-boundary weeks (e.g. Jan 1 belonging to the previous ISO year's last
week) and 53-week years are handled correctly by construction rather than by
ad hoc date math. See Doc/EdgeCases/Phase1-Foundations.md #3 and #4.
"""
from __future__ import annotations

import re
from datetime import date

_ISO_WEEK_RE = re.compile(r"^(?P<year>\d{4})-W(?P<week>\d{2})$")


class InvalidIsoWeekError(ValueError):
    """Raised when a string is not a well-formed, valid ISO week."""


def weeks_in_iso_year(year: int) -> int:
    """Number of ISO weeks in `year` (52 or 53).

    December 28th always falls in the last ISO week of its ISO year, so its
    week number is exactly that year's week count.
    """
    return date(year, 12, 28).isocalendar()[1]


def parse_iso_week(value: str) -> tuple[int, int]:
    """Parse 'YYYY-Www' into (iso_year, iso_week), validating the week exists."""
    match = _ISO_WEEK_RE.match(value.strip()) if isinstance(value, str) else None
    if not match:
        raise InvalidIsoWeekError(f"{value!r} is not in 'YYYY-Www' format")
    year = int(match.group("year"))
    week = int(match.group("week"))
    max_week = weeks_in_iso_year(year)
    if not (1 <= week <= max_week):
        raise InvalidIsoWeekError(
            f"{value!r} is invalid: ISO year {year} only has weeks 1-{max_week}"
        )
    return year, week


def format_iso_week(year: int, week: int) -> str:
    return f"{year:04d}-W{week:02d}"


def iso_week_bounds(year: int, week: int) -> tuple[date, date]:
    """Return (monday, sunday) date bounds for the given ISO week."""
    monday = date.fromisocalendar(year, week, 1)
    sunday = date.fromisocalendar(year, week, 7)
    return monday, sunday


def current_iso_week(today: date | None = None) -> str:
    today = today or date.today()
    year, week, _ = today.isocalendar()
    return format_iso_week(year, week)
