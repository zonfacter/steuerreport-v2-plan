#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import time
from typing import Any

import httpx

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.secrets import resolve_secret_value


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var/solana_native_balance_coverage"
DEFAULT_WALLET = "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
LAMPORTS_PER_SOL = Decimal("1000000000")
BALANCE_EFFECTIVE_STATUSES = {"onchain_success", "onchain_failed"}


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
    return (Decimal(int(post[index])) - Decimal(int(pre[index]))) / LAMPORTS_PER_SOL


def _token_balance_row(value: object) -> tuple[int, str, str, Decimal, int] | None:
    if not isinstance(value, dict) or value.get("accountIndex") is None:
        return None
    amount = value.get("uiTokenAmount") if isinstance(value.get("uiTokenAmount"), dict) else {}
    decimals = int(amount.get("decimals") or 0)
    raw = _decimal(amount.get("amount"))
    return (
        int(value["accountIndex"]),
        str(value.get("mint") or ""),
        str(value.get("owner") or ""),
        raw / (Decimal(10) ** decimals),
        decimals,
    )


def wallet_token_account_changes(
    transaction: dict[str, Any],
    wallet: str,
) -> list[dict[str, object]]:
    keys = _account_keys(transaction)
    meta = transaction.get("meta") if isinstance(transaction.get("meta"), dict) else {}
    pre_rows = [_token_balance_row(row) for row in meta.get("preTokenBalances") or []]
    post_rows = [_token_balance_row(row) for row in meta.get("postTokenBalances") or []]
    pre = {
        (row[0], row[1]): row
        for row in pre_rows
        if row is not None and row[2] == wallet and row[1]
    }
    post = {
        (row[0], row[1]): row
        for row in post_rows
        if row is not None and row[2] == wallet and row[1]
    }
    result: list[dict[str, object]] = []
    for account_index, mint in sorted(set(pre) | set(post)):
        before = pre.get((account_index, mint))
        after = post.get((account_index, mint))
        decimals = (after or before or (0, "", "", Decimal("0"), 0))[4]
        pre_quantity = before[3] if before is not None else Decimal("0")
        post_quantity = after[3] if after is not None else Decimal("0")
        result.append(
            {
                "token_account": keys[account_index] if account_index < len(keys) else "",
                "account_index": account_index,
                "mint": mint,
                "decimals": decimals,
                "pre_quantity": str(pre_quantity),
                "post_quantity": str(post_quantity),
                "quantity_delta": str(post_quantity - pre_quantity),
            }
        )
    return result


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
        options: dict[str, object] = {"limit": 1000, "commitment": "finalized"}
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


def _balance_snapshot(client: httpx.Client, rpc_url: str, wallet: str, label: str) -> dict[str, object]:
    result = _rpc(
        client,
        rpc_url,
        "getBalance",
        [wallet, {"commitment": "finalized"}],
        f"balance-{label}",
    )
    context = result.get("context") if isinstance(result, dict) and isinstance(result.get("context"), dict) else {}
    lamports = int(result.get("value") or 0) if isinstance(result, dict) else 0
    return {
        "slot": int(context.get("slot") or 0),
        "lamports": lamports,
        "quantity_sol": str(Decimal(lamports) / LAMPORTS_PER_SOL),
    }


def _chain_row(
    signature_row: dict[str, object],
    transaction: dict[str, Any] | None,
    wallet: str,
) -> dict[str, object]:
    signature = str(signature_row.get("signature") or "")
    block_time = transaction.get("blockTime") if isinstance(transaction, dict) else signature_row.get("blockTime")
    base = {
        "signature": signature,
        "slot": transaction.get("slot") if isinstance(transaction, dict) else signature_row.get("slot"),
        "block_time_utc": (
            datetime.fromtimestamp(int(block_time), tz=timezone.utc).isoformat()
            if block_time is not None
            else None
        ),
    }
    if not isinstance(transaction, dict):
        return {
            **base,
            "chain_status": "transaction_missing",
            "error": signature_row.get("err"),
        }
    meta = transaction.get("meta") if isinstance(transaction.get("meta"), dict) else {}
    keys = _account_keys(transaction)
    fee_lamports = int(meta.get("fee") or 0)
    wallet_paid_fee = bool(keys) and keys[0] == wallet
    return {
        **base,
        "chain_status": "onchain_failed" if meta.get("err") is not None else "onchain_success",
        "error": meta.get("err") or signature_row.get("err"),
        "wallet_native_sol_delta": str(wallet_native_delta(transaction, wallet)),
        "wallet_paid_fee": wallet_paid_fee,
        "wallet_fee_sol": str(
            Decimal(fee_lamports) / LAMPORTS_PER_SOL if wallet_paid_fee else Decimal("0")
        ),
        "signers": _signers(transaction)[:10],
        "wallet_token_account_changes": wallet_token_account_changes(transaction, wallet),
    }


def _canonical_native_effects(
    store: DuckDbStore,
    signatures: list[str],
    wallet: str,
) -> dict[str, Decimal]:
    if not signatures:
        return {}
    with store.connect() as con:
        rows = con.execute(
            """
            select event.tx_id, sum(ledger.delta_quantity)
            from balance_ledger ledger
            join canonical_events event on event.event_id = ledger.event_id
            where ledger.account = ?
              and ledger.asset = 'SOL'
              and event.tx_id in (select unnest(?))
            group by event.tx_id
            """,
            [wallet, signatures],
        ).fetchall()
    return {str(signature): _decimal(quantity) for signature, quantity in rows}


def _ledger_state(
    store: DuckDbStore,
    signatures: list[str],
    wallet: str,
) -> dict[str, object]:
    with store.connect() as con:
        total = _decimal(
            con.execute(
                """
                select coalesce(sum(delta_quantity), 0)
                from balance_ledger
                where account = ? and asset = 'SOL'
                """,
                [wallet],
            ).fetchone()[0]
        )
        source_rows = con.execute(
            """
            select event.source, coalesce(sum(ledger.delta_quantity), 0), count(*)
            from balance_ledger ledger
            join canonical_events event on event.event_id = ledger.event_id
            where ledger.account = ?
              and ledger.asset = 'SOL'
              and (
                event.tx_id is null
                or event.tx_id not in (select unnest(?))
              )
            group by event.source
            order by event.source
            """,
            [wallet, signatures],
        ).fetchall()
        opening = _decimal(
            con.execute(
                """
                select coalesce(sum(ledger.delta_quantity), 0)
                from balance_ledger ledger
                join canonical_events event on event.event_id = ledger.event_id
                where ledger.account = ?
                  and ledger.asset = 'SOL'
                  and event.source like 'opening-balance%'
                """,
                [wallet],
            ).fetchone()[0]
        )
    non_chain_quantity = sum((_decimal(row[1]) for row in source_rows), Decimal("0"))
    return {
        "current_ledger_quantity": str(total),
        "documented_opening_balance_quantity": str(opening),
        "non_chain_signature_quantity": str(non_chain_quantity),
        "non_chain_signature_sources": [
            {"source": str(source), "quantity": str(quantity), "entries_count": int(count)}
            for source, quantity, count in source_rows
        ],
    }


def enrich_rows(
    rows: list[dict[str, object]],
    canonical_effects: dict[str, Decimal],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for row in rows:
        signature = str(row.get("signature") or "")
        chain = _decimal(row.get("wallet_native_sol_delta"))
        canonical = canonical_effects.get(signature, Decimal("0"))
        if row.get("chain_status") not in BALANCE_EFFECTIVE_STATUSES:
            status = str(row.get("chain_status") or "chain_error")
        elif chain == canonical:
            status = "canonical_quantity_matched" if chain else "unchanged_wallet_balance"
        elif canonical == 0:
            status = "canonical_missing_balance_change"
        else:
            status = "canonical_quantity_mismatch"
        result.append(
            {
                **row,
                "canonical_native_sol_effect": str(canonical),
                "missing_native_sol_effect": str(chain - canonical),
                "evidence_status": status,
            }
        )
    return result


def reconciliation_summary(
    rows: list[dict[str, object]],
    ledger_state: dict[str, object],
    start_balance: dict[str, object],
    end_balance: dict[str, object],
    history_complete: bool,
) -> dict[str, object]:
    balance_effective = [
        row for row in rows if row.get("chain_status") in BALANCE_EFFECTIVE_STATUSES
    ]
    chain_total = sum(
        (_decimal(row.get("wallet_native_sol_delta")) for row in balance_effective),
        Decimal("0"),
    )
    canonical_total = sum(
        (_decimal(row.get("canonical_native_sol_effect")) for row in balance_effective),
        Decimal("0"),
    )
    missing_total = chain_total - canonical_total
    ledger_total = _decimal(ledger_state.get("current_ledger_quantity"))
    opening = _decimal(ledger_state.get("documented_opening_balance_quantity"))
    non_chain = _decimal(ledger_state.get("non_chain_signature_quantity"))
    after_tx_corrections = ledger_total + missing_total
    after_non_chain_replacement = after_tx_corrections - non_chain
    start = _decimal(start_balance.get("quantity_sol"))
    end = _decimal(end_balance.get("quantity_sol"))
    stable = start == end
    chain_matches = history_complete and stable and chain_total == end
    replacement_matches = chain_matches and after_non_chain_replacement == end
    return {
        "history_complete": history_complete,
        "snapshot_stable": stable,
        "chain_native_sol_total": str(chain_total),
        "canonical_exact_tx_native_sol_total": str(canonical_total),
        "missing_exact_tx_native_sol_total": str(missing_total),
        "current_ledger_quantity": str(ledger_total),
        "documented_opening_balance_quantity": str(opening),
        "non_chain_signature_quantity": str(non_chain),
        "ledger_after_exact_tx_corrections": str(after_tx_corrections),
        "ledger_after_non_chain_replacement": str(after_non_chain_replacement),
        "live_quantity_sol": str(end),
        "chain_net_matches_live": chain_matches,
        "replacement_plan_matches_live": replacement_matches,
    }


def _resume_rows(path: Path, wallet: str) -> dict[str, dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if payload.get("wallet") != wallet:
        return {}
    return {
        str(row.get("signature")): row
        for row in payload.get("chain_transactions", [])
        if isinstance(row, dict)
        and row.get("signature")
        and row.get("wallet_native_sol_delta") is not None
        and row.get("wallet_token_account_changes") is not None
    }


def _write_checkpoint(path: Path, wallet: str, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"wallet": wallet, "chain_transactions": rows}, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def historical_token_accounts(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    accounts: dict[tuple[str, str], dict[str, object]] = {}
    for transaction in rows:
        if transaction.get("chain_status") not in BALANCE_EFFECTIVE_STATUSES:
            continue
        for change in transaction.get("wallet_token_account_changes", []):
            if not isinstance(change, dict):
                continue
            token_account = str(change.get("token_account") or "")
            mint = str(change.get("mint") or "")
            if not token_account or not mint:
                continue
            key = (token_account, mint)
            current = accounts.setdefault(
                key,
                {
                    "token_account": token_account,
                    "mint": mint,
                    "decimals": int(change.get("decimals") or 0),
                    "first_slot": transaction.get("slot"),
                    "first_seen_utc": transaction.get("block_time_utc"),
                    "last_slot": transaction.get("slot"),
                    "last_seen_utc": transaction.get("block_time_utc"),
                    "transactions_count": 0,
                },
            )
            current["transactions_count"] = int(current["transactions_count"]) + 1
            if int(transaction.get("slot") or 0) < int(current.get("first_slot") or 0):
                current["first_slot"] = transaction.get("slot")
                current["first_seen_utc"] = transaction.get("block_time_utc")
            if int(transaction.get("slot") or 0) > int(current.get("last_slot") or 0):
                current["last_slot"] = transaction.get("slot")
                current["last_seen_utc"] = transaction.get("block_time_utc")
    return sorted(accounts.values(), key=lambda row: (str(row["mint"]), str(row["token_account"])))


def run(args: argparse.Namespace) -> dict[str, object]:
    store = DuckDbStore(Path(args.db))
    api_key = resolve_secret_value(store, "secret.alchemy.api_key")
    if not api_key:
        raise RuntimeError("secret.alchemy.api_key is not configured")
    rpc_url = f"https://solana-mainnet.g.alchemy.com/v2/{api_key}"
    output_dir = Path(args.output_dir)
    checkpoint_path = output_dir / f".{args.wallet}_native_coverage_checkpoint.json"
    resume = _resume_rows(checkpoint_path, args.wallet)
    latest_path = output_dir / f"latest_{args.wallet}_native_balance_coverage.json"
    if not resume:
        resume = _resume_rows(latest_path, args.wallet)
    chain_rows: list[dict[str, object]] = []
    fetched_count = 0
    with httpx.Client(timeout=45) as client:
        start_balance = _balance_snapshot(client, rpc_url, args.wallet, "start")
        signatures, history_complete = _signature_history(
            client,
            rpc_url,
            args.wallet,
            max(1, args.max_pages),
        )
        for index, signature_row in enumerate(signatures):
            signature = str(signature_row.get("signature") or "")
            if signature in resume:
                chain_rows.append(resume[signature])
                continue
            if fetched_count and args.delay_seconds:
                time.sleep(args.delay_seconds)
            fetched = _rpc(
                client,
                rpc_url,
                "getTransaction",
                [
                    signature,
                    {
                        "encoding": "jsonParsed",
                        "maxSupportedTransactionVersion": 0,
                        "commitment": "finalized",
                    },
                ],
                f"tx-{index + 1}",
            )
            transaction = fetched if isinstance(fetched, dict) else None
            fetched_count += 1
            chain_rows.append(_chain_row(signature_row, transaction, args.wallet))
            if len(chain_rows) % max(1, args.checkpoint_every) == 0:
                _write_checkpoint(checkpoint_path, args.wallet, chain_rows)
        end_balance = _balance_snapshot(client, rpc_url, args.wallet, "end")

    signature_values = [str(row.get("signature") or "") for row in chain_rows if row.get("signature")]
    canonical = _canonical_native_effects(store, signature_values, args.wallet)
    rows = enrich_rows(chain_rows, canonical)
    ledger_state = _ledger_state(store, signature_values, args.wallet)
    summary = reconciliation_summary(rows, ledger_state, start_balance, end_balance, history_complete)
    token_accounts = historical_token_accounts(rows)
    generated_at = datetime.now(timezone.utc)
    report = {
        "generated_at": generated_at.isoformat(),
        "wallet": args.wallet,
        "provider": "alchemy_solana_rpc",
        "rpc_url": "https://solana-mainnet.g.alchemy.com/v2/<redacted>",
        "start_balance": start_balance,
        "end_balance": end_balance,
        "history_complete": history_complete,
        "chain_signatures_count": len(signatures),
        "chain_transactions_count": len(rows),
        "transactions_fetched_count": fetched_count,
        "transaction_missing_count": sum(row.get("chain_status") == "transaction_missing" for row in rows),
        "chain_failed_transactions_count": sum(row.get("chain_status") == "onchain_failed" for row in rows),
        "canonical_matched_count": sum(row.get("evidence_status") == "canonical_quantity_matched" for row in rows),
        "canonical_missing_balance_change_count": sum(
            row.get("evidence_status") == "canonical_missing_balance_change" for row in rows
        ),
        "canonical_quantity_mismatch_count": sum(
            row.get("evidence_status") == "canonical_quantity_mismatch" for row in rows
        ),
        "ledger_state": ledger_state,
        "reconciliation": summary,
        "historical_token_accounts_count": len(token_accounts),
        "historical_token_accounts": token_accounts,
        "chain_transactions": rows,
        "target_changed": False,
        "methodology": (
            "Read-only Vollabgleich aller finalisierten Wallet-Signaturen. Fuer jede erfolgreiche "
            "Transaktion wird die native Lamport-Differenz der Wallet kontenindexbasiert aus "
            "preBalances/postBalances berechnet und mit der SOL-Wirkung im V2 balance_ledger unter "
            "derselben TxID verglichen. Die Summe der Blockchain-Deltas muss dem finalisierten "
            "getBalance entsprechen. Dokumentierte Opening-Balances werden getrennt ausgewiesen."
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    content = json.dumps(report, indent=2, ensure_ascii=False)
    versioned = output_dir / f"native_balance_coverage_{generated_at.strftime('%Y%m%dT%H%M%SZ')}_{args.wallet}.json"
    latest = latest_path
    versioned.write_text(content, encoding="utf-8")
    latest.write_text(content, encoding="utf-8")
    checkpoint_path.unlink(missing_ok=True)
    report["artifact_path"] = str(versioned.relative_to(PROJECT_ROOT))
    report["latest_artifact_path"] = str(latest.relative_to(PROJECT_ROOT))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Alchemy native SOL balance coverage audit")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--wallet", default=DEFAULT_WALLET)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--delay-seconds", type=float, default=0.03)
    parser.add_argument("--checkpoint-every", type=int, default=100)
    args = parser.parse_args()
    report = run(args)
    print(
        json.dumps(
            {key: value for key, value in report.items() if key != "chain_transactions"},
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
