#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from steuerreport_v2.db.duckdb_store import DuckDbStore


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_AUDIT = PROJECT_ROOT / "var" / "solana_tx_alchemy_audits" / "latest_solana_rpc_tx_alchemy_audit.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var" / "solana_failed_tx_tax_impacts"


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _load_failed_txids(audit_path: Path) -> list[str]:
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    txids = [
        str(row.get("tx_id"))
        for row in rows
        if isinstance(row, dict)
        and row.get("tx_id")
        and row.get("review_status") == "onchain_transaction_failed"
    ]
    return list(dict.fromkeys(txids))


def _count_by(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        result[value] = result.get(value, 0) + 1
    return result


def _rows_to_dicts(rows: list[tuple[Any, ...]], columns: list[str]) -> list[dict[str, Any]]:
    return [dict(zip(columns, row, strict=True)) for row in rows]


def build_report(store: DuckDbStore, audit_path: Path) -> dict[str, Any]:
    failed_txids = _load_failed_txids(audit_path)
    with store.connect() as con:
        con.execute("create temp table failed_tx(tx_id varchar)")
        if failed_txids:
            con.executemany("insert into failed_tx values (?)", [(txid,) for txid in failed_txids])

        event_rows = _rows_to_dicts(
            con.execute(
                """
                select
                    e.tx_id,
                    min(e.event_time) as first_event_time,
                    max(e.event_time) as last_event_time,
                    date_part('year', min(e.event_time))::integer as year,
                    string_agg(distinct e.event_type, ', ' order by e.event_type) as event_types,
                    string_agg(distinct upper(e.asset), ', ' order by upper(e.asset)) as assets,
                    string_agg(distinct coalesce(e.account, e.wallet, ''), ', ' order by coalesce(e.account, e.wallet, '')) as accounts,
                    count(*)::integer as canonical_events_count,
                    sum(abs(e.quantity)) as gross_quantity,
                    sum(e.quantity) as net_quantity
                from canonical_events e
                join failed_tx f on f.tx_id = e.tx_id
                group by e.tx_id
                order by min(e.event_time), e.tx_id
                """
            ).fetchall(),
            [
                "tx_id",
                "first_event_time",
                "last_event_time",
                "year",
                "event_types",
                "assets",
                "accounts",
                "canonical_events_count",
                "gross_quantity",
                "net_quantity",
            ],
        )
        event_summary = _rows_to_dicts(
            con.execute(
                """
                select
                    date_part('year', e.event_time)::integer as year,
                    e.event_type,
                    upper(e.asset) as asset,
                    count(*)::integer as canonical_events_count,
                    sum(e.quantity) as net_quantity,
                    sum(abs(e.quantity)) as gross_quantity
                from canonical_events e
                join failed_tx f on f.tx_id = e.tx_id
                group by 1, 2, 3
                order by 1, 2, 3
                """
            ).fetchall(),
            ["year", "event_type", "asset", "canonical_events_count", "net_quantity", "gross_quantity"],
        )
        tax_lines = _rows_to_dicts(
            con.execute(
                """
                select
                    l.tax_line_id,
                    l.asset,
                    l.disposed_at,
                    l.quantity,
                    l.acquisition_cost_eur,
                    l.disposal_proceeds_eur,
                    l.gain_loss_eur,
                    l.source_event_id,
                    e.tx_id
                from tax_lines l
                join canonical_events e on e.event_id = l.source_event_id
                join failed_tx f on f.tx_id = e.tx_id
                order by l.disposed_at, l.tax_line_id
                """
            ).fetchall(),
            [
                "tax_line_id",
                "asset",
                "disposed_at",
                "quantity",
                "acquisition_cost_eur",
                "disposal_proceeds_eur",
                "gain_loss_eur",
                "source_event_id",
                "tx_id",
            ],
        )
        tax_lots = _rows_to_dicts(
            con.execute(
                """
                select
                    l.lot_id,
                    l.asset,
                    l.acquired_at,
                    l.quantity_total,
                    l.quantity_remaining,
                    l.cost_basis_eur_total,
                    l.source_event_id,
                    e.tx_id
                from tax_lots l
                join canonical_events e on e.event_id = l.source_event_id
                join failed_tx f on f.tx_id = e.tx_id
                order by l.acquired_at, l.lot_id
                """
            ).fetchall(),
            [
                "lot_id",
                "asset",
                "acquired_at",
                "quantity_total",
                "quantity_remaining",
                "cost_basis_eur_total",
                "source_event_id",
                "tx_id",
            ],
        )
        unmatched = _rows_to_dicts(
            con.execute(
                """
                select
                    u.unmatched_id,
                    u.event_time,
                    u.event_type,
                    u.asset,
                    u.quantity,
                    u.missing_quantity,
                    u.source_event_id,
                    e.tx_id
                from tax_unmatched_disposals u
                join canonical_events e on e.event_id = u.source_event_id
                join failed_tx f on f.tx_id = e.tx_id
                order by u.event_time, u.unmatched_id
                """
            ).fetchall(),
            [
                "unmatched_id",
                "event_time",
                "event_type",
                "asset",
                "quantity",
                "missing_quantity",
                "source_event_id",
                "tx_id",
            ],
        )

    tax_lines_gain_loss_eur = sum(Decimal(str(row.get("gain_loss_eur") or "0")) for row in tax_lines)
    tax_lots_cost_basis_eur = sum(Decimal(str(row.get("cost_basis_eur_total") or "0")) for row in tax_lots)
    tax_impact_status = (
        "no_direct_tax_impact_detected"
        if not tax_lines and not tax_lots and not unmatched
        else "direct_tax_impact_needs_correction_review"
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_audit_path": str(audit_path),
        "failed_tx_count": len(failed_txids),
        "failed_tx_with_canonical_events_count": len(event_rows),
        "canonical_events_count": sum(int(row["canonical_events_count"] or 0) for row in event_rows),
        "event_status_counts": _count_by(event_rows, "event_types"),
        "asset_status_counts": _count_by(event_rows, "assets"),
        "tax_lines_count": len(tax_lines),
        "tax_lines_gain_loss_eur": tax_lines_gain_loss_eur,
        "tax_lots_count": len(tax_lots),
        "tax_lots_cost_basis_eur": tax_lots_cost_basis_eur,
        "unmatched_disposals_count": len(unmatched),
        "tax_impact_status": tax_impact_status,
        "event_summary": event_summary,
        "failed_tx_rows": event_rows,
        "tax_lines": tax_lines,
        "tax_lots": tax_lots,
        "unmatched_disposals": unmatched,
        "methodology": (
            "Read-only Steuerwirkungspruefung fuer Solana-TxIDs, die Alchemy mit meta.err "
            "als on-chain fehlgeschlagen bestaetigt hat. Geprueft wird, ob diese TxIDs "
            "direkt canonical_events, tax_lines, tax_lots oder tax_unmatched_disposals erzeugen. "
            "Der Report schreibt keine Datenbankwerte und trifft keine automatische Korrekturentscheidung."
        ),
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Tax-Impact-Pruefung fuer failed Solana TxIDs.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--audit", default=str(DEFAULT_AUDIT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    audit_path = Path(args.audit)
    result = build_report(DuckDbStore(args.db), audit_path)
    output_dir = Path(args.output_dir)
    run_id = datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"{run_id}_solana_failed_tx_tax_impact.json"
    latest_path = output_dir / "latest_solana_failed_tx_tax_impact.json"
    _write(output_path, result)
    _write(latest_path, result)
    print(
        f"wrote {output_path} status={result['tax_impact_status']} "
        f"failed_tx={result['failed_tx_count']} tax_lines={result['tax_lines_count']} "
        f"tax_lots={result['tax_lots_count']} unmatched={result['unmatched_disposals_count']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
