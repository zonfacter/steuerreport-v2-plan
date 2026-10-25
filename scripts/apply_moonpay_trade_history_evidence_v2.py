#!/usr/bin/env python3
from __future__ import annotations

from steuerreport_v2.paths import PROJECT_ROOT as SOFTWARE_ROOT

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.moonpay_receipts import MoonpayReceiptService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_years import TaxYearService


PROJECT_ROOT = SOFTWARE_ROOT
DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
DEFAULT_TRADE_HISTORY = Path(
    "/workspace/steuerreport/usertransfer/MoonPay_trade-history.csv"
)
DEFAULT_BACKUP_DIR = Path(
    str(PROJECT_ROOT / "var/backups/database")
)
DEFAULT_ARTIFACT_DIR = PROJECT_ROOT / "var/moonpay_receipts"


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _tax_line_totals(store: DuckDbStore) -> list[dict[str, object]]:
    with store.connect() as con:
        rows = con.execute(
            """
            select
                year(disposed_at)::integer as year,
                count(*)::integer as lines_count,
                coalesce(sum(gain_loss_eur), 0) as gain_loss_eur
            from tax_lines
            group by year
            order by year
            """
        ).fetchall()
    return [
        {"year": int(year), "lines_count": int(count), "gain_loss_eur": str(total)}
        for year, count, total in rows
    ]


def _moonpay_lots(
    store: DuckDbStore, event_ids: list[str]
) -> list[dict[str, object]]:
    placeholders = ",".join("?" for _ in event_ids)
    with store.connect() as con:
        rows = con.execute(
            f"""
            select
                upper(e.asset) as asset,
                count(*)::integer as lots_count,
                coalesce(sum(l.quantity_total), 0) as quantity,
                coalesce(sum(l.cost_basis_eur_total), 0) as cost_basis_eur
            from tax_lots l
            join canonical_events e on e.event_id = l.source_event_id
            where e.event_id in ({placeholders})
            group by upper(e.asset)
            order by asset
            """,
            event_ids,
        ).fetchall()
    return [
        {
            "asset": str(asset),
            "lots_count": int(count),
            "quantity": str(quantity),
            "cost_basis_eur": str(cost_basis),
        }
        for asset, count, quantity, cost_basis in rows
    ]


def _backup(db_path: Path, backup_dir: Path) -> tuple[Path, str]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / (
        f"{db_path.stem}_before_moonpay_trade_history_{stamp}{db_path.suffix}"
    )
    shutil.copy2(db_path, target)
    source_sha = _sha256(db_path)
    target_sha = _sha256(target)
    if target.stat().st_size != db_path.stat().st_size or target_sha != source_sha:
        target.unlink(missing_ok=True)
        raise RuntimeError("moonpay_backup_integrity_failed")
    return target, target_sha


def _write_artifact(payload: dict[str, object], artifact_dir: Path) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = artifact_dir / f"moonpay_trade_history_apply_{stamp}.json"
    content = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    path.write_text(content, encoding="utf-8")
    (artifact_dir / "latest_moonpay_trade_history_apply.json").write_text(
        content, encoding="utf-8"
    )
    return path


def run(args: argparse.Namespace) -> int:
    db_path = Path(args.db).resolve()
    trade_history_path = Path(args.trade_history).resolve()
    backup_dir = Path(args.backup_dir).resolve()
    artifact_dir = Path(args.artifact_dir).resolve()
    if not db_path.is_file():
        raise RuntimeError("moonpay_database_missing")
    if not trade_history_path.is_file():
        raise RuntimeError("moonpay_trade_history_missing")
    trade_history_sha = _sha256(trade_history_path)
    if trade_history_sha != args.expected_trade_history_sha256:
        raise RuntimeError(
            "moonpay_trade_history_sha_mismatch:"
            f"expected={args.expected_trade_history_sha256}:actual={trade_history_sha}"
        )

    store = DuckDbStore(db_path)
    service = MoonpayReceiptService(store, trade_history_path=trade_history_path)
    preflight = service.report()
    if not preflight.strict_ready or preflight.ready_count != 12:
        raise RuntimeError(
            "moonpay_preflight_not_ready:"
            f"status={preflight.status}:ready={preflight.ready_count}:"
            f"candidates={preflight.candidates_count}"
        )
    if args.expected_bank_camt_semantic_sha256:
        if (
            preflight.bank_camt_semantic_sha256
            != args.expected_bank_camt_semantic_sha256
            or preflight.bank_debits_matched_count != preflight.ready_count
            or preflight.total_bank_debits_eur
            != preflight.total_receipt_cost_basis_eur
        ):
            raise RuntimeError(
                "moonpay_bank_camt_preflight_mismatch:"
                f"expected={args.expected_bank_camt_semantic_sha256}:"
                f"actual={preflight.bank_camt_semantic_sha256}:"
                f"matched={preflight.bank_debits_matched_count}:"
                f"bank={preflight.total_bank_debits_eur}:"
                f"basis={preflight.total_receipt_cost_basis_eur}"
            )
    event_ids = [item.event_id for item in preflight.items]
    before_lines = _tax_line_totals(store)
    before_lots = _moonpay_lots(store, event_ids)
    payload: dict[str, object] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "execute" if args.execute else "dry-run",
        "database": str(db_path),
        "trade_history_path": str(trade_history_path),
        "trade_history_sha256": trade_history_sha,
        "preflight": preflight.model_dump(mode="json"),
        "before_tax_line_totals": before_lines,
        "before_moonpay_lots": before_lots,
    }
    if not args.execute:
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        return 0

    with store.connect() as con:
        con.execute("checkpoint")
    backup_path, backup_sha = _backup(db_path, backup_dir)
    payload.update(
        {
            "backup_path": str(backup_path),
            "backup_size_bytes": backup_path.stat().st_size,
            "backup_sha256": backup_sha,
        }
    )
    try:
        rebuild = TaxService(store).rebuild_fifo()
        after_report = service.report()
        after_lines = _tax_line_totals(store)
        after_lots = _moonpay_lots(store, event_ids)
        if before_lines != after_lines:
            raise RuntimeError(
                "moonpay_unexpected_realized_tax_line_change:"
                + json.dumps(
                    {"before": before_lines, "after": after_lines},
                    sort_keys=True,
                )
            )
        expected_by_asset: dict[str, dict[str, Decimal | int]] = {}
        for item in after_report.items:
            bucket = expected_by_asset.setdefault(
                item.asset.upper(),
                {"lots_count": 0, "quantity": Decimal("0"), "cost_basis": Decimal("0")},
            )
            bucket["lots_count"] = int(bucket["lots_count"]) + 1
            bucket["quantity"] = Decimal(str(bucket["quantity"])) + item.received_quantity
            bucket["cost_basis"] = Decimal(str(bucket["cost_basis"])) + Decimal(
                str(item.cost_basis_eur or "0")
            )
        actual_by_asset = {str(row["asset"]): row for row in after_lots}
        for asset, expected in expected_by_asset.items():
            actual = actual_by_asset.get(asset)
            if (
                actual is None
                or int(actual["lots_count"]) != int(expected["lots_count"])
                or Decimal(str(actual["quantity"])) != Decimal(str(expected["quantity"]))
                or Decimal(str(actual["cost_basis_eur"]))
                != Decimal(str(expected["cost_basis"]))
            ):
                raise RuntimeError(f"moonpay_tax_lot_postcheck_failed:{asset}")
        tax_year = TaxYearService(store)
        income = tax_year.income_report(2026)
        external = tax_year.external_inflow_report(2026, limit=0)
        if any(item.asset.upper() == "USDC" for item in income.assets):
            raise RuntimeError("moonpay_usdc_still_present_in_income_report")
        gate = ReviewService(store).gate()
        if not gate.allow_export or gate.issues_open:
            raise RuntimeError(
                f"moonpay_review_gate_failed:allow={gate.allow_export}:open={gate.issues_open}"
            )
        portfolio = PortfolioService(store).snapshot()
        payload.update(
            {
                "status": "applied",
                "tax_rebuild": {
                    "lots_count": len(rebuild.lots),
                    "tax_lines_count": len(rebuild.tax_lines),
                    "unmatched_disposals": rebuild.unmatched_disposals,
                },
                "after_tax_line_totals": after_lines,
                "after_moonpay_lots": after_lots,
                "income_2026": {
                    "declaration_income_eur": str(income.declaration_income_eur),
                    "review_only_income_eur": str(income.review_only_income_eur),
                    "events_count": income.events_count,
                },
                "external_inflows_2026": {
                    "inflows_count": external.inflows_count,
                    "review_count": external.review_count,
                    "unmatched_count": external.unmatched_count,
                },
                "review_gate": gate.model_dump(mode="json"),
                "portfolio": {
                    "total_value_eur": str(portfolio.total_value_eur),
                    "positions_count": len(portfolio.positions),
                },
                "moonpay_report": after_report.model_dump(mode="json"),
            }
        )
    except Exception as exc:
        shutil.copy2(backup_path, db_path)
        restored_sha = _sha256(db_path)
        if restored_sha != backup_sha:
            raise RuntimeError("moonpay_rollback_integrity_failed") from exc
        payload.update(
            {
                "status": "rolled_back",
                "error": str(exc),
                "restored_sha256": restored_sha,
            }
        )
        artifact_path = _write_artifact(payload, artifact_dir)
        raise RuntimeError(
            f"moonpay_apply_failed_and_rolled_back:{exc}:artifact={artifact_path}"
        ) from exc

    artifact_path = _write_artifact(payload, artifact_dir)
    payload["artifact_path"] = str(artifact_path)
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--trade-history", default=str(DEFAULT_TRADE_HISTORY))
    parser.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_DIR))
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--expected-trade-history-sha256", required=True)
    parser.add_argument("--expected-bank-camt-semantic-sha256")
    parser.add_argument("--execute", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
