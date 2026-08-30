"""Doc/Evaluation/Phase5-MCP-Delivery.md's 'Credential isolation' check:
grep all agent code for token/secret-shaped strings — zero matches, since
Google OAuth lives entirely inside the MCP servers, never in this repo
(Architecture.md §2, §11).
"""
import pathlib

FORBIDDEN_TERMS = [
    "api_key",
    "apikey",
    "client_secret",
    "access_token",
    "refresh_token",
    "authorization: bearer",
    "oauth2",
    "google_application_credentials",
    "private_key",
]


def test_no_credential_shaped_strings_in_source():
    pulse_dir = pathlib.Path(__file__).resolve().parents[1] / "pulse"
    for path in pulse_dir.rglob("*.py"):
        content = path.read_text(encoding="utf-8").lower()
        for term in FORBIDDEN_TERMS:
            assert term not in content, f"{path}: contains forbidden term {term!r}"
