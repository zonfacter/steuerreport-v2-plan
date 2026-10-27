"""Evidence-only mapping of a single Solana getTransaction result."""

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone


def _uint(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"Invalid {label}")
    return value


def _quantity(amount: int, decimals: int) -> str:
    digits = str(abs(amount)).zfill(decimals + 1)
    if not decimals:
        return digits
    return (digits[:-decimals] + "." + digits[-decimals:]).rstrip("0").rstrip(".")


def _token_amount(value: object) -> tuple[int, int]:
    if not isinstance(value, dict):
        raise ValueError("Missing uiTokenAmount")
    decimals = value.get("decimals")
    if decimals is not None and _uint(decimals, "token decimals") > 255:
        raise ValueError("Invalid token decimals")
    if "amount" in value:
        raw = value["amount"]
        if not isinstance(raw, str) or not re.fullmatch(r"[0-9]+", raw) or decimals is None:
            raise ValueError("Invalid raw token amount/decimals")
        return int(raw), decimals
    text = value.get("uiAmountString")
    if not isinstance(text, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", text):
        raise ValueError("Missing exact token amount")
    whole, _, fraction = text.partition(".")
    if decimals is not None and len(fraction.rstrip("0")) > decimals:
        raise ValueError("Token amount exceeds declared decimals")
    return int(whole + fraction), len(fraction)


def _token_deltas(meta: dict, wallet: str, account_count: int) -> dict[str, tuple[int, int]]:
    amounts: dict[str, list[tuple[int, int]]] = {}
    identities: dict[int, str] = {}
    mint_decimals: dict[str, int] = {}
    for field, sign in (("preTokenBalances", -1), ("postTokenBalances", 1)):
        balances = meta.get(field)
        if not isinstance(balances, list):
            raise ValueError(f"Missing {field}")
        seen: set[int] = set()
        for item in balances:
            if not isinstance(item, dict):
                raise ValueError("Invalid token balance")
            index = _uint(item.get("accountIndex"), "token accountIndex")
            if index >= account_count or index in seen:
                raise ValueError("Invalid or duplicate token accountIndex")
            seen.add(index)
            owner, mint = item.get("owner"), item.get("mint")
            if not isinstance(owner, str) or not owner.strip():
                raise ValueError("Ambiguous token owner")
            if not isinstance(mint, str) or not mint.strip() or mint != mint.strip():
                raise ValueError("Missing exact token mint")
            if identities.setdefault(index, mint) != mint:
                raise ValueError("Conflicting token account mint")
            amount, scale = _token_amount(item.get("uiTokenAmount"))
            decimals = item["uiTokenAmount"].get("decimals")
            if decimals is not None and mint_decimals.setdefault(mint, decimals) != decimals:
                raise ValueError("Conflicting mint decimals")
            if owner == wallet:
                amounts.setdefault(mint, []).append((sign * amount, scale))
    result = {}
    for mint, values in amounts.items():
        scale = max(decimals for _, decimals in values)
        result[mint] = (sum(amount * 10 ** (scale - decimals) for amount, decimals in values), scale)
    return result


def transaction_rows(
    wallet_address: str,
    signature: str,
    tx: dict[str, object],
    mint_symbols: Mapping[str, str],
) -> list[dict[str, object]]:
    """Keep transfers unclassified; callers own integration and review gates.

    Symbol keys must be verified, case-correct mints. Uppercased legacy keys
    cannot safely be reversed and deliberately receive no fallback lookup.
    """
    if not isinstance(wallet_address, str) or not wallet_address.strip():
        raise ValueError("Missing wallet address")
    if not isinstance(signature, str) or not signature.strip():
        raise ValueError("Missing signature")
    if not isinstance(tx, dict):
        raise ValueError("Missing transaction result")
    block_time = _uint(tx.get("blockTime"), "blockTime")
    try:
        timestamp = datetime.fromtimestamp(block_time, timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError) as exc:
        raise ValueError("Invalid blockTime") from exc
    meta = tx.get("meta")
    transaction = tx.get("transaction")
    if not isinstance(meta, dict) or "err" not in meta or not isinstance(transaction, dict):
        raise ValueError("Missing transaction/meta/error status")
    if meta["err"] is not None and not isinstance(meta["err"], (dict, str)):
        raise ValueError("Invalid transaction error status")
    message = transaction.get("message")
    if not isinstance(message, dict):
        raise ValueError("Missing transaction message")
    keys = message.get("accountKeys")
    if not isinstance(keys, list) or not keys:
        raise ValueError("Missing accountKeys")
    account_keys = [key.get("pubkey") if isinstance(key, dict) else key for key in keys]
    # Raw v0 messages omit loaded keys; jsonParsed already includes them.
    loaded = meta.get("loadedAddresses")
    if loaded is not None and all(isinstance(key, str) for key in keys):
        if not isinstance(loaded, dict):
            raise ValueError("Invalid loadedAddresses")
        for field in ("writable", "readonly"):
            if not isinstance(loaded.get(field), list):
                raise ValueError("Incomplete loadedAddresses")
            account_keys.extend(loaded[field])
    if any(not isinstance(key, str) or not key.strip() for key in account_keys):
        raise ValueError("Invalid account key")
    if len(set(account_keys)) != len(account_keys):
        raise ValueError("Duplicate account key")
    fee = _uint(meta.get("fee"), "fee")
    pre, post = meta.get("preBalances"), meta.get("postBalances")
    if not isinstance(pre, list) or not isinstance(post, list):
        raise ValueError("Missing native balances")
    if len(pre) != len(account_keys) or len(post) != len(account_keys):
        raise ValueError("Incomplete native balances")
    for balance in pre + post:
        _uint(balance, "native balance")
    try:
        raw_transaction = json.dumps(tx, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("Transaction is not valid JSON evidence") from exc

    rows: list[dict[str, object]] = []

    def emit(event_type: str, asset: str, amount: int, decimals: int, **metadata: object) -> None:
        if amount:
            rows.append({
                "timestamp_utc": timestamp,
                "event_type": event_type,
                "asset": asset,
                "quantity": _quantity(amount, decimals),
                "side": "in" if amount > 0 else "out",
                "tx_id": signature,
                "wallet_address": wallet_address,
                "history_mapper_version": "2",
                "raw_transaction": raw_transaction,
                **metadata,
            })

    wallet_fee = fee if account_keys[0] == wallet_address else 0
    if meta["err"] is None:
        deltas = _token_deltas(meta, wallet_address, len(account_keys))
        if wallet_address in account_keys:
            index = account_keys.index(wallet_address)
            emit("sol_transfer", "SOL", post[index] - pre[index] + wallet_fee, 9)
        for mint, (amount, decimals) in sorted(deltas.items()):
            asset = mint_symbols.get(mint)
            if asset is None:
                asset = "SOLANA_" + hashlib.sha256(mint.encode("utf-8")).hexdigest().upper()
            if not isinstance(asset, str) or not asset.strip():
                raise ValueError("Invalid exact mint symbol")
            emit("token_transfer", asset, amount, decimals, mint=mint)
    emit("network_fee", "SOL", -wallet_fee, 9)
    return rows
