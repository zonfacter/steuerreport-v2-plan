#!/usr/bin/env python3
from __future__ import annotations

from steuerreport_v2.paths import PROJECT_ROOT as SOFTWARE_ROOT

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx

from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService
from steuerreport_v2.domain.tax_time import reporting_tax_year


PROJECT_ROOT = SOFTWARE_ROOT
DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var/solana_program_settlement_evidence"
DEFAULT_WALLET = WalletFifoPreviewService.PRIMARY_SOLANA_WALLET
DEFAULT_POOL_ID = f"solana_rpc:{DEFAULT_WALLET}"
LAMPORTS_PER_SOL = Decimal("1000000000")


def _account_keys(transaction: dict[str, Any]) -> list[str]:
    message = transaction.get("transaction", {}).get("message", {})
    keys = [
        str(item.get("pubkey")) if isinstance(item, dict) else str(item)
        for item in message.get("accountKeys", [])
    ]
    loaded = transaction.get("meta", {}).get("loadedAddresses") or {}
    keys.extend(str(item) for item in loaded.get("writable", []))
    keys.extend(str(item) for item in loaded.get("readonly", []))
    return keys


def _signers(transaction: dict[str, Any]) -> list[str]:
    message = transaction.get("transaction", {}).get("message", {})
    return [
        str(item.get("pubkey"))
        for item in message.get("accountKeys", [])
        if isinstance(item, dict) and item.get("signer") and item.get("pubkey")
    ]


def _program_ids(transaction: dict[str, Any]) -> list[str]:
    message = transaction.get("transaction", {}).get("message", {})
    meta = transaction.get("meta", {})
    keys = _account_keys(transaction)
    instructions: list[dict[str, Any]] = [
        item for item in message.get("instructions", []) if isinstance(item, dict)
    ]
    for inner in meta.get("innerInstructions") or []:
        instructions.extend(
            item for item in inner.get("instructions", []) if isinstance(item, dict)
        )
    values: set[str] = set()
    for instruction in instructions:
        program_id = instruction.get("programId")
        program_index = instruction.get("programIdIndex")
        if program_id:
            values.add(str(program_id))
        elif isinstance(program_index, int) and 0 <= program_index < len(keys):
            values.add(keys[program_index])
    return sorted(values)


def analyze_transaction(
    *,
    event_id: str,
    event_time: datetime,
    tx_id: str,
    wallet: str,
    quantity: Decimal,
    transaction: dict[str, Any],
) -> dict[str, Any]:
    meta = transaction.get("meta") or {}
    keys = _account_keys(transaction)
    pre_balances = list(meta.get("preBalances") or [])
    post_balances = list(meta.get("postBalances") or [])
    fee_lamports = int(meta.get("fee") or 0)
    expected_decimal = quantity * LAMPORTS_PER_SOL
    expected_lamports = int(expected_decimal)
    integer_lamports = Decimal(expected_lamports) == expected_decimal
    wallet_indexes = [index for index, address in enumerate(keys) if address == wallet]
    wallet_delta_lamports = sum(
        int(post_balances[index]) - int(pre_balances[index])
        for index in wallet_indexes
        if index < len(pre_balances) and index < len(post_balances)
    )
    closed_accounts = [
        {
            "address": keys[index] if index < len(keys) else None,
            "lamports": int(pre),
        }
        for index, (pre, post) in enumerate(zip(pre_balances, post_balances))
        if index not in wallet_indexes and int(pre) > 0 and int(post) == 0
    ]
    closed_lamports = sum(int(item["lamports"]) for item in closed_accounts)
    signers = _signers(transaction)
    wallet_is_signer = wallet in signers
    exact_lamport_reconciliation = (
        integer_lamports
        and expected_lamports > 0
        and wallet_delta_lamports + fee_lamports == expected_lamports
        and closed_lamports == expected_lamports
    )
    verified = bool(
        meta.get("err") is None
        and wallet_is_signer
        and closed_accounts
        and exact_lamport_reconciliation
    )
    return {
        "event_id": event_id,
        "event_time": (
            event_time.replace(tzinfo=timezone.utc)
            if event_time.tzinfo is None
            else event_time.astimezone(timezone.utc)
        ).isoformat(),
        "tx_id": tx_id,
        "wallet": wallet,
        "asset": "SOL",
        "quantity": str(quantity),
        "expected_gross_credit_lamports": expected_lamports,
        "wallet_delta_lamports": wallet_delta_lamports,
        "fee_lamports": fee_lamports,
        "closed_accounts_total_lamports": closed_lamports,
        "closed_accounts": closed_accounts,
        "wallet_is_signer": wallet_is_signer,
        "signers": signers,
        "program_ids": _program_ids(transaction),
        "transaction_succeeded": meta.get("err") is None,
        "exact_lamport_reconciliation": exact_lamport_reconciliation,
        "classification": (
            "owned_program_account_close_rent_return" if verified else "review_required"
        ),
        "evidence_source": "alchemy_getTransaction",
    }


def _semantic_sha256(records: list[dict[str, Any]]) -> str:
    payload = json.dumps(records, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def load_target_events(
    store: DuckDbStore,
    *,
    event_ids: list[str],
    year: int,
    wallet: str,
) -> list[CanonicalEvent]:
    requested_ids = list(dict.fromkeys(value.strip() for value in event_ids if value.strip()))
    if not requested_ids:
        return []
    placeholders = ", ".join("?" for _ in requested_ids)
    with store.connect() as con:
        rows = con.execute(
            f"""
            select
                event_id, source, source_ref, event_time, event_type,
                asset, quantity, quote_asset, quote_quantity,
                fee_asset, fee_quantity, tx_id, wallet, account,
                confidence, raw_object_id
            from canonical_events
            where event_id in ({placeholders})
            """,
            requested_ids,
        ).fetchall()
    events_by_id = {
        str(row[0]): CanonicalEvent(
            event_id=row[0],
            source=row[1],
            source_ref=row[2],
            event_time=row[3],
            event_type=row[4],
            asset=row[5],
            quantity=row[6],
            quote_asset=row[7],
            quote_quantity=row[8],
            fee_asset=row[9],
            fee_quantity=row[10],
            tx_id=row[11],
            wallet=row[12],
            account=row[13],
            confidence=row[14],
            raw_object_id=row[15],
        )
        for row in rows
    }
    missing_ids = [event_id for event_id in requested_ids if event_id not in events_by_id]
    if missing_ids:
        raise ValueError(f"target_event_not_found:{','.join(missing_ids)}")

    events = [events_by_id[event_id] for event_id in requested_ids]
    for event in events:
        event_wallet = str(event.account or event.wallet or "").strip()
        invalid_reasons: list[str] = []
        if event.source.strip().lower() != "solana_rpc":
            invalid_reasons.append("source_not_solana_rpc")
        if event.asset.upper() != "SOL":
            invalid_reasons.append("asset_not_sol")
        if event.quantity <= 0:
            invalid_reasons.append("quantity_not_positive")
        if event_wallet != wallet:
            invalid_reasons.append("wallet_mismatch")
        if reporting_tax_year(event.event_time) != year:
            invalid_reasons.append("reporting_year_mismatch")
        if not str(event.tx_id or "").strip():
            invalid_reasons.append("missing_tx_id")
        if invalid_reasons:
            raise ValueError(
                f"invalid_target_event:{event.event_id}:{','.join(invalid_reasons)}"
            )
    return events


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Alchemy audit for owned Solana program-account settlement credits."
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--wallet", default=DEFAULT_WALLET)
    parser.add_argument("--pool-id", default=DEFAULT_POOL_ID)
    parser.add_argument(
        "--event-id",
        action="append",
        default=[],
        help="Audit only this canonical event ID; may be supplied more than once.",
    )
    parser.add_argument("--max-events", type=int, default=100)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    store = DuckDbStore(args.db)
    service = WalletFifoPreviewService(
        store,
        program_settlement_evidence_dir=args.output_dir / ".resolver_input_disabled",
    )
    api_key = service._alchemy_api_key()
    if not api_key:
        raise SystemExit("alchemy_api_key_missing")
    if args.event_id:
        events: list[Any] = load_target_events(
            store,
            event_ids=args.event_id,
            year=args.year,
            wallet=args.wallet,
        )
    else:
        report = service.provenance_events(
            args.year,
            asset="SOL",
            pool_id=args.pool_id,
            offset=0,
            limit=max(1, min(args.max_events, 1000)),
        )
        events = list(report.events)
    records: list[dict[str, Any]] = []
    rpc_errors: list[dict[str, str]] = []
    url = f"https://solana-mainnet.g.alchemy.com/v2/{api_key}"
    with httpx.Client(timeout=max(5, min(args.timeout_seconds, 60))) as client:
        for event in events:
            tx_id = str(getattr(event, "onchain_tx_id", None) or event.tx_id or "")
            if not tx_id:
                rpc_errors.append({"event_id": event.event_id, "error": "missing_tx_id"})
                continue
            try:
                response = client.post(
                    url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getTransaction",
                        "params": [
                            tx_id,
                            {
                                "encoding": "jsonParsed",
                                "maxSupportedTransactionVersion": 0,
                                "commitment": "finalized",
                            },
                        ],
                    },
                )
                response.raise_for_status()
                transaction = response.json().get("result")
                if not isinstance(transaction, dict):
                    raise ValueError("transaction_not_found")
                records.append(
                    analyze_transaction(
                        event_id=event.event_id,
                        event_time=event.event_time,
                        tx_id=tx_id,
                        wallet=args.wallet,
                        quantity=event.quantity,
                        transaction=transaction,
                    )
                )
            except Exception as exc:
                rpc_errors.append({"event_id": event.event_id, "tx_id": tx_id, "error": str(exc)})

    verified_count = sum(
        1
        for record in records
        if record["classification"] == "owned_program_account_close_rent_return"
    )
    generated_at = datetime.now(timezone.utc)
    payload = {
        "generated_at": generated_at.isoformat(),
        "year": args.year,
        "asset": "SOL",
        "wallet": args.wallet,
        "pool_id": args.pool_id,
        "provider": "alchemy_admin_secret",
        "records_count": len(records),
        "verified_count": verified_count,
        "review_count": len(records) - verified_count,
        "failed_count": len(rpc_errors),
        "semantic_sha256": _semantic_sha256(records),
        "records": records,
        "rpc_errors": rpc_errors,
        "methodology": (
            "Read-only Nachweis fuer native SOL-Rueckfluesse aus in derselben, von der "
            "eigenen Wallet signierten Transaktion geschlossenen Programmkonten. Freigabe "
            "nur bei exakter Lamport-Gleichheit: geschlossene Konten = Wallet-Delta + Fee "
            "= kanonische Bruttomenge. Keine Imports, Lots, Tax-Lines oder Ledgeraenderung."
        ),
    }
    timestamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    run_path = args.output_dir / f"{timestamp}_{args.year}_SOL_program_settlement_evidence.json"
    latest_path = args.output_dir / f"latest_{args.year}_SOL_program_settlement_evidence.json"
    _write_json(run_path, payload)
    _write_json(latest_path, payload)
    print(
        json.dumps(
            {
                "artifact_path": str(run_path),
                "latest_path": str(latest_path),
                "records_count": len(records),
                "verified_count": verified_count,
                "review_count": len(records) - verified_count,
                "failed_count": len(rpc_errors),
                "semantic_sha256": payload["semantic_sha256"],
            },
            indent=2,
        )
    )
    return 0 if not rpc_errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
