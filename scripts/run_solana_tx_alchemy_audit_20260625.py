#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var" / "solana_tx_alchemy_audits"
FAILED_STATUSES = {"alchemy_failed", "alchemy_not_found", "alchemy_http_error"}


def _log(message: str) -> None:
    print(f"{datetime.now(timezone.utc).isoformat()} {message}", flush=True)


def _alchemy_rpc_url(api_key: str) -> str:
    return f"https://solana-mainnet.g.alchemy.com/v2/{api_key}"


def _redacted_rpc_url(url: str) -> str:
    marker = "alchemy.com/v2/"
    if marker in url:
        return url.split(marker, 1)[0] + marker + "<redacted>"
    return url


def _parse_dt(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def _account_key_pubkey(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("pubkey") or "")
    return str(value or "")


def _collect_account_keys(raw: dict[str, Any]) -> list[str]:
    tx = raw.get("transaction") if isinstance(raw.get("transaction"), dict) else {}
    message = tx.get("message") if isinstance(tx.get("message"), dict) else {}
    keys = message.get("accountKeys") if isinstance(message.get("accountKeys"), list) else []
    return [pubkey for pubkey in (_account_key_pubkey(item) for item in keys) if pubkey]


def _collect_signers(raw: dict[str, Any]) -> list[str]:
    tx = raw.get("transaction") if isinstance(raw.get("transaction"), dict) else {}
    message = tx.get("message") if isinstance(tx.get("message"), dict) else {}
    keys = message.get("accountKeys") if isinstance(message.get("accountKeys"), list) else []
    result: list[str] = []
    for item in keys:
        if isinstance(item, dict) and item.get("signer") is True and item.get("pubkey"):
            result.append(str(item["pubkey"]))
    return result


def _collect_program_ids(raw: dict[str, Any]) -> list[str]:
    tx = raw.get("transaction") if isinstance(raw.get("transaction"), dict) else {}
    message = tx.get("message") if isinstance(tx.get("message"), dict) else {}
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    result: list[str] = []
    _collect_instruction_programs(message.get("instructions"), result)
    inner = meta.get("innerInstructions") if isinstance(meta.get("innerInstructions"), list) else []
    for group in inner:
        if isinstance(group, dict):
            _collect_instruction_programs(group.get("instructions"), result)
    return list(dict.fromkeys(result))


def _collect_instruction_programs(instructions: Any, target: list[str]) -> None:
    if not isinstance(instructions, list):
        return
    for instruction in instructions:
        if isinstance(instruction, dict):
            program_id = instruction.get("programId") or instruction.get("program")
            if program_id:
                target.append(str(program_id))


def _token_amounts(items: Any) -> dict[tuple[str, str], Decimal]:
    result: dict[tuple[str, str], Decimal] = {}
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        owner = str(item.get("owner") or "")
        mint = str(item.get("mint") or "")
        ui = item.get("uiTokenAmount") if isinstance(item.get("uiTokenAmount"), dict) else {}
        quantity = _decimal(ui.get("uiAmountString"))
        if owner and mint:
            result[(owner, mint)] = result.get((owner, mint), Decimal("0")) + quantity
    return result


def _token_delta_count(raw: dict[str, Any]) -> int:
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    pre = _token_amounts(meta.get("preTokenBalances"))
    post = _token_amounts(meta.get("postTokenBalances"))
    return sum(1 for key in set(pre) | set(post) if post.get(key, Decimal("0")) - pre.get(key, Decimal("0")) != 0)


def _fetch_alchemy_transaction(client: httpx.Client, rpc_url: str, tx_id: str) -> tuple[str, dict[str, Any] | None, str | None]:
    response = client.post(
        rpc_url,
        json={
            "jsonrpc": "2.0",
            "id": tx_id[:12],
            "method": "getTransaction",
            "params": [tx_id, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
        },
    )
    if response.status_code == 429:
        return "alchemy_failed", None, "http_429"
    if response.status_code >= 400:
        return "alchemy_http_error", None, f"http_{response.status_code}"
    payload = response.json()
    if payload.get("error"):
        return "alchemy_failed", None, str(payload.get("error"))
    result = payload.get("result")
    if not isinstance(result, dict):
        return "alchemy_not_found", None, "result_missing"
    return "alchemy_found", result, None


def _load_local_transactions(store: DuckDbStore, *, source: str, limit: int) -> list[dict[str, Any]]:
    source_filter = "" if source == "all" else "and lower(source) = lower(?)"
    params: list[object] = []
    if source != "all":
        params.append(source)
    params.append(max(1, int(limit)))
    with store.connect() as con:
        rows = con.execute(
            f"""
            select
                tx_id,
                min(event_time) as first_event_time,
                max(event_time) as last_event_time,
                count(*)::integer as events_count,
                string_agg(distinct source, ', ' order by source) as sources,
                string_agg(distinct upper(asset), ', ' order by upper(asset)) as assets,
                string_agg(distinct coalesce(account, wallet, ''), ', ' order by coalesce(account, wallet, '')) as accounts,
                sum(abs(quantity)) as gross_quantity
            from canonical_events
            where tx_id is not null
              and trim(tx_id) <> ''
              {source_filter}
            group by tx_id
            order by min(event_time), tx_id
            limit ?
            """,
            params,
        ).fetchall()
    return [
        {
            "tx_id": str(row[0]),
            "first_event_time": row[1],
            "last_event_time": row[2],
            "events_count": int(row[3] or 0),
            "sources": str(row[4] or ""),
            "assets": str(row[5] or ""),
            "accounts": [item for item in str(row[6] or "").split(", ") if item],
            "gross_quantity": str(row[7] or "0"),
        }
        for row in rows
    ]


def _audit_row(local: dict[str, Any], status: str, raw: dict[str, Any] | None, error: str | None) -> dict[str, Any]:
    tx_id = str(local["tx_id"])
    if not raw:
        return {
            **local,
            "first_event_time": str(local.get("first_event_time")),
            "last_event_time": str(local.get("last_event_time")),
            "alchemy_status": status,
            "error": error,
            "onchain_confirmed": False,
            "time_matches_local": False,
            "account_seen": False,
            "review_status": "provider_evidence_missing",
        }
    local_time = _parse_dt(local.get("first_event_time"))
    block_time = raw.get("blockTime")
    onchain_time = datetime.fromtimestamp(int(block_time), tz=timezone.utc) if isinstance(block_time, int) else None
    account_keys = set(_collect_account_keys(raw))
    accounts = {str(item) for item in local.get("accounts", []) if str(item)}
    time_delta_seconds = (
        abs(int((onchain_time - local_time).total_seconds()))
        if onchain_time is not None and local_time is not None
        else None
    )
    time_matches = time_delta_seconds is not None and time_delta_seconds <= 120
    account_seen = bool(accounts & account_keys)
    err = raw.get("meta", {}).get("err") if isinstance(raw.get("meta"), dict) else None
    if err:
        review_status = "onchain_transaction_failed"
    elif not time_matches:
        review_status = "timestamp_mismatch"
    elif accounts and not account_seen:
        review_status = "account_not_seen_in_alchemy_tx"
    else:
        review_status = "alchemy_confirmed"
    return {
        **local,
        "first_event_time": str(local.get("first_event_time")),
        "last_event_time": str(local.get("last_event_time")),
        "onchain_time_utc": onchain_time.isoformat() if onchain_time else None,
        "time_delta_seconds": time_delta_seconds,
        "alchemy_status": status,
        "error": error,
        "slot": raw.get("slot"),
        "onchain_confirmed": status == "alchemy_found" and err is None,
        "time_matches_local": time_matches,
        "account_seen": account_seen,
        "signers": _collect_signers(raw)[:8],
        "program_ids": _collect_program_ids(raw)[:25],
        "token_deltas_count": _token_delta_count(raw),
        "review_status": review_status,
    }


def _counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "unknown")
        result[value] = result.get(value, 0) + 1
    return result


def _build_result(*, source: str, limit: int, rows: list[dict[str, Any]], rpc_url: str, started_at: str) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "started_at": started_at,
        "source": source,
        "limit": limit,
        "provider": "alchemy",
        "rpc_url": _redacted_rpc_url(rpc_url),
        "tx_count": len(rows),
        "alchemy_found_count": sum(1 for row in rows if row.get("alchemy_status") == "alchemy_found"),
        "alchemy_failed_count": sum(1 for row in rows if row.get("alchemy_status") in FAILED_STATUSES),
        "confirmed_count": sum(1 for row in rows if row.get("review_status") == "alchemy_confirmed"),
        "review_status_counts": _counts(rows, "review_status"),
        "alchemy_status_counts": _counts(rows, "alchemy_status"),
        "rows": rows,
        "methodology": (
            "Read-only Alchemy getTransaction Audit fuer lokale Solana-TxIDs aus canonical_events. "
            "Geprueft werden Onchain-Auffindbarkeit, Blockzeit und optional lokaler Account-Bezug. "
            "Es werden keine Imports, Tax-Lines, Lots, Review-Decisions oder Preise geschrieben. "
            "RPC-URLs werden redaktiert."
        ),
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Alchemy Audit fuer lokale Solana-TxIDs.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--source", default="solana_rpc", help="'solana_rpc' oder 'all'.")
    parser.add_argument("--limit", type=int, default=100_000)
    parser.add_argument("--delay-seconds", type=float, default=0.05)
    parser.add_argument("--timeout-seconds", type=float, default=20)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    started_at = datetime.now(timezone.utc).isoformat()
    store = DuckDbStore(args.db)
    api_key = WalletFifoPreviewService(store)._alchemy_api_key()
    if not api_key:
        raise SystemExit("alchemy_api_key_missing")
    rpc_url = _alchemy_rpc_url(api_key)
    source_label = args.source.strip().lower() or "solana_rpc"
    output_dir = Path(args.output_dir)
    run_id = datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"{run_id}_{source_label}_tx_alchemy_audit.json"
    latest_path = output_dir / f"latest_{source_label}_tx_alchemy_audit.json"
    cached: dict[str, dict[str, Any]] = {}
    if args.resume and latest_path.exists():
        try:
            previous = json.loads(latest_path.read_text(encoding="utf-8"))
            cached = {
                str(row["tx_id"]): row
                for row in previous.get("rows", [])
                if row.get("tx_id") and row.get("alchemy_status") == "alchemy_found"
            }
        except Exception:
            cached = {}

    local_rows = _load_local_transactions(store, source=source_label, limit=max(1, int(args.limit)))
    audited: list[dict[str, Any]] = []
    _log(f"start source={source_label} tx_count={len(local_rows)} resume_cached={len(cached)}")
    with httpx.Client(timeout=max(3.0, min(float(args.timeout_seconds), 60.0))) as client:
        for index, local in enumerate(local_rows, start=1):
            tx_id = str(local["tx_id"])
            if tx_id in cached:
                audited.append(cached[tx_id] | {"cache_status": "resume"})
                continue
            status, raw, error = _fetch_alchemy_transaction(client, rpc_url, tx_id)
            audited.append(_audit_row(local, status, raw, error))
            if index % 50 == 0 or index == len(local_rows):
                result = _build_result(source=source_label, limit=args.limit, rows=audited, rpc_url=rpc_url, started_at=started_at)
                _write(output_path, result)
                _write(latest_path, result)
                _log(
                    f"progress {index}/{len(local_rows)} found={result['alchemy_found_count']} "
                    f"confirmed={result['confirmed_count']} failed={result['alchemy_failed_count']}"
                )
            if args.delay_seconds > 0:
                time.sleep(float(args.delay_seconds))
    result = _build_result(source=source_label, limit=args.limit, rows=audited, rpc_url=rpc_url, started_at=started_at)
    _write(output_path, result)
    _write(latest_path, result)
    _log(
        f"done output={output_path} latest={latest_path} found={result['alchemy_found_count']} "
        f"confirmed={result['confirmed_count']} failed={result['alchemy_failed_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
