"""Instruction-injection heuristics — Architecture.md §3
(`safety/prompt_guard.py`) and §8.

Flagged reviews are still analyzed for sentiment/theme in later phases but
excluded from being selected as verbatim quotes — this module only decides
the flag, exclusion happens downstream (Phase 3's quote validator).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore (all |any )?(the )?(previous|prior|above|earlier) instructions", re.I),
    re.compile(r"disregard (all |any )?(the )?(previous|prior|above|earlier)", re.I),
    re.compile(r"\bsystem prompt\b", re.I),
    re.compile(r"\byou are now\b", re.I),
    re.compile(r"</?(system|assistant|user)\s*>", re.I),
    re.compile(r"```"),
    re.compile(r"\bact as (a|an)\b", re.I),
    re.compile(r"\bnew instructions?:", re.I),
)


@dataclass(frozen=True)
class GuardResult:
    flagged: bool
    reasons: tuple[str, ...]


def check_text(text: str) -> GuardResult:
    if not text:
        return GuardResult(flagged=False, reasons=())
    reasons = [pattern.pattern for pattern in _INJECTION_PATTERNS if pattern.search(text)]
    return GuardResult(flagged=bool(reasons), reasons=tuple(reasons))
