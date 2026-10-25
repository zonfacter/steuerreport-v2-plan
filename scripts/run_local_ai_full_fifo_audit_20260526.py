#!/usr/bin/env python3
from __future__ import annotations

from steuerreport_v2.private_settings import private_value

import argparse
import csv
import json
import os
import textwrap
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "var" / "local_ai_prework" / "packages" / "full_fifo_audit_20260526"
DB_PATH = Path(os.environ.get("STEUERREPORT_V2_AUDIT_DB", ROOT / "data" / "steuerreport_v2.duckdb"))
API_BASE = os.environ.get("STEUERREPORT_V2_API", "http://127.0.0.1:8010")
LLM_BASE = os.environ.get("LOCAL_LLM_BASE") or private_value("local_llm_base") or "http://127.0.0.1:11435/v1"
LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL") or private_value("local_llm_model") or "local-model"

MAIN_WALLET = private_value('legacy_helium_wallet')
FAIRSPOT_WALLET = private_value('staking_route_wallet')


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local-AI full FIFO audit prework.")
    parser.add_argument("--dry-run", action="store_true", help="Build full audit files but skip LLM call.")
    args = parser.parse_args()

    started_at = datetime.now(UTC).isoformat()
    raw_dir = PACKAGE / "raw"
    reports_dir = PACKAGE / "reports"
    raw_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    audit = build_full_audit(raw_dir)
    manifest = {
        "package": "full_fifo_audit_20260526",
        "started_at": started_at,
        "mode": "readonly_full_scan",
        "scope": "all canonical_events, tax_lines, tax_lots, unmatched_disposals, balance_ledger, raw links",
        "rules": [
            "No database writes.",
            "No imports.",
            "No FIFO rebuild.",
            "Every canonical event is exported to raw/all_canonical_events.csv.",
            "Every tax line is exported to raw/all_tax_lines.csv.",
            "All findings are deterministic pre-AI flags and must be verified by Codex before changes.",
        ],
        "raw_files": sorted(str(path.relative_to(PACKAGE)) for path in raw_dir.glob("*")),
    }
    write_json(PACKAGE / "manifest.json", manifest)

    if args.dry_run:
        report = dry_run_report(audit)
        status = "dry_run"
    else:
        report, status = call_llm(build_prompt(audit))

    report_path = reports_dir / "full_fifo_audit_report.md"
    report_path.write_text(report.strip() + "\n", encoding="utf-8")
    write_json(
        PACKAGE / "run_status.json",
        {
            "status": status,
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "report": str(report_path.relative_to(PACKAGE)),
            "events_scanned": audit["summary"]["canonical_events"],
            "tax_lines_scanned": audit["summary"]["tax_lines"],
            "findings": audit["summary"]["findings_total"],
        },
    )
    return 0


def build_full_audit(raw_dir: Path) -> dict[str, Any]:
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        events = query_dicts(
            con,
            """
            select
                e.event_id, e.source, e.source_ref, e.event_time, e.event_type,
                e.asset, e.quantity, e.quote_asset, e.quote_quantity, e.fee_asset,
                e.fee_quantity, e.tx_id, e.wallet, e.account, e.confidence,
                e.raw_object_id, b.filename, r.row_number, r.payload_json
            from canonical_events e
            left join raw_objects r on r.raw_object_id = e.raw_object_id
            left join raw_import_batches b on b.batch_id = r.batch_id
            order by
                e.event_time,
                case when r.row_number is null then 1 else 0 end,
                r.row_number,
                e.event_id
            """,
        )
        tax_lines = query_dicts(
            con,
            """
            select
                l.tax_line_id, l.asset, l.disposed_at, l.quantity,
                l.acquisition_cost_eur, l.disposal_proceeds_eur, l.gain_loss_eur,
                l.holding_days, l.source_event_id, l.lot_id,
                e.source, e.source_ref, e.event_type, e.account, e.tx_id, e.raw_object_id
            from tax_lines l
            left join canonical_events e on e.event_id = l.source_event_id
            order by l.disposed_at, l.tax_line_id
            """,
        )
        tax_lots = query_dicts(
            con,
            """
            select lot_id, asset, acquired_at, quantity_total, quantity_remaining,
                   cost_basis_eur_total, source_event_id
            from tax_lots
            order by acquired_at, lot_id
            """,
        )
        negative_balances = query_dicts(
            con,
            """
            select
                bl.event_id, bl.event_time, bl.account, bl.asset,
                bl.delta_quantity, bl.balance_quantity,
                e.source, e.source_ref, e.event_type, e.quantity,
                e.quote_asset, e.quote_quantity, e.fee_asset, e.fee_quantity,
                e.tx_id, e.wallet, e.raw_object_id,
                b.filename, r.row_number, r.payload_json
            from balance_ledger bl
            left join canonical_events e on e.event_id = bl.event_id
            left join raw_objects r on r.raw_object_id = e.raw_object_id
            left join raw_import_batches b on b.batch_id = r.batch_id
            where bl.balance_quantity < 0
            order by bl.event_time, bl.event_id
            """,
        )
        negative_balance_context = query_dicts(
            con,
            """
            with ledger_events as (
                select
                    row_number() over (
                        partition by bl.account, bl.asset
                        order by
                            bl.event_time,
                            case when r.row_number is null then 1 else 0 end,
                            r.row_number,
                            bl.event_id
                    ) as ledger_seq,
                    bl.event_id, bl.event_time, bl.account, bl.asset,
                    bl.delta_quantity, bl.balance_quantity,
                    e.source, e.source_ref, e.event_type, e.quantity,
                    e.quote_asset, e.quote_quantity, e.fee_asset, e.fee_quantity,
                    e.tx_id, e.wallet, e.raw_object_id,
                    b.filename, r.row_number, r.payload_json
                from balance_ledger bl
                left join canonical_events e on e.event_id = bl.event_id
                left join raw_objects r on r.raw_object_id = e.raw_object_id
                left join raw_import_batches b on b.batch_id = r.batch_id
            ),
            negatives as (
                select event_id as negative_event_id, account, asset, ledger_seq
                from ledger_events
                where balance_quantity < 0
            )
            select
                n.negative_event_id,
                le.ledger_seq - n.ledger_seq as offset_from_negative,
                le.*
            from negatives n
            join ledger_events le
              on le.account = n.account
             and le.asset = n.asset
             and le.ledger_seq between n.ledger_seq - 5 and n.ledger_seq + 5
            order by n.account, n.asset, n.ledger_seq, offset_from_negative
            """,
        )
        raw_without_events = query_dicts(
            con,
            """
            select b.source, b.filename, count(*) as raw_objects
            from raw_objects r
            join raw_import_batches b on b.batch_id = r.batch_id
            left join canonical_events e on e.raw_object_id = r.raw_object_id
            where e.event_id is null
            group by b.source, b.filename
            order by raw_objects desc, b.filename
            """,
        )

    api = {
        "review_gates": fetch_api("/api/v1/review/gates").get("data"),
        "tax_summary": fetch_api("/api/v1/tax/summary").get("data"),
        "sources_overview": compact_sources(fetch_api("/api/v1/sources/overview").get("data", {})),
        "portfolio_reconciliation": compact_reconciliation(fetch_api("/api/v1/portfolio/reconciliation").get("data", {})),
        "portfolio_snapshot": compact_snapshot(fetch_api("/api/v1/portfolio/snapshot").get("data", {})),
    }

    write_csv(raw_dir / "all_canonical_events.csv", events)
    write_csv(raw_dir / "all_tax_lines.csv", tax_lines)
    write_csv(raw_dir / "all_tax_lots.csv", tax_lots)
    write_json(raw_dir / "negative_balance_ledger_entries.json", negative_balances)
    write_json(raw_dir / "negative_balance_ledger_context.json", negative_balance_context)
    write_json(raw_dir / "raw_objects_without_canonical_events_by_file.json", raw_without_events)
    write_json(raw_dir / "api_state.json", api)

    findings = build_findings(events, tax_lines, tax_lots, negative_balances, raw_without_events, api)
    write_csv(raw_dir / "all_findings.csv", findings)
    write_json(raw_dir / "findings_by_code.json", summarize_findings(findings))

    chunk_summaries = build_chunk_summaries(events, findings, chunk_size=1000)
    write_json(raw_dir / "canonical_event_chunk_summaries.json", chunk_summaries)

    summary = {
        "canonical_events": len(events),
        "tax_lines": len(tax_lines),
        "tax_lots": len(tax_lots),
        "negative_balance_entries": len(negative_balances),
        "raw_files_with_unmapped_rows": len(raw_without_events),
        "findings_total": len(findings),
        "findings_by_code": summarize_findings(findings),
        "event_span": event_span(events),
        "api": api,
    }
    write_json(raw_dir / "full_audit_summary.json", summary)
    return {
        "summary": summary,
        "top_findings": findings[:250],
        "chunk_summaries": chunk_summaries[:60],
        "artifact_paths": {
            "all_events": "raw/all_canonical_events.csv",
            "all_tax_lines": "raw/all_tax_lines.csv",
            "all_tax_lots": "raw/all_tax_lots.csv",
            "all_findings": "raw/all_findings.csv",
            "negative_balance_context": "raw/negative_balance_ledger_context.json",
            "chunk_summaries": "raw/canonical_event_chunk_summaries.json",
            "api_state": "raw/api_state.json",
        },
    }


def build_findings(
    events: list[dict[str, Any]],
    tax_lines: list[dict[str, Any]],
    tax_lots: list[dict[str, Any]],
    negative_balances: list[dict[str, Any]],
    raw_without_events: list[dict[str, Any]],
    api: dict[str, Any],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    seen_tx: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)

    for index, event in enumerate(events, start=1):
        payload = parse_payload(event.get("payload_json"))
        raw_type = raw_value(payload, "type", "operation", "category")
        payer = raw_value(payload, "payer", "sender", "from", "from_address")
        payee = raw_value(payload, "payee", "receiver", "to", "to_address")
        event_type = str(event.get("event_type") or "")
        source = str(event.get("source") or "")
        asset = str(event.get("asset") or "")
        account = str(event.get("account") or "")
        quantity = dec(event.get("quantity"))
        tx_id = str(event.get("tx_id") or "")

        if tx_id:
            seen_tx[(source, asset, tx_id)].append(event)
        if event_type == "unknown":
            findings.append(unknown_event_type_finding(event, payload, index))
        if not account:
            findings.append(finding("missing_account", event, index, "Canonical Event hat keinen Account."))
        if str(event.get("raw_object_id") or "") == "":
            findings.append(finding("missing_raw_link", event, index, "Canonical Event hat keinen Raw-Object-Link."))
        if source == "helium" and raw_type and "payment" in raw_type.lower() and event_type != "transfer":
            findings.append(
                finding(
                    "helium_payment_not_transfer",
                    event,
                    index,
                    f"Helium payment row ist {event_type}, erwartet transfer. payer={payer} payee={payee}",
                )
            )
        if FAIRSPOT_WALLET in {account, payer, payee} and event_type != "transfer":
            findings.append(
                finding(
                    "fairspot_not_transfer",
                    event,
                    index,
                    f"Fairspot-Bezug ist {event_type}, erwartet transfer/counterparty. payer={payer} payee={payee}",
                )
            )
        if event_type == "transfer" and quantity > 0 and event.get("quote_asset") and event.get("quote_quantity"):
            findings.append(positive_transfer_with_quote_finding(event, payload, index))

    for (_source, _asset, _tx_id), grouped in seen_tx.items():
        if len(grouped) > 5:
            sample = grouped[0]
            is_pionex_grid_tax_id = (
                str(sample.get("source") or "") == "pionex"
                and str(sample.get("tx_id") or "").startswith("s_")
                and str(sample.get("filename") or "") == "raw-trading-details.csv"
            )
            findings.append(
                finding(
                    "high_duplicate_txid_count",
                    sample,
                    0,
                    f"TXID kommt {len(grouped)} mal fuer Source/Asset vor; moeglich bei Splits, aber pruefen.",
                )
            )
            if is_pionex_grid_tax_id:
                findings[-1]["severity"] = "info"
                findings[-1]["message"] = (
                    f"Pionex tax_id {sample.get('tx_id')} kommt {len(grouped)} mal "
                    "fuer Source/Asset vor; bei raw-trading-details.csv sind dies "
                    "Grid-/Split-Gruppen und keine eindeutigen On-Chain- oder "
                    "Exchange-TXIDs."
                )

    for line in tax_lines:
        event = {"event_id": line.get("source_event_id"), **line}
        if dec(line.get("acquisition_cost_eur")) == 0:
            findings.append(finding("zero_acquisition_cost_tax_line", event, 0, "Tax-Line mit 0 EUR Anschaffungskosten."))
        if dec(line.get("disposal_proceeds_eur")) == 0:
            findings.append(finding("zero_disposal_proceeds_tax_line", event, 0, "Tax-Line mit 0 EUR Veraeusserungserloes."))
        if int(dec(line.get("holding_days"))) < 0:
            findings.append(finding("negative_holding_days", event, 0, "Tax-Line hat negative Haltedauer."))

    for lot in tax_lots:
        event = {"event_id": lot.get("source_event_id"), **lot}
        if dec(lot.get("cost_basis_eur_total")) == 0:
            findings.append(finding("zero_cost_tax_lot", event, 0, "Tax-Lot mit 0 EUR Kostenbasis."))
        if dec(lot.get("quantity_remaining")) < 0:
            findings.append(finding("negative_remaining_lot", event, 0, "Tax-Lot hat negative Restmenge."))

    for row in negative_balances[:5000]:
        balance_quantity = dec(row.get("balance_quantity"))
        transient_pionex_dust = (
            str(row.get("source") or "") == "pionex"
            and str(row.get("asset") or "") == "HNT"
            and abs(balance_quantity) < Decimal("1")
        )
        findings.append(
            {
                "code": "negative_balance_ledger",
                "severity": "info" if transient_pionex_dust else "warning",
                "event_index": "",
                "event_id": row.get("event_id"),
                "event_time": row.get("event_time"),
                "source": row.get("source"),
                "event_type": row.get("event_type"),
                "asset": row.get("asset"),
                "quantity": row.get("delta_quantity"),
                "account": row.get("account"),
                "tx_id": row.get("tx_id"),
                "filename": row.get("filename"),
                "row_number": row.get("row_number"),
                "balance_quantity": row.get("balance_quantity"),
                "raw_object_id": row.get("raw_object_id"),
                "message": (
                    (
                        "Pionex-HNT Grid-/Split-Dust wurde kurzzeitig negativ und "
                        "im folgenden Split wieder positiv; keine FIFO- oder "
                        "Review-Blockade. "
                    )
                    if transient_pionex_dust
                    else ""
                )
                + (
                    f"Balance Ledger wurde negativ: {row.get('balance_quantity')} "
                    f"(raw={row.get('filename')} row={row.get('row_number')})."
                ),
            }
        )

    for row in raw_without_events:
        findings.append(
            {
                "code": "raw_objects_without_canonical_events",
                "severity": "info",
                "event_index": "",
                "event_id": "",
                "event_time": "",
                "source": row.get("source"),
                "event_type": "",
                "asset": "",
                "quantity": row.get("raw_objects"),
                "account": "",
                "tx_id": "",
                "message": f"Raw-Datei hat {row.get('raw_objects')} Rohzeilen ohne Canonical Event: {row.get('filename')}",
            }
        )

    reconciliation_blocker_sources = {
        row.get("source_group")
        for row in api.get("portfolio_reconciliation", {}).get("blockers", [])
    }
    for source in api.get("sources_overview", {}).get("sources", []):
        if dec(source.get("delta_value_eur")) != 0 and int(dec(source.get("open_reconciliation_issues"))) > 0:
            severity = (
                "blocker"
                if source.get("label") in reconciliation_blocker_sources
                else "warning"
            )
            findings.append(
                {
                    "code": "live_ledger_delta",
                    "severity": severity,
                    "event_index": "",
                    "event_id": "",
                    "event_time": "",
                    "source": source.get("label"),
                    "event_type": "",
                    "asset": "",
                    "quantity": "",
                    "account": "",
                    "tx_id": "",
                    "message": (
                        f"Live/Ledger Delta {source.get('delta_value_eur')} EUR, "
                        f"ledger={source.get('ledger_value_eur')} live={source.get('live_value_eur')}"
                    ),
                }
            )

    severity_order = {"blocker": 0, "warning": 1, "info": 2}
    return sorted(findings, key=lambda item: (severity_order.get(str(item["severity"]), 9), str(item["code"]), str(item["event_time"])))


def finding(code: str, event: dict[str, Any], index: int, message: str) -> dict[str, Any]:
    severity = "blocker" if code in {"fairspot_not_transfer", "helium_payment_not_transfer", "live_ledger_delta"} else "warning"
    return {
        "code": code,
        "severity": severity,
        "event_index": index,
        "event_id": event.get("event_id"),
        "event_time": event.get("event_time") or event.get("disposed_at") or event.get("acquired_at"),
        "source": event.get("source"),
        "event_type": event.get("event_type"),
        "asset": event.get("asset"),
        "quantity": event.get("quantity"),
        "account": event.get("account"),
        "tx_id": event.get("tx_id"),
        "filename": event.get("filename"),
        "row_number": event.get("row_number"),
        "balance_quantity": event.get("balance_quantity"),
        "raw_object_id": event.get("raw_object_id"),
        "message": message,
    }


def positive_transfer_with_quote_finding(
    event: dict[str, Any],
    payload: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    source = str(event.get("source") or "")
    filename = str(event.get("filename") or "")
    source_ref = str(event.get("source_ref") or "")
    quote_asset = str(event.get("quote_asset") or "").upper()
    action = raw_value(payload, "action", "action (english)")
    raw_type = raw_value(payload, "type")
    method = raw_value(payload, "method")

    known_acquisition = False
    reason = ""
    if source == "binance" and "Fiat-Buy-History" in filename and quote_asset == "EUR":
        known_acquisition = True
        reason = f"Binance Fiat-Buy-History mit EUR Spend und Methode {method or '-'}."
    elif source == "manual-csv" and source_ref.startswith("manual-opening:"):
        known_acquisition = True
        reason = "Manuell belegter Opening-/Deposit-Lot mit Quote."
    elif source == "bitget" and filename == "Spot Financial Record.csv":
        normalized_action = action.upper()
        if normalized_action in {"STRATEGY_TRANSFER_IN", "RECHARGE", "NEW_FIAT_RECHARGE_USER_IN"}:
            known_acquisition = True
            reason = (
                "Bitget Spot Financial Record Transfer-In/Deposit mit "
                f"Bewertungsfeld Amount (USDT), Action {normalized_action}."
            )

    if known_acquisition:
        item = finding(
            "valued_acquisition_transfer",
            event,
            index,
            f"Bewerteter positiver Transfer erzeugt nachvollziehbaren Anschaffungslot. {reason}",
        )
        item["severity"] = "info"
        item["raw_type"] = raw_type
        item["action"] = action
        return item

    item = finding(
        "positive_transfer_with_quote_lot",
        event,
        index,
        "Positiver Transfer mit Quote erzeugt Anschaffungslot; fachlich pruefen, ob externer Zufluss oder interner Transfer.",
    )
    item["raw_type"] = raw_type
    item["action"] = action
    return item


def unknown_event_type_finding(
    event: dict[str, Any],
    payload: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    quantity = dec(event.get("quantity"))
    operation = raw_value(payload, "operation")
    action = raw_value(payload, "action", "action (english)")
    status = raw_value(payload, "status")
    raw_type = raw_value(payload, "type")
    raw_event_type = raw_value(payload, "event_type")
    defi_label = raw_value(payload, "defi_label")
    raw_source = raw_value(payload, "source")
    source = str(event.get("source") or "")

    known_zero_quantity = quantity == 0 and bool(
        operation
        or action
        or status
        or raw_type
        or raw_event_type
        or defi_label
        or raw_source
    )
    if known_zero_quantity:
        item = finding(
            "known_zero_quantity_unknown_event",
            event,
            index,
            (
                "Canonical Event ist unknown mit 0 Menge; bekannte Schatten-/Infozeile "
                f"aus Rohoperation {operation or action or status or raw_type or raw_event_type or defi_label or raw_source}."
            ),
        )
        item["severity"] = "info"
        item["raw_operation"] = operation
        item["action"] = action
        item["raw_type"] = raw_type
        item["raw_event_type"] = raw_event_type
        item["defi_label"] = defi_label
        item["raw_source"] = raw_source
        item["status"] = status
        return item

    item = finding("unknown_event_type", event, index, "Canonical Event ist unknown.")
    item["raw_operation"] = operation
    item["action"] = action
    item["raw_type"] = raw_type
    item["raw_event_type"] = raw_event_type
    item["defi_label"] = defi_label
    item["raw_source"] = raw_source
    item["status"] = status
    item["source"] = source
    return item


def build_chunk_summaries(events: list[dict[str, Any]], findings: list[dict[str, Any]], chunk_size: int) -> list[dict[str, Any]]:
    findings_by_index: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in findings:
        try:
            index = int(item.get("event_index") or 0)
        except (TypeError, ValueError):
            continue
        if index:
            findings_by_index[index].append(item)

    chunks = []
    for start in range(0, len(events), chunk_size):
        chunk = events[start : start + chunk_size]
        source_counts = Counter(str(row.get("source") or "") for row in chunk)
        type_counts = Counter(str(row.get("event_type") or "") for row in chunk)
        asset_counts = Counter(str(row.get("asset") or "") for row in chunk)
        chunk_findings = [
            finding
            for index in range(start + 1, start + len(chunk) + 1)
            for finding in findings_by_index.get(index, [])
        ]
        chunks.append(
            {
                "chunk": len(chunks) + 1,
                "row_start": start + 1,
                "row_end": start + len(chunk),
                "event_time_start": chunk[0].get("event_time") if chunk else None,
                "event_time_end": chunk[-1].get("event_time") if chunk else None,
                "source_counts": dict(source_counts.most_common()),
                "event_type_counts": dict(type_counts.most_common()),
                "asset_counts_top10": dict(asset_counts.most_common(10)),
                "findings_count": len(chunk_findings),
                "findings_by_code": dict(Counter(str(item["code"]) for item in chunk_findings).most_common()),
                "finding_samples": chunk_findings[:10],
            }
        )
    return chunks


def summarize_findings(findings: list[dict[str, Any]]) -> dict[str, Any]:
    by_code = Counter(str(item["code"]) for item in findings)
    by_severity = Counter(str(item["severity"]) for item in findings)
    return {"by_code": dict(by_code.most_common()), "by_severity": dict(by_severity.most_common())}


def event_span(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        return {"first": None, "last": None}
    return {"first": events[0].get("event_time"), "last": events[-1].get("event_time")}


def compact_sources(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "total_value_eur": data.get("total_value_eur"),
        "sources": [
            {
                key: item.get(key)
                for key in (
                    "label",
                    "source_type",
                    "value_eur",
                    "value_basis",
                    "ledger_value_eur",
                    "live_value_eur",
                    "delta_value_eur",
                    "open_reconciliation_issues",
                    "last_live_at",
                )
            }
            for item in data.get("sources", [])
        ],
    }


def compact_reconciliation(data: dict[str, Any]) -> dict[str, Any]:
    rows = data.get("rows", [])
    return {
        "total_ledger_value_eur": data.get("total_ledger_value_eur"),
        "expected_zero_ledger_value_eur": data.get("expected_zero_ledger_value_eur"),
        "live_unverified_ledger_value_eur": data.get("live_unverified_ledger_value_eur"),
        "missing_wallets": data.get("missing_wallets", []),
        "blockers": [row for row in rows if row.get("severity") == "blocker"][:50],
    }


def compact_snapshot(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "total_value_eur": data.get("total_value_eur"),
        "missing_price_assets": data.get("missing_price_assets", []),
        "asset_summary_top20": data.get("asset_summary", [])[:20],
        "account_summary_top20": data.get("account_summary", [])[:20],
    }


def parse_payload(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def raw_value(payload: dict[str, Any], *keys: str) -> str:
    normalized = {normalize_key(key): value for key, value in payload.items()}
    for key in keys:
        value = normalized.get(normalize_key(key))
        if value not in (None, ""):
            return str(value)
    return ""


def normalize_key(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in value).strip("_")


def dec(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return Decimal("0")


def query_dicts(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    result = con.execute(sql)
    columns = [item[0] for item in result.description]
    return [
        {column: json_safe(value) for column, value in zip(columns, row, strict=True)}
        for row in result.fetchall()
    ]


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def fetch_api(path: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{API_BASE}{path}", timeout=240) as response:
        return json.loads(response.read().decode("utf-8"))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def build_prompt(audit: dict[str, Any]) -> str:
    return textwrap.dedent(
        f"""
        Du bist lokale KI fuer Steuerreport V2. Arbeite ausschliesslich im Readonly-Modus.

        Harte Regeln:
        - Keine Datenbank schreiben.
        - Keine Imports ausfuehren.
        - Kein FIFO-Rebuild ausfuehren.
        - Keine Review-Entscheidungen setzen.
        - Keine steuerliche Endentscheidung.
        - Nichts erfinden. Nutze nur die gelieferten Audit-Artefakte.

        Auftrag des Nutzers:
        Die komplette aktuelle Datenlage pruefen: alle Canonical Events, alle
        FIFO Tax-Lines und alle relevanten Live-vs-Ledger Abweichungen.
        Die vollstaendigen Tabellen liegen als Artefakte vor:
        {json.dumps(audit["artifact_paths"], ensure_ascii=False, indent=2)}

        Wichtig: Die maschinellen Pruefregeln haben jede Canonical-Event-Zeile
        und jede Tax-Line gescannt. Du bewertest die Findings und priorisierst
        die naechsten Codex-Schritte. Du darfst nicht behaupten, dass 100 Prozent
        steuerlich fertig sind, solange Blocker bestehen.

        Audit-Zusammenfassung:
        {json.dumps(audit["summary"], ensure_ascii=False, indent=2)[:22000]}

        Erste Findings:
        {json.dumps(audit["top_findings"], ensure_ascii=False, indent=2)[:22000]}

        Chunk-Summaries:
        {json.dumps(audit["chunk_summaries"], ensure_ascii=False, indent=2)[:22000]}

        Schreibe einen deutschen Markdown-Report mit exakt diesen Abschnitten:
        # Full FIFO Audit
        ## Kurzurteil
        ## Gepruefter Umfang
        ## Harte Blocker
        ## Warnungen
        ## Fairspot/HNT Bewertung
        ## Live-vs-Ledger Bewertung
        ## FIFO-Risiko bis 2021
        ## Was Codex zuerst reparieren muss
        ## Akzeptanzkriterien fuer 100 Prozent Rueckverfolgung
        ## Stop-Kriterien
        """
    ).strip()


def call_llm(prompt: str) -> tuple[str, str]:
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4200,
        "temperature": 0.1,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    try:
        request = urllib.request.Request(
            f"{LLM_BASE}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2400) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data["choices"][0]["message"].get("content") or ""
        return content or "Leere Modellantwort.", "ok"
    except (KeyError, urllib.error.URLError, TimeoutError, OSError) as exc:
        return f"# Lokale KI Aufgabe fehlgeschlagen\n\n`{type(exc).__name__}: {exc}`\n", "failed"


def dry_run_report(audit: dict[str, Any]) -> str:
    return textwrap.dedent(
        f"""
        # Full FIFO Audit

        ## Kurzurteil

        Dry-Run erfolgreich. Alle Daten wurden read-only exportiert und gescannt.

        ## Gepruefter Umfang

        - Canonical Events: {audit['summary']['canonical_events']}
        - Tax-Lines: {audit['summary']['tax_lines']}
        - Tax-Lots: {audit['summary']['tax_lots']}
        - Findings: {audit['summary']['findings_total']}

        ## Artefakte

        - `raw/all_canonical_events.csv`
        - `raw/all_tax_lines.csv`
        - `raw/all_tax_lots.csv`
        - `raw/all_findings.csv`
        - `raw/canonical_event_chunk_summaries.json`
        """
    ).strip()


if __name__ == "__main__":
    raise SystemExit(main())
