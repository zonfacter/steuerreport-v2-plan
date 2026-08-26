#!/usr/bin/env python3
from __future__ import annotations

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
from steuerreport_v2.domain.tax_time import reporting_tax_year
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var/solana_service_swap_evidence"
DEFAULT_WALLET = WalletFifoPreviewService.PRIMARY_SOLANA_WALLET
JUPITER_V6_PROGRAM = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
LAMPORTS_PER_SOL = Decimal("1000000000")


def _event_from_row(row: tuple[Any, ...]) -> CanonicalEvent:
    return CanonicalEvent(
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


def load_route_events(
    store: DuckDbStore,
    *,
    source_event_id: str,
    funding_event_id: str,
    deposit_event_id: str,
    year: int,
    wallet: str,
) -> tuple[CanonicalEvent, CanonicalEvent, CanonicalEvent, dict[str, Any]]:
    requested_ids = [source_event_id, funding_event_id, deposit_event_id]
    if len(set(requested_ids)) != len(requested_ids) or any(
        not value for value in requested_ids
    ):
        raise ValueError("route_event_ids_must_be_unique_and_nonempty")
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
        events_by_id = {str(row[0]): _event_from_row(row) for row in rows}
        missing_ids = [
            event_id for event_id in requested_ids if event_id not in events_by_id
        ]
        if missing_ids:
            raise ValueError(f"route_event_not_found:{','.join(missing_ids)}")
        deposit_event = events_by_id[deposit_event_id]
        raw_payload: dict[str, Any] = {}
        if deposit_event.raw_object_id:
            raw_row = con.execute(
                "select payload_json from raw_objects where raw_object_id = ?",
                [deposit_event.raw_object_id],
            ).fetchone()
            if raw_row and raw_row[0]:
                parsed = json.loads(str(raw_row[0]))
                if isinstance(parsed, dict):
                    raw_payload = parsed

    source_event = events_by_id[source_event_id]
    funding_event = events_by_id[funding_event_id]
    deposit_event = events_by_id[deposit_event_id]
    errors: list[str] = []
    for label, event in (
        ("source", source_event),
        ("funding", funding_event),
        ("deposit", deposit_event),
    ):
        if reporting_tax_year(event.event_time) != year:
            errors.append(f"{label}_reporting_year_mismatch")
        if not str(event.tx_id or "").strip():
            errors.append(f"{label}_missing_tx_id")
    if source_event.source.lower() != "solana_rpc" or source_event.quantity >= 0:
        errors.append("invalid_source_outflow")
    if str(source_event.account or source_event.wallet or "") != wallet:
        errors.append("source_wallet_mismatch")
    if funding_event.source.lower() != "solana_rpc" or funding_event.quantity >= 0:
        errors.append("invalid_funding_outflow")
    if funding_event.asset.upper() != "SOL":
        errors.append("funding_asset_not_sol")
    if str(funding_event.account or funding_event.wallet or "") != wallet:
        errors.append("funding_wallet_mismatch")
    if deposit_event.source.lower() not in {"binance", "bitget", "pionex"}:
        errors.append("deposit_source_not_supported_cex")
    if deposit_event.event_type != "transfer" or deposit_event.quantity <= 0:
        errors.append("invalid_cex_deposit")
    if errors:
        raise ValueError(f"invalid_route_events:{','.join(errors)}")
    return source_event, funding_event, deposit_event, raw_payload


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


def _instructions(transaction: dict[str, Any]) -> list[dict[str, Any]]:
    message = transaction.get("transaction", {}).get("message", {})
    meta = transaction.get("meta") or {}
    result = [
        item for item in message.get("instructions", []) if isinstance(item, dict)
    ]
    for inner in meta.get("innerInstructions") or []:
        result.extend(
            item for item in inner.get("instructions", []) if isinstance(item, dict)
        )
    return result


def _program_ids(transaction: dict[str, Any]) -> list[str]:
    keys = _account_keys(transaction)
    values: set[str] = set()
    for instruction in _instructions(transaction):
        program_id = instruction.get("programId")
        program_index = instruction.get("programIdIndex")
        if program_id:
            values.add(str(program_id))
        elif isinstance(program_index, int) and 0 <= program_index < len(keys):
            values.add(keys[program_index])
    return sorted(values)


def _native_delta_lamports(transaction: dict[str, Any], address: str) -> int | None:
    keys = _account_keys(transaction)
    meta = transaction.get("meta") or {}
    pre_balances = list(meta.get("preBalances") or [])
    post_balances = list(meta.get("postBalances") or [])
    indexes = [index for index, key in enumerate(keys) if key == address]
    if not indexes:
        return None
    return sum(
        int(post_balances[index]) - int(pre_balances[index])
        for index in indexes
        if index < len(pre_balances) and index < len(post_balances)
    )


def _native_balance_lamports(
    transaction: dict[str, Any], address: str, *, after: bool
) -> int | None:
    keys = _account_keys(transaction)
    meta = transaction.get("meta") or {}
    balances = list(
        meta.get("postBalances" if after else "preBalances") or []
    )
    indexes = [index for index, key in enumerate(keys) if key == address]
    if not indexes:
        return None
    return sum(balances[index] for index in indexes if index < len(balances))


def _block_time(transaction: dict[str, Any]) -> datetime | None:
    value = transaction.get("blockTime")
    if not isinstance(value, int):
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)


def _token_owner_deltas(
    transaction: dict[str, Any],
) -> dict[tuple[str, str], Decimal]:
    meta = transaction.get("meta") or {}
    result: dict[tuple[str, str], Decimal] = {}
    for multiplier, balances in (
        (Decimal("-1"), meta.get("preTokenBalances") or []),
        (Decimal("1"), meta.get("postTokenBalances") or []),
    ):
        for balance in balances:
            owner = str(balance.get("owner") or "")
            mint = str(balance.get("mint") or "")
            amount = balance.get("uiTokenAmount") or {}
            quantity = Decimal(str(amount.get("uiAmountString") or "0"))
            key = (owner, mint)
            result[key] = result.get(key, Decimal("0")) + multiplier * quantity
    return result


def _native_transfers(transaction: dict[str, Any]) -> list[dict[str, Any]]:
    transfers: list[dict[str, Any]] = []
    for instruction in _instructions(transaction):
        parsed = instruction.get("parsed")
        if instruction.get("program") != "system" or not isinstance(parsed, dict):
            continue
        if parsed.get("type") != "transfer":
            continue
        info = parsed.get("info") or {}
        transfers.append(
            {
                "source": str(info.get("source") or ""),
                "destination": str(info.get("destination") or ""),
                "lamports": int(info.get("lamports") or 0),
            }
        )
    return transfers


def analyze_route(
    *,
    source_event: CanonicalEvent,
    funding_event: CanonicalEvent,
    deposit_event: CanonicalEvent,
    deposit_raw_payload: dict[str, Any],
    wallet: str,
    route_wallet: str,
    swap_tx_id: str,
    source_transaction: dict[str, Any],
    funding_transaction: dict[str, Any],
    swap_transaction: dict[str, Any],
    deposit_transaction: dict[str, Any],
) -> dict[str, Any]:
    source_quantity = abs(source_event.quantity)
    source_deltas = _token_owner_deltas(source_transaction)
    matching_mints = sorted(
        mint
        for (owner, mint), quantity in source_deltas.items()
        if owner == wallet
        and quantity == -source_quantity
        and source_deltas.get((route_wallet, mint)) == source_quantity
    )
    source_mint = matching_mints[0] if len(matching_mints) == 1 else None

    funding_fee_quantity = (
        abs(funding_event.fee_quantity or Decimal("0"))
        if str(funding_event.fee_asset or "").upper() == "SOL"
        else Decimal("0")
    )
    expected_funding_lamports_decimal = (
        abs(funding_event.quantity) - funding_fee_quantity
    ) * LAMPORTS_PER_SOL
    expected_funding_lamports = int(expected_funding_lamports_decimal)
    funding_integer_lamports = (
        Decimal(expected_funding_lamports) == expected_funding_lamports_decimal
    )
    funding_matches = [
        transfer
        for transfer in _native_transfers(funding_transaction)
        if transfer["source"] == wallet
        and transfer["destination"] == route_wallet
        and transfer["lamports"] == expected_funding_lamports
    ]

    swap_deltas = _token_owner_deltas(swap_transaction)
    swap_input_quantity = (
        abs(swap_deltas.get((route_wallet, source_mint), Decimal("0")))
        if source_mint
        else Decimal("0")
    )
    swap_fee_lamports = int((swap_transaction.get("meta") or {}).get("fee") or 0)
    swap_native_delta_lamports = _native_delta_lamports(swap_transaction, route_wallet)
    swap_output_lamports = (
        swap_native_delta_lamports + swap_fee_lamports
        if swap_native_delta_lamports is not None
        else 0
    )

    deposit_address = str(
        deposit_raw_payload.get("Address") or deposit_raw_payload.get("address") or ""
    ).strip()
    expected_deposit_lamports_decimal = deposit_event.quantity * LAMPORTS_PER_SOL
    expected_deposit_lamports = int(expected_deposit_lamports_decimal)
    deposit_integer_lamports = (
        Decimal(expected_deposit_lamports) == expected_deposit_lamports_decimal
    )
    deposit_matches = [
        transfer
        for transfer in _native_transfers(deposit_transaction)
        if transfer["source"] == route_wallet
        and transfer["destination"] == deposit_address
        and transfer["lamports"] == expected_deposit_lamports
    ]

    source_network_fee_lamports = int(
        (source_transaction.get("meta") or {}).get("fee") or 0
    )
    funding_network_fee_lamports = int(
        (funding_transaction.get("meta") or {}).get("fee") or 0
    )
    deposit_network_fee_lamports = int(
        (deposit_transaction.get("meta") or {}).get("fee") or 0
    )
    source_native_delta = _native_delta_lamports(source_transaction, wallet)
    funding_native_delta = _native_delta_lamports(funding_transaction, wallet)
    source_native_outflow_lamports = max(-(source_native_delta or 0), 0)
    funding_native_outflow_lamports = max(-(funding_native_delta or 0), 0)
    direct_wallet_cost_lamports = (
        source_native_outflow_lamports + funding_native_outflow_lamports
    )
    output_withheld_lamports = max(
        swap_output_lamports - expected_deposit_lamports,
        0,
    )
    route_balance_after_deposit_lamports = (
        _native_balance_lamports(deposit_transaction, route_wallet, after=True) or 0
    )
    expected_route_balance_after_deposit = (
        expected_funding_lamports
        + swap_output_lamports
        - expected_deposit_lamports
        - swap_fee_lamports
        - deposit_network_fee_lamports
    )
    swap_event_time = _block_time(swap_transaction)
    deposit_onchain_event_time = _block_time(deposit_transaction)

    source_signers = _signers(source_transaction)
    funding_signers = _signers(funding_transaction)
    swap_signers = _signers(swap_transaction)
    deposit_signers = _signers(deposit_transaction)
    swap_program_ids = _program_ids(swap_transaction)
    source_succeeded = (source_transaction.get("meta") or {}).get("err") is None
    funding_succeeded = (funding_transaction.get("meta") or {}).get("err") is None
    swap_succeeded = (swap_transaction.get("meta") or {}).get("err") is None
    deposit_succeeded = (deposit_transaction.get("meta") or {}).get("err") is None
    decision_layer = {
        "source_wallet_is_signer": wallet in source_signers,
        "source_asset_to_route_exact": source_mint is not None and source_succeeded,
        "funding_wallet_is_signer": wallet in funding_signers,
        "funding_to_route_exact": bool(
            funding_integer_lamports and funding_matches and funding_succeeded
        ),
        "route_wallet_is_swap_signer": route_wallet in swap_signers,
        "jupiter_program_present": JUPITER_V6_PROGRAM in swap_program_ids,
        "swap_input_exact": swap_input_quantity == source_quantity and swap_succeeded,
        "swap_output_positive": swap_output_lamports > 0,
        "route_wallet_is_deposit_signer": route_wallet in deposit_signers,
        "cex_deposit_address_matches": bool(deposit_address and deposit_matches),
        "route_to_cex_deposit_exact": bool(
            deposit_integer_lamports and deposit_matches and deposit_succeeded
        ),
        "cex_deposit_completed": str(
            deposit_raw_payload.get("Status") or deposit_raw_payload.get("status") or ""
        )
        .strip()
        .lower()
        == "completed",
        "swap_timestamp_present": swap_event_time is not None,
        "wallet_native_costs_reconciled": bool(
            source_native_delta is not None
            and funding_native_delta is not None
            and source_native_outflow_lamports >= source_network_fee_lamports
            and funding_native_outflow_lamports
            == expected_funding_lamports + funding_network_fee_lamports
        ),
        "route_native_balance_reconciled": bool(
            route_balance_after_deposit_lamports
            == expected_route_balance_after_deposit
        ),
    }
    evidence_ready = all(decision_layer.values())
    return {
        "source_event_id": source_event.event_id,
        "source_event_time": source_event.event_time.isoformat(),
        "source_tx_id": str(source_event.tx_id),
        "source_wallet": wallet,
        "source_asset": source_event.asset.upper(),
        "source_mint": source_mint,
        "source_quantity": str(source_quantity),
        "funding_event_id": funding_event.event_id,
        "funding_event_time": funding_event.event_time.isoformat(),
        "funding_tx_id": str(funding_event.tx_id),
        "funding_quantity": str(abs(funding_event.quantity)),
        "funding_transfer_lamports": expected_funding_lamports,
        "swap_tx_id": swap_tx_id,
        "swap_event_time": swap_event_time.isoformat() if swap_event_time else None,
        "route_wallet": route_wallet,
        "swap_input_quantity": str(swap_input_quantity),
        "swap_output_lamports": swap_output_lamports,
        "swap_output_quantity": str(Decimal(swap_output_lamports) / LAMPORTS_PER_SOL),
        "deposit_event_id": deposit_event.event_id,
        "deposit_event_time": deposit_event.event_time.isoformat(),
        "deposit_onchain_event_time": (
            deposit_onchain_event_time.isoformat()
            if deposit_onchain_event_time
            else None
        ),
        "deposit_tx_id": str(deposit_event.tx_id),
        "deposit_exchange": deposit_event.source.lower(),
        "deposit_address": deposit_address,
        "deposit_asset": deposit_event.asset.upper(),
        "deposit_quantity": str(deposit_event.quantity),
        "source_native_outflow_lamports": source_native_outflow_lamports,
        "source_network_fee_lamports": source_network_fee_lamports,
        "funding_native_outflow_lamports": funding_native_outflow_lamports,
        "funding_network_fee_lamports": funding_network_fee_lamports,
        "swap_network_fee_lamports": swap_fee_lamports,
        "deposit_network_fee_lamports": deposit_network_fee_lamports,
        "direct_wallet_cost_lamports": direct_wallet_cost_lamports,
        "direct_wallet_cost_quantity": str(
            Decimal(direct_wallet_cost_lamports) / LAMPORTS_PER_SOL
        ),
        "output_withheld_lamports": output_withheld_lamports,
        "output_withheld_quantity": str(
            Decimal(output_withheld_lamports) / LAMPORTS_PER_SOL
        ),
        "route_balance_after_deposit_lamports": route_balance_after_deposit_lamports,
        "route_balance_after_deposit_quantity": str(
            Decimal(route_balance_after_deposit_lamports) / LAMPORTS_PER_SOL
        ),
        "source_signers": source_signers,
        "funding_signers": funding_signers,
        "swap_signers": swap_signers,
        "deposit_signers": deposit_signers,
        "swap_program_ids": swap_program_ids,
        "decision_layer": decision_layer,
        "classification": (
            "service_mediated_jupiter_swap_evidence_ready"
            if evidence_ready
            else "review_required"
        ),
        "tax_treatment": "taxable_crypto_to_crypto_swap_mapping_review_required",
        "evidence_source": "alchemy_getTransaction_and_cex_deposit_history",
    }


def _semantic_sha256(records: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        records, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    temporary.replace(path)


def _rpc_transaction(
    client: httpx.Client,
    *,
    url: str,
    tx_id: str,
) -> dict[str, Any]:
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
        raise ValueError(f"transaction_not_found:{tx_id}")
    return transaction


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Alchemy evidence audit for a service-mediated Solana Jupiter "
            "swap ending in a documented CEX deposit."
        )
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--source-event-id", required=True)
    parser.add_argument("--funding-event-id", required=True)
    parser.add_argument("--swap-tx-id", required=True)
    parser.add_argument("--deposit-event-id", required=True)
    parser.add_argument("--wallet", default=DEFAULT_WALLET)
    parser.add_argument("--route-wallet", required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    store = DuckDbStore(args.db)
    source_event, funding_event, deposit_event, deposit_raw_payload = load_route_events(
        store,
        source_event_id=args.source_event_id,
        funding_event_id=args.funding_event_id,
        deposit_event_id=args.deposit_event_id,
        year=args.year,
        wallet=args.wallet,
    )
    service = WalletFifoPreviewService(store)
    api_key = service._alchemy_api_key()
    if not api_key:
        raise SystemExit("alchemy_api_key_missing")
    url = f"https://solana-mainnet.g.alchemy.com/v2/{api_key}"
    tx_ids = {
        "source": str(source_event.tx_id),
        "funding": str(funding_event.tx_id),
        "swap": args.swap_tx_id,
        "deposit": str(deposit_event.tx_id),
    }
    rpc_errors: list[dict[str, str]] = []
    transactions: dict[str, dict[str, Any]] = {}
    with httpx.Client(timeout=max(5, min(args.timeout_seconds, 60))) as client:
        for label, tx_id in tx_ids.items():
            try:
                transactions[label] = _rpc_transaction(client, url=url, tx_id=tx_id)
            except Exception as exc:
                rpc_errors.append({"label": label, "tx_id": tx_id, "error": str(exc)})

    records: list[dict[str, Any]] = []
    if not rpc_errors:
        records.append(
            analyze_route(
                source_event=source_event,
                funding_event=funding_event,
                deposit_event=deposit_event,
                deposit_raw_payload=deposit_raw_payload,
                wallet=args.wallet,
                route_wallet=args.route_wallet,
                swap_tx_id=args.swap_tx_id,
                source_transaction=transactions["source"],
                funding_transaction=transactions["funding"],
                swap_transaction=transactions["swap"],
                deposit_transaction=transactions["deposit"],
            )
        )
    verified_count = sum(
        1
        for record in records
        if record["classification"] == "service_mediated_jupiter_swap_evidence_ready"
    )
    generated_at = datetime.now(timezone.utc)
    payload = {
        "generated_at": generated_at.isoformat(),
        "year": args.year,
        "wallet": args.wallet,
        "route_wallet": args.route_wallet,
        "provider": "alchemy_admin_secret",
        "records_count": len(records),
        "verified_count": verified_count,
        "review_count": len(records) - verified_count,
        "failed_count": len(rpc_errors),
        "semantic_sha256": _semantic_sha256(records),
        "records": records,
        "rpc_errors": rpc_errors,
        "methodology": (
            "Read-only Nachweis einer servicevermittelten Jupiter-Route: eigene Wallet "
            "sendet das Input-Asset und SOL-Funding an eine nicht als Eigenwallet "
            "registrierte Route-Adresse; diese signiert den Jupiter-Swap und zahlt den "
            "Output an eine dokumentierte CEX-Deposit-Adresse aus. Der Nachweis erklaert "
            "keinen Eigenuebertrag und aendert keine Imports, Lots, Tax-Lines oder Ledger. "
            "Die steuerliche Abbildung von Input-Veraeusserung, Output-Anschaffung und "
            "Servicekosten bleibt bis zur expliziten Methodenregel im Review."
        ),
    }
    timestamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    run_path = args.output_dir / f"{timestamp}_{args.year}_service_swap_evidence.json"
    latest_path = args.output_dir / f"latest_{args.year}_service_swap_evidence.json"
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
