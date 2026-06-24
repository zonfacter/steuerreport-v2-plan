#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"
DEFAULT_RPC_URLS = [
    DEFAULT_RPC_URL,
    "https://solana-rpc.publicnode.com",
    "https://solana.publicnode.dev",
]
DEFAULT_WALLET = "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY"
DEFAULT_FROM_TIME = "2026-06-19T21:39:00+00:00"
DEFAULT_TO_TIME = "2026-06-19T21:42:00+00:00"

HELIUM_REWARD_INSTRUCTIONS = {
    "setcurrentrewardswrapperv1",
    "setcurrentrewardsv0",
    "distributecompressionrewardsv0",
}

TOKEN_MINTS = {
    "HNT": "hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux",
    "IOT": "iotEVVZLEywoTn1QdwNPddxPWszn3zFhEot3MfL9fns",
    "MOBILE": "mb1eu7TzEc71KxDpsmsKoucSSuuoGLv1drys1oP2jh6",
}
SYMBOL_BY_MINT = {mint: symbol for symbol, mint in TOKEN_MINTS.items()}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Helium/Solana Reward-Evidence per Solana RPC."
    )
    parser.add_argument("--wallet", default=DEFAULT_WALLET)
    parser.add_argument("--from-time", default=DEFAULT_FROM_TIME)
    parser.add_argument("--to-time", default=DEFAULT_TO_TIME)
    parser.add_argument("--rpc-url", default="")
    parser.add_argument("--max-signatures", type=int, default=80)
    parser.add_argument("--max-transactions", type=int, default=80)
    parser.add_argument("--delay-seconds", type=float, default=0.15)
    parser.add_argument("--retry-seconds", type=float, default=2.0)
    parser.add_argument("--signatures", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    from_time = _parse_datetime(args.from_time)
    to_time = _parse_datetime(args.to_time)
    output = Path(args.output) if args.output else _default_output_path(args.wallet, from_time, to_time)
    rpc_urls = [args.rpc_url] if args.rpc_url else DEFAULT_RPC_URLS
    report = verify_rewards(
        wallet=args.wallet,
        from_time=from_time,
        to_time=to_time,
        rpc_urls=rpc_urls,
        max_signatures=max(1, args.max_signatures),
        max_transactions=max(1, args.max_transactions),
        delay_seconds=max(0.0, args.delay_seconds),
        retry_seconds=max(0.0, args.retry_seconds),
        signatures=[item.strip() for item in args.signatures.split(",") if item.strip()],
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({**report["summary"], "artifact_path": str(output)}, indent=2, default=str))
    return 0


def verify_rewards(
    *,
    wallet: str,
    from_time: datetime,
    to_time: datetime,
    rpc_urls: list[str],
    max_signatures: int,
    max_transactions: int,
    delay_seconds: float,
    retry_seconds: float,
    signatures: list[str] | None = None,
) -> dict[str, Any]:
    rpc_stats = {"requests": 0, "rate_limited": 0, "failed": 0}
    if signatures:
        all_signatures: list[dict[str, object]] = [
            {"signature": signature, "blockTime": None}
            for signature in signatures
        ]
        selected = all_signatures[:max_transactions]
    else:
        signatures_payload = _rpc_any(
            rpc_urls,
            "getSignaturesForAddress",
            [
                wallet,
                {
                    "limit": min(max_signatures, 1000),
                },
            ],
            stats=rpc_stats,
            retry_seconds=retry_seconds,
        )
        all_signatures = [
            item
            for item in signatures_payload
            if isinstance(item, dict)
            and item.get("signature")
            and item.get("blockTime") is not None
        ]
        selected = [
            item
            for item in all_signatures
            if from_time.timestamp() <= int(item["blockTime"]) <= to_time.timestamp()
        ][:max_transactions]

    rows: list[dict[str, Any]] = []
    transactions_checked = 0
    reward_instruction_transactions = 0
    for index, item in enumerate(selected):
        if index > 0 and delay_seconds:
            time.sleep(delay_seconds)
        signature = str(item["signature"])
        try:
            tx = _rpc_any(
                rpc_urls,
                "getTransaction",
                [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
                stats=rpc_stats,
                retry_seconds=retry_seconds,
            )
        except RuntimeError as exc:
            rows.append(
                {
                    "signature": signature,
                    "block_time": int(item["blockTime"]) if item.get("blockTime") is not None else None,
                    "event_time": (
                        datetime.fromtimestamp(int(item["blockTime"]), timezone.utc).isoformat()
                        if item.get("blockTime") is not None
                        else None
                    ),
                    "asset": None,
                    "quantity": "0",
                    "reward_instruction_detected": False,
                    "reward_instruction_logs": [],
                    "classification": "rpc_failed",
                    "error": str(exc),
                }
            )
            continue
        if not isinstance(tx, dict):
            continue
        transactions_checked += 1
        block_time = int(tx["blockTime"]) if tx.get("blockTime") is not None else (
            int(item["blockTime"]) if item.get("blockTime") is not None else None
        )
        logs = _log_messages(tx)
        reward_logs = reward_instruction_logs(logs)
        if reward_logs:
            reward_instruction_transactions += 1
        deltas = token_deltas_for_wallet(tx, wallet)
        for symbol, quantity in sorted(deltas.items()):
            if symbol not in TOKEN_MINTS or quantity <= 0:
                continue
            rows.append(
                {
                    "signature": signature,
                    "block_time": block_time,
                    "event_time": (
                        datetime.fromtimestamp(block_time, timezone.utc).isoformat()
                        if block_time is not None
                        else None
                    ),
                    "asset": symbol,
                    "quantity": str(quantity),
                    "reward_instruction_detected": bool(reward_logs),
                    "reward_instruction_logs": reward_logs,
                    "classification": (
                        "helium_reward"
                        if reward_logs
                        else "positive_transfer_without_reward_instruction"
                    ),
                }
            )

    reward_rows = [row for row in rows if row["classification"] == "helium_reward"]
    totals: dict[str, Decimal] = {}
    for row in reward_rows:
        asset = str(row["asset"])
        totals[asset] = totals.get(asset, Decimal("0")) + Decimal(str(row["quantity"]))
    return {
        "summary": {
            "wallet": wallet,
            "from_time": from_time.isoformat(),
            "to_time": to_time.isoformat(),
            "rpc_urls": [_redact_rpc_url(url) for url in rpc_urls],
            "rpc_requests": rpc_stats["requests"],
            "rpc_rate_limited": rpc_stats["rate_limited"],
            "rpc_failed": rpc_stats["failed"],
            "signatures_seen": len(all_signatures),
            "manual_signatures": bool(signatures),
            "signatures_in_window": len(selected),
            "transactions_checked": transactions_checked,
            "reward_instruction_transactions": reward_instruction_transactions,
            "reward_rows": len(reward_rows),
            "reward_totals": {asset: str(quantity) for asset, quantity in sorted(totals.items())},
            "target_changed": False,
            "import_effect": "none",
        },
        "rows": rows,
        "methodology": (
            "Read-only Solana-RPC Evidence: getSignaturesForAddress begrenzt auf "
            "das Zeitfenster, getTransaction je Signatur, positive HNT/IOT/MOBILE-"
            "Token-Balance-Deltas fuer die Wallet plus Helium Reward-Instructions "
            "in meta.logMessages. Es werden keine Raw-Objects, Canonical Events "
            "oder Tax-Lines geschrieben."
        ),
    }


def token_deltas_for_wallet(tx: dict[str, Any], wallet: str) -> dict[str, Decimal]:
    meta = tx.get("meta") if isinstance(tx.get("meta"), dict) else {}
    pre = _token_balance_map(meta.get("preTokenBalances"), wallet)
    post = _token_balance_map(meta.get("postTokenBalances"), wallet)
    result: dict[str, Decimal] = {}
    for mint in sorted(set(pre) | set(post)):
        symbol = SYMBOL_BY_MINT.get(mint)
        if symbol is None:
            continue
        result[symbol] = post.get(mint, Decimal("0")) - pre.get(mint, Decimal("0"))
    return result


def _redact_rpc_url(url: str) -> str:
    if "alchemy.com/v2/" in url:
        return re.sub(r"(/v2/)[^/?#]+", r"\1<redacted>", url)
    if "api-key=" in url:
        return re.sub(r"(api-key=)[^&#]+", r"\1<redacted>", url)
    return url


def reward_instruction_logs(logs: list[str]) -> list[str]:
    matched: list[str] = []
    for log in logs:
        normalized = re.sub(r"[^a-z0-9]", "", log.lower())
        if any(instruction in normalized for instruction in HELIUM_REWARD_INSTRUCTIONS):
            matched.append(log)
    return matched


def _token_balance_map(value: object, wallet: str) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    if not isinstance(value, list):
        return result
    for item in value:
        if not isinstance(item, dict):
            continue
        owner = str(item.get("owner") or "")
        if owner and owner != wallet:
            continue
        mint = str(item.get("mint") or "")
        amount = item.get("uiTokenAmount") if isinstance(item.get("uiTokenAmount"), dict) else {}
        quantity = Decimal(str(amount.get("uiAmountString") or "0"))
        if mint:
            result[mint] = result.get(mint, Decimal("0")) + quantity
    return result


def _log_messages(tx: dict[str, Any]) -> list[str]:
    meta = tx.get("meta") if isinstance(tx.get("meta"), dict) else {}
    logs = meta.get("logMessages")
    return [str(item) for item in logs] if isinstance(logs, list) else []


def _rpc_any(
    rpc_urls: list[str],
    method: str,
    params: list[object],
    *,
    stats: dict[str, int] | None = None,
    retry_seconds: float = 0.0,
) -> object:
    errors: list[str] = []
    for rpc_url in rpc_urls:
        try:
            return _rpc(rpc_url, method, params, stats=stats)
        except RuntimeError as exc:
            errors.append(str(exc))
            if "http_429" in str(exc) and retry_seconds > 0:
                time.sleep(retry_seconds)
                try:
                    return _rpc(rpc_url, method, params, stats=stats)
                except RuntimeError as retry_exc:
                    errors.append(str(retry_exc))
            continue
    raise RuntimeError("; ".join(errors[-3:]))


def _rpc(
    rpc_url: str,
    method: str,
    params: list[object],
    *,
    stats: dict[str, int] | None = None,
) -> object:
    request = urllib.request.Request(
        rpc_url,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if stats is not None:
                stats["requests"] += 1
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        if stats is not None:
            stats["requests"] += 1
            if exc.code == 429:
                stats["rate_limited"] += 1
            else:
                stats["failed"] += 1
        raise RuntimeError(f"{rpc_url}:{method}:http_{exc.code}") from exc
    except Exception as exc:
        if stats is not None:
            stats["failed"] += 1
        raise RuntimeError(f"{rpc_url}:{method}:{type(exc).__name__}") from exc
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(f"solana_rpc_error:{payload['error']}")
    return payload.get("result") if isinstance(payload, dict) else None


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _default_output_path(wallet: str, from_time: datetime, to_time: datetime) -> Path:
    from_label = from_time.strftime("%Y%m%dT%H%M%SZ")
    to_label = to_time.strftime("%Y%m%dT%H%M%SZ")
    return (
        PROJECT_ROOT
        / "var"
        / "staging_audits"
        / f"helium_solana_reward_evidence_{wallet[:8]}_{wallet[-8:]}_{from_label}_{to_label}.json"
    )


if __name__ == "__main__":
    sys.exit(main())
