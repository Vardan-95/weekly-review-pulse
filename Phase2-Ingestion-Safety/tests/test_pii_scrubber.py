import pytest

from pulse.safety.pii_scrubber import scrub_text

PII_FIXTURES = [
    ("Contact me at jane.doe@example.com for details", "email"),
    ("Call me on 9876543210 please", "phone"),
    ("My number is 987-654-3210, call anytime", "phone"),
    ("My card 4111 1111 1111 1111 was charged twice", "card"),
    ("Card number 4111111111111111 declined", "card"),
]

CLEAN_FIXTURES = [
    "10/10 would recommend",
    "Using v2.4.1 and it's great",
    "Great app, 5 stars!",
    "Crashed twice this week but otherwise fine",
]


@pytest.mark.parametrize("text,category", PII_FIXTURES)
def test_pii_is_redacted(text, category):
    result = scrub_text(text)
    assert result.redacted is True
    assert category in result.categories


@pytest.mark.parametrize("text", CLEAN_FIXTURES)
def test_clean_text_not_redacted(text):
    result = scrub_text(text)
    assert result.redacted is False
    assert result.text == text


def test_empty_text():
    result = scrub_text("")
    assert result.redacted is False
    assert result.text == ""


def test_email_replaced_with_placeholder():
    result = scrub_text("email me: user@test.com")
    assert "[REDACTED_EMAIL]" in result.text
    assert "user@test.com" not in result.text


def test_card_scrubbed_before_phone_pattern_can_partially_match():
    """A 16-digit card number must come out as one CARD redaction, not a
    PHONE redaction plus leftover digits."""
    result = scrub_text("Card 4111111111111111 declined")
    assert result.text == "Card [REDACTED_CARD] declined"
    assert result.categories == ("card",)
