"""Proves the namespace-collision fix actually works: Phases 1-5 each
define a top-level `pulse` package, which normally means only one of them
could ever be `import pulse`-able in the same process. phase_loader.py's
alias mechanism is what lets Phase 6 use all five at once."""
from __future__ import annotations

import sys

from pulse.integration.phase_loader import load_phase_module, load_phase_package


def test_two_phases_load_side_by_side_without_colliding():
    phase1 = load_phase_package("phase1")
    phase2 = load_phase_package("phase2")

    assert phase1 is not phase2
    assert phase1.__name__ == "phase1_pulse"
    assert phase2.__name__ == "phase2_pulse"
    assert sys.modules["phase1_pulse"] is phase1
    assert sys.modules["phase2_pulse"] is phase2


def test_relative_imports_inside_a_loaded_phase_resolve_against_its_alias():
    # Phase 2's ingestion/app_store.py does `from ..review import ...` —
    # if that resolved against the literal string "pulse" instead of the
    # phase2 alias, this import would either fail or silently pick up the
    # wrong phase's review.py.
    app_store = load_phase_module("phase2", "ingestion.app_store")
    assert app_store.RawReview.__module__ == "phase2_pulse.review"


def test_loading_the_same_phase_twice_returns_the_cached_module():
    first = load_phase_package("phase3")
    second = load_phase_package("phase3")
    assert first is second


def test_each_phase_version_string_is_distinct():
    versions = {
        key: load_phase_package(key).__version__
        for key in ("phase1", "phase2", "phase3", "phase4", "phase5")
    }
    assert versions == {
        "phase1": "0.1.0",
        "phase2": "0.2.0",
        "phase3": "0.3.0",
        "phase4": "0.4.0",
        "phase5": "0.5.0",
    }
