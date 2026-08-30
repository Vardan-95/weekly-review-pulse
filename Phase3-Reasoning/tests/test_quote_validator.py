from datetime import date

from pulse.analysis.quote_validator import validate_quote
from pulse.review import ScrubbedReview


def _review(review_id, body, title="", injection_flagged=False):
    return ScrubbedReview(
        review_id=review_id,
        source="app_store",
        product="Groww",
        rating=3,
        title=title,
        body_scrubbed=body,
        locale="in",
        review_date=date(2026, 8, 20),
        pii_redacted=False,
        injection_flagged=injection_flagged,
    )


def test_exact_substring_is_valid():
    reviews = [_review("r1", "The app crashes every time I open it.")]
    result = validate_quote("crashes every time I open it", reviews)
    assert result.is_valid is True
    assert result.matched_review_id == "r1"


def test_hallucinated_quote_is_rejected():
    reviews = [_review("r1", "The app crashes every time I open it.")]
    result = validate_quote("the app is the best I have ever used", reviews)
    assert result.is_valid is False
    assert result.matched_review_id is None


def test_paraphrase_is_rejected():
    """A reordered/synonym-swapped paraphrase must fail — never a close
    match (EdgeCases/Phase3-Reasoning.md #5)."""
    reviews = [_review("r1", "The app crashes every time I open it.")]
    result = validate_quote("it crashes every time the app is opened", reviews)
    assert result.is_valid is False


def test_smart_quotes_and_dashes_still_match():
    """Typographic punctuation differences must not cause a false
    rejection (EdgeCases/Phase3-Reasoning.md #6)."""
    reviews = [_review("r1", "It’s great — truly the best app.")]
    result = validate_quote("it's great - truly the best app", reviews)
    assert result.is_valid is True


def test_case_and_whitespace_insensitive():
    reviews = [_review("r1", "Support   takes   forever to reply")]
    result = validate_quote("SUPPORT TAKES FOREVER to reply", reviews)
    assert result.is_valid is True


def test_empty_candidate_rejected():
    reviews = [_review("r1", "Great app overall")]
    result = validate_quote("   ", reviews)
    assert result.is_valid is False


def test_title_is_also_searchable():
    reviews = [_review("r1", "very good", title="Amazing experience overall")]
    result = validate_quote("amazing experience", reviews)
    assert result.is_valid is True
