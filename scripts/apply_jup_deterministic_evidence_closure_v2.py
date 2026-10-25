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
from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.source_registry import SourceRegistryService
from steuerreport_v2.domain.tax_time import reporting_year_sql


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
SCRIPT_ROOT = PROJECT_ROOT / "scripts"
DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var/jup_deterministic_evidence_closure"
PRICE_CONFIG = PROJECT_ROOT / "configs/crypto_price_sources.json"
PRICE_PACKAGE = PROJECT_ROOT / "configs/binance_small_assets_price_evidence_20260710.json"
PRICE_IMPORT_SCRIPT = SCRIPT_ROOT / "import_binance_small_assets_price_evidence_v2.py"
NATIVE_AUDIT_SCRIPT = SCRIPT_ROOT / "audit_solana_native_balance_coverage_v2.py"
NATIVE_BACKFILL_SCRIPT = SCRIPT_ROOT / "backfill_solana_native_balance_evidence_v2.py"
TOKEN_AUDIT_SCRIPT = SCRIPT_ROOT / "audit_solana_token_account_coverage_v2.py"

MAIN_WALLET = "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
JUP_WALLET = "GmHYjZGkcHBZ3WyGZ9eUGDZMfHvJTLtTKXu6dnSc63yu"
SPCXX_MINT = "Xs3oZwbHvqis4NYcf4YKWmEia2eC84wSiVrcYcTqpH8"
SPCXX_TX_ID = (
    "2XWdreG6W3FEvfQLhEXc1FzYnVQVdbcJVhtdPvSrMu66mALxdc87mYig4kxz2xgYCqgtWGJHiRY9umt8m58QBzLG"
)
JUP_TOKEN_TARGETS = {
    "HNT": "hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux",
    "JLWSOL": "2uQsyo1fXXQkDtcpXnLofWy88PxcvnfH2L8FPSE62FVU",
    "JUP": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "WSOL": "So11111111111111111111111111111111111111112",
    "SPCXX": SPCXX_MINT,
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
EXPECTED_COUNTS = {
    "raw_import_batches": 33,
    "raw_objects": 47083,
    "canonical_events": 47670,
    "balance_ledger": 73237,
    "flow_ledger": 32508,
    "tax_lots": 40876,
    "tax_lines": 50954,
}
EXPECTED_TAX_YEARS = {
    2021: (3623, Decimal("10048.283393798240890397")),
    2022: (30624, Decimal("-15053.578034744224594288")),
    2023: (10631, Decimal("-4010.187014094415025478")),
    2024: (5329, Decimal("26254.079164487826404406")),
    2025: (715, Decimal("-3837.693361478882093609")),
    2026: (32, Decimal("-5351.807012902019512114")),
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


def _wallet_balances(
    con: Any,
    wallet: str,
    assets: set[str],
) -> dict[str, str]:
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
        unmatched = int(con.execute("select count(*) from tax_unmatched_disposals").fetchone()[0])
        zero_proceeds = int(
            con.execute(
                "select count(*) from tax_lines where disposal_proceeds_eur is null or disposal_proceeds_eur <= 0"
            ).fetchone()[0]
        )
        unknown_spcxx = int(
            con.execute(
                """
                select count(*) from canonical_events
                where upper(asset) in ('XS3OZW...QPH8', 'XS3OZWBHVQIS4NYCF4YKWMEIA2EC84WSIVRCYCTQPH8')
                   or upper(coalesce(quote_asset, '')) in (
                       'XS3OZW...QPH8', 'XS3OZWBHVQIS4NYCF4YKWMEIA2EC84WSIVRCYCTQPH8'
                   )
                """
            ).fetchone()[0]
        )
        spcxx_rows = con.execute(
            """
            select event_type, asset, quantity, quote_asset, quote_quantity, tx_id
            from canonical_events
            where asset = 'SPCXX' or quote_asset = 'SPCXX'
            order by event_time, event_id
            """
        ).fetchall()
        exact_price_points = int(
            con.execute(
                "select count(*) from price_ledger where source like 'binance_public_klines:%'"
            ).fetchone()[0]
        )
        current_spcxx_prices = int(
            con.execute(
                """
                select count(*) from price_ledger
                where asset = 'SPCXX' and source = 'coingecko:simple-price:eur'
                """
            ).fetchone()[0]
        )
        main_balances = _wallet_balances(con, MAIN_WALLET, set(EXPECTED_MAIN_BALANCES))
        jup_balances = _wallet_balances(con, JUP_WALLET, set(EXPECTED_JUP_BALANCES))
    gate = ReviewService(store).gate()
    result: dict[str, Any] = {
        "counts": counts,
        "tax_years": [
            {"year": int(year), "tax_lines": int(count), "gain_loss_eur": str(gain)}
            for year, count, gain in tax_rows
        ],
        "main_wallet_balances": main_balances,
        "jup_wallet_balances": jup_balances,
        "unmatched_disposals": unmatched,
        "zero_or_missing_proceeds": zero_proceeds,
        "unknown_spcxx_events": unknown_spcxx,
        "spcxx_events": [
            {
                "event_type": str(event_type),
                "asset": str(asset),
                "quantity": str(quantity),
                "quote_asset": str(quote_asset) if quote_asset is not None else None,
                "quote_quantity": str(quote_quantity) if quote_quantity is not None else None,
                "tx_id": str(tx_id) if tx_id is not None else None,
            }
            for event_type, asset, quantity, quote_asset, quote_quantity, tx_id in spcxx_rows
        ],
        "binance_exact_price_points": exact_price_points,
        "current_spcxx_prices": current_spcxx_prices,
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
            "spcxx_positions": [
                {
                    "account": position.account,
                    "quantity": str(position.quantity),
                    "value_eur": str(position.value_eur) if position.value_eur is not None else None,
                }
                for position in portfolio.positions
                if position.asset == "SPCXX"
            ],
        }
    return result


def _quantity_mismatches(
    actual: dict[str, str],
    expected: dict[str, Decimal],
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
    main_mismatches = _quantity_mismatches(
        state["main_wallet_balances"], EXPECTED_MAIN_BALANCES
    )
    if main_mismatches:
        raise RuntimeError("main_wallet_balance_mismatch:" + json.dumps(main_mismatches, sort_keys=True))
    jup_mismatches = _quantity_mismatches(
        state["jup_wallet_balances"], EXPECTED_JUP_BALANCES
    )
    if jup_mismatches:
        raise RuntimeError("jup_wallet_balance_mismatch:" + json.dumps(jup_mismatches, sort_keys=True))
    if state["unmatched_disposals"] or state["zero_or_missing_proceeds"]:
        raise RuntimeError(
            "tax_evidence_gap:"
            f"unmatched={state['unmatched_disposals']}:zero={state['zero_or_missing_proceeds']}"
        )
    if state["unknown_spcxx_events"]:
        raise RuntimeError(f"unknown_spcxx_events:{state['unknown_spcxx_events']}")
    expected_spcxx = {
        "event_type": "trade",
        "asset": "SPCXX",
        "quantity": "1.182348460000000000",
        "quote_asset": "SOL",
        "quote_quantity": "3.002167496000000000",
        "tx_id": SPCXX_TX_ID,
    }
    if state["spcxx_events"] != [expected_spcxx]:
        raise RuntimeError(f"spcxx_trade_mismatch:{state['spcxx_events']}")
    if state["binance_exact_price_points"] != 17:
        raise RuntimeError(f"binance_price_evidence_mismatch:{state['binance_exact_price_points']}")
    if state["current_spcxx_prices"] < 1:
        raise RuntimeError("spcxx_current_price_missing")
    if not state["review_gate"]["allow_export"] or state["review_gate"]["issues_open"]:
        raise RuntimeError(f"review_gate_closed:{state['review_gate']}")
    portfolio = state.get("portfolio") or {}
    positions = portfolio.get("spcxx_positions") or []
    if len(positions) != 1 or _decimal(positions[0].get("quantity")) != Decimal("1.18234846"):
        raise RuntimeError(f"spcxx_portfolio_position_mismatch:{positions}")
    if _decimal(positions[0].get("value_eur")) < Decimal("1"):
        raise RuntimeError(f"spcxx_portfolio_value_missing:{positions}")


def _assert_native_audit(report: dict[str, Any]) -> None:
    reconciliation = report.get("reconciliation") or {}
    if report.get("wallet") != JUP_WALLET:
        raise RuntimeError(f"native_audit_wrong_wallet:{report.get('wallet')}")
    if report.get("history_complete") is not True:
        raise RuntimeError("native_audit_history_incomplete")
    if int(report.get("transaction_missing_count") or 0):
        raise RuntimeError(f"native_audit_transactions_missing:{report['transaction_missing_count']}")
    if int(report.get("canonical_missing_balance_change_count") or 0):
        raise RuntimeError(
            f"native_audit_canonical_missing:{report['canonical_missing_balance_change_count']}"
        )
    if int(report.get("canonical_quantity_mismatch_count") or 0):
        raise RuntimeError(f"native_audit_quantity_mismatch:{report['canonical_quantity_mismatch_count']}")
    if reconciliation.get("chain_net_matches_live") is not True:
        raise RuntimeError(f"native_audit_chain_live_mismatch:{reconciliation}")
    if _decimal(reconciliation.get("live_quantity_sol")) != EXPECTED_JUP_BALANCES["SOL"]:
        raise RuntimeError(f"native_audit_unexpected_live_balance:{reconciliation}")


def _assert_token_audit(report: dict[str, Any]) -> None:
    if report.get("wallet") != JUP_WALLET or report.get("history_complete") is not True:
        raise RuntimeError("token_audit_wallet_or_history_mismatch")
    if int(report.get("canonical_missing_balance_change_count") or 0):
        raise RuntimeError("token_audit_canonical_balance_changes_missing")
    if int(report.get("canonical_quantity_mismatch_count") or 0):
        raise RuntimeError("token_audit_canonical_quantity_mismatch")
    targets = {str(row.get("asset")): row for row in report.get("targets", [])}
    if set(targets) != set(JUP_TOKEN_TARGETS):
        raise RuntimeError(f"token_audit_target_mismatch:{sorted(targets)}")
    for asset, expected in EXPECTED_JUP_BALANCES.items():
        if asset == "SOL":
            continue
        row = targets.get(asset) or {}
        if row.get("history_complete") is not True or row.get("chain_net_matches_current") is not True:
            raise RuntimeError(f"token_audit_chain_current_mismatch:{asset}:{row}")
        if _decimal(row.get("current_quantity")) != expected:
            raise RuntimeError(
                f"token_audit_current_quantity_mismatch:{asset}:"
                f"{row.get('current_quantity')}:{expected}"
            )
        if _decimal(row.get("canonical_vs_chain_delta")) != 0:
            raise RuntimeError(f"token_audit_canonical_delta:{asset}:{row}")


def _assert_registry(report: dict[str, Any]) -> None:
    if int(report.get("unregistered_observations_count") or 0):
        raise RuntimeError(f"source_registry_unregistered:{report['unregistered_observations_count']}")
    if int(report.get("portfolio_policy_violations_count") or 0):
        raise RuntimeError(f"source_registry_portfolio_violation:{report['portfolio_policy_violations_count']}")
    entries = {str(row.get("source_id")): row for row in report.get("entries", [])}
    for source_id in ("solana-main-wallet", "jup-inheritance-wallet"):
        row = entries.get(source_id) or {}
        if row.get("coverage_status") != "complete":
            raise RuntimeError(f"source_registry_coverage_not_complete:{source_id}:{row}")
        if row.get("quantity_gate_status") != "matched" or row.get("strict_ready") is not True:
            raise RuntimeError(f"source_registry_quantity_not_matched:{source_id}:{row}")


def _compact_refresh(result: Any) -> dict[str, Any]:
    return {
        "fetched_at": result.fetched_at.isoformat(),
        "connectors": result.connectors,
        "imported_snapshots": result.imported_snapshots,
        "connector_results": [row.model_dump(mode="json") for row in result.connector_results],
    }


def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    db_path = Path(args.db).resolve()
    generated_at = datetime.now(timezone.utc)
    required = [
        db_path,
        PRICE_CONFIG,
        PRICE_PACKAGE,
        PRICE_IMPORT_SCRIPT,
        NATIVE_AUDIT_SCRIPT,
        NATIVE_BACKFILL_SCRIPT,
        TOKEN_AUDIT_SCRIPT,
        PROJECT_ROOT / "configs/source_registry.json",
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
        f"steuerreport_v2_before_jup_deterministic_closure_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.duckdb"
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
        report["binance_price_evidence"] = _run_json(
            [
                sys.executable,
                str(PRICE_IMPORT_SCRIPT),
                "--db",
                str(db_path),
                "--package",
                str(PRICE_PACKAGE),
                "--apply",
            ]
        )
        initial_pipeline = PipelineService(DuckDbStore(db_path)).rebuild_all()
        if not initial_pipeline.allow_export or initial_pipeline.review_issues_open:
            raise RuntimeError(
                "initial_rebuild_gate_closed:"
                f"allow_export={initial_pipeline.allow_export}:issues={initial_pipeline.review_issues_open}"
            )
        report["deterministic_initial_pipeline"] = initial_pipeline.model_dump(mode="json")

        native_pre = _run_json(
            [
                sys.executable,
                str(NATIVE_AUDIT_SCRIPT),
                "--db",
                str(db_path),
                "--wallet",
                JUP_WALLET,
            ]
        )
        report["jup_native_pre_audit"] = native_pre
        native_gaps = int(native_pre.get("canonical_missing_balance_change_count") or 0) + int(
            native_pre.get("canonical_quantity_mismatch_count") or 0
        )
        if native_gaps:
            audit_path = PROJECT_ROOT / str(native_pre["artifact_path"])
            report["jup_native_backfill"] = _run_json(
                [
                    sys.executable,
                    str(NATIVE_BACKFILL_SCRIPT),
                    "--db",
                    str(db_path),
                    "--audit",
                    str(audit_path),
                    "--output-dir",
                    str(PROJECT_ROOT / "var/jup_solana_native_evidence_backfills"),
                    "--apply",
                ]
            )
        else:
            report["jup_native_backfill"] = {"status": "not_required", "target_changed": False}

        current_price = ExternalPriceBackfillService(DuckDbStore(db_path)).run_current_portfolio(
            config_path=str(PRICE_CONFIG),
            provider="coingecko",
            assets_filter=["SPCXX"],
            max_requests=1,
            timeout_seconds=30,
            confidence=Decimal("0.95"),
            dry_run=False,
        )
        report["spcxx_current_price"] = current_price.model_dump(mode="json")
        if current_price.failed or current_price.imported_prices != 1:
            raise RuntimeError(
                f"spcxx_current_price_failed:imported={current_price.imported_prices}:failed={current_price.failed}"
            )

        final_pipeline = PipelineService(DuckDbStore(db_path)).rebuild_all()
        if not final_pipeline.allow_export or final_pipeline.review_issues_open:
            raise RuntimeError(
                "final_rebuild_gate_closed:"
                f"allow_export={final_pipeline.allow_export}:issues={final_pipeline.review_issues_open}"
            )
        report["final_pipeline"] = final_pipeline.model_dump(mode="json")
        report["live_snapshot_refresh"] = _compact_refresh(
            PortfolioService(DuckDbStore(db_path)).refresh_reconciliation_snapshots(
                ["jup_wallet", "solana_wallet"]
            )
        )

        native_final = _run_json(
            [
                sys.executable,
                str(NATIVE_AUDIT_SCRIPT),
                "--db",
                str(db_path),
                "--wallet",
                JUP_WALLET,
            ]
        )
        _assert_native_audit(native_final)
        report["jup_native_final_audit"] = native_final
        native_final_path = PROJECT_ROOT / str(native_final["artifact_path"])
        token_command = [
            sys.executable,
            str(TOKEN_AUDIT_SCRIPT),
            "--db",
            str(db_path),
            "--wallet",
            JUP_WALLET,
            "--wallet-audit",
            str(native_final_path),
        ]
        for asset, mint in JUP_TOKEN_TARGETS.items():
            token_command.extend(["--target", f"{asset}={mint}"])
        token_summary = _run_json(token_command)
        token_path = PROJECT_ROOT / str(token_summary["artifact_path"])
        token_report = json.loads(token_path.read_text(encoding="utf-8"))
        _assert_token_audit(token_report)
        report["jup_token_final_audit"] = {
            **token_summary,
            "targets": [
                {
                    key: row.get(key)
                    for key in (
                        "asset",
                        "mint",
                        "current_quantity",
                        "chain_net_delta",
                        "chain_net_matches_current",
                        "canonical_balance_effect_total",
                        "canonical_vs_chain_delta",
                    )
                }
                for row in token_report.get("targets", [])
            ],
        }

        final_state = _state(db_path, include_portfolio=True)
        _assert_final_state(final_state)
        report["post_state"] = final_state
        registry = SourceRegistryService(DuckDbStore(db_path)).run().model_dump(mode="json")
        _assert_registry(registry)
        report["source_registry"] = {
            key: registry[key]
            for key in (
                "generated_at",
                "registry_version",
                "status",
                "strict_ready",
                "semantic_sha256",
                "unregistered_observations_count",
                "portfolio_policy_violations_count",
                "quantity_blocker_entries_count",
                "artifact_path",
                "findings",
                "next_actions",
            )
        }
        report["source_registry"]["verified_entries"] = [
            {
                "source_id": row["source_id"],
                "coverage_status": row["coverage_status"],
                "quantity_gate_status": row["quantity_gate_status"],
                "strict_ready": row["strict_ready"],
                "current_value_delta_eur": row["current_value_delta_eur"],
            }
            for row in registry["entries"]
            if row["source_id"] in {"solana-main-wallet", "jup-inheritance-wallet"}
        ]
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
    versioned = output_dir / (
        f"jup_deterministic_evidence_closure_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    latest = output_dir / "latest_jup_deterministic_evidence_closure.json"
    versioned.write_text(content, encoding="utf-8")
    latest.write_text(content, encoding="utf-8")
    report["artifact_path"] = str(versioned.relative_to(PROJECT_ROOT))
    report["latest_artifact_path"] = str(latest.relative_to(PROJECT_ROOT))
    return report, exit_code


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rollback-safe JUP, SPCXX and deterministic price evidence rollout"
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
