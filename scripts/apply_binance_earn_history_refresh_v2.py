#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from steuerreport_v2.db.duckdb_store import DuckDbStore  # noqa: E402
from steuerreport_v2.domain.binance_earn import BinanceEarnHistoryService  # noqa: E402
from steuerreport_v2.domain.portfolio import PortfolioService  # noqa: E402
from steuerreport_v2.domain.review import ReviewService  # noqa: E402
from steuerreport_v2.domain.sources import SourceService  # noqa: E402


DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
DEFAULT_BACKUP_DIR = Path("/workspace/backups/steuerreport-v2-plan/database")
DEFAULT_ARTIFACT_DIR = PROJECT_ROOT / "var/binance_simple_earn_history"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tax_line_totals(store: DuckDbStore) -> list[dict[str, object]]:
    with store.connect() as con:
        rows = con.execute(
            """
            select
                year(disposed_at)::integer as year,
                count(*)::integer as lines_count,
                coalesce(sum(acquisition_cost_eur), 0) as acquisition_cost_eur,
                coalesce(sum(disposal_proceeds_eur), 0) as disposal_proceeds_eur,
                coalesce(sum(gain_loss_eur), 0) as gain_loss_eur
            from tax_lines
            group by year
            order by year
            """
        ).fetchall()
    return [
        {
            "year": int(year),
            "lines_count": int(count),
            "acquisition_cost_eur": str(cost),
            "disposal_proceeds_eur": str(proceeds),
            "gain_loss_eur": str(gain_loss),
        }
        for year, count, cost, proceeds, gain_loss in rows
    ]


def _prepared_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    counts: Counter[str] = Counter()
    quantities: defaultdict[tuple[str, str], Decimal] = defaultdict(
        lambda: Decimal("0")
    )
    for row in rows:
        record_type = str(row.get("record_type") or "")
        asset = str(row.get("asset") or "").upper()
        counts[f"{record_type}:{asset}"] += 1
        quantity = row.get("rewards") or row.get("amount") or "0"
        quantities[(record_type, asset)] += Decimal(str(quantity))
    return {
        "rows": len(rows),
        "counts": dict(sorted(counts.items())),
        "quantities": {
            f"{record_type}:{asset}": str(quantity)
            for (record_type, asset), quantity in sorted(quantities.items())
        },
    }


def _event_summary(store: DuckDbStore, batch_id: str) -> list[dict[str, object]]:
    with store.connect() as con:
        rows = con.execute(
            """
            select event_type, coalesce(account, ''), upper(asset), count(*)::integer,
                   coalesce(sum(quantity), 0)
            from canonical_events
            where raw_object_id in (
                select raw_object_id from raw_objects where batch_id = ?
            )
            group by 1, 2, 3
            order by 3, 1, 2
            """,
            [batch_id],
        ).fetchall()
    return [
        {
            "event_type": str(event_type),
            "account": str(account),
            "asset": str(asset),
            "events_count": int(count),
            "quantity": str(quantity),
        }
        for event_type, account, asset, count, quantity in rows
    ]


def _backup(db_path: Path, backup_dir: Path) -> tuple[Path, str]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / (
        f"{db_path.stem}_before_binance_earn_refresh_{stamp}{db_path.suffix}"
    )
    shutil.copy2(db_path, target)
    source_sha = _sha256(db_path)
    target_sha = _sha256(target)
    if target.stat().st_size != db_path.stat().st_size or target_sha != source_sha:
        target.unlink(missing_ok=True)
        raise RuntimeError("binance_earn_backup_integrity_failed")
    return target, target_sha


def _write_artifact(payload: dict[str, object], artifact_dir: Path) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = artifact_dir / f"binance_earn_history_apply_{stamp}.json"
    content = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    path.write_text(content, encoding="utf-8")
    (artifact_dir / "latest_binance_earn_history_apply.json").write_text(
        content,
        encoding="utf-8",
    )
    return path


def _validate_api_harvest(payload: dict[str, object]) -> None:
    requests = payload.get("requests")
    if payload.get("credential_status") != "configured":
        raise RuntimeError("binance_earn_harvest_credentials_not_configured")
    if payload.get("truncated") is True:
        raise RuntimeError("binance_earn_harvest_truncated")
    if not isinstance(requests, list) or any(
        not isinstance(item, dict) or item.get("status") != "ok"
        for item in requests
    ):
        raise RuntimeError("binance_earn_harvest_request_error")


def _assert_expected_rows(
    summary: dict[str, object],
    *,
    expected_rows: int,
    expected_jup_rewards: Decimal,
    expected_jup_redemption: Decimal,
    expected_sol_rewards: Decimal,
) -> None:
    quantities = summary["quantities"]
    if not isinstance(quantities, dict):
        raise RuntimeError("binance_earn_prepared_summary_invalid")
    expected = {
        "flexible_rewards_realtime:JUP": expected_jup_rewards,
        "flexible_redemption:JUP": expected_jup_redemption,
        "locked_rewards:SOL": expected_sol_rewards,
    }
    if int(summary["rows"]) != expected_rows:
        raise RuntimeError(
            f"binance_earn_rows_mismatch:expected={expected_rows}:actual={summary['rows']}"
        )
    for key, expected_quantity in expected.items():
        actual = Decimal(str(quantities.get(key, "0")))
        if actual != expected_quantity:
            raise RuntimeError(
                f"binance_earn_quantity_mismatch:{key}:"
                f"expected={expected_quantity}:actual={actual}"
            )


def run(args: argparse.Namespace) -> int:
    db_path = Path(args.db).resolve()
    harvest_path = Path(args.harvest).resolve()
    backup_dir = Path(args.backup_dir).resolve()
    artifact_dir = Path(args.artifact_dir).resolve()
    if not db_path.is_file():
        raise RuntimeError("binance_earn_database_missing")
    if not harvest_path.is_file():
        raise RuntimeError("binance_earn_harvest_missing")
    harvest_sha = _sha256(harvest_path)
    if harvest_sha != args.expected_harvest_sha256:
        raise RuntimeError(
            "binance_earn_harvest_sha_mismatch:"
            f"expected={args.expected_harvest_sha256}:actual={harvest_sha}"
        )
    harvest_payload = json.loads(harvest_path.read_text(encoding="utf-8"))
    if not isinstance(harvest_payload, dict):
        raise RuntimeError("binance_earn_harvest_payload_invalid")
    _validate_api_harvest(harvest_payload)

    store = DuckDbStore(db_path)
    service = BinanceEarnHistoryService(store)
    all_rows, prepared_rows, warnings, duplicate = service._prepared_rows_from_harvest(
        str(harvest_path)
    )
    preview = service.preview_harvest_import(str(harvest_path))
    prepared_summary = _prepared_summary(prepared_rows)
    _assert_expected_rows(
        prepared_summary,
        expected_rows=args.expected_rows,
        expected_jup_rewards=Decimal(args.expected_jup_rewards),
        expected_jup_redemption=Decimal(args.expected_jup_redemption),
        expected_sol_rewards=Decimal(args.expected_sol_rewards),
    )
    if not preview.can_execute or duplicate is not None:
        raise RuntimeError(
            f"binance_earn_preflight_blocked:{preview.blocked_reason or 'duplicate'}"
        )
    before_tax = _tax_line_totals(store)
    payload: dict[str, object] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "execute" if args.execute else "dry-run",
        "database": str(db_path),
        "harvest_path": str(harvest_path),
        "harvest_sha256": harvest_sha,
        "api_records_total": len(all_rows),
        "prepared_summary": prepared_summary,
        "warnings": warnings,
        "preflight": preview.model_dump(mode="json"),
        "before_tax_line_totals": before_tax,
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
        result = service.import_harvest(str(harvest_path), execute=True)
        if result.batch is None or result.run is None:
            raise RuntimeError("binance_earn_import_did_not_execute")
        if result.run.normalized_events != args.expected_normalized_events:
            raise RuntimeError(
                "binance_earn_event_count_mismatch:"
                f"expected={args.expected_normalized_events}:"
                f"actual={result.run.normalized_events}"
            )
        after_tax = _tax_line_totals(store)
        if before_tax != after_tax:
            raise RuntimeError(
                "binance_earn_unexpected_realized_tax_line_change:"
                + json.dumps(
                    {"before": before_tax, "after": after_tax},
                    sort_keys=True,
                )
            )
        evidence = SourceService(store).binance_reconciliation_evidence(
            since=datetime(2026, 6, 14, tzinfo=timezone.utc),
            assets=["JUP", "SOL", "USDC", "BONK"],
        )
        if evidence is None:
            raise RuntimeError("binance_earn_reconciliation_evidence_missing")
        by_asset = {item.asset: item for item in evidence.asset_reports}
        jup = by_asset.get("JUP")
        if jup is None or abs(jup.delta_quantity or Decimal("0")) > Decimal("0.000000001"):
            raise RuntimeError("binance_earn_jup_live_ledger_postcheck_failed")
        if evidence.delta_value_eur is None or abs(evidence.delta_value_eur) >= Decimal("1"):
            raise RuntimeError(
                "binance_earn_reconciliation_delta_not_dust:"
                f"{evidence.delta_value_eur}"
            )
        gate = ReviewService(store).gate()
        if not gate.allow_export or gate.issues_open:
            raise RuntimeError(
                f"binance_earn_review_gate_failed:allow={gate.allow_export}:"
                f"open={gate.issues_open}"
            )
        portfolio = PortfolioService(store).snapshot()
        payload.update(
            {
                "status": "applied",
                "batch": result.batch.model_dump(mode="json"),
                "pipeline": result.run.model_dump(mode="json"),
                "canonical_event_summary": _event_summary(
                    store,
                    result.batch.batch_id,
                ),
                "after_tax_line_totals": after_tax,
                "review_gate": gate.model_dump(mode="json"),
                "portfolio": {
                    "total_value_eur": str(portfolio.total_value_eur),
                    "positions_count": len(portfolio.positions),
                },
                "binance_reconciliation_evidence": evidence.model_dump(mode="json"),
            }
        )
    except Exception as exc:
        shutil.copy2(backup_path, db_path)
        restored_sha = _sha256(db_path)
        if restored_sha != backup_sha:
            raise RuntimeError("binance_earn_rollback_integrity_failed") from exc
        payload.update(
            {
                "status": "rolled_back",
                "error": str(exc),
                "restored_sha256": restored_sha,
            }
        )
        artifact_path = _write_artifact(payload, artifact_dir)
        raise RuntimeError(
            f"binance_earn_apply_failed_and_rolled_back:{exc}:artifact={artifact_path}"
        ) from exc

    artifact_path = _write_artifact(payload, artifact_dir)
    print(
        json.dumps(
            {
                "status": "applied",
                "artifact_path": str(artifact_path),
                "backup_path": str(backup_path),
                "batch_id": payload["batch"]["batch_id"],  # type: ignore[index]
                "prepared_summary": prepared_summary,
                "review_gate": payload["review_gate"],
                "portfolio": payload["portfolio"],
                "reconciliation_delta_eur": payload[
                    "binance_reconciliation_evidence"
                ]["delta_value_eur"],  # type: ignore[index]
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--harvest", required=True)
    parser.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_DIR))
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--expected-harvest-sha256", required=True)
    parser.add_argument("--expected-rows", type=int, required=True)
    parser.add_argument("--expected-normalized-events", type=int, required=True)
    parser.add_argument("--expected-jup-rewards", required=True)
    parser.add_argument("--expected-jup-redemption", required=True)
    parser.add_argument("--expected-sol-rewards", required=True)
    parser.add_argument("--execute", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
