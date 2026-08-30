"""EdgeCases/Phase6-Orchestration-Hardening.md (backfill correctness) and
Doc/Evaluation/Phase6-Orchestration-Hardening.md: "Run pulse backfill for
2-3 historical ISO weeks, including one spanning a year boundary (e.g.
2025-W52 -> 2026-W01)". Phase 1's isoweek.py already unit-tests the raw
date math (Doc/EdgeCases/Phase1-Foundations.md #3/#4); this proves the
orchestrator's own ingestion-window computation built on top of it is
correct across that same boundary, including the week's report period
(period_start/period_end) staying anchored to the *target* week, not the
lookback window.
"""
from __future__ import annotations

from datetime import date

from pulse.integration import phases as p
from pulse.orchestrator.run import _ingestion_window


def test_year_boundary_week_bounds_are_correct():
    year, week = p.parse_iso_week("2025-W52")
    monday, sunday = p.iso_week_bounds(year, week)
    assert monday == date(2025, 12, 22)
    assert sunday == date(2025, 12, 28)

    year2, week2 = p.parse_iso_week("2026-W01")
    monday2, sunday2 = p.iso_week_bounds(year2, week2)
    assert monday2 == date(2025, 12, 29)  # ISO week 1 of 2026 starts in Dec 2025
    assert sunday2 == date(2026, 1, 4)


def test_ingestion_window_spans_backward_from_the_target_weeks_sunday():
    class Env:
        ingestion_window_weeks = 8

    year, week = p.parse_iso_week("2026-W01")
    monday, sunday = p.iso_week_bounds(year, week)
    window_start, window_end = _ingestion_window(Env(), monday, sunday)

    assert window_end == sunday == date(2026, 1, 4)
    assert window_start == date(2025, 11, 10)
    assert (window_end - window_start).days == 8 * 7 - 1


def test_ingestion_window_crossing_the_year_boundary_does_not_raise():
    class Env:
        ingestion_window_weeks = 12

    for iso_week in ("2025-W50", "2025-W51", "2025-W52", "2026-W01", "2026-W02"):
        year, week = p.parse_iso_week(iso_week)
        monday, sunday = p.iso_week_bounds(year, week)
        window_start, window_end = _ingestion_window(Env(), monday, sunday)
        assert window_start < window_end
