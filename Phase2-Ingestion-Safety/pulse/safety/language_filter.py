"""English-only / Hinglish language filter — Architecture.md §3
(`safety/language_filter.py`) and §8.

Two independent checks decide whether a review's text counts as English:

1. Script check — if a large enough share of its alphabetic characters
   belong to a non-Latin script (Devanagari, Arabic, CJK, ...), the review
   is written in a non-English language outright.
2. Hinglish check — Hindi written in the Latin alphabet passes the script
   check (it *is* Latin script) but reads as Hindi, so a curated wordlist
   of common Hindi/Hinglish tokens is used to score how Hindi-sounding the
   text is.

Both are heuristics, not a trained language-detection model, and are tuned
toward precision (don't wrongly reject real English feedback) over recall
(catch every non-English review) — see Doc/Evaluation/
Phase2-Ingestion-Safety.md for targets and Doc/EdgeCases/
Phase2-Ingestion-Safety.md #11-#15 for known gaps.

Emoji stripping also lives here, not in pii_scrubber: emoji characters
must never influence the language decision or be treated as review
content, per the "only consider the text" requirement.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"  # regional indicator symbols (flags)
    "\U0001F300-\U0001F5FF"  # misc symbols & pictographs
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F700-\U0001F77F"  # alchemical symbols
    "\U0001F780-\U0001F7FF"  # geometric shapes extended
    "\U0001F800-\U0001F8FF"  # supplemental arrows-C
    "\U0001F900-\U0001F9FF"  # supplemental symbols & pictographs
    "\U0001FA00-\U0001FA6F"  # chess symbols
    "\U0001FA70-\U0001FAFF"  # symbols & pictographs extended-A
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002700-\U000027BF"  # dingbats
    "\U00002B00-\U00002BFF"  # misc symbols & arrows
    "\U0001F3FB-\U0001F3FF"  # skin tone modifiers
    "\U0000FE0F"  # variation selector-16 (emoji presentation)
    "\U0000200D"  # zero-width joiner (compound/family emoji)
    "]+",
    flags=re.UNICODE,
)
_EXTRA_SPACE_RE = re.compile(r"[ \t]{2,}")
_WORD_RE = re.compile(r"[A-Za-z']+")

_LATIN_MAX_ORDINAL = 0x0250  # covers Basic Latin, Latin-1 Supplement, Latin Extended A/B

_NON_LATIN_SCRIPT_THRESHOLD = 0.3
_HINGLISH_SCORE_THRESHOLD = 0.2
_HINGLISH_MIN_WORDS = 2

# Curated, non-exhaustive: common Hindi words/stopwords as written in
# everyday Hinglish reviews. False negatives (a Hinglish review that slips
# through because it doesn't use any of these words) are expected.
_HINGLISH_WORDS = frozenset(
    {
        "hai", "hain", "nahi", "nahin", "acha", "accha", "achha", "bahut",
        "bohot", "bhot", "kya", "kyun", "kyu", "bhai", "yaar", "theek",
        "thik", "sahi", "bakwas", "paisa", "paise", "vasool", "matlab",
        "aap", "tum", "mera", "meri", "mere", "tumhara", "karo", "karna",
        "hoga", "hogi", "hoti", "hota", "bilkul", "ekdum", "faltu", "pura",
        "sirf", "phir", "abhi", "kabhi", "chalu", "band", "thoda",
        "zyada", "jyada", "bekaar", "bekar", "badhiya", "mast", "waala",
        "wala", "wale", "kaafi", "kafi", "kaam", "rupaye", "rupiya",
        "chal", "raha", "rahi", "rahe", "diya", "gaya", "gayi", "kiya",
        "kiye", "milta", "milti", "milte",
    }
)


def strip_emojis(text: str) -> str:
    """Remove emoji characters; collapse the whitespace left behind."""
    if not text:
        return text
    cleaned = _EMOJI_RE.sub("", text)
    cleaned = _EXTRA_SPACE_RE.sub(" ", cleaned).strip()
    return cleaned


def _non_latin_letter_ratio(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    non_latin = sum(1 for ch in letters if ord(ch) >= _LATIN_MAX_ORDINAL)
    return non_latin / len(letters)


def hinglish_score(text: str) -> float:
    words = [w.lower() for w in _WORD_RE.findall(text)]
    if not words:
        return 0.0
    hits = sum(1 for w in words if w in _HINGLISH_WORDS)
    return hits / len(words)


@dataclass(frozen=True)
class LanguageResult:
    is_english: bool
    reason: str | None  # None if English, else "non_latin_script" | "hinglish"


def classify_language(text: str) -> LanguageResult:
    stripped = text.strip()
    if not stripped:
        # No text to judge (e.g. a rating-only review, or a review that was
        # pure emoji before stripping) — nothing to reject on.
        return LanguageResult(is_english=True, reason=None)

    if _non_latin_letter_ratio(stripped) > _NON_LATIN_SCRIPT_THRESHOLD:
        return LanguageResult(is_english=False, reason="non_latin_script")

    words = _WORD_RE.findall(stripped)
    if len(words) >= _HINGLISH_MIN_WORDS and hinglish_score(stripped) >= _HINGLISH_SCORE_THRESHOLD:
        return LanguageResult(is_english=False, reason="hinglish")

    return LanguageResult(is_english=True, reason=None)
