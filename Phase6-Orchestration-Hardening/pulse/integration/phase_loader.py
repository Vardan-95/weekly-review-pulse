"""Resolves the Phase 1-5 namespace collision: every phase folder defines
its own top-level `pulse` package (`pulse/__init__.py`), by design, so each
phase is independently self-contained and independently testable (see
Doc/ImplementationPlan.md). That's exactly what makes them uninstallable
side by side under Python's normal import rules — `import pulse` can only
ever resolve to whichever phase's folder happens to be first on `sys.path`.

Rather than retrofit Phase 1-5 into namespace packages (touching five
already-verified, already-tested phases just to satisfy Phase 6's wiring
needs), Phase 6 loads each phase's `pulse` package under its own alias in
`sys.modules` (`phase1_pulse`, `phase2_pulse`, ...), using
`importlib.util.spec_from_file_location` with an explicit
`submodule_search_locations`. Python's import machinery then resolves that
package's relative imports (`from ..review import RawReview`, etc.) against
the alias, not the literal string "pulse" — so Phase 2's `ingestion/app_store.py`
happily imports `phase2_pulse.review` even though the file on disk still
says `from ..review import RawReview`. No source file in any phase folder
is modified.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[3]

_PHASE_DIRS = {
    "phase1": REPO_ROOT / "Phase1-Foundations",
    "phase2": REPO_ROOT / "Phase2-Ingestion-Safety",
    "phase3": REPO_ROOT / "Phase3-Reasoning",
    "phase4": REPO_ROOT / "Phase4-Rendering",
    "phase5": REPO_ROOT / "Phase5-MCP-Delivery",
}


class PhaseLoadError(RuntimeError):
    """Raised when a phase folder or its `pulse` package can't be found."""


def _alias(phase_key: str) -> str:
    return f"{phase_key}_pulse"


def load_phase_package(phase_key: str) -> ModuleType:
    """Loads `<phase_dir>/pulse` under `sys.modules["<phase_key>_pulse"]`.

    Idempotent: calling this twice for the same phase_key returns the same
    cached module rather than re-executing it (mirrors how `import` itself
    behaves for a module already in `sys.modules`).
    """
    if phase_key not in _PHASE_DIRS:
        raise PhaseLoadError(f"unknown phase key {phase_key!r}, must be one of {sorted(_PHASE_DIRS)}")

    alias = _alias(phase_key)
    if alias in sys.modules:
        return sys.modules[alias]

    phase_dir = _PHASE_DIRS[phase_key]
    pulse_dir = phase_dir / "pulse"
    init_path = pulse_dir / "__init__.py"
    if not init_path.is_file():
        raise PhaseLoadError(f"{phase_key}: no pulse package found at {init_path}")

    spec = importlib.util.spec_from_file_location(
        alias, init_path, submodule_search_locations=[str(pulse_dir)]
    )
    if spec is None or spec.loader is None:
        raise PhaseLoadError(f"{phase_key}: failed to build an import spec for {init_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        del sys.modules[alias]
        raise
    return module


def load_phase_module(phase_key: str, dotted_submodule: str) -> ModuleType:
    """Loads a submodule of a phase package, e.g.
    `load_phase_module("phase2", "ingestion.app_store")` ->
    the module backing `phase2_pulse.ingestion.app_store`.

    Ensures the phase's top-level package is loaded first (registering its
    alias and `__path__` in `sys.modules`), then delegates to the normal
    import system, which is what lets relative imports inside that
    submodule resolve correctly against the alias.
    """
    load_phase_package(phase_key)
    return importlib.import_module(f"{_alias(phase_key)}.{dotted_submodule}")
