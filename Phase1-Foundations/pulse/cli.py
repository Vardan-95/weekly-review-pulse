"""CLI entrypoint — Architecture.md §3 (`cli.py`): pulse run / backfill / status.

Phase 1 wires argument parsing, config loading, and the run ledger together.
The pipeline itself is stubbed (see orchestrator/run.py) until Phase 2+.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config.loader import (
    ConfigValidationError,
    get_environment,
    get_product,
    load_environments,
    load_products,
)
from .isoweek import InvalidIsoWeekError, current_iso_week, format_iso_week, parse_iso_week
from .ledger.store import RunLedger
from .orchestrator.run import run_stub

_BASE_DIR = Path(__file__).resolve().parent
_PRODUCTS_PATH = _BASE_DIR / "config" / "products.yaml"
_ENVIRONMENTS_PATH = _BASE_DIR / "config" / "environments.yaml"
_DEFAULT_DB_PATH = _BASE_DIR.parent / "data" / "ledger.sqlite3"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pulse", description="Weekly Product Review Pulse")
    parser.add_argument(
        "--env", default="dev", help="Environment name from environments.yaml (default: dev)"
    )
    parser.add_argument(
        "--db", default=str(_DEFAULT_DB_PATH), help="Path to the run ledger SQLite file"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run the pulse for a product (defaults to the current ISO week)")
    run_p.add_argument("--product", required=True)
    run_p.add_argument("--week", help="ISO week, e.g. 2026-W30 (default: current week)")
    run_p.add_argument("--force", action="store_true", help="Re-run even if a completed run exists")

    backfill_p = sub.add_parser("backfill", help="Run the pulse for a specific historical ISO week")
    backfill_p.add_argument("--product", required=True)
    backfill_p.add_argument("--week", required=True, help="ISO week, e.g. 2026-W30")
    backfill_p.add_argument("--force", action="store_true")

    status_p = sub.add_parser("status", help="Show the ledger status for a product/week")
    status_p.add_argument("--product", required=True)
    status_p.add_argument("--week", required=True, help="ISO week, e.g. 2026-W30")

    return parser


def _load_config() -> tuple[dict, dict]:
    products = load_products(_PRODUCTS_PATH)
    environments = load_environments(_ENVIRONMENTS_PATH)
    return products, environments


def _resolve_week(week_arg: str | None) -> str:
    if week_arg is None:
        return current_iso_week()
    year, week = parse_iso_week(week_arg)
    return format_iso_week(year, week)


def cmd_status(args: argparse.Namespace) -> int:
    products, _ = _load_config()
    get_product(products, args.product)  # validates the product exists
    iso_week = _resolve_week(args.week)

    with RunLedger(args.db) as ledger:
        record = ledger.get_run(args.product, iso_week)

    if record is None:
        print(f"No run found for {args.product} {iso_week}.")
        return 0

    print(f"{args.product} {iso_week}: status={record.status}")
    print(
        f"  doc:   status={record.doc_status} "
        f"heading_id={record.doc_heading_id} link={record.doc_deep_link}"
    )
    print(
        f"  email: status={record.email_status} "
        f"message_id={record.email_message_id} mode={record.email_mode}"
    )
    print(f"  usage: tokens={record.tokens_used} cost_usd={record.cost_usd:.4f}")
    if record.error:
        print(f"  error: {record.error}")
    return 0


def _run_or_backfill(args: argparse.Namespace, iso_week: str) -> int:
    products, environments = _load_config()
    product = get_product(products, args.product)
    env = get_environment(environments, args.env)

    with RunLedger(args.db) as ledger:
        return run_stub(product, env, iso_week, ledger, force=args.force)


def cmd_run(args: argparse.Namespace) -> int:
    iso_week = _resolve_week(args.week)
    return _run_or_backfill(args, iso_week)


def cmd_backfill(args: argparse.Namespace) -> int:
    year, week = parse_iso_week(args.week)
    iso_week = format_iso_week(year, week)
    return _run_or_backfill(args, iso_week)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            return cmd_status(args)
        if args.command == "run":
            return cmd_run(args)
        if args.command == "backfill":
            return cmd_backfill(args)
    except (ConfigValidationError, InvalidIsoWeekError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
