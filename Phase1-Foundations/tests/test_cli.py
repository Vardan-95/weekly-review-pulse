import pytest

from pulse import cli

_PRODUCTS_YAML = """
products:
  - name: TestProduct
    app_store_id: "123456"
    play_store_package: "com.test.app"
    doc_id: "doc-abc"
    doc_title: "Weekly Review Pulse — TestProduct"
    stakeholders:
      - test@example.com
"""

_ENVIRONMENTS_YAML = """
environments:
  dev:
    email_mode: draft
    ingestion_window_weeks: 8
    max_tokens_per_run: 1000
"""


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    products_path = tmp_path / "products.yaml"
    products_path.write_text(_PRODUCTS_YAML, encoding="utf-8")
    environments_path = tmp_path / "environments.yaml"
    environments_path.write_text(_ENVIRONMENTS_YAML, encoding="utf-8")

    monkeypatch.setattr(cli, "_PRODUCTS_PATH", products_path)
    monkeypatch.setattr(cli, "_ENVIRONMENTS_PATH", environments_path)

    return tmp_path / "ledger.sqlite3"


def test_status_reports_no_run_found(isolated_db, capsys):
    exit_code = cli.main(
        ["--db", str(isolated_db), "status", "--product", "TestProduct", "--week", "2026-W30"]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "No run found" in out


def test_status_unknown_product_fails_fast(isolated_db, capsys):
    exit_code = cli.main(
        ["--db", str(isolated_db), "status", "--product", "DoesNotExist", "--week", "2026-W30"]
    )
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "Unknown product" in err


def test_run_unknown_product_fails_fast_before_ledger_write(isolated_db, capsys):
    exit_code = cli.main(["--db", str(isolated_db), "run", "--product", "DoesNotExist"])
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "Unknown product" in err
    assert not isolated_db.exists()  # no ledger write happened


def test_run_then_status_round_trip(isolated_db, capsys):
    exit_code = cli.main(
        ["--db", str(isolated_db), "run", "--product", "TestProduct", "--week", "2026-W30"]
    )
    assert exit_code == 0
    capsys.readouterr()

    exit_code = cli.main(
        ["--db", str(isolated_db), "status", "--product", "TestProduct", "--week", "2026-W30"]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "status=SKIPPED" in out


def test_backfill_requires_explicit_week():
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["backfill", "--product", "TestProduct"])


def test_backfill_rejects_malformed_week(isolated_db, capsys):
    exit_code = cli.main(
        ["--db", str(isolated_db), "backfill", "--product", "TestProduct", "--week", "not-a-week"]
    )
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "not-a-week" in err
