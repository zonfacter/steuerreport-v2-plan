#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from steuerreport_v2.db.duckdb_store import DuckDbStore


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_ALCHEMY_AUDIT = PROJECT_ROOT / "var" / "solana_tx_alchemy_audits" / "latest_all_tx_alchemy_audit.json"
DEFAULT_FAILED_IMPACT = PROJECT_ROOT / "var" / "solana_failed_tx_tax_impacts" / "latest_solana_failed_tx_tax_impact.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var" / "all_transaction_evidence_matrices"
SOLANA_BASE58_ALPHABET = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _is_plausible_solana_signature(value: object) -> bool:
    text = str(value or "")
    return 64 <= len(text) <= 90 and all(char in SOLANA_BASE58_ALPHABET for char in text)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _evidence_class(source: str, tx_id: str) -> str:
    normalized = source.lower()
    if _is_plausible_solana_signature(tx_id):
        return "solana_onchain_signature"
    if normalized == "helium":
        return "legacy_helium_chain"
    if normalized.startswith(("binance", "bitget", "pionex")):
        return "cex_or_platform_ledger_id"
    if normalized.startswith("opening-balance"):
        return "opening_balance_without_txid"
    if normalized == "manual-csv" or tx_id.startswith("manual-"):
        return "manual_evidence_id"
    return "other_internal_id"


def _review_status(
    *,
    evidence_class: str,
    sources: str,
    alchemy_row: dict[str, Any] | None,
    failed_impact_status: str,
) -> str:
    if evidence_class == "solana_onchain_signature":
        if not alchemy_row:
            return "solana_signature_missing_alchemy_audit"
        status = str(alchemy_row.get("review_status") or "")
        if status == "alchemy_confirmed":
            return "onchain_confirmed"
        if status == "onchain_transaction_failed" and failed_impact_status == "no_direct_tax_impact_detected":
            return "onchain_failed_no_direct_tax_impact"
        if status in {"timestamp_mismatch", "account_not_seen_in_alchemy_tx"} and any(
            item in sources.lower() for item in ("binance", "bitget", "pionex")
        ):
            return "cex_onchain_txid_found_ledger_match_needed"
        return status or "solana_onchain_review_needed"
    if evidence_class == "legacy_helium_chain":
        return "legacy_helium_evidence_path"
    if evidence_class == "cex_or_platform_ledger_id":
        return "cex_ledger_evidence_path"
    if evidence_class == "manual_evidence_id":
        return "manual_evidence_path"
    if evidence_class == "opening_balance_without_txid":
        return "opening_balance_evidence_path"
    return "internal_id_review_path"


def build_matrix(store: DuckDbStore, *, alchemy_audit_path: Path, failed_impact_path: Path) -> dict[str, Any]:
    alchemy_payload = _load_json(alchemy_audit_path)
    failed_impact_payload = _load_json(failed_impact_path)
    failed_impact_status = str(failed_impact_payload.get("tax_impact_status") or "")
    alchemy_by_tx = {
        str(row.get("tx_id")): row
        for row in alchemy_payload.get("rows", [])
        if isinstance(row, dict) and row.get("tx_id")
    }

    with store.connect() as con:
        rows = con.execute(
            """
            select
                tx_id,
                min(event_time) as first_event_time,
                max(event_time) as last_event_time,
                string_agg(distinct source, ', ' order by source) as sources,
                string_agg(distinct event_type, ', ' order by event_type) as event_types,
                string_agg(distinct upper(asset), ', ' order by upper(asset)) as assets,
                string_agg(distinct coalesce(account, wallet, ''), ', ' order by coalesce(account, wallet, '')) as accounts,
                count(*)::integer as canonical_events_count,
                sum(abs(quantity)) as gross_quantity
            from canonical_events
            where tx_id is not null and trim(tx_id) <> ''
            group by tx_id
            order by min(event_time), tx_id
            """
        ).fetchall()

    matrix_rows: list[dict[str, Any]] = []
    for row in rows:
        tx_id = str(row[0])
        sources = str(row[3] or "")
        first_source = sources.split(", ", 1)[0]
        evidence_class = _evidence_class(first_source, tx_id)
        alchemy_row = alchemy_by_tx.get(tx_id)
        matrix_rows.append(
            {
                "tx_id": tx_id,
                "first_event_time": row[1],
                "last_event_time": row[2],
                "year": int(row[1].year) if isinstance(row[1], datetime) else None,
                "sources": sources,
                "event_types": str(row[4] or ""),
                "assets": str(row[5] or ""),
                "accounts": str(row[6] or ""),
                "canonical_events_count": int(row[7] or 0),
                "gross_quantity": row[8] or Decimal("0"),
                "evidence_class": evidence_class,
                "review_status": _review_status(
                    evidence_class=evidence_class,
                    sources=sources,
                    alchemy_row=alchemy_row,
                    failed_impact_status=failed_impact_status,
                ),
                "alchemy_status": alchemy_row.get("alchemy_status") if alchemy_row else None,
                "alchemy_review_status": alchemy_row.get("review_status") if alchemy_row else None,
                "onchain_time_utc": alchemy_row.get("onchain_time_utc") if alchemy_row else None,
            }
        )

    class_counts = Counter(str(row["evidence_class"]) for row in matrix_rows)
    review_counts = Counter(str(row["review_status"]) for row in matrix_rows)
    source_counts = Counter()
    for row in matrix_rows:
        for source in str(row["sources"]).split(", "):
            if source:
                source_counts[source] += 1
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tx_count": len(matrix_rows),
        "canonical_events_count": sum(int(row["canonical_events_count"]) for row in matrix_rows),
        "alchemy_audit_path": str(alchemy_audit_path),
        "failed_tx_tax_impact_path": str(failed_impact_path),
        "evidence_class_counts": dict(class_counts),
        "review_status_counts": dict(review_counts),
        "source_tx_counts": dict(source_counts),
        "solana_signature_count": class_counts.get("solana_onchain_signature", 0),
        "non_solana_txid_count": len(matrix_rows) - class_counts.get("solana_onchain_signature", 0),
        "rows": matrix_rows,
        "methodology": (
            "Read-only Gesamtmatrix ueber alle lokalen canonical_events.tx_id Werte. "
            "Echte Solana-Signaturen werden gegen den Alchemy-Audit gemappt; Legacy-Helium-, "
            "CEX-/Plattform- und manuelle IDs werden bewusst als andere Belegpfade klassifiziert. "
            "Der Report schreibt keine Steuerdaten und ersetzt keine CEX-Ledger- oder Legacy-Belege."
        ),
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Gesamtmatrix fuer alle lokalen Transaktions-IDs.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--alchemy-audit", default=str(DEFAULT_ALCHEMY_AUDIT))
    parser.add_argument("--failed-impact", default=str(DEFAULT_FAILED_IMPACT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    result = build_matrix(
        DuckDbStore(args.db),
        alchemy_audit_path=Path(args.alchemy_audit),
        failed_impact_path=Path(args.failed_impact),
    )
    output_dir = Path(args.output_dir)
    run_id = datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"{run_id}_all_transaction_evidence_matrix.json"
    latest_path = output_dir / "latest_all_transaction_evidence_matrix.json"
    _write(output_path, result)
    _write(latest_path, result)
    print(
        f"wrote {output_path} tx_count={result['tx_count']} "
        f"solana={result['solana_signature_count']} non_solana={result['non_solana_txid_count']}",
        flush=True,
    )
    print(f"review_status_counts={result['review_status_counts']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
