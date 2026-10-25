#!/usr/bin/env python3
from __future__ import annotations

from steuerreport_v2.paths import PROJECT_ROOT as SOFTWARE_ROOT

from steuerreport_v2.private_settings import private_value

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import time
from typing import Any

import httpx

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.secrets import resolve_secret_value


PROJECT_ROOT = SOFTWARE_ROOT
DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var/solana_wallet_history_coverage"
DEFAULT_WALLET = private_value('primary_solana_wallet')
MINT_SYMBOLS = {
    "hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux": "HNT",
    "iotEVVZLEywoTn1QdwNPddxPWszn3zFhEot3MfL9fns": "IOT",
    "mb1eu7TzEc71KxDpsmsKoucSSuuoGLv1drys1oP2jh6": "MOBILE",
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": "JUP",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "7atgF8KQo4wJrD5ATGX7t1V2zVvykPJbFfNeVf1icFv1": "CWIF",
}


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except Exception:
        return Decimal("0")


def _account_keys(transaction: dict[str, Any]) -> list[str]:
    tx = transaction.get("transaction") if isinstance(transaction.get("transaction"), dict) else {}
    message = tx.get("message") if isinstance(tx.get("message"), dict) else {}
    rows = message.get("accountKeys") if isinstance(message.get("accountKeys"), list) else []
    return [str(row.get("pubkey") or "") if isinstance(row, dict) else str(row) for row in rows]


def _signers(transaction: dict[str, Any]) -> list[str]:
    tx = transaction.get("transaction") if isinstance(transaction.get("transaction"), dict) else {}
    message = tx.get("message") if isinstance(tx.get("message"), dict) else {}
    rows = message.get("accountKeys") if isinstance(message.get("accountKeys"), list) else []
    return [
        str(row.get("pubkey"))
        for row in rows
        if isinstance(row, dict) and row.get("signer") is True and row.get("pubkey")
    ]


def wallet_native_delta(transaction: dict[str, Any], wallet: str) -> Decimal:
    keys = _account_keys(transaction)
    if wallet not in keys:
        return Decimal("0")
    index = keys.index(wallet)
    meta = transaction.get("meta") if isinstance(transaction.get("meta"), dict) else {}
    pre = meta.get("preBalances") if isinstance(meta.get("preBalances"), list) else []
    post = meta.get("postBalances") if isinstance(meta.get("postBalances"), list) else []
    if index >= len(pre) or index >= len(post):
        return Decimal("0")
    return (Decimal(int(post[index])) - Decimal(int(pre[index]))) / Decimal("1000000000")


def _token_balance_map(value: object, wallet: str) -> dict[str, Decimal]:
    result: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    if not isinstance(value, list):
        return {}
    for row in value:
        if not isinstance(row, dict) or str(row.get("owner") or "") != wallet:
            continue
        mint = str(row.get("mint") or "")
        amount = row.get("uiTokenAmount") if isinstance(row.get("uiTokenAmount"), dict) else {}
        if mint:
            result[mint] += _decimal(amount.get("uiAmountString"))
    return dict(result)


def wallet_token_deltas(transaction: dict[str, Any], wallet: str) -> dict[str, Decimal]:
    meta = transaction.get("meta") if isinstance(transaction.get("meta"), dict) else {}
    pre = _token_balance_map(meta.get("preTokenBalances"), wallet)
    post = _token_balance_map(meta.get("postTokenBalances"), wallet)
    return {
        mint: post.get(mint, Decimal("0")) - pre.get(mint, Decimal("0"))
        for mint in sorted(set(pre) | set(post))
        if post.get(mint, Decimal("0")) - pre.get(mint, Decimal("0")) != 0
    }


def _rpc(client: httpx.Client, rpc_url: str, method: str, params: list[object], request_id: str) -> object:
    for attempt in range(5):
        response = client.post(
            rpc_url,
            json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        )
        if response.status_code == 429 and attempt < 4:
            time.sleep(1.0 + attempt)
            continue
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("error"):
            raise RuntimeError(f"{method}: {payload['error']}")
        return payload.get("result") if isinstance(payload, dict) else None
    raise RuntimeError(f"{method}: retries exhausted")


def _signature_history(
    client: httpx.Client,
    rpc_url: str,
    wallet: str,
    max_pages: int,
) -> tuple[list[dict[str, object]], bool]:
    rows: list[dict[str, object]] = []
    before: str | None = None
    history_complete = False
    for page in range(max_pages):
        options: dict[str, object] = {"limit": 1000}
        if before:
            options["before"] = before
        result = _rpc(
            client,
            rpc_url,
            "getSignaturesForAddress",
            [wallet, options],
            f"signatures-{page + 1}",
        )
        page_rows = [row for row in result if isinstance(row, dict)] if isinstance(result, list) else []
        rows.extend(page_rows)
        if len(page_rows) < 1000:
            history_complete = True
            break
        before = str(page_rows[-1].get("signature") or "")
        if not before:
            break
    return rows, history_complete


def _known_canonical_txids(store: DuckDbStore) -> set[str]:
    with store.connect() as con:
        rows = con.execute(
            "select distinct tx_id from canonical_events where tx_id is not null and trim(tx_id) <> ''"
        ).fetchall()
    return {str(row[0]) for row in rows}


def _resume_rows(path: Path, wallet: str) -> dict[str, dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if payload.get("wallet") != wallet:
        return {}
    return {
        str(row.get("signature")): row
        for row in payload.get("missing_signature_details", [])
        if isinstance(row, dict) and row.get("signature")
    }


def _transaction_row(signature_row: dict[str, object], transaction: dict[str, Any], wallet: str) -> dict[str, object]:
    meta = transaction.get("meta") if isinstance(transaction.get("meta"), dict) else {}
    block_time = transaction.get("blockTime") or signature_row.get("blockTime")
    native_delta = wallet_native_delta(transaction, wallet)
    token_deltas = wallet_token_deltas(transaction, wallet)
    return {
        "signature": str(signature_row.get("signature") or ""),
        "slot": transaction.get("slot") or signature_row.get("slot"),
        "block_time_utc": (
            datetime.fromtimestamp(int(block_time), tz=timezone.utc).isoformat()
            if block_time is not None
            else None
        ),
        "status": "onchain_success" if meta.get("err") is None else "onchain_failed",
        "error": meta.get("err"),
        "fee_lamports": int(meta.get("fee") or 0),
        "wallet_is_signer": wallet in _signers(transaction),
        "signers": _signers(transaction)[:10],
        "native_sol_delta": str(native_delta),
        "token_deltas": [
            {
                "mint": mint,
                "asset": MINT_SYMBOLS.get(mint),
                "quantity_delta": str(quantity),
            }
            for mint, quantity in token_deltas.items()
        ],
        "wallet_balance_changed": native_delta != 0 or bool(token_deltas),
    }


def summarize_rows(rows: list[dict[str, object]]) -> dict[str, str]:
    totals: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for row in rows:
        if row.get("status") != "onchain_success":
            continue
        totals["SOL"] += _decimal(row.get("native_sol_delta"))
        for token in row.get("token_deltas", []):
            if not isinstance(token, dict):
                continue
            key = str(token.get("asset") or f"mint:{token.get('mint')}")
            totals[key] += _decimal(token.get("quantity_delta"))
    return {asset: str(quantity) for asset, quantity in sorted(totals.items()) if quantity != 0}


def run(args: argparse.Namespace) -> dict[str, object]:
    store = DuckDbStore(Path(args.db))
    api_key = resolve_secret_value(store, "secret.alchemy.api_key")
    if not api_key:
        raise RuntimeError("secret.alchemy.api_key is not configured")
    rpc_url = f"https://solana-mainnet.g.alchemy.com/v2/{api_key}"
    output_dir = Path(args.output_dir)
    latest_path = output_dir / f"latest_{args.wallet}_history_coverage.json"
    resume = _resume_rows(latest_path, args.wallet)
    with httpx.Client(timeout=45) as client:
        signatures, history_complete = _signature_history(
            client,
            rpc_url,
            args.wallet,
            max(1, args.max_pages),
        )
        known = _known_canonical_txids(store)
        missing = [row for row in signatures if str(row.get("signature") or "") not in known]
        details: list[dict[str, object]] = []
        checked = 0
        for index, signature_row in enumerate(missing):
            signature = str(signature_row.get("signature") or "")
            if signature in resume:
                details.append(resume[signature])
                continue
            if checked >= args.max_missing_transactions:
                continue
            if signature_row.get("err") is not None:
                details.append(
                    {
                        "signature": signature,
                        "slot": signature_row.get("slot"),
                        "block_time_utc": (
                            datetime.fromtimestamp(int(signature_row["blockTime"]), tz=timezone.utc).isoformat()
                            if signature_row.get("blockTime") is not None
                            else None
                        ),
                        "status": "signature_failed",
                        "error": signature_row.get("err"),
                        "wallet_balance_changed": False,
                    }
                )
                continue
            if checked and args.delay_seconds:
                time.sleep(args.delay_seconds)
            transaction = _rpc(
                client,
                rpc_url,
                "getTransaction",
                [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
                f"tx-{index + 1}",
            )
            checked += 1
            if isinstance(transaction, dict):
                details.append(_transaction_row(signature_row, transaction, args.wallet))
            else:
                details.append(
                    {
                        "signature": signature,
                        "slot": signature_row.get("slot"),
                        "status": "transaction_missing",
                        "wallet_balance_changed": False,
                    }
                )
    detail_by_signature = {str(row.get("signature")): row for row in details}
    ordered_details = [
        detail_by_signature[str(row.get("signature"))]
        for row in missing
        if str(row.get("signature")) in detail_by_signature
    ]
    generated_at = datetime.now(timezone.utc)
    report = {
        "generated_at": generated_at.isoformat(),
        "wallet": args.wallet,
        "provider": "alchemy_solana_rpc",
        "rpc_url": "https://solana-mainnet.g.alchemy.com/v2/<redacted>",
        "history_complete": history_complete,
        "signature_pages": (len(signatures) + 999) // 1000,
        "chain_signatures_count": len(signatures),
        "chain_failed_signatures_count": sum(row.get("err") is not None for row in signatures),
        "canonical_signature_matches_count": sum(
            str(row.get("signature") or "") in known for row in signatures
        ),
        "missing_signatures_count": len(missing),
        "missing_signature_details_count": len(ordered_details),
        "missing_successful_balance_change_count": sum(
            row.get("status") == "onchain_success" and bool(row.get("wallet_balance_changed"))
            for row in ordered_details
        ),
        "missing_delta_totals": summarize_rows(ordered_details),
        "missing_signature_details": ordered_details,
        "target_changed": False,
        "methodology": (
            "Read-only Vollabgleich aller per getSignaturesForAddress erreichbaren Signaturen der Wallet "
            "gegen kanonische TXIDs. Nur bislang fehlende erfolgreiche Signaturen werden per getTransaction "
            "geprueft und als native SOL- bzw. SPL-Token-Balancedelta zusammengefasst. Keine Raw-Objects, "
            "Canonical Events, Ledger, FIFO-Lots, Preise oder Steuerwerte werden veraendert."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    versioned = output_dir / f"history_coverage_{generated_at.strftime('%Y%m%dT%H%M%SZ')}_{args.wallet}.json"
    content = json.dumps(report, indent=2, ensure_ascii=False)
    versioned.write_text(content, encoding="utf-8")
    latest_path.write_text(content, encoding="utf-8")
    report["artifact_path"] = str(versioned.relative_to(PROJECT_ROOT))
    report["latest_artifact_path"] = str(latest_path.relative_to(PROJECT_ROOT))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Alchemy Solana Wallet History Coverage Audit")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--wallet", default=DEFAULT_WALLET)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--max-missing-transactions", type=int, default=1000)
    parser.add_argument("--delay-seconds", type=float, default=0.03)
    args = parser.parse_args()
    report = run(args)
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "missing_signature_details"},
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
