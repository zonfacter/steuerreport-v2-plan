#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.parity import V1ParityService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_BLOCKPIT = (
    Path("/workspace/steuerreport/usertransfer")
    / "blockpit"
    / "blockpit 09052026 Transactions.csv"
)
DEFAULT_ALLOWED_ASSETS = {
    "ADA",
    "BNB",
    "BTC",
    "BTT",
    "BTTOLD",
    "BUSD",
    "CBDC",
    "CDT",
    "COTI",
    "DOCK",
    "DOGE",
    "ETH",
    "GFT",
    "HNT",
    "HOT",
    "IOT",
    "JUP",
    "JUPDROP",
    "JUPSOL",
    "MANEKI",
    "MOBILE",
    "PEPE",
    "POPCAT",
    "PYTH",
    "SOL",
    "USDC",
    "USDT",
    "VET",
    "VTHO",
    "WABI",
    "WBTC",
    "WIN",
    "WRX",
    "ZEUS",
}
STABLE_ASSETS = {"EUR", "USD", "USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD"}


def _asset(row: dict[str, str], column: str) -> str:
    return str(row.get(column) or "").strip().upper()


def _row_class(row: dict[str, str]) -> str:
    label = str(row.get("Label") or "").strip()
    incoming = _asset(row, "Incoming Asset")
    outgoing = _asset(row, "Outgoing Asset")
    fee = _asset(row, "Fee Asset (optional)")
    if label == "Trade":
        if incoming in STABLE_ASSETS and outgoing not in STABLE_ASSETS:
            return "trade_sell_to_stable"
        if outgoing in STABLE_ASSETS and incoming not in STABLE_ASSETS:
            return "trade_buy_from_stable"
        if incoming and outgoing:
            return "trade_crypto_crypto"
        return "trade_incomplete"
    if label == "Deposit":
        if incoming in {"JUPDROP", "PYTH"}:
            return "deposit_airdrop_missing_price"
        if incoming and fee == "SOL":
            return "deposit_with_sol_fee"
        if incoming:
            return "deposit_plain"
        return "deposit_other"
    if label == "Withdrawal":
        if outgoing == "SOL":
            return "withdrawal_sol"
        if outgoing in STABLE_ASSETS:
            return "withdrawal_stable"
        if outgoing:
            return "withdrawal_crypto"
        return "withdrawal_other"
    if label == "Fee":
        return "fee_only"
    return "other_" + label.lower().replace(" ", "_").replace("-", "_")


def _decimal(value: str | None) -> Decimal:
    if value is None or str(value).strip() == "":
        return Decimal("0")
    try:
        return Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation:
        return Decimal("0")


def _row_movements(row: dict[str, str]) -> list[tuple[str, Decimal]]:
    label = str(row.get("Label") or "").strip()
    incoming = _asset(row, "Incoming Asset")
    outgoing = _asset(row, "Outgoing Asset")
    fee = _asset(row, "Fee Asset (optional)")
    incoming_amount = _decimal(row.get("Incoming Amount"))
    outgoing_amount = _decimal(row.get("Outgoing Amount"))
    fee_amount = _decimal(row.get("Fee Amount (optional)"))
    movements: list[tuple[str, Decimal]] = []
    if label == "Trade":
        if incoming and incoming_amount:
            movements.append((incoming, incoming_amount))
        if outgoing and outgoing_amount:
            movements.append((outgoing, -outgoing_amount))
    elif label == "Deposit":
        if incoming and incoming_amount:
            movements.append((incoming, incoming_amount))
    elif label in {"Withdrawal", "Fee"}:
        if outgoing and outgoing_amount:
            movements.append((outgoing, -outgoing_amount))
    else:
        if incoming and incoming_amount:
            movements.append((incoming, incoming_amount))
        if outgoing and outgoing_amount:
            movements.append((outgoing, -outgoing_amount))
    if fee and fee_amount:
        movements.append((fee, -abs(fee_amount)))
    return movements


def _assets_requiring_latest_price(rows: list[dict[str, str]]) -> set[str]:
    assets: set[str] = set()
    for row in rows:
        for asset, delta in _row_movements(row):
            if delta > 0 and asset not in STABLE_ASSETS and asset != "EUR":
                assets.add(asset)
    return assets


def _parse_year(value: str) -> int | None:
    try:
        return datetime.strptime(value, "%d.%m.%Y %H:%M:%S").year
    except ValueError:
        return None


def _row_time(row: dict[str, str]) -> datetime:
    try:
        return datetime.strptime(str(row.get("Date (UTC)") or ""), "%d.%m.%Y %H:%M:%S")
    except ValueError:
        return datetime.min


def _backup_database(db_path: Path) -> Path | None:
    if not db_path.exists():
        return None
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{db_path.stem}_before_blockpit_supplement_{stamp}{db_path.suffix}"
    shutil.copy2(db_path, target)
    return target


def _snapshot_database(db_path: Path, purpose: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = Path(tempfile.gettempdir()) / f"{db_path.stem}_blockpit_{purpose}_{stamp}{db_path.suffix}"
    shutil.copy2(db_path, target)
    return target


def _review_snapshot(store: DuckDbStore) -> dict[str, object]:
    gate = ReviewService(store).gate()
    return {
        "allow_export": gate.allow_export,
        "issues_open": gate.issues_open,
        "blocking_issues_open": gate.blocking_issues_open,
        "issues": [issue.model_dump(mode="json") for issue in gate.issues],
    }


def _parity_snapshot(store: DuckDbStore) -> dict[str, object]:
    diagnostics = V1ParityService(store).diagnostics()
    return {
        "compared": diagnostics.compared,
        "matches": diagnostics.matches,
        "differences": diagnostics.differences,
        "missing_v2": diagnostics.missing_v2,
        "groups": len(diagnostics.groups),
        "top_groups": [
            group.model_dump(mode="json")
            for group in diagnostics.groups[:10]
        ],
    }


def _apply_import(
    *,
    db_path: Path,
    source: str,
    blockpit_path: Path,
    file_hash: str,
    rows: list[dict[str, str]],
    integration: str,
    max_year: int | None,
    replace_source: bool,
    create_backup: bool,
) -> dict[str, object]:
    store = DuckDbStore(db_path)
    before_review = _review_snapshot(store)
    before_parity = _parity_snapshot(store)
    backup = _backup_database(db_path) if create_backup else None
    if replace_source:
        store.delete_import_batches_by_source(source)
    batch = CsvRawImporter(store).import_rows(
        source=source,
        filename=f"{blockpit_path.name} [{integration} <= {max_year}]",
        file_hash=file_hash,
        rows=rows,
    )
    pipeline = PipelineService(store).rebuild_all()
    after_review = _review_snapshot(store)
    after_parity = _parity_snapshot(store)
    return {
        "backup": str(backup) if backup is not None else None,
        "batch_id": batch.batch_id,
        "raw_objects": batch.raw_object_count,
        "pipeline": pipeline.model_dump(mode="json"),
        "review_before": before_review,
        "review_after": after_review,
        "parity_before": before_parity,
        "parity_after": after_parity,
    }


def _asset_values(row: dict[str, str]) -> set[str]:
    return {
        str(row.get(column) or "").strip().upper()
        for column in (
            "Outgoing Asset",
            "Incoming Asset",
            "Fee Asset (optional)",
        )
        if str(row.get(column) or "").strip()
    }


def _filtered_rows(
    path: Path,
    integration: str,
    max_year: int | None,
    allowed_assets: set[str],
    include_classes: set[str],
    exclude_classes: set[str],
) -> tuple[list[dict[str, str]], int, dict[str, int], dict[str, int]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        rows = []
        skipped_unknown_assets = 0
        class_counts: dict[str, int] = {}
        skipped_class_counts: dict[str, int] = {}
        for row in reader:
            if row.get("Integration Name") != integration:
                continue
            year = _parse_year(str(row.get("Date (UTC)") or ""))
            if max_year is not None and (year is None or year > max_year):
                continue
            row_class = _row_class(row)
            assets = _asset_values(row)
            if assets and not assets <= allowed_assets:
                skipped_unknown_assets += 1
                continue
            if include_classes and row_class not in include_classes:
                skipped_class_counts[row_class] = skipped_class_counts.get(row_class, 0) + 1
                continue
            if row_class in exclude_classes:
                skipped_class_counts[row_class] = skipped_class_counts.get(row_class, 0) + 1
                continue
            class_counts[row_class] = class_counts.get(row_class, 0) + 1
            rows.append(dict(row))
        return rows, skipped_unknown_assets, class_counts, skipped_class_counts


def _filter_rows_by_class(rows: list[dict[str, str]], row_class: str) -> list[dict[str, str]]:
    return [row for row in rows if _row_class(row) == row_class]


def _matrix_result(
    *,
    db_path: Path,
    source: str,
    blockpit_path: Path,
    base_file_hash: str,
    rows: list[dict[str, str]],
    integration: str,
    max_year: int | None,
    replace_source: bool,
    classes: list[str],
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for row_class in classes:
        class_rows = _filter_rows_by_class(rows, row_class)
        if not class_rows:
            continue
        stage_path = _snapshot_database(db_path, row_class)
        readiness = _readiness_result(stage_path, class_rows)
        preflight = _apply_import(
            db_path=stage_path,
            source=source,
            blockpit_path=blockpit_path,
            file_hash=f"{base_file_hash}#class={row_class}",
            rows=class_rows,
            integration=integration,
            max_year=max_year,
            replace_source=replace_source,
            create_backup=False,
        )
        review_after = preflight["review_after"]
        parity_before = preflight["parity_before"]
        parity_after = preflight["parity_after"]
        issue_codes = [
            f"{issue['code']}:{issue['scope']}"
            for issue in review_after["issues"]
        ]
        results.append(
            {
                "class": row_class,
                "rows": len(class_rows),
                "stage_db": str(stage_path),
                "allow_export": review_after["allow_export"],
                "issues_open": review_after["issues_open"],
                "blocking_issues_open": review_after["blocking_issues_open"],
                "issue_codes": issue_codes,
                "readiness": readiness,
                "parity_before": parity_before,
                "parity_after": parity_after,
                "parity_delta": {
                    "matches": int(parity_after["matches"]) - int(parity_before["matches"]),
                    "differences": int(parity_after["differences"])
                    - int(parity_before["differences"]),
                    "missing_v2": int(parity_after["missing_v2"]) - int(parity_before["missing_v2"]),
                },
            }
        )
    return results


def _current_balances(store: DuckDbStore, account: str) -> dict[str, Decimal]:
    with store.connect() as con:
        rows = con.execute(
            """
            select asset, sum(delta_quantity) as quantity
            from balance_ledger
            where account = ?
            group by asset
            """,
            [account],
        ).fetchall()
    return {str(row[0]): Decimal(str(row[1])) for row in rows}


def _readiness_result(db_path: Path, rows: list[dict[str, str]]) -> dict[str, object]:
    store = DuckDbStore(db_path)
    balances = _current_balances(store, "Solana")
    latest_prices = store.latest_price_points()
    needed_prices = _assets_requiring_latest_price(rows)
    missing_prices = sorted(asset for asset in needed_prices if asset not in latest_prices)
    running = dict(balances)
    min_balance = dict(balances)
    gross_negative_movements: dict[str, Decimal] = {}
    gross_positive_movements: dict[str, Decimal] = {}
    for row in sorted(rows, key=_row_time):
        for asset, delta in _row_movements(row):
            running[asset] = running.get(asset, Decimal("0")) + delta
            min_balance[asset] = min(min_balance.get(asset, running[asset]), running[asset])
            if delta < 0:
                gross_negative_movements[asset] = gross_negative_movements.get(asset, Decimal("0")) + abs(delta)
            elif delta > 0:
                gross_positive_movements[asset] = gross_positive_movements.get(asset, Decimal("0")) + delta
    required_opening_balance = {
        asset: str(abs(quantity))
        for asset, quantity in sorted(min_balance.items())
        if quantity < 0
    }
    return {
        "missing_latest_price_assets": missing_prices,
        "required_opening_balance": required_opening_balance,
        "gross_positive_movements": {
            asset: str(quantity)
            for asset, quantity in sorted(gross_positive_movements.items())
            if quantity != 0
        },
        "gross_negative_movements": {
            asset: str(quantity)
            for asset, quantity in sorted(gross_negative_movements.items())
            if quantity != 0
        },
    }


def run(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    source = args.source
    blockpit_path = Path(args.blockpit_csv)
    allowed_assets = {
        asset.strip().upper()
        for asset in args.allowed_assets.split(",")
        if asset.strip()
    }
    include_classes = {
        value.strip()
        for value in args.include_classes.split(",")
        if value.strip()
    }
    exclude_classes = {
        value.strip()
        for value in args.exclude_classes.split(",")
        if value.strip()
    }
    rows, skipped_unknown_assets, class_counts, skipped_class_counts = _filtered_rows(
        blockpit_path,
        args.integration,
        args.max_year,
        allowed_assets,
        include_classes,
        exclude_classes,
    )
    file_hash = (
        "sha256:"
        + hashlib.sha256(blockpit_path.read_bytes()).hexdigest()
        + f"#integration={args.integration}#max_year={args.max_year}"
        + "#allowed=" + ",".join(sorted(allowed_assets))
    )

    result: dict[str, object] = {
        "mode": "execute" if args.execute else "dry-run",
        "source": source,
        "blockpit_csv": str(blockpit_path),
        "integration": args.integration,
        "max_year": args.max_year,
        "allowed_assets": sorted(allowed_assets),
        "include_classes": sorted(include_classes),
        "exclude_classes": sorted(exclude_classes),
        "filtered_rows": len(rows),
        "skipped_unknown_assets": skipped_unknown_assets,
        "class_counts": dict(sorted(class_counts.items())),
        "skipped_class_counts": dict(sorted(skipped_class_counts.items())),
    }
    if args.class_matrix:
        matrix_classes = [
            value.strip()
            for value in args.matrix_classes.split(",")
            if value.strip()
        ] or sorted(class_counts)
        result["mode"] = "class-matrix"
        result["matrix"] = _matrix_result(
            db_path=db_path,
            source=source,
            blockpit_path=blockpit_path,
            base_file_hash=file_hash,
            rows=rows,
            integration=args.integration,
            max_year=args.max_year,
            replace_source=args.replace_source,
            classes=matrix_classes,
        )
        result["target_changed"] = False
        print(json.dumps(result, indent=2))
        return 0
    if args.readiness_report:
        readiness_classes = [
            value.strip()
            for value in args.matrix_classes.split(",")
            if value.strip()
        ] or sorted(class_counts)
        readiness_db_path = _snapshot_database(db_path, "readiness")
        result["mode"] = "readiness-report"
        result["readiness_db"] = str(readiness_db_path)
        result["readiness"] = {
            row_class: _readiness_result(readiness_db_path, _filter_rows_by_class(rows, row_class))
            for row_class in readiness_classes
            if _filter_rows_by_class(rows, row_class)
        }
        result["target_changed"] = False
        print(json.dumps(result, indent=2))
        return 0
    if args.analyze_classes:
        print(json.dumps(result, indent=2))
        return 0
    if not args.execute:
        print(json.dumps(result, indent=2))
        return 0

    if not args.force:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        stage_path = Path(tempfile.gettempdir()) / f"{db_path.stem}_blockpit_stage_{stamp}{db_path.suffix}"
        shutil.copy2(db_path, stage_path)
        preflight = _apply_import(
            db_path=stage_path,
            source=source,
            blockpit_path=blockpit_path,
            file_hash=file_hash,
            rows=rows,
            integration=args.integration,
            max_year=args.max_year,
            replace_source=args.replace_source,
            create_backup=False,
        )
        result["preflight_db"] = str(stage_path)
        result["preflight"] = preflight
        if not preflight["review_after"]["allow_export"]:
            result["target_changed"] = False
            result["blocked_reason"] = "preflight_review_not_export_ready"
            print(json.dumps(result, indent=2))
            return 2

    applied = _apply_import(
        db_path=db_path,
        source=source,
        blockpit_path=blockpit_path,
        file_hash=file_hash,
        rows=rows,
        integration=args.integration,
        max_year=args.max_year,
        replace_source=args.replace_source,
        create_backup=True,
    )
    result.update(applied)
    result["target_changed"] = True
    print(json.dumps(result, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Importiert einen gefilterten Blockpit-Ergaenzungsbestand."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--blockpit-csv", default=str(DEFAULT_BLOCKPIT))
    parser.add_argument("--integration", default="Solana")
    parser.add_argument("--source", default="blockpit-solana")
    parser.add_argument("--max-year", type=int, default=2024)
    parser.add_argument(
        "--allowed-assets",
        default=",".join(sorted(DEFAULT_ALLOWED_ASSETS)),
        help="Kommagetrennte Asset-Whitelist. Zeilen mit anderen Assets werden verworfen.",
    )
    parser.add_argument(
        "--include-classes",
        default="",
        help="Kommagetrennte Blockpit-Klassen, die importiert werden sollen.",
    )
    parser.add_argument(
        "--exclude-classes",
        default="deposit_airdrop_missing_price",
        help="Kommagetrennte Blockpit-Klassen, die verworfen werden sollen.",
    )
    parser.add_argument(
        "--analyze-classes",
        action="store_true",
        help="Gibt nur Klassenverteilung und Filterergebnis aus.",
    )
    parser.add_argument(
        "--class-matrix",
        action="store_true",
        help="Fuehrt fuer jede Klasse einen isolierten Staging-Preflight aus.",
    )
    parser.add_argument(
        "--readiness-report",
        action="store_true",
        help="Ermittelt je Klasse fehlende Preise und benoetigte Startbestaende ohne Import.",
    )
    parser.add_argument(
        "--matrix-classes",
        default="",
        help="Optionale kommagetrennte Klassenliste fuer --class-matrix.",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Importiert trotz fehlgeschlagener Staging-Review in die Ziel-DB.",
    )
    parser.add_argument("--replace-source", action="store_true", default=True)
    args = parser.parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
