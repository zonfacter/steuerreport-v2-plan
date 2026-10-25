#!/usr/bin/env python3
from __future__ import annotations

from steuerreport_v2.paths import PROJECT_ROOT as SOFTWARE_ROOT

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService


PROJECT_ROOT = SOFTWARE_ROOT
DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_CLOSURE = PROJECT_ROOT / "var" / "all_transaction_evidence_closures" / "latest_all_transaction_evidence_closure.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var" / "all_transaction_open_detail_reviews"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"


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


def _alchemy_rpc_url(api_key: str) -> str:
    return f"https://solana-mainnet.g.alchemy.com/v2/{api_key}"


def _redacted_rpc_url(url: str) -> str:
    marker = "alchemy.com/v2/"
    if marker in url:
        return url.split(marker, 1)[0] + marker + "<redacted>"
    return url


def _fetch_transaction(client: httpx.Client, rpc_url: str, tx_id: str) -> dict[str, Any] | None:
    response = client.post(
        rpc_url,
        json={
            "jsonrpc": "2.0",
            "id": tx_id[:12],
            "method": "getTransaction",
            "params": [tx_id, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
        },
    )
    response.raise_for_status()
    payload = response.json()
    result = payload.get("result")
    return result if isinstance(result, dict) else None


def _account_key_pubkey(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("pubkey") or "")
    return str(value or "")


def _account_keys(raw: dict[str, Any]) -> list[str]:
    message = raw.get("transaction", {}).get("message", {})
    keys = message.get("accountKeys") if isinstance(message.get("accountKeys"), list) else []
    return [key for key in (_account_key_pubkey(item) for item in keys) if key]


def _signers(raw: dict[str, Any]) -> list[str]:
    message = raw.get("transaction", {}).get("message", {})
    keys = message.get("accountKeys") if isinstance(message.get("accountKeys"), list) else []
    result: list[str] = []
    for item in keys:
        if isinstance(item, dict) and item.get("signer") is True and item.get("pubkey"):
            result.append(str(item["pubkey"]))
    return result


def _collect_instruction_programs(instructions: Any, target: list[str]) -> None:
    if not isinstance(instructions, list):
        return
    for instruction in instructions:
        if isinstance(instruction, dict):
            program_id = instruction.get("programId") or instruction.get("program")
            if program_id:
                target.append(str(program_id))


def _program_ids(raw: dict[str, Any]) -> list[str]:
    message = raw.get("transaction", {}).get("message", {})
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    result: list[str] = []
    _collect_instruction_programs(message.get("instructions"), result)
    for group in meta.get("innerInstructions") if isinstance(meta.get("innerInstructions"), list) else []:
        if isinstance(group, dict):
            _collect_instruction_programs(group.get("instructions"), result)
    return list(dict.fromkeys(result))


def _token_balance_map(items: Any) -> dict[tuple[str, str, str], Decimal]:
    result: dict[tuple[str, str, str], Decimal] = {}
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        owner = str(item.get("owner") or "")
        mint = str(item.get("mint") or "")
        account_index = str(item.get("accountIndex") if item.get("accountIndex") is not None else "")
        amount = _decimal((item.get("uiTokenAmount") or {}).get("uiAmountString") if isinstance(item.get("uiTokenAmount"), dict) else None)
        if mint:
            result[(owner, mint, account_index)] = result.get((owner, mint, account_index), Decimal("0")) + amount
    return result


def _token_deltas(raw: dict[str, Any]) -> list[dict[str, Any]]:
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    pre = _token_balance_map(meta.get("preTokenBalances"))
    post = _token_balance_map(meta.get("postTokenBalances"))
    rows: list[dict[str, Any]] = []
    for owner, mint, account_index in sorted(set(pre) | set(post)):
        before = pre.get((owner, mint, account_index), Decimal("0"))
        after = post.get((owner, mint, account_index), Decimal("0"))
        delta = after - before
        if delta:
            rows.append(
                {
                    "owner": owner,
                    "mint": mint,
                    "account_index": account_index,
                    "pre_amount": before,
                    "post_amount": after,
                    "delta": delta,
                    "asset_hint": "USDC" if mint == USDC_MINT else None,
                }
            )
    return rows


def _load_closure_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("open_rows") if isinstance(payload.get("open_rows"), list) else []
    return [row for row in rows if isinstance(row, dict) and row.get("tx_id")]


def _local_raw_rows(store: DuckDbStore, tx_id: str) -> list[dict[str, Any]]:
    with store.connect() as con:
        rows = con.execute(
            """
            select r.raw_object_id, r.batch_id, r.row_number, substr(r.payload_json, 1, 2400) as payload_preview
            from raw_objects r
            join canonical_events e on e.raw_object_id = r.raw_object_id
            where e.tx_id = ?
            order by r.row_number
            """,
            [tx_id],
        ).fetchall()
    return [
        {
            "raw_object_id": str(row[0]),
            "batch_id": str(row[1]),
            "row_number": int(row[2] or 0),
            "payload_preview": str(row[3] or ""),
        }
        for row in rows
    ]


def _classification(row: dict[str, Any], token_deltas: list[dict[str, Any]], signers: list[str], local_accounts: set[str]) -> str:
    status = str(row.get("review_status") or "")
    has_local_owner_delta = any(str(delta.get("owner") or "") in local_accounts for delta in token_deltas)
    if row.get("tax_impact_detected") and has_local_owner_delta and not (set(signers) & local_accounts):
        return "owner_delta_without_local_signer_tax_review"
    if status == "cex_onchain_txid_found_ledger_match_needed":
        return "cex_ledger_match_required"
    if has_local_owner_delta:
        return "local_owner_token_delta_seen"
    return "route_or_account_owner_review_required"


def build_report(store: DuckDbStore, *, closure_path: Path, timeout_seconds: float = 30.0) -> dict[str, Any]:
    rows = _load_closure_rows(closure_path)
    api_key = WalletFifoPreviewService(store)._alchemy_api_key()
    if not api_key:
        raise RuntimeError("alchemy_api_key_missing")
    rpc_url = _alchemy_rpc_url(api_key)
    details: list[dict[str, Any]] = []
    with httpx.Client(timeout=max(3.0, min(float(timeout_seconds), 60.0))) as client:
        for row in rows:
            tx_id = str(row["tx_id"])
            raw = _fetch_transaction(client, rpc_url, tx_id)
            if raw is None:
                details.append({**row, "detail_status": "alchemy_result_missing", "raw_rows": _local_raw_rows(store, tx_id)})
                continue
            signers = _signers(raw)
            keys = _account_keys(raw)
            programs = _program_ids(raw)
            deltas = _token_deltas(raw)
            local_accounts = {item.strip() for item in str(row.get("accounts") or "").split(",") if item.strip()}
            details.append(
                {
                    **row,
                    "detail_status": "alchemy_detail_found",
                    "slot": raw.get("slot"),
                    "block_time_utc": (
                        datetime.fromtimestamp(int(raw["blockTime"]), tz=timezone.utc).isoformat()
                        if isinstance(raw.get("blockTime"), int)
                        else None
                    ),
                    "fee_lamports": (raw.get("meta") or {}).get("fee") if isinstance(raw.get("meta"), dict) else None,
                    "meta_err": (raw.get("meta") or {}).get("err") if isinstance(raw.get("meta"), dict) else None,
                    "signers": signers,
                    "account_keys_sample": keys[:30],
                    "program_ids": programs,
                    "token_deltas": deltas,
                    "local_account_seen_in_keys": bool(set(keys) & local_accounts),
                    "local_account_seen_as_token_owner": any(str(delta.get("owner") or "") in local_accounts for delta in deltas),
                    "detail_classification": _classification(row, deltas, signers, local_accounts),
                    "raw_rows": _local_raw_rows(store, tx_id),
                }
            )
    classification_counts: dict[str, int] = {}
    for detail in details:
        key = str(detail.get("detail_classification") or detail.get("detail_status") or "unknown")
        classification_counts[key] = classification_counts.get(key, 0) + 1
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "closure_path": str(closure_path),
        "provider": "alchemy",
        "rpc_url": _redacted_rpc_url(rpc_url),
        "open_tx_count": len(details),
        "tax_impact_open_count": sum(1 for row in details if row.get("tax_impact_detected")),
        "classification_counts": classification_counts,
        "rows": details,
        "methodology": (
            "Read-only Detailreview fuer offene Transaktionen aus dem Abschlussreport. "
            "Je TxID werden Alchemy getTransaction, Signer, Programme, Token-Deltas, lokale Raw-Previews "
            "und direkte Steuerwirkung zusammengefuehrt. Der Report schreibt keine Steuerdaten und "
            "entscheidet nicht automatisch ueber Income/Transfer."
        ),
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default), encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Detailreview fuer offene Transaktionen.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--closure", default=str(DEFAULT_CLOSURE))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()

    result = build_report(DuckDbStore(args.db), closure_path=Path(args.closure), timeout_seconds=args.timeout_seconds)
    output_dir = Path(args.output_dir)
    run_id = datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"{run_id}_all_transaction_open_detail_review.json"
    latest_path = output_dir / "latest_all_transaction_open_detail_review.json"
    _write(output_path, result)
    _write(latest_path, result)
    print(
        f"wrote {output_path} open_tx={result['open_tx_count']} "
        f"tax_impact={result['tax_impact_open_count']} classifications={result['classification_counts']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
