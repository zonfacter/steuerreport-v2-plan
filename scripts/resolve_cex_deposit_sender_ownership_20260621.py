#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlencode

import httpx

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from steuerreport_v2.db.duckdb_store import DuckDbStore  # noqa: E402
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService  # noqa: E402

API_BASE = os.environ.get("STEUERREPORT_V2_API", "http://127.0.0.1:8010")
DB_PATH = Path(os.environ.get("STEUERREPORT_V2_DB", ROOT / "data" / "steuerreport_v2.duckdb"))
OUT_DIR = ROOT / "var" / "cex_deposit_sender_ownership"
LAMPORTS_PER_SOL = Decimal("1000000000")


@dataclass(frozen=True)
class AddressRegistry:
    owned_private_wallets: dict[str, str]
    owned_cex_deposit_addresses: dict[str, str]
    known_infrastructure_wallets: dict[str, str]
    service_programs: dict[str, str]


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve Binance/Solana deposit sender ownership for BMF/FIFO review.")
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--cex", default="binance")
    parser.add_argument("--network", default="SOL")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--api-base", default=API_BASE)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--registry", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Do not write output file.")
    args = parser.parse_args()

    store = DuckDbStore(args.db)
    service = WalletFifoPreviewService(store)
    registry = load_registry(args.registry, service)
    helius_key = secret_value(store, "secret.helius.api_key") or os.environ.get("HELIUS_API_KEY", "").strip()
    alchemy_key = service._alchemy_api_key()

    deposits_report = get_api(
        args.api_base,
        f"/api/v1/tax-years/{args.year}/cex-deposit-transfer-evidence",
        {"cex": args.cex, "network": args.network, "limit": str(args.limit)},
    )
    deposits = deposits_report.get("deposits") if isinstance(deposits_report, dict) else []
    if not isinstance(deposits, list):
        raise SystemExit("cex_deposit_transfer_evidence returned no deposit list")

    results: list[dict[str, Any]] = []
    with httpx.Client(timeout=30) as client:
        for deposit in deposits[: max(1, args.limit)]:
            if not isinstance(deposit, dict):
                continue
            txid = str(deposit.get("tx_id") or "")
            if not txid:
                results.append(build_result(deposit, None, "missing_txid", registry))
                continue
            tx_data: dict[str, Any] | None = None
            provider = "none"
            provider_error = None
            if helius_key:
                try:
                    tx_data = fetch_helius_transaction(client, helius_key, txid)
                    provider = "helius"
                except Exception as exc:  # keep fallback useful for overnight runs
                    provider_error = f"helius:{type(exc).__name__}"
            if tx_data is None and alchemy_key:
                try:
                    tx_data = fetch_alchemy_transaction(client, alchemy_key, txid)
                    provider = "alchemy"
                except Exception as exc:
                    provider_error = f"alchemy:{type(exc).__name__}"
            result = build_result(deposit, tx_data, provider_error or provider, registry)
            results.append(result)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "year": args.year,
        "cex": args.cex,
        "network": args.network,
        "provider_preference": ["helius", "alchemy"],
        "helius_configured": bool(helius_key),
        "alchemy_configured": bool(alchemy_key),
        "registry_counts": {
            "owned_private_wallets": len(registry.owned_private_wallets),
            "owned_cex_deposit_addresses": len(registry.owned_cex_deposit_addresses),
            "known_infrastructure_wallets": len(registry.known_infrastructure_wallets),
            "service_programs": len(registry.service_programs),
        },
        "summary": summarize(results),
        "results": results,
        "methodology": (
            "Read-only CEX Deposit Sender Ownership Resolver. Uses Helius Enhanced Transactions when configured, "
            "then Alchemy Solana RPC as fallback. It matches on-chain sender/signers/transfers against a local "
            "address registry and emits review JSON only. It does not change Canonical Events, FIFO lots, tax lines, "
            "prices, imports or review decisions."
        ),
    }
    if args.dry_run:
        print(json.dumps(redact_payload(payload), indent=2, ensure_ascii=False, default=str))
        return 0

    output_path = args.out or default_output_path(args.year)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps({"status": "ok", "output": str(output_path), "summary": payload["summary"]}, indent=2))
    return 0


def get_api(api_base: str, path: str, params: dict[str, str]) -> dict[str, Any]:
    url = f"{api_base.rstrip('/')}{path}?{urlencode(params)}"
    response = httpx.get(url, timeout=60)
    response.raise_for_status()
    body = response.json()
    if body.get("status") != "ok":
        raise RuntimeError(body.get("errors") or "api_error")
    data = body.get("data")
    return data if isinstance(data, dict) else {}


def secret_value(store: DuckDbStore, key: str) -> str:
    try:
        settings = {setting.key: setting.value_json for setting in store.list_admin_settings()}
        raw = settings.get(key)
        return str(json.loads(raw)).strip() if raw else ""
    except Exception:
        return ""


def load_registry(path: Path | None, service: WalletFifoPreviewService) -> AddressRegistry:
    if path and path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
    else:
        raw = {}
    owned_private_wallets = {
        address: label
        for address, label in {
            "4dCdKKXm1aHzMLFHFz7Cyn6CA14RK7WdYKeAGrHx4fod": "Jup Wallet",
            "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY": "Solana Main Wallet",
            **{wallet: "Known own Solana wallet" for wallet in service.KNOWN_OWN_SOLANA_WALLETS},
        }.items()
    }
    owned_cex_deposit_addresses: dict[str, str] = {}
    known_infrastructure_wallets = {
        "DWf2k9851Uxny6fvj3jq5bY6W5xaHmjxfBVobMPSHVvM": "Binance Solana Hot Wallet",
    }
    service_programs = {
        "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4": "Jupiter Aggregator",
        "PERPHjGBqRHArX4DySjwM6UJHiR3sWAatqfdBS2qQJu": "Perp/DEX Program",
    }
    for item in raw.get("owned_private_wallets", []):
        if isinstance(item, dict) and item.get("address"):
            owned_private_wallets[str(item["address"])] = str(item.get("label") or "Private Wallet")
    for item in raw.get("owned_cex_deposit_addresses", []):
        if isinstance(item, dict) and item.get("address"):
            owned_cex_deposit_addresses[str(item["address"])] = str(item.get("exchange") or "CEX Deposit")
    for item in raw.get("known_infrastructure_wallets", []):
        if isinstance(item, dict) and item.get("address"):
            known_infrastructure_wallets[str(item["address"])] = str(item.get("label") or "Infrastructure Wallet")
    return AddressRegistry(
        owned_private_wallets=owned_private_wallets,
        owned_cex_deposit_addresses=owned_cex_deposit_addresses,
        known_infrastructure_wallets=known_infrastructure_wallets,
        service_programs=service_programs,
    )


def fetch_helius_transaction(client: httpx.Client, api_key: str, txid: str) -> dict[str, Any] | None:
    url = f"https://mainnet.helius-rpc.com/v0/transactions?api-key={api_key}"
    response = client.post(url, json={"transactions": [txid]})
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, list) and payload:
        return {"provider": "helius", "raw": payload[0]}
    return None


def fetch_alchemy_transaction(client: httpx.Client, api_key: str, txid: str) -> dict[str, Any] | None:
    url = f"https://solana-mainnet.g.alchemy.com/v2/{api_key}"
    response = client.post(
        url,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [txid, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
        },
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(payload["error"])
    result = payload.get("result")
    return {"provider": "alchemy", "raw": result} if isinstance(result, dict) else None


def build_result(
    deposit: dict[str, Any],
    tx_data: dict[str, Any] | None,
    provider_status: str,
    registry: AddressRegistry,
) -> dict[str, Any]:
    txid = str(deposit.get("tx_id") or "")
    asset = str(deposit.get("asset") or "").upper()
    amount = decimal_or_none(deposit.get("onchain_quantity")) or decimal_or_none(deposit.get("credited_quantity")) or Decimal("0")
    deposit_address = str(deposit.get("deposit_address") or "")
    owned_cex_deposit = bool(deposit_address and (deposit_address in registry.owned_cex_deposit_addresses or deposit.get("deposit_raw_object_id")))
    tx_summary = extract_transaction_summary(tx_data, asset, amount, deposit_address)
    sender = tx_summary.get("sender_address")
    signer = tx_summary.get("primary_signer")
    programs = tx_summary.get("program_ids") if isinstance(tx_summary.get("program_ids"), list) else []
    sender_is_own_wallet = bool(sender and sender in registry.owned_private_wallets)
    signer_is_own_wallet = bool(signer and signer in registry.owned_private_wallets)
    service_route = any(str(program) in registry.service_programs for program in programs)
    third_party = bool(sender and not sender_is_own_wallet and sender not in registry.known_infrastructure_wallets)
    decision_layer = {
        "binance_deposit_address_owned": owned_cex_deposit,
        "sender_is_own_wallet": sender_is_own_wallet or signer_is_own_wallet,
        "service_program_route_not_income": service_route and not (sender_is_own_wallet or signer_is_own_wallet),
        "exchange_deposit_transfer_neutral": owned_cex_deposit and (sender_is_own_wallet or signer_is_own_wallet),
    }
    if decision_layer["exchange_deposit_transfer_neutral"]:
        final_tax_status = "TAX_NEUTRAL_TRANSFER_PENDING_REVIEW"
    elif decision_layer["service_program_route_not_income"]:
        final_tax_status = "COMPLEX_ROUTE_REVIEW"
    elif third_party:
        final_tax_status = "UNVERIFIED_THIRD_PARTY"
    else:
        final_tax_status = "PENDING_REVIEW"
    return {
        "txid": txid,
        "timestamp_utc": tx_summary.get("timestamp_utc") or deposit.get("onchain_time") or deposit.get("cex_credit_time"),
        "asset": asset,
        "amount": str(amount),
        "provider_status": provider_status,
        "onchain_sender": sender,
        "primary_signer": signer,
        "deposit_address": deposit_address or None,
        "cex_account": deposit.get("cex_account"),
        "fifo_transfer_status": deposit.get("fifo_transfer_status"),
        "carried_cost_basis_eur": deposit.get("carried_cost_basis_eur"),
        "program_ids": programs,
        "native_transfers": tx_summary.get("native_transfers", []),
        "token_transfers": tx_summary.get("token_transfers", []),
        "decision_layer": decision_layer,
        "final_tax_status": final_tax_status,
        "review_note": review_note(final_tax_status),
    }


def extract_transaction_summary(
    tx_data: dict[str, Any] | None,
    asset: str,
    amount: Decimal,
    deposit_address: str,
) -> dict[str, Any]:
    if not tx_data:
        return {"program_ids": []}
    provider = tx_data.get("provider")
    raw = tx_data.get("raw")
    if provider == "helius" and isinstance(raw, dict):
        return extract_helius_summary(raw, asset, amount, deposit_address)
    if provider == "alchemy" and isinstance(raw, dict):
        return extract_alchemy_summary(raw, asset, amount, deposit_address)
    return {"program_ids": []}


def extract_helius_summary(raw: dict[str, Any], asset: str, amount: Decimal, deposit_address: str) -> dict[str, Any]:
    native = raw.get("nativeTransfers") if isinstance(raw.get("nativeTransfers"), list) else []
    token = raw.get("tokenTransfers") if isinstance(raw.get("tokenTransfers"), list) else []
    sender = None
    if asset == "SOL":
        for transfer in native:
            if str(transfer.get("toUserAccount") or "") == deposit_address:
                sender = str(transfer.get("fromUserAccount") or "") or None
                break
    else:
        for transfer in token:
            if str(transfer.get("toUserAccount") or "") == deposit_address:
                sender = str(transfer.get("fromUserAccount") or "") or None
                break
    timestamp = raw.get("timestamp")
    return {
        "timestamp_utc": datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat() if isinstance(timestamp, int) else None,
        "sender_address": sender,
        "primary_signer": raw.get("feePayer"),
        "program_ids": [str(raw.get("source"))] if raw.get("source") else [],
        "native_transfers": native,
        "token_transfers": token,
    }


def extract_alchemy_summary(raw: dict[str, Any], asset: str, amount: Decimal, deposit_address: str) -> dict[str, Any]:
    transaction = raw.get("transaction") if isinstance(raw.get("transaction"), dict) else {}
    message = transaction.get("message") if isinstance(transaction.get("message"), dict) else {}
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    account_keys = message.get("accountKeys") if isinstance(message.get("accountKeys"), list) else []
    signers = [
        str(key.get("pubkey"))
        for key in account_keys
        if isinstance(key, dict) and key.get("signer") is True and key.get("pubkey")
    ]
    program_ids: list[str] = []
    collect_programs(message.get("instructions"), program_ids)
    for group in meta.get("innerInstructions") if isinstance(meta.get("innerInstructions"), list) else []:
        if isinstance(group, dict):
            collect_programs(group.get("instructions"), program_ids)
    sender = infer_sender_from_balances(raw, asset, amount, deposit_address)
    timestamp = raw.get("blockTime")
    return {
        "timestamp_utc": datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat() if isinstance(timestamp, int) else None,
        "sender_address": sender,
        "primary_signer": signers[0] if signers else None,
        "program_ids": list(dict.fromkeys(program_ids)),
        "native_transfers": [],
        "token_transfers": [],
    }


def collect_programs(instructions: Any, target: list[str]) -> None:
    if not isinstance(instructions, list):
        return
    for instruction in instructions:
        if isinstance(instruction, dict) and instruction.get("programId"):
            target.append(str(instruction["programId"]))


def infer_sender_from_balances(raw: dict[str, Any], asset: str, amount: Decimal, deposit_address: str) -> str | None:
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    if asset == "SOL":
        return infer_sol_sender(raw, amount, deposit_address)
    pre = token_balance_owner_amounts(meta.get("preTokenBalances"))
    post = token_balance_owner_amounts(meta.get("postTokenBalances"))
    deltas: dict[tuple[str, str], Decimal] = {}
    for key in set(pre) | set(post):
        deltas[key] = post.get(key, Decimal("0")) - pre.get(key, Decimal("0"))
    negative = [(owner, mint, delta) for (owner, mint), delta in deltas.items() if delta < 0]
    if not negative:
        return None
    return min(negative, key=lambda item: abs(abs(item[2]) - amount))[0]


def infer_sol_sender(raw: dict[str, Any], amount: Decimal, deposit_address: str) -> str | None:
    transaction = raw.get("transaction") if isinstance(raw.get("transaction"), dict) else {}
    message = transaction.get("message") if isinstance(transaction.get("message"), dict) else {}
    account_keys = message.get("accountKeys") if isinstance(message.get("accountKeys"), list) else []
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    pre_balances = meta.get("preBalances") if isinstance(meta.get("preBalances"), list) else []
    post_balances = meta.get("postBalances") if isinstance(meta.get("postBalances"), list) else []
    best: tuple[str, Decimal] | None = None
    for idx, key in enumerate(account_keys):
        if idx >= len(pre_balances) or idx >= len(post_balances):
            continue
        pubkey = str(key.get("pubkey") if isinstance(key, dict) else key)
        delta = (Decimal(str(post_balances[idx])) - Decimal(str(pre_balances[idx]))) / LAMPORTS_PER_SOL
        if delta < 0:
            distance = abs(abs(delta) - amount)
            if best is None or distance < best[1]:
                best = (pubkey, distance)
    return best[0] if best else None


def token_balance_owner_amounts(items: Any) -> dict[tuple[str, str], Decimal]:
    result: dict[tuple[str, str], Decimal] = {}
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        owner = str(item.get("owner") or "")
        mint = str(item.get("mint") or "")
        ui = item.get("uiTokenAmount") if isinstance(item.get("uiTokenAmount"), dict) else {}
        quantity = decimal_or_none(ui.get("uiAmountString")) or Decimal("0")
        if owner and mint:
            result[(owner, mint)] = result.get((owner, mint), Decimal("0")) + quantity
    return result


def decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def review_note(status: str) -> str:
    if status == "TAX_NEUTRAL_TRANSFER_PENDING_REVIEW":
        return "Own sender/deposit match found; review can confirm tax-neutral FIFO transfer."
    if status == "COMPLEX_ROUTE_REVIEW":
        return "Service/program route detected; do not classify as income or external inflow without route evidence."
    if status == "UNVERIFIED_THIRD_PARTY":
        return "Sender is not in owned wallet registry; conservative review required."
    return "Insufficient provider or registry evidence; keep pending."


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for item in results:
        status = str(item.get("final_tax_status") or "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1
    return {
        "transactions": len(results),
        "status_counts": counts,
        "tax_neutral_candidates": counts.get("TAX_NEUTRAL_TRANSFER_PENDING_REVIEW", 0),
        "complex_route_review": counts.get("COMPLEX_ROUTE_REVIEW", 0),
        "unverified_third_party": counts.get("UNVERIFIED_THIRD_PARTY", 0),
        "pending_review": counts.get("PENDING_REVIEW", 0),
    }


def default_output_path(year: int) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return OUT_DIR / f"{stamp}_{year}_binance_solana_sender_ownership.json"


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
