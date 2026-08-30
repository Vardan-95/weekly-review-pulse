from pulse.ledger.store import RunLedger


def test_round_trip(tmp_path):
    with RunLedger(tmp_path / "ledger.sqlite3") as ledger:
        record = ledger.upsert_start("Groww", "2026-W30", doc_id="doc-1", email_mode="draft")
        assert record.status == "STARTED"
        assert record.product == "Groww"
        assert record.iso_week == "2026-W30"
        assert record.doc_id == "doc-1"
        assert record.email_mode == "draft"
        assert record.completed_at is None

        fetched = ledger.get_run("Groww", "2026-W30")
        assert fetched is not None
        assert fetched.run_id == record.run_id


def test_get_run_missing_returns_none(tmp_path):
    with RunLedger(tmp_path / "ledger.sqlite3") as ledger:
        assert ledger.get_run("Groww", "2026-W30") is None


def test_upsert_is_idempotent_same_row(tmp_path):
    with RunLedger(tmp_path / "ledger.sqlite3") as ledger:
        first = ledger.upsert_start("Groww", "2026-W30")
        second = ledger.upsert_start("Groww", "2026-W30")
        assert first.run_id == second.run_id
        assert len(ledger.list_runs("Groww")) == 1


def test_partial_failure_semantics(tmp_path):
    with RunLedger(tmp_path / "ledger.sqlite3") as ledger:
        record = ledger.upsert_start("Groww", "2026-W30")
        ledger.update_doc(
            record.run_id, status="SUCCEEDED", heading_id="h1", deep_link="https://x/#h1"
        )
        ledger.update_email(record.run_id, status="FAILED")
        ledger.complete(record.run_id, status="FAILED", error="gmail mcp outage")

        fetched = ledger.get_run("Groww", "2026-W30")
        assert fetched.doc_status == "SUCCEEDED"
        assert fetched.doc_heading_id == "h1"
        assert fetched.email_status == "FAILED"
        assert fetched.status == "FAILED"
        assert fetched.error == "gmail mcp outage"


def test_in_progress_run_is_visible_not_hidden(tmp_path):
    """A crashed run left in STARTED must be reported accurately, not as
    SUCCEEDED — EdgeCases/Phase1-Foundations.md #5."""
    with RunLedger(tmp_path / "ledger.sqlite3") as ledger:
        ledger.upsert_start("Groww", "2026-W30")
        fetched = ledger.get_run("Groww", "2026-W30")
        assert fetched.status == "STARTED"
        assert fetched.completed_at is None


def test_reopening_ledger_file_preserves_schema(tmp_path):
    """A fresh DB path auto-initializes; reopening an existing one doesn't
    error or wipe data — EdgeCases/Phase1-Foundations.md #9."""
    db_path = tmp_path / "ledger.sqlite3"
    with RunLedger(db_path) as ledger:
        ledger.upsert_start("Groww", "2026-W30")

    with RunLedger(db_path) as ledger:
        fetched = ledger.get_run("Groww", "2026-W30")
        assert fetched is not None


def test_invalid_status_rejected(tmp_path):
    import pytest

    with RunLedger(tmp_path / "ledger.sqlite3") as ledger:
        record = ledger.upsert_start("Groww", "2026-W30")
        with pytest.raises(ValueError):
            ledger.complete(record.run_id, status="NOT_A_REAL_STATUS")
