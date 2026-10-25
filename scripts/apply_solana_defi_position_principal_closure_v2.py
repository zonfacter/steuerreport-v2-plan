#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.tax_time import event_reporting_year_sql, reporting_year_sql


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var/solana_defi_position_principal_closure"

MAIN_WALLET = "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
JUP_WALLET = "GmHYjZGkcHBZ3WyGZ9eUGDZMfHvJTLtTKXu6dnSc63yu"
HNT_LOCK_TX = (
    "3Vyyy5cn8Y71z3bMHtCPryMFXuCdXdr3MGgbDYaZk8BvrsTq4SHA23bFA2giqB7fLwMDJvDUB1iyEtLPW8dh7kSc"
)
HNT_RETURN_TX = (
    "5xoV3svzcd962XKmG5YCo1EFKz5JdamH3uaQntJEQdcC3YdgJcxxW3P8RKfYqupxZbnZT3tM8ZmL4Ycy3mX1XkEo"
)

EXPECTED_COUNTS = {
    "raw_import_batches": 33,
    "raw_objects": 47083,
    "canonical_events": 47670,
    "balance_ledger": 73237,
    "flow_ledger": 32508,
    "tax_lots": 40876,
    "tax_lines": 50954,
    "tax_unmatched_disposals": 0,
}
EXPECTED_TAX_YEARS = {
    2021: (3623, Decimal("10048.283393798240890397")),
    2022: (30624, Decimal("-15053.578034744224594288")),
    2023: (10631, Decimal("-4010.187014094415025478")),
    2024: (5329, Decimal("26254.079164487826404406")),
    2025: (715, Decimal("-3837.693361478882093609")),
    2026: (32, Decimal("-5351.807012902019512114")),
}
EXPECTED_HNT_INCOME_2024 = {
    "lots": 7,
    "cost_basis_eur_total": Decimal("1119.807732800578367000"),
}
EXPECTED_MAIN_BALANCES = {
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
EXPECTED_JUP_BALANCES = {
    "HNT": Decimal("2142.46096778"),
    "JLWSOL": Decimal("5.305138706"),
    "JUP": Decimal("8775.789676"),
    "SOL": Decimal("0.262660279"),
    "SPCXX": Decimal("1.18234846"),
    "USDC": Decimal("1.99"),
    "USDT": Decimal("0"),
    "WSOL": Decimal("0"),
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


def _wallet_balances(con: Any, wallet: str, assets: set[str]) -> dict[str, str]:
    rows = con.execute(
        """
        select asset, coalesce(sum(delta_quantity), 0)
        from balance_ledger
        where account = ? and asset in (select unnest(?))
        group by asset order by asset
        """,
        [wallet, sorted(assets)],
    ).fetchall()
    values = {str(asset): _decimal(quantity) for asset, quantity in rows}
    return {asset: str(values.get(asset, Decimal("0"))) for asset in sorted(assets)}


def _state(db_path: Path, *, include_portfolio: bool = False) -> dict[str, Any]:
    store = DuckDbStore(db_path)
    with store.connect() as con:
        counts = {
            table: int(con.execute(f"select count(*) from {table}").fetchone()[0])
            for table in EXPECTED_COUNTS
        }
        tax_rows = con.execute(
            f"""
            select {reporting_year_sql('disposed_at')}, count(*), coalesce(sum(gain_loss_eur), 0)
            from tax_lines
            where {reporting_year_sql('disposed_at')} between 2021 and 2026
            group by 1 order by 1
            """
        ).fetchall()
        principal_rows = con.execute(
            """
            select tx_id, event_type, asset, quantity, account
            from canonical_events
            where tx_id in (?, ?)
              and upper(asset) = 'HNT'
              and quantity != 0
            order by event_time, event_id
            """,
            [HNT_LOCK_TX, HNT_RETURN_TX],
        ).fetchall()
        hnt_income = con.execute(
            f"""
            select count(*), coalesce(sum(lot.cost_basis_eur_total), 0)
            from tax_lots lot
            join canonical_events event on event.event_id = lot.source_event_id
            left join raw_objects raw on raw.raw_object_id = event.raw_object_id
            where {event_reporting_year_sql('event', 'raw')} = 2024
              and event.event_type = 'income'
              and upper(lot.asset) = 'HNT'
            """
        ).fetchone()
        zero_proceeds = int(
            con.execute(
                "select count(*) from tax_lines where disposal_proceeds_eur is null or disposal_proceeds_eur <= 0"
            ).fetchone()[0]
        )
        spcxx = con.execute(
            """
            select count(*), coalesce(sum(quantity), 0)
            from canonical_events where asset = 'SPCXX'
            """
        ).fetchone()
        main_balances = _wallet_balances(con, MAIN_WALLET, set(EXPECTED_MAIN_BALANCES))
        jup_balances = _wallet_balances(con, JUP_WALLET, set(EXPECTED_JUP_BALANCES))
    gate = ReviewService(store).gate()
    result: dict[str, Any] = {
        "counts": counts,
        "tax_years": [
            {"year": int(year), "tax_lines": int(count), "gain_loss_eur": str(gain)}
            for year, count, gain in tax_rows
        ],
        "hnt_position_principal": [
            {
                "tx_id": str(tx_id),
                "event_type": str(event_type),
                "asset": str(asset),
                "quantity": str(quantity),
                "account": str(account),
            }
            for tx_id, event_type, asset, quantity, account in principal_rows
        ],
        "hnt_income_2024": {
            "lots": int(hnt_income[0]),
            "cost_basis_eur_total": str(hnt_income[1]),
        },
        "main_wallet_balances": main_balances,
        "jup_wallet_balances": jup_balances,
        "zero_or_missing_proceeds": zero_proceeds,
        "spcxx_events": int(spcxx[0]),
        "spcxx_quantity": str(spcxx[1]),
        "review_gate": {
            "allow_export": gate.allow_export,
            "issues_open": gate.issues_open,
        },
    }
    if include_portfolio:
        portfolio = PortfolioService(store).snapshot()
        result["portfolio"] = {
            "total_value_eur": str(portfolio.total_value_eur),
            "positions_count": len(portfolio.positions),
        }
    return result


def _quantity_mismatches(
    actual: dict[str, str], expected: dict[str, Decimal]
) -> dict[str, dict[str, str]]:
    return {
        asset: {"expected": str(quantity), "actual": str(actual.get(asset, "0"))}
        for asset, quantity in expected.items()
        if _decimal(actual.get(asset)) != quantity
    }


def _assert_final_state(state: dict[str, Any]) -> None:
    if state["counts"] != EXPECTED_COUNTS:
        raise RuntimeError(f"final_count_mismatch:{state['counts']}")
    actual_tax = {
        int(row["year"]): (int(row["tax_lines"]), _decimal(row["gain_loss_eur"]))
        for row in state["tax_years"]
    }
    if actual_tax != EXPECTED_TAX_YEARS:
        raise RuntimeError(f"final_tax_year_mismatch:{state['tax_years']}")
    expected_pair = [
        {
            "tx_id": HNT_LOCK_TX,
            "event_type": "transfer",
            "asset": "HNT",
            "quantity": "-800.000000000000000000",
            "account": MAIN_WALLET,
        },
        {
            "tx_id": HNT_RETURN_TX,
            "event_type": "transfer",
            "asset": "HNT",
            "quantity": "800.000000000000000000",
            "account": MAIN_WALLET,
        },
    ]
    if state["hnt_position_principal"] != expected_pair:
        raise RuntimeError(f"hnt_position_principal_mismatch:{state['hnt_position_principal']}")
    income = state["hnt_income_2024"]
    if (
        int(income["lots"]) != EXPECTED_HNT_INCOME_2024["lots"]
        or _decimal(income["cost_basis_eur_total"])
        != EXPECTED_HNT_INCOME_2024["cost_basis_eur_total"]
    ):
        raise RuntimeError(f"hnt_income_2024_mismatch:{income}")
    for label, actual, expected in (
        ("main", state["main_wallet_balances"], EXPECTED_MAIN_BALANCES),
        ("jup", state["jup_wallet_balances"], EXPECTED_JUP_BALANCES),
    ):
        mismatches = _quantity_mismatches(actual, expected)
        if mismatches:
            raise RuntimeError(
                f"{label}_wallet_balance_mismatch:" + json.dumps(mismatches, sort_keys=True)
            )
    if state["zero_or_missing_proceeds"]:
        raise RuntimeError(f"tax_proceeds_gap:{state['zero_or_missing_proceeds']}")
    if state["spcxx_events"] != 1 or _decimal(state["spcxx_quantity"]) != Decimal("1.18234846"):
        raise RuntimeError(
            f"spcxx_state_mismatch:{state['spcxx_events']}:{state['spcxx_quantity']}"
        )
    if not state["review_gate"]["allow_export"] or state["review_gate"]["issues_open"]:
        raise RuntimeError(f"review_gate_closed:{state['review_gate']}")
    portfolio = state.get("portfolio") or {}
    if _decimal(portfolio.get("total_value_eur")) <= 0 or int(portfolio.get("positions_count") or 0) != 42:
        raise RuntimeError(f"portfolio_state_mismatch:{portfolio}")


def _write_report(report: dict[str, Any], output_dir: Path, generated_at: datetime) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    versioned = output_dir / (
        f"solana_defi_position_principal_closure_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    latest = output_dir / "latest_solana_defi_position_principal_closure.json"
    try:
        artifact_path = str(versioned.relative_to(PROJECT_ROOT))
        latest_artifact_path = str(latest.relative_to(PROJECT_ROOT))
    except ValueError:
        artifact_path = str(versioned)
        latest_artifact_path = str(latest)
    report["artifact_path"] = artifact_path
    report["latest_artifact_path"] = latest_artifact_path
    content = json.dumps(report, indent=2, ensure_ascii=False)
    versioned.write_text(content, encoding="utf-8")
    latest.write_text(content, encoding="utf-8")


def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    db_path = Path(args.db).resolve()
    output_dir = Path(args.output_dir).resolve()
    generated_at = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "mode": "execute" if args.execute else "preview",
        "db": str(db_path),
        "target_changed": False,
    }
    if not db_path.exists():
        report.update({"status": "blocked", "error": "database_missing"})
        _write_report(report, output_dir, generated_at)
        return report, 2
    report["pre_state"] = _state(db_path, include_portfolio=True)
    try:
        _assert_final_state(report["pre_state"])
    except RuntimeError:
        already_applied = False
    else:
        already_applied = True
    if already_applied:
        report["status"] = "already_applied"
        _write_report(report, output_dir, generated_at)
        return report, 0
    if not args.execute:
        report["status"] = "ready"
        _write_report(report, output_dir, generated_at)
        return report, 0

    backup = Path(args.backup_dir) / (
        f"steuerreport_v2_before_solana_defi_principal_closure_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.duckdb"
    )
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(db_path, backup)
    report.update(
        {
            "backup": str(backup),
            "backup_size_bytes": backup.stat().st_size,
            "backup_sha256": _sha256(backup),
        }
    )
    try:
        pipeline = PipelineService(DuckDbStore(db_path)).rebuild_all()
        report["pipeline"] = pipeline.model_dump(mode="json")
        final_state = _state(db_path, include_portfolio=True)
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
    _write_report(report, output_dir, generated_at)
    return report, exit_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rollback-safe Solana DeFi position-principal tax closure"
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--backup-dir", default="/root/steuerreport_v2_backups")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--execute", action="store_true")
    report, exit_code = run(parser.parse_args())
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
