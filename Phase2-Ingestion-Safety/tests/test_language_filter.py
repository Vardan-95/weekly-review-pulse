from pulse.safety.language_filter import classify_language, strip_emojis


def test_strip_emojis_removes_emoji_keeps_text():
    assert strip_emojis("Great app 😃👍") == "Great app"


def test_strip_emojis_leading_emoji():
    assert strip_emojis("🔥🔥🔥 amazing performance") == "amazing performance"


def test_strip_emojis_emoji_only_becomes_empty():
    assert strip_emojis("😃😃😃") == ""


def test_strip_emojis_no_emoji_unchanged():
    assert strip_emojis("Solid app, no complaints.") == "Solid app, no complaints."


def test_strip_emojis_empty_text():
    assert strip_emojis("") == ""


def test_english_review_classified_as_english():
    result = classify_language("The app crashes every time I try to log in.")
    assert result.is_english is True
    assert result.reason is None


def test_pure_hindi_script_rejected():
    result = classify_language("यह ऐप बहुत अच्छा है, मुझे पसंद है")
    assert result.is_english is False
    assert result.reason == "non_latin_script"


def test_hinglish_rejected():
    result = classify_language("Yeh app bahut acha hai, bilkul sahi kaam karta hai")
    assert result.is_english is False
    assert result.reason == "hinglish"


def test_empty_text_defaults_to_english():
    """No text to judge (e.g. rating-only review) — nothing to reject."""
    result = classify_language("")
    assert result.is_english is True


def test_single_stray_hindi_word_does_not_reject_english_review():
    """One borrowed/ambiguous word shouldn't tip an otherwise clearly
    English review into rejection — the density threshold guards this
    (EdgeCases/Phase2-Ingestion-Safety.md #14)."""
    result = classify_language(
        "This app hai honestly one of the best banking apps I have used so far"
    )
    assert result.is_english is True
