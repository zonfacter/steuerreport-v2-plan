#!/usr/bin/env python3
from __future__ import annotations

from steuerreport_v2.paths import PROJECT_ROOT as SOFTWARE_ROOT

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from steuerreport_v2.db.duckdb_store import DuckDbStore


PROJECT_ROOT = SOFTWARE_ROOT
DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_MATRIX = PROJECT_ROOT / "var" / "all_transaction_evidence_matrices" / "latest_all_transaction_evidence_matrix.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var" / "all_transaction_evidence_closures"
NEEDS_REVIEW_STATUSES = {
    "cex_onchain_txid_found_ledger_match_needed",
    "account_not_seen_in_alchemy_tx",
    "solana_signature_missing_alchemy_audit",
    "solana_onchain_review_needed",
    "timestamp_mismatch",
    "internal_id_review_path",
}


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _load_matrix(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("matrix_must_be_json_object")
    return payload


def _fetch_tax_impacts(store: DuckDbStore, txids: list[str]) -> dict[str, dict[str, Any]]:
    if not txids:
        return {}
    with store.connect() as con:
        con.execute("create temp table review_tx(tx_id varchar)")
        con.executemany("insert into review_tx values (?)", [(txid,) for txid in txids])
        event_rows = con.execute(
            """
            select
                e.tx_id,
                count(*)::integer as canonical_events_count,
                sum(abs(e.quantity)) as gross_quantity
            from canonical_events e
            join review_tx r on r.tx_id = e.tx_id
            group by e.tx_id
            """
        ).fetchall()
        line_rows = con.execute(
            """
            select
                e.tx_id,
                count(*)::integer as tax_lines_count,
                coalesce(sum(l.gain_loss_eur), 0) as tax_lines_gain_loss_eur
            from tax_lines l
            join canonical_events e on e.event_id = l.source_event_id
            join review_tx r on r.tx_id = e.tx_id
            group by e.tx_id
            """
        ).fetchall()
        lot_rows = con.execute(
            """
            select
                e.tx_id,
                count(*)::integer as tax_lots_count,
                coalesce(sum(l.cost_basis_eur_total), 0) as tax_lots_cost_basis_eur
            from tax_lots l
            join canonical_events e on e.event_id = l.source_event_id
            join review_tx r on r.tx_id = e.tx_id
            group by e.tx_id
            """
        ).fetchall()
        unmatched_rows = con.execute(
            """
            select
                e.tx_id,
                count(*)::integer as unmatched_disposals_count,
                coalesce(sum(u.missing_quantity), 0) as unmatched_missing_quantity
            from tax_unmatched_disposals u
            join canonical_events e on e.event_id = u.source_event_id
            join review_tx r on r.tx_id = e.tx_id
            group by e.tx_id
            """
        ).fetchall()

    impacts = {
        txid: {
            "canonical_events_count": 0,
            "gross_quantity": Decimal("0"),
            "tax_lines_count": 0,
            "tax_lines_gain_loss_eur": Decimal("0"),
            "tax_lots_count": 0,
            "tax_lots_cost_basis_eur": Decimal("0"),
            "unmatched_disposals_count": 0,
            "unmatched_missing_quantity": Decimal("0"),
        }
        for txid in txids
    }
    for tx_id, count, gross in event_rows:
        impacts[str(tx_id)]["canonical_events_count"] = int(count or 0)
        impacts[str(tx_id)]["gross_quantity"] = gross or Decimal("0")
    for tx_id, count, gain_loss in line_rows:
        impacts[str(tx_id)]["tax_lines_count"] = int(count or 0)
        impacts[str(tx_id)]["tax_lines_gain_loss_eur"] = gain_loss or Decimal("0")
    for tx_id, count, cost_basis in lot_rows:
        impacts[str(tx_id)]["tax_lots_count"] = int(count or 0)
        impacts[str(tx_id)]["tax_lots_cost_basis_eur"] = cost_basis or Decimal("0")
    for tx_id, count, missing in unmatched_rows:
        impacts[str(tx_id)]["unmatched_disposals_count"] = int(count or 0)
        impacts[str(tx_id)]["unmatched_missing_quantity"] = missing or Decimal("0")
    return impacts


def _next_action(row: dict[str, Any], impact: dict[str, Any]) -> str:
    status = str(row.get("review_status") or "")
    if impact.get("tax_lines_count") or impact.get("tax_lots_count") or impact.get("unmatched_disposals_count"):
        return "tax_impact_review_before_export"
    if status == "cex_onchain_txid_found_ledger_match_needed":
        return "match_cex_ledger_timestamp_amount_and_direction"
    if status == "account_not_seen_in_alchemy_tx":
        return "inspect_onchain_route_owner_signer_and_service_program"
    if status == "solana_signature_missing_alchemy_audit":
        return "rerun_alchemy_audit_for_signature"
    return "manual_review"


def build_report(store: DuckDbStore, matrix_path: Path) -> dict[str, Any]:
    matrix = _load_matrix(matrix_path)
    rows = [row for row in matrix.get("rows", []) if isinstance(row, dict)]
    review_rows = [row for row in rows if str(row.get("review_status") or "") in NEEDS_REVIEW_STATUSES]
    review_txids = [str(row["tx_id"]) for row in review_rows if row.get("tx_id")]
    impacts = _fetch_tax_impacts(store, review_txids)
    enriched_review_rows: list[dict[str, Any]] = []
    for row in review_rows:
        tx_id = str(row.get("tx_id") or "")
        impact = impacts.get(tx_id, {})
        enriched_review_rows.append(
            {
                **row,
                **impact,
                "next_action": _next_action(row, impact),
                "tax_impact_detected": bool(
                    impact.get("tax_lines_count")
                    or impact.get("tax_lots_count")
                    or impact.get("unmatched_disposals_count")
                ),
            }
        )
    review_status_counts = Counter(str(row.get("review_status") or "unknown") for row in enriched_review_rows)
    next_action_counts = Counter(str(row.get("next_action") or "unknown") for row in enriched_review_rows)
    tax_impact_review_count = sum(1 for row in enriched_review_rows if row.get("tax_impact_detected"))
    tx_count = int(matrix.get("tx_count") or len(rows))
    review_count = len(enriched_review_rows)
    assigned_count = max(0, tx_count - review_count)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "matrix_path": str(matrix_path),
        "tx_count": tx_count,
        "evidence_path_assigned_count": assigned_count,
        "needs_review_count": review_count,
        "tax_impact_review_count": tax_impact_review_count,
        "closure_ratio": (assigned_count / tx_count) if tx_count else 0,
        "review_status_counts": dict(review_status_counts),
        "next_action_counts": dict(next_action_counts),
        "open_rows": enriched_review_rows,
        "methodology": (
            "Read-only Abschlussreport auf Basis der Gesamt-Transaktions-Belegmatrix. "
            "Alle Transaktionen mit bereits zugeordnetem Belegpfad gelten als evidence_path_assigned, "
            "nicht automatisch als steuerlich final geprueft. Offene Rows werden gegen tax_lines, "
            "tax_lots und tax_unmatched_disposals geprueft und erhalten eine konkrete Next Action. "
            "Der Report schreibt keine Steuerdaten."
        ),
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Abschlussreport fuer alle lokalen Transaktions-IDs.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--matrix", default=str(DEFAULT_MATRIX))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    result = build_report(DuckDbStore(args.db), Path(args.matrix))
    output_dir = Path(args.output_dir)
    run_id = datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"{run_id}_all_transaction_evidence_closure.json"
    latest_path = output_dir / "latest_all_transaction_evidence_closure.json"
    _write(output_path, result)
    _write(latest_path, result)
    print(
        f"wrote {output_path} tx_count={result['tx_count']} assigned={result['evidence_path_assigned_count']} "
        f"needs_review={result['needs_review_count']} tax_impact_review={result['tax_impact_review_count']}",
        flush=True,
    )
    print(f"next_action_counts={result['next_action_counts']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
