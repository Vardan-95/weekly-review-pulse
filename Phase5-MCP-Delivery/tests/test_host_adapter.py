"""build_tool_caller() now returns a real GoogleWorkspaceMCPToolCaller
(the host decision is resolved — see mcp/host_adapter.py's module
docstring). Actually invoking .call_tool() requires the `mcp` package and
a running google_workspace_mcp server/Google OAuth, neither of which
exist in this environment, so that path isn't exercised here — same
"real but untested against a live dependency" status as this project's
other real clients (e.g. Phase 2's RequestsAppStoreClient).
"""
from pulse.mcp.host_adapter import (
    GoogleWorkspaceMCPToolCaller,
    _looks_like_error_text,
    _resolve_server_command,
    build_tool_caller,
)
from pulse.mcp.protocol import MCPError


def test_build_tool_caller_returns_a_real_caller_instance():
    caller = build_tool_caller()
    assert isinstance(caller, GoogleWorkspaceMCPToolCaller)
    assert hasattr(caller, "call_tool")


def test_server_command_is_configurable():
    caller = GoogleWorkspaceMCPToolCaller(server_command=["python", "-m", "custom_server"])
    assert caller._server_command == ["python", "-m", "custom_server"]


def test_default_server_command_is_uvx_workspace_mcp():
    """Verified against a real local run (2026-08-30): --single-user is
    required for this project's single-account use case, and --tools docs
    gmail drive (not --tool-tier core, which loads all 12 services and
    requests unnecessarily broad OAuth scopes) restricts to what's
    actually used. drive was added 2026-08-31 for CXO-report chart image
    uploads - confirmed live it doesn't trigger a new OAuth consent."""
    caller = GoogleWorkspaceMCPToolCaller()
    assert caller._server_command == ["uvx", "workspace-mcp", "--single-user", "--tools", "docs", "gmail", "drive"]


def test_looks_like_error_text_catches_validation_errors():
    """VERIFIED live (2026-08-30): a pydantic argument-validation failure
    comes back as normal text content with no error flag set — this
    substring check is how it's actually caught."""
    text = (
        "2 validation errors for call[batch_update_doc]\n"
        "operations\n  Missing required argument [type=missing_argument, ...]\n"
    )
    assert _looks_like_error_text(text) is True


def test_looks_like_error_text_catches_action_required():
    text = "Error calling tool 'get_doc_content': **ACTION REQUIRED: Google Authentication Needed**"
    assert _looks_like_error_text(text) is True


def test_looks_like_error_text_does_not_flag_normal_content():
    text = 'File: "Weekly Review Pulse — Groww" (ID: doc-1)\n\n--- CONTENT ---\n\nSome real document text.'
    assert _looks_like_error_text(text) is False


def test_resolve_server_command_uses_shutil_which_when_found(monkeypatch):
    """VERIFIED live (2026-08-30): a bare "uvx" passed straight to
    asyncio's subprocess spawn can fail with a cryptic WinError 2 on
    Windows even when `uvx` works fine interactively, because subprocess
    spawning doesn't do PATH lookup the way a shell does and can see a
    stale PATH snapshot - resolving to an absolute path up front avoids
    that class of failure entirely."""
    monkeypatch.setattr("shutil.which", lambda exe: r"C:\fake\uvx.exe")
    resolved = _resolve_server_command(["uvx", "workspace-mcp", "--single-user"])
    assert resolved == [r"C:\fake\uvx.exe", "workspace-mcp", "--single-user"]


def test_resolve_server_command_falls_back_to_local_bin(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda exe: None)
    fake_home = tmp_path
    (fake_home / ".local" / "bin").mkdir(parents=True)
    fake_exe = fake_home / ".local" / "bin" / "uvx.exe"
    fake_exe.write_text("")
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

    resolved = _resolve_server_command(["uvx", "workspace-mcp"])
    assert resolved[0] == str(fake_exe)


def test_resolve_server_command_raises_a_clear_error_when_not_found_anywhere(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", lambda exe: None)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)  # empty dir, no fallback

    try:
        _resolve_server_command(["uvx", "workspace-mcp"])
        assert False, "expected MCPError"
    except MCPError as exc:
        assert "uvx" in str(exc)
