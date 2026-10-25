#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any

import httpx

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.secrets import resolve_secret_value


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var/solana_v1_ownership_scope"
DEFAULT_WALLET = "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
DEFAULT_NATIVE_AUDIT = (
    PROJECT_ROOT
    / "var/solana_native_balance_coverage"
    / f"latest_{DEFAULT_WALLET}_native_balance_coverage.json"
)


def _rpc(
    client: httpx.Client,
    rpc_url: str,
    method: str,
    params: list[object],
    request_id: str,
) -> object:
    for attempt in range(5):
        response = client.post(
            rpc_url,
            json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        )
        if response.status_code == 429 and attempt < 4:
            time.sleep(1 + attempt)
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
    address: str,
    max_pages: int,
) -> tuple[list[dict[str, object]], bool]:
    rows: list[dict[str, object]] = []
    before: str | None = None
    complete = False
    for page in range(max_pages):
        options: dict[str, object] = {"limit": 1000, "commitment": "finalized"}
        if before:
            options["before"] = before
        result = _rpc(
            client,
            rpc_url,
            "getSignaturesForAddress",
            [address, options],
            f"signatures-{address[:8]}-{page + 1}",
        )
        page_rows = [row for row in result if isinstance(row, dict)] if isinstance(result, list) else []
        rows.extend(page_rows)
        if len(page_rows) < 1000:
            complete = True
            break
        before = str(page_rows[-1].get("signature") or "")
        if not before:
            break
    return rows, complete


def _load_native_audit(path: Path, wallet: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("wallet") != wallet:
        raise ValueError(f"native audit does not match wallet: {path}")
    if payload.get("history_complete") is not True:
        raise ValueError(f"native wallet history is incomplete: {path}")
    return payload


def _v1_source_rows(store: DuckDbStore) -> tuple[str, list[dict[str, object]]]:
    with store.connect() as con:
        batch = con.execute(
            """
            select batch_id
            from raw_import_batches
            where source = 'solana_rpc'
              and lower(coalesce(filename, '')) like '%.sqlite%'
            order by created_at
            limit 1
            """
        ).fetchone()
    if batch is None:
        raise RuntimeError("original V1 solana_rpc import batch not found")
    batch_id = str(batch[0])
    return batch_id, [
        json.loads(row.payload_json)
        for row in store.list_raw_objects(batch_id, limit=None)
    ]


def _tx_id(row: dict[str, object]) -> str:
    return str(row.get("tx_id") or row.get("signature") or row.get("transaction_hash") or "").strip()


def classify_v1_rows(
    rows: list[dict[str, object]],
    main_wallet_signatures: set[str],
    token_account_signatures: set[str],
) -> dict[str, object]:
    counts: defaultdict[str, int] = defaultdict(int)
    txids: defaultdict[str, set[str]] = defaultdict(set)
    missing_txid_rows = 0
    for row in rows:
        signature = _tx_id(row)
        if not signature:
            missing_txid_rows += 1
            continue
        if signature in main_wallet_signatures:
            scope = "main_wallet_signature"
        elif signature in token_account_signatures:
            scope = "owned_token_account_signature"
        else:
            scope = "outside_owned_wallet_scope"
        counts[scope] += 1
        txids[scope].add(signature)
    ownership_by_txid = {
        signature: scope
        for scope in ("main_wallet_signature", "owned_token_account_signature")
        for signature in sorted(txids[scope])
    }
    return {
        "rows_count": len(rows),
        "missing_txid_rows_count": missing_txid_rows,
        "scope_counts": {scope: counts[scope] for scope in sorted(counts)},
        "scope_txid_counts": {scope: len(txids[scope]) for scope in sorted(txids)},
        "ownership_by_txid": ownership_by_txid,
        "outside_owned_wallet_scope_txids": sorted(txids["outside_owned_wallet_scope"]),
    }


def run(args: argparse.Namespace) -> dict[str, object]:
    store = DuckDbStore(Path(args.db))
    audit_path = Path(args.native_audit)
    native = _load_native_audit(audit_path, args.wallet)
    main_signatures = {
        str(row.get("signature") or "")
        for row in native.get("chain_transactions", [])
        if isinstance(row, dict) and row.get("signature")
    }
    token_accounts = [
        str(row.get("token_account") or "")
        for row in native.get("historical_token_accounts", [])
        if isinstance(row, dict) and row.get("token_account")
    ]
    api_key = resolve_secret_value(store, "secret.alchemy.api_key")
    if not api_key:
        raise RuntimeError("secret.alchemy.api_key is not configured")
    rpc_url = f"https://solana-mainnet.g.alchemy.com/v2/{api_key}"
    token_signatures: set[str] = set()
    account_reports: list[dict[str, object]] = []
    with httpx.Client(timeout=45) as client:
        for index, token_account in enumerate(sorted(set(token_accounts))):
            if index and args.delay_seconds:
                time.sleep(args.delay_seconds)
            rows, complete = _signature_history(
                client,
                rpc_url,
                token_account,
                max(1, args.max_pages),
            )
            signatures = {
                str(row.get("signature") or "") for row in rows if row.get("signature")
            }
            token_signatures.update(signatures)
            account_reports.append(
                {
                    "token_account": token_account,
                    "history_complete": complete,
                    "signatures_count": len(signatures),
                }
            )
    batch_id, v1_rows = _v1_source_rows(store)
    classification = classify_v1_rows(v1_rows, main_signatures, token_signatures)
    generated_at = datetime.now(timezone.utc)
    report = {
        "generated_at": generated_at.isoformat(),
        "wallet": args.wallet,
        "provider": "alchemy_solana_rpc",
        "rpc_url": "https://solana-mainnet.g.alchemy.com/v2/<redacted>",
        "native_audit": str(audit_path.relative_to(PROJECT_ROOT)),
        "v1_batch_id": batch_id,
        "main_wallet_signatures_count": len(main_signatures),
        "historical_token_accounts_count": len(account_reports),
        "token_account_signatures_count": len(token_signatures),
        "token_account_histories_complete": bool(account_reports)
        and all(row["history_complete"] for row in account_reports),
        "token_accounts": account_reports,
        **classification,
        "target_changed": False,
        "methodology": (
            "Read-only Eigentumsabgleich der V1-Solana-Rohzeilen. Eine TxID gehoert nur dann zum "
            "Main-Wallet-Scope, wenn sie in der vollstaendigen Wallet-Signaturhistorie oder in der "
            "vollstaendigen Historie eines aus pre/postTokenBalances belegten eigenen Tokenkontos "
            "vorkommt. Eine alleinige Default-Wallet-Inferenz ist nicht ausreichend."
        ),
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    content = json.dumps(report, indent=2, ensure_ascii=False)
    versioned = output_dir / f"v1_ownership_scope_{generated_at.strftime('%Y%m%dT%H%M%SZ')}_{args.wallet}.json"
    latest = output_dir / f"latest_{args.wallet}_v1_ownership_scope.json"
    versioned.write_text(content, encoding="utf-8")
    latest.write_text(content, encoding="utf-8")
    report["artifact_path"] = str(versioned.relative_to(PROJECT_ROOT))
    report["latest_artifact_path"] = str(latest.relative_to(PROJECT_ROOT))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only V1 Solana sender/token-account ownership audit")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--wallet", default=DEFAULT_WALLET)
    parser.add_argument("--native-audit", default=str(DEFAULT_NATIVE_AUDIT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--delay-seconds", type=float, default=0.03)
    args = parser.parse_args()
    report = run(args)
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "ownership_by_txid"},
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
