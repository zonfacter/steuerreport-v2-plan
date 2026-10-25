#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.review import ReviewService


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
SCRIPT_ROOT = PROJECT_ROOT / "scripts"
DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var/main_solana_evidence_closure"
PRICE_PACKAGE_SCRIPT = SCRIPT_ROOT / "import_evidence_price_package_v2.py"
TOKEN_BACKFILL_SCRIPT = SCRIPT_ROOT / "backfill_solana_token_account_evidence_v2.py"
NATIVE_BACKFILL_SCRIPT = SCRIPT_ROOT / "backfill_solana_native_balance_evidence_v2.py"
PRIMARY_TOKEN_AUDIT = (
    PROJECT_ROOT
    / "var/solana_token_account_coverage"
    / "token_account_coverage_20260710T201911Z_6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP.json"
)
SHARK_TOKEN_AUDIT = (
    PROJECT_ROOT
    / "var/solana_token_account_coverage"
    / "token_account_coverage_20260710T212451Z_6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP.json"
)
OPENING_BATCH_ID = "bb73e499-058e-47cb-85ca-ea623a33dae8"
WALLET = "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
EXPECTED_BALANCES = {
    "CWIF": Decimal("11310642.83"),
    "HNT": Decimal("75.175403"),
    "IOT": Decimal("0"),
    "JUP": Decimal("0.000001"),
    "MOBILE": Decimal("0"),
    "SHARK": Decimal("963.536668"),
    "SOL": Decimal("0.236133776"),
    "USDC": Decimal("0.000990"),
    "USDT": Decimal("0.000001"),
}


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except Exception:
        return Decimal("0")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(16 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _run_json(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    payload = json.loads(completed.stdout)
    if not isinstance(payload, dict):
        raise RuntimeError(f"command did not return a JSON object: {command[1]}")
    return payload


def _state(db_path: Path) -> dict[str, Any]:
    store = DuckDbStore(db_path)
    with store.connect() as con:
        balance_rows = con.execute(
            """
            select asset, coalesce(sum(delta_quantity), 0)
            from balance_ledger
            where account = ? and asset in (select unnest(?))
            group by asset order by asset
            """,
            [WALLET, sorted(EXPECTED_BALANCES)],
        ).fetchall()
        tax_rows = con.execute(
            """
            select extract(year from disposed_at)::integer, count(*), coalesce(sum(gain_loss_eur), 0)
            from tax_lines
            where extract(year from disposed_at)::integer between 2021 and 2026
            group by 1 order by 1
            """
        ).fetchall()
        unmatched = int(con.execute("select count(*) from tax_unmatched_disposals").fetchone()[0])
        opening = int(
            con.execute(
                "select count(*) from raw_import_batches where batch_id = ?",
                [OPENING_BATCH_ID],
            ).fetchone()[0]
        )
        counts = {
            table: int(con.execute(f"select count(*) from {table}").fetchone()[0])
            for table in ("raw_import_batches", "raw_objects", "canonical_events", "tax_lots", "tax_lines")
        }
    gate = ReviewService(store).gate()
    balances = {str(asset): _decimal(quantity) for asset, quantity in balance_rows}
    return {
        "counts": counts,
        "balances": {asset: str(balances.get(asset, Decimal("0"))) for asset in EXPECTED_BALANCES},
        "tax_years": [
            {"year": int(year), "lines_count": int(count), "gain_loss_eur": str(gain)}
            for year, count, gain in tax_rows
        ],
        "unmatched_disposals": unmatched,
        "opening_batch_present": bool(opening),
        "review_gate": {
            "allow_export": gate.allow_export,
            "issues_open": gate.issues_open,
        },
    }


def _assert_final_state(state: dict[str, Any]) -> None:
    actual = {asset: _decimal(value) for asset, value in state["balances"].items()}
    mismatches = {
        asset: {"expected": str(expected), "actual": str(actual.get(asset, Decimal("0")))}
        for asset, expected in EXPECTED_BALANCES.items()
        if actual.get(asset, Decimal("0")) != expected
    }
    if mismatches:
        raise RuntimeError("final_balance_mismatch:" + json.dumps(mismatches, sort_keys=True))
    if state["opening_batch_present"]:
        raise RuntimeError("opening_balance_batch_still_present")
    if state["unmatched_disposals"]:
        raise RuntimeError(f"unmatched_disposals:{state['unmatched_disposals']}")
    if not state["review_gate"]["allow_export"] or state["review_gate"]["issues_open"]:
        raise RuntimeError(f"review_gate_closed:{state['review_gate']}")


def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    db_path = Path(args.db)
    generated_at = datetime.now(timezone.utc)
    required = [
        db_path,
        PRICE_PACKAGE_SCRIPT,
        TOKEN_BACKFILL_SCRIPT,
        NATIVE_BACKFILL_SCRIPT,
        PRIMARY_TOKEN_AUDIT,
        SHARK_TOKEN_AUDIT,
    ]
    missing = [str(path) for path in required if not path.exists()]
    report: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "mode": "execute" if args.execute else "preview",
        "db": str(db_path),
        "required_files_missing": missing,
        "pre_state": _state(db_path) if db_path.exists() else None,
        "target_changed": False,
    }
    if missing:
        report["status"] = "blocked"
        return report, 2
    if not args.execute:
        report["status"] = "ready"
        return report, 0

    backup = Path(args.backup_dir) / (
        f"steuerreport_v2_before_main_solana_evidence_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.duckdb"
    )
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(db_path, backup)
    report["backup"] = str(backup)
    report["backup_size_bytes"] = backup.stat().st_size
    report["backup_sha256"] = _sha256(backup)
    try:
        report["price_package"] = _run_json(
            [sys.executable, str(PRICE_PACKAGE_SCRIPT), "--db", str(db_path), "--apply"]
        )
        initial_pipeline = PipelineService(DuckDbStore(db_path)).rebuild_all()
        if not initial_pipeline.allow_export or initial_pipeline.review_issues_open:
            raise RuntimeError(
                "initial_rebuild_gate_closed:"
                f"allow_export={initial_pipeline.allow_export},issues={initial_pipeline.review_issues_open}"
            )
        report["initial_pipeline"] = initial_pipeline.model_dump(mode="json")
        report["primary_token_backfill"] = _run_json(
            [
                sys.executable,
                str(TOKEN_BACKFILL_SCRIPT),
                "--db",
                str(db_path),
                "--audit",
                str(PRIMARY_TOKEN_AUDIT),
                "--apply",
            ]
        )
        report["native_backfill"] = _run_json(
            [sys.executable, str(NATIVE_BACKFILL_SCRIPT), "--db", str(db_path), "--apply"]
        )
        report["opening_batch_removal"] = PipelineService(
            DuckDbStore(db_path)
        ).delete_import_and_rebuild(OPENING_BATCH_ID).model_dump(mode="json")
        report["shark_token_backfill"] = _run_json(
            [
                sys.executable,
                str(TOKEN_BACKFILL_SCRIPT),
                "--db",
                str(db_path),
                "--audit",
                str(SHARK_TOKEN_AUDIT),
                "--apply",
            ]
        )
        final_state = _state(db_path)
        _assert_final_state(final_state)
        report["post_state"] = final_state
        report["status"] = "applied"
        report["target_changed"] = True
        exit_code = 0
    except Exception as exc:
        shutil.copy2(backup, db_path)
        report["status"] = "rolled_back"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["restored_state"] = _state(db_path)
        exit_code = 2

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    content = json.dumps(report, indent=2, ensure_ascii=False)
    versioned = output_dir / f"main_solana_evidence_closure_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    latest = output_dir / "latest_main_solana_evidence_closure.json"
    versioned.write_text(content, encoding="utf-8")
    latest.write_text(content, encoding="utf-8")
    report["artifact_path"] = str(versioned.relative_to(PROJECT_ROOT))
    report["latest_artifact_path"] = str(latest.relative_to(PROJECT_ROOT))
    return report, exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Rollback-safe main Solana evidence closure rollout")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--backup-dir", default="/root/steuerreport_v2_backups")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    report, exit_code = run(args)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
