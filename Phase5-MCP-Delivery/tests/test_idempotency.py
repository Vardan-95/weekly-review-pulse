from pulse.idempotency import compute_report_content_hash, compute_run_key, named_range_name


def test_named_range_matches_convention():
    assert named_range_name("Groww", "2026-W35") == "pulse-section-groww-2026-W35"


def test_named_range_slugifies_multiword_product():
    assert named_range_name("PowerUp Money", "2026-W10") == "pulse-section-powerup-money-2026-W10"


def test_run_key_is_deterministic():
    h = compute_report_content_hash("subject", "html", "text")
    key1 = compute_run_key("Groww", "2026-W35", h)
    key2 = compute_run_key("Groww", "2026-W35", h)
    assert key1 == key2


def test_run_key_differs_across_realistic_variations():
    """EdgeCases/Phase5-MCP-Delivery.md #9: run_key must not collide
    across different products/weeks/content."""
    h1 = compute_report_content_hash("Weekly Review Pulse — Groww (2026-W35)", "html-a", "text-a")
    h2 = compute_report_content_hash("Weekly Review Pulse — Kuvera (2026-W35)", "html-a", "text-a")
    keys = {
        compute_run_key("Groww", "2026-W35", h1),
        compute_run_key("Kuvera", "2026-W35", h2),
        compute_run_key("Groww", "2026-W36", h1),
        compute_run_key("Groww", "2026-W35", compute_report_content_hash("different", "html-b", "text-b")),
    }
    assert len(keys) == 4


def test_content_hash_distinguishes_field_boundaries():
    """'ab' + 'c' must not hash the same as 'a' + 'bc' — guards against a
    naive-concatenation collision bug."""
    h1 = compute_report_content_hash("ab", "c")
    h2 = compute_report_content_hash("a", "bc")
    assert h1 != h2
