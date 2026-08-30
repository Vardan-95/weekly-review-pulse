from tests.conftest import make_env

from pulse.promotion import check_promotion_readiness


def test_dev_draft_is_fine():
    assert check_promotion_readiness(make_env(name="dev", email_mode="draft")).ok


def test_production_send_is_fine():
    assert check_promotion_readiness(make_env(name="production", email_mode="send")).ok


def test_production_draft_is_flagged():
    result = check_promotion_readiness(make_env(name="production", email_mode="draft"))
    assert not result.ok
    assert "production" in result.warning
    assert "draft" in result.warning


def test_non_production_send_is_flagged():
    result = check_promotion_readiness(make_env(name="dev", email_mode="send"))
    assert not result.ok
    assert "dev" in result.warning
