from datetime import date

import pytest

from pulse.isoweek import (
    InvalidIsoWeekError,
    current_iso_week,
    format_iso_week,
    iso_week_bounds,
    parse_iso_week,
    weeks_in_iso_year,
)


def _find_year_with_n_weeks(n: int, start: int = 2020, span: int = 20) -> int:
    for year in range(start, start + span):
        if weeks_in_iso_year(year) == n:
            return year
    pytest.skip(f"no {n}-week ISO year found in scanned range")


def test_parses_valid_week():
    assert parse_iso_week("2026-W30") == (2026, 30)


def test_round_trip_format():
    assert format_iso_week(*parse_iso_week("2026-W05")) == "2026-W05"


def test_53_week_year_is_accepted():
    year = _find_year_with_n_weeks(53)
    assert parse_iso_week(f"{year}-W53") == (year, 53)


def test_week_53_rejected_for_52_week_year():
    year = _find_year_with_n_weeks(52)
    with pytest.raises(InvalidIsoWeekError):
        parse_iso_week(f"{year}-W53")


def test_malformed_string_rejected():
    with pytest.raises(InvalidIsoWeekError):
        parse_iso_week("not-a-week")


def test_week_zero_rejected():
    with pytest.raises(InvalidIsoWeekError):
        parse_iso_week("2026-W00")


def test_iso_week_bounds_is_monday_to_sunday():
    monday, sunday = iso_week_bounds(2026, 30)
    assert monday.isoweekday() == 1
    assert sunday.isoweekday() == 7
    assert (sunday - monday).days == 6


def test_january_first_can_belong_to_previous_iso_year():
    for year in range(2020, 2036):
        jan1 = date(year, 1, 1)
        iso_year, iso_week, _ = jan1.isocalendar()
        if iso_year == year - 1:
            assert iso_week == weeks_in_iso_year(year - 1)
            return
    pytest.skip("no such year found in scanned range")


def test_current_iso_week_matches_stdlib():
    today = date(2026, 8, 29)
    year, week, _ = today.isocalendar()
    assert current_iso_week(today) == format_iso_week(year, week)
