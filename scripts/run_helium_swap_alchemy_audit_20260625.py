#!/usr/bin/env python3
from __future__ import annotations

from steuerreport_v2.paths import PROJECT_ROOT as SOFTWARE_ROOT

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
from steuerreport_v2.domain.tax_years import TaxYearService


PROJECT_ROOT = SOFTWARE_ROOT
DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var" / "helium_swap_alchemy_audits"
TOKEN_MINTS = {
    "HNT": "hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux",
    "IOT": "iotEVVZLEywoTn1QdwNPddxPWszn3zFhEot3MfL9fns",
    "MOBILE": "mb1eu7TzEc71KxDpsmsKoucSSuuoGLv1drys1oP2jh6",
}
SYMBOL_BY_MINT = {mint: symbol for symbol, mint in TOKEN_MINTS.items()}
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


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
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
    signers: list[str] = []
    for item in keys:
        if isinstance(item, dict) and item.get("signer") is True and item.get("pubkey"):
            signers.append(str(item["pubkey"]))
    return signers


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


def _token_deltas(raw: dict[str, Any]) -> list[dict[str, Any]]:
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    pre = _token_amounts(meta.get("preTokenBalances"))
    post = _token_amounts(meta.get("postTokenBalances"))
    rows: list[dict[str, Any]] = []
    for owner, mint in sorted(set(pre) | set(post)):
        delta = post.get((owner, mint), Decimal("0")) - pre.get((owner, mint), Decimal("0"))
        if delta == 0:
            continue
        rows.append(
            {
                "owner": owner,
                "mint": mint,
                "asset": SYMBOL_BY_MINT.get(mint),
                "delta": str(delta),
            }
        )
    return rows


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


def _audit_row(row: Any, status: str, raw: dict[str, Any] | None, error: str | None) -> dict[str, Any]:
    tx_id = str(row.tx_id)
    if not raw:
        return {
            "tx_id": tx_id,
            "year": row.year,
            "local_time_utc": row.first_event_time,
            "account": row.account,
            "assets": row.assets,
            "context_value_eur": str(row.context_value_eur),
            "alchemy_status": status,
            "error": error,
            "provider": "alchemy",
            "onchain_confirmed": False,
            "time_matches_local": False,
            "wallet_seen": False,
            "helium_token_delta_seen": False,
            "review_status": "provider_evidence_missing",
        }
    local_time = _parse_dt(row.first_event_time)
    block_time = raw.get("blockTime")
    onchain_time = (
        datetime.fromtimestamp(int(block_time), tz=timezone.utc)
        if isinstance(block_time, int)
        else None
    )
    account_keys = _collect_account_keys(raw)
    signers = _collect_signers(raw)
    token_deltas = _token_deltas(raw)
    helium_deltas = [item for item in token_deltas if item.get("asset") in TOKEN_MINTS]
    wallet_seen = bool(row.account and str(row.account) in set(account_keys + [str(item.get("owner")) for item in token_deltas]))
    time_delta_seconds = (
        abs(int((onchain_time - local_time).total_seconds()))
        if onchain_time is not None and local_time is not None
        else None
    )
    time_matches = time_delta_seconds is not None and time_delta_seconds <= 120
    err = raw.get("meta", {}).get("err") if isinstance(raw.get("meta"), dict) else None
    review_status = "alchemy_confirmed"
    if err:
        review_status = "onchain_transaction_failed"
    elif not wallet_seen:
        review_status = "wallet_not_seen_in_alchemy_tx"
    elif not helium_deltas:
        review_status = "helium_token_delta_not_seen"
    elif not time_matches:
        review_status = "timestamp_mismatch"
    return {
        "tx_id": tx_id,
        "year": row.year,
        "local_time_utc": row.first_event_time,
        "onchain_time_utc": onchain_time.isoformat() if onchain_time else None,
        "time_delta_seconds": time_delta_seconds,
        "account": row.account,
        "assets": row.assets,
        "context_value_eur": str(row.context_value_eur),
        "alchemy_status": status,
        "error": error,
        "slot": raw.get("slot"),
        "provider": "alchemy",
        "onchain_confirmed": status == "alchemy_found" and err is None,
        "time_matches_local": time_matches,
        "wallet_seen": wallet_seen,
        "helium_token_delta_seen": bool(helium_deltas),
        "signers": signers[:8],
        "program_ids": _collect_program_ids(raw)[:25],
        "helium_token_deltas": helium_deltas,
        "token_deltas_count": len(token_deltas),
        "review_status": review_status,
    }


def _status_counts(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        status = str(row.get(key) or "unknown")
        result[status] = result.get(status, 0) + 1
    return result


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    tmp.replace(path)


def build_result(*, year: int | None, limit: int, rows: list[dict[str, Any]], rpc_url: str, started_at: str) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "started_at": started_at,
        "year": year,
        "limit": limit,
        "provider": "alchemy",
        "rpc_url": _redacted_rpc_url(rpc_url),
        "tx_count": len(rows),
        "alchemy_found_count": sum(1 for row in rows if row.get("alchemy_status") == "alchemy_found"),
        "alchemy_failed_count": sum(1 for row in rows if row.get("alchemy_status") in FAILED_STATUSES),
        "confirmed_count": sum(1 for row in rows if row.get("review_status") == "alchemy_confirmed"),
        "review_status_counts": _status_counts(rows, "review_status"),
        "alchemy_status_counts": _status_counts(rows, "alchemy_status"),
        "rows": rows,
        "methodology": (
            "Read-only Alchemy getTransaction Audit fuer Helium HNT/IOT/MOBILE Swap-/Trading-TxIDs. "
            "Das Artefakt bestaetigt On-Chain-Auffindbarkeit, Blockzeit, Wallet-Bezug und Helium-Token-Deltas. "
            "Es schreibt keine Imports, Tax-Lines, Lots, Review-Decisions oder Preise. RPC-URLs werden redaktiert."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Alchemy Audit fuer Helium-Swap-TxIDs.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--all-years", action="store_true")
    parser.add_argument("--limit", type=int, default=100_000)
    parser.add_argument("--delay-seconds", type=float, default=0.05)
    parser.add_argument("--timeout-seconds", type=float, default=20)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    started_at = datetime.now(timezone.utc).isoformat()
    db = DuckDbStore(args.db)
    api_key = WalletFifoPreviewService(db)._alchemy_api_key()
    if not api_key:
        raise SystemExit("alchemy_api_key_missing")
    rpc_url = _alchemy_rpc_url(api_key)
    year = None if args.all_years else int(args.year)
    output_dir = Path(args.output_dir)
    year_label = "all_years" if year is None else str(year)
    run_id = datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"{run_id}_{year_label}_helium_swap_alchemy_audit.json"
    latest_path = output_dir / f"latest_{year_label}_helium_swap_alchemy_audit.json"
    previous_by_tx: dict[str, dict[str, Any]] = {}
    if args.resume and latest_path.exists():
        try:
            previous = json.loads(latest_path.read_text(encoding="utf-8"))
            previous_by_tx = {
                str(row["tx_id"]): row
                for row in previous.get("rows", [])
                if row.get("tx_id") and row.get("alchemy_status") == "alchemy_found"
            }
        except Exception:
            previous_by_tx = {}

    report = TaxYearService(db).helium_swap_evidence_review(year=year, limit=max(1, int(args.limit)))
    rows = report.rows[: max(1, int(args.limit))]
    audited: list[dict[str, Any]] = []
    _log(f"start year={year_label} tx_count={len(rows)} resume_cached={len(previous_by_tx)}")
    with httpx.Client(timeout=max(3.0, min(float(args.timeout_seconds), 60.0))) as client:
        for index, row in enumerate(rows, start=1):
            cached = previous_by_tx.get(str(row.tx_id))
            if cached is not None:
                audited.append(cached | {"cache_status": "resume"})
                continue
            status, raw, error = _fetch_alchemy_transaction(client, rpc_url, str(row.tx_id))
            audited.append(_audit_row(row, status, raw, error))
            if index % 25 == 0 or index == len(rows):
                result = build_result(year=year, limit=args.limit, rows=audited, rpc_url=rpc_url, started_at=started_at)
                _write_json(output_path, result)
                _write_json(latest_path, result)
                _log(
                    f"progress {index}/{len(rows)} found={result['alchemy_found_count']} "
                    f"confirmed={result['confirmed_count']} failed={result['alchemy_failed_count']}"
                )
            if args.delay_seconds > 0:
                time.sleep(float(args.delay_seconds))
    result = build_result(year=year, limit=args.limit, rows=audited, rpc_url=rpc_url, started_at=started_at)
    _write_json(output_path, result)
    _write_json(latest_path, result)
    _log(
        f"done output={output_path} latest={latest_path} found={result['alchemy_found_count']} "
        f"confirmed={result['confirmed_count']} failed={result['alchemy_failed_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
