#!/usr/bin/env python3
from __future__ import annotations

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


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var/solana_token_account_coverage"
DEFAULT_WALLET = "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY"
DEFAULT_WALLET_AUDIT = (
    PROJECT_ROOT
    / "var/solana_native_balance_coverage"
    / f"latest_{DEFAULT_WALLET}_native_balance_coverage.json"
)
DEFAULT_TARGETS = {
    "HNT": "hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux",
    "IOT": "iotEVVZLEywoTn1QdwNPddxPWszn3zFhEot3MfL9fns",
    "MOBILE": "mb1eu7TzEc71KxDpsmsKoucSSuuoGLv1drys1oP2jh6",
    "JUP": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
    "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "CWIF": "7atgF8KQo4wJrD5ATGX7t1V2zVvykPJbFfNeVf1icFv1",
    "SHARK": "SHARKSYJjqaNyxVfrpnBN9pjgkhwDhatnMyicWPnr1s",
}
MINT_SYMBOLS = {
    "hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux": "HNT",
    "iotEVVZLEywoTn1QdwNPddxPWszn3zFhEot3MfL9fns": "IOT",
    "mb1eu7TzEc71KxDpsmsKoucSSuuoGLv1drys1oP2jh6": "MOBILE",
    "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN": "JUP",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "7atgF8KQo4wJrD5ATGX7t1V2zVvykPJbFfNeVf1icFv1": "CWIF",
    "SHARKSYJjqaNyxVfrpnBN9pjgkhwDhatnMyicWPnr1s": "SHARK",
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


def _raw_token_balance(row: object) -> tuple[str, Decimal, int] | None:
    if not isinstance(row, dict):
        return None
    mint = str(row.get("mint") or "")
    amount = row.get("uiTokenAmount") if isinstance(row.get("uiTokenAmount"), dict) else {}
    decimals = int(amount.get("decimals") or 0)
    raw = _decimal(amount.get("amount"))
    return mint, raw / (Decimal(10) ** decimals), decimals


def token_account_delta(
    transaction: dict[str, Any],
    token_account: str,
    expected_mint: str,
) -> dict[str, object] | None:
    keys = _account_keys(transaction)
    if token_account not in keys:
        return None
    account_index = keys.index(token_account)
    meta = transaction.get("meta") if isinstance(transaction.get("meta"), dict) else {}
    pre_rows = meta.get("preTokenBalances") if isinstance(meta.get("preTokenBalances"), list) else []
    post_rows = meta.get("postTokenBalances") if isinstance(meta.get("postTokenBalances"), list) else []
    pre = next(
        (_raw_token_balance(row) for row in pre_rows if isinstance(row, dict) and row.get("accountIndex") == account_index),
        None,
    )
    post = next(
        (_raw_token_balance(row) for row in post_rows if isinstance(row, dict) and row.get("accountIndex") == account_index),
        None,
    )
    if pre is None and post is None:
        return None
    mint = (post or pre or (expected_mint, Decimal("0"), 0))[0]
    if mint != expected_mint:
        return None
    decimals = (post or pre or (expected_mint, Decimal("0"), 0))[2]
    pre_quantity = pre[1] if pre is not None else Decimal("0")
    post_quantity = post[1] if post is not None else Decimal("0")
    return {
        "account_index": account_index,
        "mint": mint,
        "decimals": decimals,
        "pre_quantity": str(pre_quantity),
        "post_quantity": str(post_quantity),
        "quantity_delta": str(post_quantity - pre_quantity),
    }


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


def _wallet_token_balance_map(value: object, wallet: str) -> dict[str, Decimal]:
    result: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    if not isinstance(value, list):
        return {}
    for row in value:
        if not isinstance(row, dict) or str(row.get("owner") or "") != wallet:
            continue
        token = _raw_token_balance(row)
        if token is not None and token[0]:
            result[token[0]] += token[1]
    return dict(result)


def wallet_token_deltas(
    transaction: dict[str, Any],
    wallet: str,
    mint_symbols: dict[str, str] | None = None,
) -> list[dict[str, str | None]]:
    symbols = mint_symbols or MINT_SYMBOLS
    meta = transaction.get("meta") if isinstance(transaction.get("meta"), dict) else {}
    pre = _wallet_token_balance_map(meta.get("preTokenBalances"), wallet)
    post = _wallet_token_balance_map(meta.get("postTokenBalances"), wallet)
    return [
        {
            "mint": mint,
            "asset": symbols.get(mint),
            "quantity_delta": str(post.get(mint, Decimal("0")) - pre.get(mint, Decimal("0"))),
        }
        for mint in sorted(set(pre) | set(post))
        if post.get(mint, Decimal("0")) - pre.get(mint, Decimal("0")) != 0
    ]


def transaction_program_summary(
    transaction: dict[str, Any],
    token_account: str,
    expected_mint: str,
) -> dict[str, object]:
    tx = transaction.get("transaction") if isinstance(transaction.get("transaction"), dict) else {}
    message = tx.get("message") if isinstance(tx.get("message"), dict) else {}
    meta = transaction.get("meta") if isinstance(transaction.get("meta"), dict) else {}
    account_keys = message.get("accountKeys") if isinstance(message.get("accountKeys"), list) else []
    signers = [
        str(row.get("pubkey"))
        for row in account_keys
        if isinstance(row, dict) and row.get("signer") is True and row.get("pubkey")
    ]
    instructions = list(message.get("instructions") or [])
    for group in meta.get("innerInstructions") if isinstance(meta.get("innerInstructions"), list) else []:
        if isinstance(group, dict) and isinstance(group.get("instructions"), list):
            instructions.extend(group["instructions"])
    programs: set[str] = set()
    labels: set[str] = set()
    counterpart_accounts: set[str] = set()
    for instruction in instructions:
        if not isinstance(instruction, dict):
            continue
        program_id = str(instruction.get("programId") or "")
        if program_id:
            programs.add(program_id)
        parsed = instruction.get("parsed") if isinstance(instruction.get("parsed"), dict) else {}
        label = str(parsed.get("type") or "")
        if label:
            labels.add(label)
        info = parsed.get("info") if isinstance(parsed.get("info"), dict) else {}
        if label in {"transfer", "transferChecked"}:
            source = str(info.get("source") or "")
            destination = str(info.get("destination") or "")
            mint = str(info.get("mint") or "")
            if (not mint or mint == expected_mint) and source == token_account and destination:
                counterpart_accounts.add(destination)
            if (not mint or mint == expected_mint) and destination == token_account and source:
                counterpart_accounts.add(source)
    for log in meta.get("logMessages") if isinstance(meta.get("logMessages"), list) else []:
        text = str(log)
        if "Instruction:" in text:
            labels.add(text.split("Instruction:", 1)[1].strip())
    return {
        "signers": signers,
        "instruction_labels": sorted(labels),
        "program_ids": sorted(programs),
        "counterpart_token_accounts": sorted(counterpart_accounts),
    }


def movement_classification(program_summary: dict[str, object], quantity_delta: Decimal) -> tuple[str, str]:
    labels = {str(value) for value in program_summary.get("instruction_labels", [])}
    reward_labels = {
        "ClaimRewardsV0",
        "ClaimRewardsV1",
        "DistributeCompressionRewardsV0",
        "SetCurrentRewardsV0",
        "SetCurrentRewardsWrapperV1",
    }
    if quantity_delta > 0 and labels & reward_labels:
        return "helium_reward", "explicit_helium_reward_instruction"
    if labels & {"ClosePositionV0", "Withdraw", "WithdrawV0"}:
        return "defi_position_transfer", "position_withdraw_instruction"
    if "BuyWithUsdt" in labels:
        return "program_spend", "program_buy_with_usdt_instruction"
    if "RedeemV0" in labels:
        return "defi_redeem", "redeem_instruction"
    route_labels = {
        "PlaceTakeOrder",
        "PlatformFeeSplProxySwapV2",
        "Route",
        "SharedAccountsRoute",
        "Swap",
        "swap",
        "SwapV2",
    }
    if labels & route_labels:
        return "swap_or_order_route", "swap_or_order_instruction"
    if labels & {"TransferChecked", "transferChecked"}:
        return "direct_token_transfer", "checked_token_transfer"
    return "unclassified_program_route", "no_supported_classification_rule"


def canonical_balance_effect(rows: list[dict[str, object]], asset: str) -> Decimal:
    target = asset.upper()
    effect = Decimal("0")
    for row in rows:
        quantity = _decimal(row.get("quantity"))
        if str(row.get("asset") or "").upper() == target:
            effect += quantity
        if str(row.get("quote_asset") or "").upper() == target and row.get("quote_quantity") is not None:
            quote_quantity = abs(_decimal(row.get("quote_quantity")))
            effect += -quote_quantity if quantity >= 0 else quote_quantity
        if str(row.get("fee_asset") or "").upper() == target:
            effect -= abs(_decimal(row.get("fee_quantity")))
    return effect


def _rpc(
    client: httpx.Client,
    rpc_url: str,
    method: str,
    params: list[object],
    request_id: str,
) -> object:
    for attempt in range(8):
        response = client.post(
            rpc_url,
            json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        )
        if response.status_code == 429 and attempt < 7:
            retry_after = _decimal(response.headers.get("retry-after"))
            time.sleep(float(max(retry_after, Decimal(str(min(30, 2 ** attempt))))))
            continue
        if response.is_error:
            raise RuntimeError(f"{method}: HTTP {response.status_code}")
        payload = response.json()
        if isinstance(payload, dict) and payload.get("error"):
            raise RuntimeError(f"{method}: {payload['error']}")
        return payload.get("result") if isinstance(payload, dict) else None
    raise RuntimeError(f"{method}: retries exhausted")


def _signature_history(
    client: httpx.Client,
    rpc_url: str,
    token_account: str,
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
            [token_account, options],
            f"signatures-{token_account[:6]}-{page + 1}",
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


def _token_accounts(
    client: httpx.Client,
    rpc_url: str,
    wallet: str,
    mint: str,
) -> list[dict[str, object]]:
    result = _rpc(
        client,
        rpc_url,
        "getTokenAccountsByOwner",
        [wallet, {"mint": mint}, {"encoding": "jsonParsed", "commitment": "finalized"}],
        f"accounts-{mint[:6]}",
    )
    rows = result.get("value") if isinstance(result, dict) else None
    accounts: list[dict[str, object]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        account = row.get("account") if isinstance(row.get("account"), dict) else {}
        data = account.get("data") if isinstance(account.get("data"), dict) else {}
        parsed = data.get("parsed") if isinstance(data.get("parsed"), dict) else {}
        info = parsed.get("info") if isinstance(parsed.get("info"), dict) else {}
        amount = info.get("tokenAmount") if isinstance(info.get("tokenAmount"), dict) else {}
        decimals = int(amount.get("decimals") or 0)
        withheld_raw = Decimal("0")
        for extension in info.get("extensions") if isinstance(info.get("extensions"), list) else []:
            if not isinstance(extension, dict) or extension.get("extension") != "transferFeeAmount":
                continue
            state = extension.get("state") if isinstance(extension.get("state"), dict) else {}
            withheld_raw += _decimal(state.get("withheldAmount"))
        accounts.append(
            {
                "token_account": str(row.get("pubkey") or ""),
                "mint": str(info.get("mint") or mint),
                "token_program": str(data.get("program") or ""),
                "decimals": decimals,
                "current_quantity": str(_decimal(amount.get("uiAmountString"))),
                "withheld_quantity": str(withheld_raw / (Decimal(10) ** decimals)),
            }
        )
    return accounts


def _historical_token_accounts(path: Path, wallet: str, mint: str) -> list[dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if payload.get("wallet") != wallet:
        return []
    return [
        {
            "token_account": str(row.get("token_account") or ""),
            "mint": mint,
            "token_program": "historical_discovery",
            "decimals": int(row.get("decimals") or 0),
            "current_quantity": "0",
            "withheld_quantity": "0",
            "account_state": "historical_closed_or_zero",
        }
        for row in payload.get("historical_token_accounts", [])
        if isinstance(row, dict)
        and str(row.get("mint") or "") == mint
        and row.get("token_account")
    ]


def merge_token_accounts(
    current: list[dict[str, object]],
    historical: list[dict[str, object]],
) -> list[dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}
    for row in historical:
        token_account = str(row.get("token_account") or "")
        if token_account:
            merged[token_account] = dict(row)
    for row in current:
        token_account = str(row.get("token_account") or "")
        if token_account:
            merged[token_account] = {**row, "account_state": "current"}
    return [merged[key] for key in sorted(merged)]


def _canonical_rows(store: DuckDbStore, txids: list[str]) -> dict[str, list[dict[str, object]]]:
    if not txids:
        return {}
    with store.connect() as con:
        rows = con.execute(
            """
            select
                tx_id, event_time, event_type, asset, quantity,
                quote_asset, quote_quantity, fee_asset, fee_quantity,
                source, account, wallet
            from canonical_events
            where tx_id in (select unnest(?))
            order by tx_id, event_time, event_id
            """,
            [txids],
        ).fetchall()
    result: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        result[str(row[0])].append(
            {
                "event_time": row[1].replace(tzinfo=timezone.utc).isoformat() if row[1] else None,
                "event_type": row[2],
                "asset": row[3],
                "quantity": str(row[4]) if row[4] is not None else None,
                "quote_asset": row[5],
                "quote_quantity": str(row[6]) if row[6] is not None else None,
                "fee_asset": row[7],
                "fee_quantity": str(row[8]) if row[8] is not None else None,
                "source": row[9],
                "account": row[10],
                "wallet": row[11],
            }
        )
    return dict(result)


def _chain_row(
    signature_row: dict[str, object],
    transaction: dict[str, Any] | None,
    token_account: str,
    mint: str,
    wallet: str,
    mint_symbols: dict[str, str] | None = None,
) -> dict[str, object]:
    signature = str(signature_row.get("signature") or "")
    block_time = transaction.get("blockTime") if isinstance(transaction, dict) else signature_row.get("blockTime")
    base = {
        "signature": signature,
        "token_account": token_account,
        "slot": transaction.get("slot") if isinstance(transaction, dict) else signature_row.get("slot"),
        "block_time_utc": (
            datetime.fromtimestamp(int(block_time), tz=timezone.utc).isoformat()
            if block_time is not None
            else None
        ),
    }
    if signature_row.get("err") is not None:
        return {**base, "chain_status": "signature_failed", "error": signature_row.get("err")}
    if not isinstance(transaction, dict):
        return {**base, "chain_status": "transaction_missing"}
    meta = transaction.get("meta") if isinstance(transaction.get("meta"), dict) else {}
    if meta.get("err") is not None:
        return {**base, "chain_status": "transaction_failed", "error": meta.get("err")}
    delta = token_account_delta(transaction, token_account, mint)
    if delta is None:
        return {**base, "chain_status": "token_balance_entry_missing"}
    program_summary = transaction_program_summary(transaction, token_account, mint)
    classification, classification_reason = movement_classification(
        program_summary,
        _decimal(delta.get("quantity_delta")),
    )
    keys = _account_keys(transaction)
    fee_lamports = int(meta.get("fee") or 0)
    wallet_paid_fee = bool(keys) and keys[0] == wallet
    native_delta = wallet_native_delta(transaction, wallet)
    wallet_fee_sol = Decimal(fee_lamports) / Decimal("1000000000") if wallet_paid_fee else Decimal("0")
    return {
        **base,
        "chain_status": "onchain_success",
        **delta,
        **program_summary,
        "movement_classification": classification,
        "classification_reason": classification_reason,
        "wallet_native_sol_delta": str(native_delta),
        "wallet_fee_sol": str(wallet_fee_sol),
        "wallet_non_fee_sol_delta": str(native_delta + wallet_fee_sol),
        "wallet_token_deltas": wallet_token_deltas(transaction, wallet, mint_symbols),
    }


def aggregate_token_account_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        signature = str(row.get("signature") or "")
        if signature:
            grouped[signature].append(row)
    result: list[dict[str, object]] = []
    for signature, items in grouped.items():
        representative = dict(items[0])
        successful = [row for row in items if row.get("chain_status") == "onchain_success"]
        if successful:
            representative = dict(successful[0])
            representative["quantity_delta"] = str(
                sum((_decimal(row.get("quantity_delta")) for row in successful), Decimal("0"))
            )
        representative["token_accounts"] = sorted(
            {str(row.get("token_account") or "") for row in items if row.get("token_account")}
        )
        representative["token_account_components"] = [
            {
                "token_account": row.get("token_account"),
                "quantity_delta": row.get("quantity_delta"),
                "pre_quantity": row.get("pre_quantity"),
                "post_quantity": row.get("post_quantity"),
                "chain_status": row.get("chain_status"),
            }
            for row in items
        ]
        representative["instruction_labels"] = sorted(
            {
                str(value)
                for row in items
                for value in row.get("instruction_labels", [])
            }
        )
        representative["program_ids"] = sorted(
            {str(value) for row in items for value in row.get("program_ids", [])}
        )
        representative["counterpart_token_accounts"] = sorted(
            {
                str(value)
                for row in items
                for value in row.get("counterpart_token_accounts", [])
            }
        )
        representative["signature"] = signature
        result.append(representative)
    return sorted(result, key=lambda row: (str(row.get("block_time_utc") or ""), str(row["signature"])))


def _enrich_chain_rows(
    chain_rows: list[dict[str, object]],
    canonical_by_tx: dict[str, list[dict[str, object]]],
    asset: str,
    wallet: str,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for row in chain_rows:
        signature = str(row.get("signature") or "")
        all_canonical = canonical_by_tx.get(signature, [])
        canonical = [
            event
            for event in all_canonical
            if str(event.get("account") or "") == wallet or str(event.get("wallet") or "") == wallet
        ]
        counterparty_canonical = [event for event in all_canonical if event not in canonical]
        effect = canonical_balance_effect(canonical, asset)
        chain_delta = _decimal(row.get("quantity_delta"))
        if row.get("chain_status") != "onchain_success":
            evidence_status = str(row.get("chain_status") or "chain_error")
        elif chain_delta == 0:
            evidence_status = "unchanged_token_account"
        elif not canonical:
            evidence_status = "canonical_missing_balance_change"
        elif effect != chain_delta:
            evidence_status = "canonical_quantity_mismatch"
        else:
            evidence_status = "canonical_quantity_matched"
        result.append(
            {
                **row,
                "canonical_events_count": len(canonical),
                "counterparty_canonical_events_count": len(counterparty_canonical),
                "canonical_balance_effect": str(effect),
                "canonical_delta_difference": str(effect - chain_delta),
                "evidence_status": evidence_status,
                "canonical_events": canonical,
                "counterparty_canonical_events": counterparty_canonical,
            }
        )
    return result


def _parse_targets(values: list[str] | None) -> dict[str, str]:
    if not values:
        return dict(DEFAULT_TARGETS)
    targets: dict[str, str] = {}
    for value in values:
        asset, separator, mint = value.partition("=")
        if not separator or not asset.strip() or not mint.strip():
            raise ValueError(f"invalid target: {value}; expected ASSET=MINT")
        targets[asset.strip().upper()] = mint.strip()
    return targets


def _classification_summary(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    counts: defaultdict[str, int] = defaultdict(int)
    quantities: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for row in rows:
        if row.get("evidence_status") != "canonical_missing_balance_change":
            continue
        classification = str(row.get("movement_classification") or "unclassified_program_route")
        counts[classification] += 1
        quantities[classification] += _decimal(row.get("quantity_delta"))
    return [
        {
            "movement_classification": classification,
            "transactions_count": counts[classification],
            "quantity_delta": str(quantities[classification]),
        }
        for classification in sorted(counts)
    ]


def run(args: argparse.Namespace) -> dict[str, object]:
    store = DuckDbStore(Path(args.db))
    api_key = resolve_secret_value(store, "secret.alchemy.api_key")
    if not api_key:
        raise RuntimeError("secret.alchemy.api_key is not configured")
    rpc_url = f"https://solana-mainnet.g.alchemy.com/v2/{api_key}"
    targets = _parse_targets(args.target)
    mint_symbols = {**MINT_SYMBOLS, **{mint: asset for asset, mint in targets.items()}}
    target_reports: list[dict[str, object]] = []
    fetched_transactions: dict[str, dict[str, Any] | None] = {}
    with httpx.Client(timeout=45) as client:
        for asset, mint in targets.items():
            current_accounts = _token_accounts(client, rpc_url, args.wallet, mint)
            accounts = merge_token_accounts(
                current_accounts,
                _historical_token_accounts(Path(args.wallet_audit), args.wallet, mint),
            )
            histories: list[tuple[dict[str, object], dict[str, object]]] = []
            history_complete = bool(accounts)
            for account in accounts:
                token_account = str(account.get("token_account") or "")
                signature_rows, account_complete = _signature_history(
                    client,
                    rpc_url,
                    token_account,
                    max(1, args.max_pages),
                )
                history_complete = history_complete and account_complete
                histories.extend((account, row) for row in signature_rows)

            chain_rows: list[dict[str, object]] = []
            fetched_count = 0
            for index, (account, signature_row) in enumerate(histories):
                signature = str(signature_row.get("signature") or "")
                transaction: dict[str, Any] | None = None
                if signature_row.get("err") is None and fetched_count < args.max_transactions:
                    if signature not in fetched_transactions:
                        if fetched_count and args.delay_seconds:
                            time.sleep(args.delay_seconds)
                        fetched = _rpc(
                            client,
                            rpc_url,
                            "getTransaction",
                            [signature, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}],
                            f"tx-{asset}-{index + 1}",
                        )
                        fetched_transactions[signature] = fetched if isinstance(fetched, dict) else None
                        fetched_count += 1
                    transaction = fetched_transactions.get(signature)
                chain_rows.append(
                    _chain_row(
                        signature_row,
                        transaction,
                        str(account.get("token_account") or ""),
                        mint,
                        args.wallet,
                        mint_symbols,
                    )
                )

            aggregate_rows = aggregate_token_account_rows(chain_rows)
            canonical_by_tx = _canonical_rows(
                store,
                sorted({str(row.get("signature") or "") for row in aggregate_rows if row.get("signature")}),
            )
            rows = _enrich_chain_rows(aggregate_rows, canonical_by_tx, asset, args.wallet)
            current_quantity = sum(
                (_decimal(row.get("current_quantity")) for row in current_accounts),
                Decimal("0"),
            )
            chain_delta = sum(
                (_decimal(row.get("quantity_delta")) for row in rows if row.get("chain_status") == "onchain_success"),
                Decimal("0"),
            )
            canonical_effect = sum(
                (_decimal(row.get("canonical_balance_effect")) for row in rows),
                Decimal("0"),
            )
            target_reports.append(
                {
                    "asset": asset,
                    "mint": mint,
                    "token_accounts": accounts,
                    "token_accounts_count": len(accounts),
                    "current_token_accounts_count": len(current_accounts),
                    "historical_token_accounts_count": len(accounts) - len(current_accounts),
                    "history_complete": history_complete,
                    "token_account_signatures_count": len(histories),
                    "signatures_count": len(rows),
                    "failed_signatures_count": sum(row.get("chain_status") == "signature_failed" for row in rows),
                    "successful_balance_changes_count": sum(
                        row.get("chain_status") == "onchain_success" and _decimal(row.get("quantity_delta")) != 0
                        for row in rows
                    ),
                    "canonical_matched_count": sum(
                        row.get("evidence_status") == "canonical_quantity_matched" for row in rows
                    ),
                    "canonical_missing_balance_change_count": sum(
                        row.get("evidence_status") == "canonical_missing_balance_change" for row in rows
                    ),
                    "canonical_quantity_mismatch_count": sum(
                        row.get("evidence_status") == "canonical_quantity_mismatch" for row in rows
                    ),
                    "canonical_missing_by_classification": _classification_summary(rows),
                    "canonical_missing_reward_quantity": str(
                        sum(
                            (
                                _decimal(row.get("quantity_delta"))
                                for row in rows
                                if row.get("evidence_status") == "canonical_missing_balance_change"
                                and row.get("movement_classification") == "helium_reward"
                            ),
                            Decimal("0"),
                        )
                    ),
                    "current_quantity": str(current_quantity),
                    "chain_net_delta": str(chain_delta),
                    "chain_net_matches_current": history_complete and chain_delta == current_quantity,
                    "canonical_balance_effect_total": str(canonical_effect),
                    "canonical_vs_chain_delta": str(canonical_effect - chain_delta),
                    "transactions": rows,
                }
            )

    generated_at = datetime.now(timezone.utc)
    report = {
        "generated_at": generated_at.isoformat(),
        "wallet": args.wallet,
        "provider": "alchemy_solana_rpc",
        "rpc_url": "https://solana-mainnet.g.alchemy.com/v2/<redacted>",
        "targets_count": len(target_reports),
        "history_complete": bool(target_reports) and all(row.get("history_complete") for row in target_reports),
        "canonical_missing_balance_change_count": sum(
            int(row.get("canonical_missing_balance_change_count") or 0) for row in target_reports
        ),
        "canonical_quantity_mismatch_count": sum(
            int(row.get("canonical_quantity_mismatch_count") or 0) for row in target_reports
        ),
        "targets": target_reports,
        "target_changed": False,
        "methodology": (
            "Read-only Vollabgleich der aktuellen SPL- und Token-2022-Konten je exakter Mint-Adresse. "
            "Alle per getSignaturesForAddress erreichbaren Signaturen werden kontenindexbasiert gegen "
            "preTokenBalances/postTokenBalances und anschliessend gegen kanonische TXIDs und Mengenwirkung "
            "geprueft. Token-2022 withheld_quantity wird separat ausgewiesen und nicht zum verfuegbaren "
            "Bestand addiert. Keine Raw-Objects, Canonical Events, Ledger, FIFO-Lots, Preise oder Steuerwerte "
            "werden veraendert."
        ),
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    content = json.dumps(report, indent=2, ensure_ascii=False)
    versioned = output_dir / f"token_account_coverage_{generated_at.strftime('%Y%m%dT%H%M%SZ')}_{args.wallet}.json"
    latest = output_dir / f"latest_{args.wallet}_token_account_coverage.json"
    versioned.write_text(content, encoding="utf-8")
    latest.write_text(content, encoding="utf-8")
    report["artifact_path"] = str(versioned.relative_to(PROJECT_ROOT))
    report["latest_artifact_path"] = str(latest.relative_to(PROJECT_ROOT))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Solana Token Account Coverage Audit")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--wallet", default=DEFAULT_WALLET)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--wallet-audit", default=str(DEFAULT_WALLET_AUDIT))
    parser.add_argument("--target", action="append", help="ASSET=MINT; repeatable")
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--max-transactions", type=int, default=1000)
    parser.add_argument("--delay-seconds", type=float, default=0.03)
    args = parser.parse_args()
    report = run(args)
    print(json.dumps({key: value for key, value in report.items() if key != "targets"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
