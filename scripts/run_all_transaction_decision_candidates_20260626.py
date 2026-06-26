#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_DETAIL = PROJECT_ROOT / "var" / "all_transaction_open_detail_reviews" / "latest_all_transaction_open_detail_review.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var" / "all_transaction_decision_candidates"
BINANCE_DEPOSIT_ADDRESS = "Ftf2dgeRpBrPFmbd4wQWWqSjCmRjGes1GzNXtxKETeLW"
OWN_SOLANA_WALLETS = {
    "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY": "Main Solana Wallet",
    "4dCdKKXm1aHzMLFHFz7Cyn6CA14RK7WdYKeAGrHx4fod": "JUP Wallet",
}
KNOWN_INFRASTRUCTURE = {
    "3wUnjrkdLcXARm51UmsPNAn43bh5zAB7MDv28C2MHNfr": "Bitget Exchange",
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9": "Binance Hot Wallet",
}


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _load_detail(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("detail_review_must_be_json_object")
    return payload


def _raw_payload(row: dict[str, Any]) -> dict[str, Any]:
    raw_rows = row.get("raw_rows") if isinstance(row.get("raw_rows"), list) else []
    if not raw_rows:
        return {}
    preview = str((raw_rows[0] or {}).get("payload_preview") or "")
    if not preview:
        return {}
    try:
        return json.loads(preview)
    except Exception:
        return {}


def _matching_token_delta(row: dict[str, Any], owner: str, asset: str) -> Decimal:
    total = Decimal("0")
    for item in row.get("token_deltas") if isinstance(row.get("token_deltas"), list) else []:
        if str(item.get("owner") or "") != owner:
            continue
        if asset.upper() == "USDC" and str(item.get("asset_hint") or "").upper() == "USDC":
            total += _decimal(item.get("delta"))
        elif str(item.get("asset_hint") or "").upper() == asset.upper():
            total += _decimal(item.get("delta"))
    return total


def _decision_candidate(row: dict[str, Any]) -> dict[str, Any]:
    raw = _raw_payload(row)
    classification = str(row.get("detail_classification") or "")
    tx_id = str(row.get("tx_id") or "")
    sources = str(row.get("sources") or "")
    signers = [str(item) for item in row.get("signers", []) if item]
    amount = _decimal(raw.get("Amount") or raw.get("amount") or row.get("gross_quantity"))
    asset = str(raw.get("Coin") or raw.get("asset") or row.get("assets") or "").upper()
    raw_address = str(raw.get("Address") or raw.get("address") or "")
    raw_status = str(raw.get("Status") or raw.get("status") or "")

    base = {
        "tx_id": tx_id,
        "year": row.get("year"),
        "sources": sources,
        "asset": asset,
        "amount": amount,
        "first_event_time": row.get("first_event_time"),
        "block_time_utc": row.get("block_time_utc"),
        "detail_classification": classification,
        "tax_impact_detected": bool(row.get("tax_impact_detected")),
        "raw_address": raw_address,
        "raw_status": raw_status,
        "signers": signers,
        "known_signers": {signer: KNOWN_INFRASTRUCTURE[signer] for signer in signers if signer in KNOWN_INFRASTRUCTURE},
        "decision_payload": {},
    }

    if classification == "cex_ledger_match_required" and sources == "binance":
        completed = raw_status.lower() == "completed"
        deposit_address_matches = raw_address == BINANCE_DEPOSIT_ADDRESS
        if completed and deposit_address_matches and not row.get("tax_impact_detected"):
            return {
                **base,
                "candidate_status": "cex_deposit_ledger_onchain_evidence_ready",
                "recommended_tax_treatment": "Transfer / Uebertrag nur nach Eigentums-/Senderabgleich; noch keine steuerpflichtige Veraeusserung.",
                "manual_decision_safe": False,
                "next_action": "link_with_source_wallet_or_exchange_withdrawal_before_fifo_carry",
                "decision_payload": {
                    "cex": "binance",
                    "deposit_address": raw_address,
                    "deposit_txid": tx_id,
                    "amount": str(amount),
                    "asset": asset,
                    "ledger_status": raw_status,
                    "onchain_found": True,
                    "tax_impact_detected": False,
                },
            }
    if classification == "cex_ledger_match_required" and sources == "binance_withdrawal_api":
        target_is_owned = raw_address in OWN_SOLANA_WALLETS
        return {
            **base,
            "candidate_status": "cex_withdrawal_to_owned_wallet_evidence_ready" if target_is_owned else "cex_withdrawal_target_review_needed",
            "recommended_tax_treatment": (
                "Transfer / Uebertrag von Binance zur eigenen Wallet; FIFO-Carry moeglich, wenn Quelle Binance-Bestand belegt ist."
                if target_is_owned
                else "Withdrawal-Zieladresse fachlich pruefen."
            ),
            "manual_decision_safe": bool(target_is_owned and not row.get("tax_impact_detected")),
            "next_action": "link_binance_source_lot_before_fifo_carry" if target_is_owned else "verify_withdrawal_target_owner",
            "decision_payload": {
                "cex": "binance",
                "withdrawal_address": raw_address,
                "withdrawal_txid": tx_id,
                "amount": str(raw.get("amount") or amount),
                "gross_amount": str(raw.get("gross_amount") or ""),
                "fee": str(raw.get("transaction_fee") or ""),
                "asset": asset,
                "target_wallet_label": OWN_SOLANA_WALLETS.get(raw_address),
                "tax_impact_detected": False,
            },
        }
    if classification == "route_or_account_owner_review_required":
        return {
            **base,
            "candidate_status": "zero_quantity_perp_route_no_tax_impact",
            "recommended_tax_treatment": "Keine direkte Steuerwirkung erkannt; als Route-/Programmaudit-Beleg dokumentieren, nicht als Transfer/Income buchen.",
            "manual_decision_safe": True,
            "next_action": "document_zero_quantity_program_route",
            "decision_payload": {
                "program_ids": row.get("program_ids", []),
                "gross_quantity": str(row.get("gross_quantity") or "0"),
                "tax_impact_detected": False,
            },
        }
    if classification == "owner_delta_without_local_signer_tax_review":
        owner = str(row.get("accounts") or "")
        local_delta = _matching_token_delta(row, owner, asset)
        return {
            **base,
            "candidate_status": "external_token_inflow_tax_review_required",
            "recommended_tax_treatment": "Externer Zufluss auf eigene Wallet; steuerlich offen, nicht als interner Transfer/FIFO-Carry schliessen.",
            "manual_decision_safe": False,
            "next_action": "identify_sender_relationship_and_reason_for_payment",
            "decision_payload": {
                "owner_wallet": owner,
                "owner_wallet_label": OWN_SOLANA_WALLETS.get(owner),
                "local_token_delta": str(local_delta),
                "external_signers": signers,
                "tax_lots_count": row.get("tax_lots_count"),
                "tax_lots_cost_basis_eur": row.get("tax_lots_cost_basis_eur"),
            },
        }
    return {
        **base,
        "candidate_status": "manual_review_required",
        "recommended_tax_treatment": "Fachliche Einzelpruefung erforderlich.",
        "manual_decision_safe": False,
        "next_action": "manual_review",
    }


def build_report(detail_path: Path) -> dict[str, Any]:
    detail = _load_detail(detail_path)
    rows = [row for row in detail.get("rows", []) if isinstance(row, dict)]
    candidates = [_decision_candidate(row) for row in rows]
    status_counts = Counter(str(row.get("candidate_status") or "unknown") for row in candidates)
    safe_count = sum(1 for row in candidates if row.get("manual_decision_safe") is True)
    tax_review_count = sum(1 for row in candidates if row.get("candidate_status") == "external_token_inflow_tax_review_required")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "detail_review_path": str(detail_path),
        "open_tx_count": len(candidates),
        "manual_decision_safe_count": safe_count,
        "tax_review_required_count": tax_review_count,
        "candidate_status_counts": dict(status_counts),
        "rows": candidates,
        "methodology": (
            "Read-only Entscheidungskandidaten auf Basis des offenen Detailreviews. "
            "Der Report erzeugt keine Review-Decisions und schreibt keine Steuerdaten. "
            "manual_decision_safe bedeutet nur: dokumentarisch plausibel ohne direkte Steuerwirkung; "
            "steuerliche Finalisierung bleibt ein separater, bewusster Schritt."
        ),
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Entscheidungskandidaten fuer offene Transaktionen.")
    parser.add_argument("--detail-review", default=str(DEFAULT_DETAIL))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()
    result = build_report(Path(args.detail_review))
    output_dir = Path(args.output_dir)
    run_id = datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"{run_id}_all_transaction_decision_candidates.json"
    latest_path = output_dir / "latest_all_transaction_decision_candidates.json"
    _write(output_path, result)
    _write(latest_path, result)
    print(
        f"wrote {output_path} open_tx={result['open_tx_count']} "
        f"safe={result['manual_decision_safe_count']} tax_review={result['tax_review_required_count']} "
        f"statuses={result['candidate_status_counts']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
