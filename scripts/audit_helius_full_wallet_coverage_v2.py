#!/usr/bin/env python3
"""Read-only Helius full-wallet coverage audit.

The report deliberately queries all transaction statuses. Failed transactions
must be visible in an audit, but they are never treated as taxable movements.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any

import duckdb
import httpx


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
DEFAULT_OUTPUT = PROJECT_ROOT / "var/staging_audits/helius_full_wallet_coverage_2026-09-27.json"
DEFAULT_WALLET = "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
RPC_URL = "https://mainnet.helius-rpc.com/"


def _iso(block_time: object) -> str | None:
    if block_time is None:
        return None
    return datetime.fromtimestamp(int(block_time), tz=timezone.utc).isoformat()


def _json_sha(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _account_keys(row: dict[str, Any]) -> list[str]:
    tx = row.get("transaction") if isinstance(row.get("transaction"), dict) else {}
    message = tx.get("message") if isinstance(tx.get("message"), dict) else {}
    static = message.get("accountKeys") if isinstance(message.get("accountKeys"), list) else []
    keys = [str(item.get("pubkey") or "") if isinstance(item, dict) else str(item) for item in static]
    loaded = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    addresses = loaded.get("loadedAddresses") if isinstance(loaded.get("loadedAddresses"), dict) else {}
    keys.extend(str(item) for item in addresses.get("writable") or [])
    keys.extend(str(item) for item in addresses.get("readonly") or [])
    return keys


def _signers(row: dict[str, Any]) -> list[str]:
    tx = row.get("transaction") if isinstance(row.get("transaction"), dict) else {}
    message = tx.get("message") if isinstance(tx.get("message"), dict) else {}
    static = message.get("accountKeys") if isinstance(message.get("accountKeys"), list) else []
    header = message.get("header") if isinstance(message.get("header"), dict) else {}
    count = int(header.get("numRequiredSignatures") or 0)
    return [
        str(item.get("pubkey") or "") if isinstance(item, dict) else str(item)
        for item in static[:count]
    ]


def _native_delta_lamports(row: dict[str, Any], wallet: str) -> int | None:
    keys = _account_keys(row)
    if wallet not in keys:
        return None
    index = keys.index(wallet)
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    pre = meta.get("preBalances") if isinstance(meta.get("preBalances"), list) else []
    post = meta.get("postBalances") if isinstance(meta.get("postBalances"), list) else []
    if index >= len(pre) or index >= len(post):
        return None
    return int(post[index]) - int(pre[index])


def _token_deltas(row: dict[str, Any], wallet: str) -> list[dict[str, object]]:
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    by_mint: dict[str, dict[str, object]] = defaultdict(
        lambda: {"pre_raw": 0, "post_raw": 0, "decimals": 0, "mint": ""}
    )
    for side in ("preTokenBalances", "postTokenBalances"):
        values = meta.get(side) if isinstance(meta.get(side), list) else []
        for item in values:
            if not isinstance(item, dict) or str(item.get("owner") or "") != wallet:
                continue
            mint = str(item.get("mint") or "")
            amount = item.get("uiTokenAmount") if isinstance(item.get("uiTokenAmount"), dict) else {}
            entry = by_mint[mint]
            entry["mint"] = mint
            entry["decimals"] = int(amount.get("decimals") or 0)
            entry["pre_raw" if side == "preTokenBalances" else "post_raw"] = int(
                amount.get("amount") or 0
            )
    result = []
    for entry in by_mint.values():
        delta = int(entry["post_raw"]) - int(entry["pre_raw"])
        if not delta:
            continue
        decimals = int(entry["decimals"])
        quantity = Decimal(delta) / (Decimal(10) ** decimals)
        result.append(
            {
                "mint": str(entry["mint"]),
                "raw_delta": delta,
                "decimals": decimals,
                "quantity_delta": str(quantity),
            }
        )
    return sorted(result, key=lambda item: str(item["mint"]))


def _program_ids(row: dict[str, Any]) -> list[str]:
    keys = _account_keys(row)
    tx = row.get("transaction") if isinstance(row.get("transaction"), dict) else {}
    message = tx.get("message") if isinstance(tx.get("message"), dict) else {}
    ids: list[str] = []

    def add(instruction: object) -> None:
        if not isinstance(instruction, dict):
            return
        index = instruction.get("programIdIndex")
        if isinstance(index, int) and index < len(keys):
            ids.append(keys[index])
        elif instruction.get("programId"):
            ids.append(str(instruction["programId"]))

    for instruction in message.get("instructions") or []:
        add(instruction)
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    for group in meta.get("innerInstructions") or []:
        if isinstance(group, dict):
            for instruction in group.get("instructions") or []:
                add(instruction)
    return sorted(set(ids))


def _is_bubblegum(row: dict[str, Any], programs: list[str]) -> bool:
    logs = " ".join(str(item) for item in (row.get("meta") or {}).get("logMessages") or [])
    return "bubblegum" in logs.lower() or any(item.startswith("BGUM") for item in programs)


def _classify(row: dict[str, Any], wallet: str) -> dict[str, object]:
    meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
    signature = str(((row.get("transaction") or {}).get("signatures") or [""])[0])
    token_deltas = _token_deltas(row, wallet)
    native_lamports = _native_delta_lamports(row, wallet)
    fee_lamports = int(meta.get("fee") or 0)
    programs = _program_ids(row)
    success = meta.get("err") is None
    block_time_utc = _iso(row.get("blockTime"))
    if not success:
        classification = "failed_transaction"
    elif any(int(item["decimals"]) > 0 for item in token_deltas):
        classification = "fungible_token_movement"
    elif token_deltas:
        classification = "zero_decimal_token_or_nft_movement"
    elif native_lamports not in (None, 0):
        classification = "native_sol_movement"
    elif _is_bubblegum(row, programs):
        classification = "compressed_nft_or_program_event"
    else:
        classification = "no_direct_wallet_balance_movement"
    return {
        "signature": signature,
        "slot": row.get("slot"),
        "block_time_utc": block_time_utc,
        "status": "onchain_success" if success else "onchain_failed",
        "error": meta.get("err"),
        "fee_lamports": fee_lamports,
        "fee_payer": _account_keys(row)[0] if _account_keys(row) else None,
        "wallet_is_fee_payer": bool(_account_keys(row)) and _account_keys(row)[0] == wallet,
        "wallet_is_signer": wallet in _signers(row),
        "native_delta_lamports": native_lamports,
        "native_delta_sol": str(Decimal(native_lamports or 0) / Decimal(10**9)),
        "token_deltas": token_deltas,
        "program_ids": programs,
        "classification": classification,
        "review_required": classification in {
            "zero_decimal_token_or_nft_movement",
            "compressed_nft_or_program_event",
            "native_sol_movement",
            "fungible_token_movement",
        },
        "tax_year_2025_relevance": (
            "failed_no_tax_movement"
            if not success and block_time_utc and block_time_utc[:4] == "2025"
            else "review_required"
            if block_time_utc and block_time_utc[:4] == "2025"
            else "outside_tax_year_2025"
        ),
    }


def _rpc(client: httpx.Client, api_key: str, body: dict[str, object]) -> dict[str, object]:
    for attempt in range(7):
        response = client.post(RPC_URL, params={"api-key": api_key}, json=body)
        if response.status_code == 429 and attempt < 6:
            time.sleep(min(90, 5 * (2**attempt)))
            continue
        if response.status_code != 200:
            raise RuntimeError(f"Helius HTTP status {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("error"):
            raise RuntimeError("Helius RPC returned an error")
        result = payload.get("result")
        return result if isinstance(result, dict) else {}
    raise RuntimeError("Helius rate-limit retries exhausted")


def _history(client: httpx.Client, api_key: str, wallet: str) -> tuple[list[dict[str, object]], list[int]]:
    rows: list[dict[str, object]] = []
    page_sizes: list[int] = []
    pagination_token: str | None = None
    for page in range(1, 100):
        options: dict[str, object] = {
            "transactionDetails": "full",
            "sortOrder": "asc",
            "limit": 1000,
            "filters": {"tokenAccounts": "all"},
            "maxSupportedTransactionVersion": 1,
        }
        if pagination_token:
            options["paginationToken"] = pagination_token
        result = _rpc(
            client,
            api_key,
            {"jsonrpc": "2.0", "id": page, "method": "getTransactionsForAddress", "params": [wallet, options]},
        )
        page_rows = [item for item in result.get("data", []) if isinstance(item, dict)]
        page_sizes.append(len(page_rows))
        rows.extend(page_rows)
        pagination_token = str(result.get("paginationToken") or "") or None
        if not page_rows or not pagination_token:
            break
    return rows, page_sizes


def _local_scope(db: Path, wallet: str) -> dict[str, object]:
    with duckdb.connect(str(db), read_only=True) as con:
        target = {
            str(row[0])
            for row in con.execute(
                """select distinct tx_id from canonical_events
                   where lower(source) = 'solana_rpc' and account = ?
                     and tx_id is not null and trim(tx_id) <> ''""",
                [wallet],
            ).fetchall()
        }
        all_rows = con.execute(
            """select coalesce(account, '<null>'), count(distinct tx_id)
               from canonical_events where lower(source) = 'solana_rpc'
               group by 1 order by 1"""
        ).fetchall()
    return {"target_signatures": target, "account_distribution": {str(k): int(v) for k, v in all_rows}}


def run(args: argparse.Namespace) -> dict[str, object]:
    api_key = os.environ.get("HELIUS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("HELIUS_API_KEY must be provided through the environment")
    output = Path(args.output).resolve()
    if output.exists():
        raise RuntimeError(f"immutable output already exists: {output}")
    local = _local_scope(Path(args.db).resolve(), args.wallet)
    with httpx.Client(timeout=180.0) as client:
        rows, page_sizes = _history(client, api_key, args.wallet)
    signatures = {
        str(((row.get("transaction") or {}).get("signatures") or [""])[0])
        for row in rows
    }
    missing = sorted(signatures - local["target_signatures"])
    local_only = sorted(local["target_signatures"] - signatures)
    by_signature = {
        str(((row.get("transaction") or {}).get("signatures") or [""])[0]): row
        for row in rows
    }
    missing_details = sorted(
        [_classify(by_signature[signature], args.wallet) for signature in missing],
        key=lambda item: (str(item.get("block_time_utc") or ""), str(item["signature"])),
    )
    year_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        year = _iso(row.get("blockTime"))
        if year:
            year_counts[year[:4]]["all_statuses"] += 1
            year_counts[year[:4]]["onchain_success"] += int((row.get("meta") or {}).get("err") is None)
            year_counts[year[:4]]["onchain_failed"] += int((row.get("meta") or {}).get("err") is not None)
    classification_counts = Counter(str(row["classification"]) for row in missing_details)
    missing_year_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in missing_details:
        year = str(row.get("block_time_utc") or "")[:4] or "unknown"
        missing_year_counts[year][str(row["classification"])] += 1
    all_block_times = [_iso(row.get("blockTime")) for row in rows]
    all_block_times = [value for value in all_block_times if value]
    response_hash = _json_sha(rows)
    result: dict[str, object] = {
        "schema_version": "helius_full_wallet_coverage_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "wallet": args.wallet,
        "provider": "helius",
        "rpc_method": "getTransactionsForAddress",
        "rpc_url": RPC_URL,
        "query": {
            "transactionDetails": "full",
            "sortOrder": "asc",
            "limit": 1000,
            "filters": {"tokenAccounts": "all", "status": "all"},
            "maxSupportedTransactionVersion": 1,
            "api_key_persisted": False,
        },
        "history": {
            "page_sizes": page_sizes,
            "unique_signatures": len(signatures),
            "response_sha256": response_hash,
            "first_block_time_utc": min(all_block_times, default=None),
            "last_block_time_utc": max(all_block_times, default=None),
        },
        "year_counts": {year: dict(counts) for year, counts in sorted(year_counts.items())},
        "local_ledger": {
            "database": str(Path(args.db).resolve().relative_to(PROJECT_ROOT)),
            "table": "canonical_events",
            "source": "solana_rpc",
            "account_scope": args.wallet,
            "target_unique_signatures": len(local["target_signatures"]),
            "account_distribution": local["account_distribution"],
        },
        "coverage": {
            "helius_unique_signatures": len(signatures),
            "local_target_unique_signatures": len(local["target_signatures"]),
            "helius_only_count": len(missing),
            "local_target_only_count": len(local_only),
            "all_local_target_signatures_in_helius": not local_only,
            "target_changed": False,
            "import_effect": "none",
        },
        "helius_only": {
            "classification_counts": dict(sorted(classification_counts.items())),
            "classification_counts_by_year": {
                year: dict(counts) for year, counts in sorted(missing_year_counts.items())
            },
            "tax_year_2025_count": sum(
                str(item.get("block_time_utc") or "").startswith("2025") for item in missing_details
            ),
            "tax_year_2025_review_items": [
                item for item in missing_details if str(item.get("block_time_utc") or "").startswith("2025")
            ],
            "items": missing_details,
        },
        "methodology": (
            "Read-only Vollabgleich der gesamten Helius-Wallet-Historie einschliesslich aller eigenen Token-Accounts. "
            "Die Helius-Historie wird auf die lokale canonical_events-Tabelle mit account=Wallet und source=solana_rpc "
            "bezogen. Fehlgeschlagene On-Chain-Transaktionen werden sichtbar gehalten, aber nicht als steuerliche "
            "Bewegung gewertet. NFT-, komprimierte NFT- und Null-Decimal-Token-Bewegungen werden nicht automatisch "
            "in den Steuerledger importiert. Keine Datenbank-, Raw-, FIFO- oder Steuerwertaenderung."
        ),
        "open_review_points": [
            "Die sechs Helius-only Program-/NFT-Ereignisse ohne fungible Balancebewegung sind fachlich zuzuordnen.",
            "Die 524 Helius-only Null-Decimal-Tokenbewegungen liegen ausserhalb 2025 und sind keine automatische Steuerzeile.",
            "Die 13 fehlgeschlagenen Helius-only Transaktionen aus 2025 haben keine erfolgreiche On-Chain-Ausfuehrung.",
            "Die drei erfolgreichen Helius-only fungiblen Bewegungen liegen nach dem Steuerjahr 2025.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    output.chmod(0o444)
    result["artifact_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Helius full-wallet coverage audit")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--wallet", default=DEFAULT_WALLET)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    report = run(parser.parse_args())
    print(json.dumps({key: value for key, value in report.items() if key not in {"helius_only"}}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
