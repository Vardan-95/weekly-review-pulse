import pytest

from pulse.mcp.protocol import MCPAuthError, MCPError, MCPTransientError
from pulse.mcp.retry import with_mcp_retries


def test_retries_transient_then_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise MCPTransientError("simulated 503")
        return "ok"

    result = with_mcp_retries(flaky, attempts=3, backoff_base=0.01)
    assert result == "ok"
    assert calls["n"] == 3


def test_exhausts_retries_and_raises():
    def always_fails():
        raise MCPTransientError("simulated persistent outage")

    with pytest.raises(MCPTransientError):
        with_mcp_retries(always_fails, attempts=3, backoff_base=0.01)


def test_does_not_retry_indefinitely():
    calls = {"n": 0}

    def always_fails():
        calls["n"] += 1
        raise MCPTransientError("simulated persistent outage")

    with pytest.raises(MCPTransientError):
        with_mcp_retries(always_fails, attempts=3, backoff_base=0.01)
    assert calls["n"] == 3


def test_auth_error_is_not_retried():
    calls = {"n": 0}

    def fails_with_auth_error():
        calls["n"] += 1
        raise MCPAuthError("token expired")

    with pytest.raises(MCPAuthError):
        with_mcp_retries(fails_with_auth_error, attempts=3, backoff_base=0.01)
    assert calls["n"] == 1


def test_generic_mcp_error_is_not_retried():
    calls = {"n": 0}

    def fails_generic():
        calls["n"] += 1
        raise MCPError("document not found")

    with pytest.raises(MCPError):
        with_mcp_retries(fails_generic, attempts=3, backoff_base=0.01)
    assert calls["n"] == 1
