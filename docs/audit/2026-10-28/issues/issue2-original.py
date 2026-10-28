#!/usr/bin/env python3
"""Oeffentlicher synthetischer Bitget-Repro; keine echten Kontodaten.

Ausfuehrung in der installierten rc32-Umgebung, bevorzugt ohne Netzwerk/Mounts:
    python rc32_regression.py > rc32-regression-result.json

Exit 0: alle Sollbedingungen erfuellt; 1: Fachregression reproduziert;
2: falsche Version oder technischer Testfehler. Jede Probe nutzt eine eigene
wegwerfbare DuckDB. Es werden weder produktive DBs noch Importdateien gelesen.
Alle Betraege, Zeitpunkte, Referenzen und Kontobezeichnungen sind erfunden.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal

sys.dont_write_bytecode = True
D = Decimal
SYNTHETIC_TIME = "2031-07-09T12:00:00+01:00"


def csv_text(headers: list[str], rows: list[list[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue()


def native_csv(kind: str, amount: str, fee: str, *, date_header: str = "Time",
               opening_balance_row: bool = False) -> str:
    neutral = kind in {"adjust_margin_ifm", "adjust_down_leverage"}
    effect = D(0) if neutral else D(amount) + D(fee)
    rows = []
    if opening_balance_row:
        rows.append(["synthetic-opening", "2031-07-09T11:00:00+01:00", "USDT",
                     "DEMOUSDT", "Single-asset", "trans_from_exchange", "100", "0", "100"])
    rows.append(["synthetic-order-A", SYNTHETIC_TIME, "USDT", "DEMOUSDT",
                 "Single-asset", kind, amount, fee, str(D(100) + effect)])
    return csv_text(
        ["Order", date_header, "Coin", "Futures", "Margin Mode", "Type",
         "Amount", "Fee", "Wallet balance"], rows,
    )


def legacy_csv(kind: str, net_amount: str, fee: str) -> str:
    return csv_text(
        ["Coin", "Trading Pair", "Action (English)",
         "Surplus/deduction (after fee)", "Fee", "Timestamp UTC+8 (Order)"],
        [["USDT", "DEMOUSDT_UMCBL", kind, net_amount, fee,
          "2031-07-09 12:00:00"]],
    )


def generic_csv(kind: str, amount: str, fee: str = "") -> str:
    return csv_text(
        ["timestamp", "type", "asset", "amount", "fee_asset",
         "fee_quantity", "account", "id"],
        [[SYNTHETIC_TIME, kind, "USDT", amount, "USDT" if fee else "",
          fee, "Synthetic Futures Account", "synthetic-event-A"]],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", default="0.2.0rc32")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="steuerreport-synthetic-bitget-") as temp:
        root = Path(temp)
        # Vor JEDEM App-Import: keine produktiven Konfigurationen laden.
        os.environ["STEUERREPORT_V2_ROOT"] = str(root)
        os.environ["STEUERREPORT_STATE_DIR"] = str(root / "state")
        os.environ["STEUERREPORT_PRIVATE_CONFIG_DIR"] = str(root / "configs")
        os.environ["STEUERREPORT_PRIVATE_PROFILE"] = ""
        os.environ["STEUERREPORT_V2_DB"] = str(root / "unused-default.duckdb")
        os.environ["TZ"] = "UTC"
        if hasattr(time, "tzset"):
            time.tzset()

        import steuerreport_v2
        from steuerreport_v2.db.duckdb_store import DuckDbStore
        from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
        from steuerreport_v2.importers.raw_normalizer import RawNormalizer
        from steuerreport_v2.ledger.balance import BalanceLedgerBuilder

        version = steuerreport_v2.__version__
        if version != args.expected_version:
            print(json.dumps({"error": "version_mismatch", "actual_version": version,
                              "expected_version": args.expected_version}))
            return 2

        results: list[dict] = []

        def probe(name: str, source: str, content: str, *, expected_delta: str,
                  expected_types: list[str] | None = None,
                  expected_time: str | None = None,
                  note: str = "", preview_required: bool = True) -> None:
            result = {"name": name, "source": source, "csv": content, "note": note,
                      "expected": {"usdt_delta": expected_delta,
                                   "event_types": expected_types,
                                   "utc_time": expected_time}}
            try:
                store = DuckDbStore(root / (name + ".duckdb"))
                importer = CsvRawImporter(store)
                preview = importer.preview_text(source=source, filename="synthetic.csv",
                                                content=content)
                batch = importer.import_text(source=source, filename="synthetic.csv",
                                             content=content)
                events, normalization = RawNormalizer(store).normalize_batch_with_report(
                    batch.batch_id
                )
                entries = BalanceLedgerBuilder(store).rebuild()
                total = sum((entry.delta_quantity for entry in entries
                             if entry.asset == "USDT"), D(0))
                event_views = []
                for event in events:
                    stamp = event.event_time
                    # DuckDB speichert die zuvor unter TZ=UTC erzeugte UTC-Zeit
                    # ggf. ohne Offset. Keine lokale Zeitzone hinzuerfinden.
                    if stamp.tzinfo is None:
                        stamp = stamp.replace(tzinfo=timezone.utc)
                    else:
                        stamp = stamp.astimezone(timezone.utc)
                    event_views.append({
                        "event_type": event.event_type, "asset": event.asset,
                        "quantity": str(event.quantity), "fee_asset": event.fee_asset,
                        "fee_quantity": (str(event.fee_quantity)
                                         if event.fee_quantity is not None else None),
                        "utc_time": stamp.isoformat(),
                    })
                failed = []
                if preview_required and not preview.can_import:
                    failed.append("preview_rejects_supported_schema")
                if normalization.skipped_raw_objects:
                    failed.append("raw_rows_skipped")
                if total != D(expected_delta):
                    failed.append("cash_delta_differs")
                if expected_types is not None and sorted(
                    event.event_type for event in events
                ) != sorted(expected_types):
                    failed.append("event_classification_differs")
                if expected_time is not None and (
                    len(event_views) != 1 or event_views[0]["utc_time"] != expected_time
                ):
                    failed.append("utc_time_differs")
                result.update(
                    passed=not failed, failed_checks=failed,
                    actual={"preview_can_import": preview.can_import,
                            "missing_required_groups": preview.missing_required_groups,
                            "normalization": {
                                k: v for k, v in asdict(normalization).items()
                                if k != "batch_id"
                            },
                            "events": event_views, "usdt_delta": str(total)},
                )
            except Exception as exc:
                # Keine Pfade/privaten Laufzeitdaten in einen oeffentlichen Repro
                # uebernehmen. Technische Fehler sind kein bestaetigter Fachbug.
                result.update(passed=False, failed_checks=["test_execution_error"],
                              exception_type=type(exc).__name__)
            results.append(result)

        probe("native_date_header", "bitget", native_csv("open_long", "0", "-0.37",
              date_header="Date"), expected_delta="-0.37", expected_types=["derivative"],
              expected_time="2031-07-09T11:00:00+00:00",
              note="Aktuelles Financial-Schema: Date mit explizitem Offset; keine TZ-Annahme noetig.")
        probe("native_open_gross_fee", "bitget", native_csv("open_long", "0", "-0.37"),
              expected_delta="-0.37", expected_types=["derivative"],
              note="Nur Date zu Time umbenannt, um den Gebuehrenfehler getrennt zu pruefen.")
        probe("native_close_profit_gross_fee", "bitget",
              native_csv("close_long", "12.80", "-0.20"),
              expected_delta="12.60", expected_types=["derivative"])
        probe("native_close_loss_gross_fee", "bitget",
              native_csv("close_short", "-8.40", "-0.15"),
              expected_delta="-8.55", expected_types=["derivative"])
        probe("native_funding_paid", "bitget",
              native_csv("contract_margin_settle_fee", "-2.30", "0"),
              expected_delta="-2.30", expected_types=["derivative"],
              note="Sollklassifikation: signierter Derivate-Funding-Cashflow; derzeit kein eigener Funding-EventType.")
        probe("native_funding_received", "bitget",
              native_csv("contract_margin_settle_fee", "1.10", "0"),
              expected_delta="1.10", expected_types=["derivative"],
              note="Funding kann positiv sein. Cash-Vorzeichen und Klassifikation getrennt beurteilen.")
        probe("native_funding_separate_fee_cash_control", "bitget",
              native_csv("contract_margin_settle_fee", "-2.30", "-0.02"),
              expected_delta="-2.32",
              note="Nur Cash-Kontrolle: hypothetisches Bruttoschema mit separat erhobener Fee.")
        probe("native_collateral_adjustment", "bitget",
              native_csv("adjust_margin_ifm", "25", "0", opening_balance_row=True),
              expected_delta="100",
              note="Reine Sicherheitenumbuchung: Wallet balance bleibt unveraendert, Amount ist kein Walletzufluss.")
        probe("native_leverage_adjustment", "bitget",
              native_csv("adjust_down_leverage", "-10", "0", opening_balance_row=True),
              expected_delta="100",
              note="Reine Hebel-/Sicherheitenanpassung, keine Aenderung des Gesamt-Walletbestands.")
        probe("legacy_after_fee_derivative_control", "bitget",
              legacy_csv("open_long", "-0.37", "-0.37"), expected_delta="-0.37",
              expected_types=["derivative"], expected_time="2031-07-09T04:00:00+00:00",
              note="Regression-Schutz: altes explizites AFTER-FEE-Schema darf Fee nicht nochmals abbuchen.")
        probe("legacy_after_fee_funding_once", "bitget",
              legacy_csv("contract_margin_settle_fee", "-2.32", "-0.02"),
              expected_delta="-2.32",
              note="Synthetisches AFTER-FEE-Funding: Nettowert enthaelt die separat ausgewiesene Fee schon.")
        probe("generic_explicit_derivative", "manual-csv",
              generic_csv("derivative", "-8.55"), expected_delta="-8.55",
              expected_types=["derivative"],
              note="Der Event-Vertrag erlaubt derivative; explizites generisches Mapping sollte ihn erhalten.")
        probe("generic_derivative_with_separate_fee", "manual-csv",
              generic_csv("derivative", "-8.40", "-0.15"), expected_delta="-8.55",
              expected_types=["derivative"],
              note="Eine reine Type-Alias-Korrektur darf nicht ploetzlich diese separate Fee verlieren.")
        probe("explicit_offset_control", "bitget", native_csv("trans_from_exchange", "10", "0"),
              expected_delta="10", expected_types=["transfer"],
              expected_time="2031-07-09T11:00:00+00:00",
              note="Ein vorhandener Offset muss Vorrang vor dem historischen Bitget-Default UTC+8 haben.")
        workaround = csv_text(
            ["timestamp", "type", "asset", "amount", "account", "id"],
            [[SYNTHETIC_TIME, "unknown", "USDT", "-8.40", "Synthetic Account", "demo-principal"],
             [SYNTHETIC_TIME, "fee", "USDT", "-0.15", "Synthetic Account", "demo-fee"],
             [SYNTHETIC_TIME, "unknown", "USDT", "0", "Synthetic Account", "demo-collateral"]],
        )
        probe("explicit_cash_workaround_control", "manual-csv", workaround,
              expected_delta="-8.55", expected_types=["unknown", "fee", "unknown"],
              note="Kontrolle: signierte Cash-Beine und neutrale Rohdatenbelege; ausdruecklich keine Steuerfreigabe.")

        execution_errors = sum("test_execution_error" in r["failed_checks"] for r in results)
        failures = sum(not r["passed"] for r in results)
        report = {
            "application_version": version, "synthetic_data_only": True,
            "disposable_databases_only": True, "production_data_access": False,
            "network_operations_in_test": False,
            "tested_layers": ["CSV preview", "raw import", "canonical normalization", "balance ledger"],
            "summary": {"cases": len(results), "passed": len(results) - failures,
                        "failed": failures, "execution_errors": execution_errors},
            "cases": results,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2 if execution_errors else 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
