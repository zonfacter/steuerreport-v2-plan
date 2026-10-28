from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceProfile:
    source: str
    label: str
    time_columns: tuple[str, ...]
    asset_columns: tuple[str, ...]
    quantity_columns: tuple[str, ...]
    type_columns: tuple[str, ...]
    pair_columns: tuple[str, ...] = ()
    quote_asset_columns: tuple[str, ...] = ()
    quote_quantity_columns: tuple[str, ...] = ()
    fee_asset_columns: tuple[str, ...] = ()
    fee_quantity_columns: tuple[str, ...] = ()
    tx_id_columns: tuple[str, ...] = ()
    account_columns: tuple[str, ...] = ()
    source_ref_columns: tuple[str, ...] = ()
    default_account: str | None = None


def normalize_column_name(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", " ").split())


def first_matching_column(columns: list[str], aliases: tuple[str, ...]) -> str | None:
    normalized_columns = {normalize_column_name(column): column for column in columns}
    for alias in aliases:
        match = normalized_columns.get(normalize_column_name(alias))
        if match is not None:
            return match
    return None


def inspect_profile_columns(
    profile: SourceProfile,
    columns: list[str],
) -> tuple[dict[str, str | None], list[str]]:
    matched = {
        "time": first_matching_column(columns, profile.time_columns),
        "asset": first_matching_column(columns, profile.asset_columns),
        "quantity": first_matching_column(columns, profile.quantity_columns),
        "type": first_matching_column(columns, profile.type_columns),
        "pair": first_matching_column(columns, profile.pair_columns),
        "quote_asset": first_matching_column(columns, profile.quote_asset_columns),
        "quote_quantity": first_matching_column(columns, profile.quote_quantity_columns),
        "fee_asset": first_matching_column(columns, profile.fee_asset_columns),
        "fee_quantity": first_matching_column(columns, profile.fee_quantity_columns),
        "tx_id": first_matching_column(columns, profile.tx_id_columns),
        "account": first_matching_column(columns, profile.account_columns),
    }
    missing = []
    if matched["time"] is None:
        missing.append("time")
    if (
        matched["asset"] is None
        and matched["pair"] is None
        and not _has_derived_asset_column(profile, columns)
    ):
        missing.append("asset")
    if matched["quantity"] is None:
        missing.append("quantity")
    return matched, missing


def _has_derived_asset_column(profile: SourceProfile, columns: list[str]) -> bool:
    normalized_columns = {normalize_column_name(column) for column in columns}
    if profile.source == "pionex":
        if {"received quantity", "received currency"} <= normalized_columns:
            return True
        if {"buy amount", "buy currency"} <= normalized_columns:
            return True
        if {"amount usdt", "direction"} <= normalized_columns:
            return True
        return False
    if profile.source in {"blockpit", "blockpit-solana"}:
        return bool(
            normalized_columns
            & {
                "incoming asset",
                "incoming amount",
                "outgoing asset",
                "outgoing amount",
                "fee asset (optional)",
                "fee amount (optional)",
            }
        )
    if profile.source != "helium":
        return False
    derived_asset_columns = {
        "hnt amount",
        "iot amount",
        "mobile amount",
        "iot tokens",
        "mobile tokens",
        "mining rewards",
        "mining rewards hnt",
        "mining rewards iot",
        "mining rewards mobile",
        "commissions hnt",
        "commissions iot",
        "commissions mobile",
    }
    if {"sender", "receiver", "amount"} <= normalized_columns:
        return True
    return bool(normalized_columns & derived_asset_columns)


GENERIC_PROFILE = SourceProfile(
    source="manual-csv",
    label="Manuelles CSV",
    time_columns=("time", "date", "datetime", "timestamp", "utc time", "utc_time"),
    asset_columns=("asset", "coin", "currency", "token"),
    quantity_columns=("amount", "quantity", "qty", "change", "delta"),
    type_columns=("type", "operation", "side", "category"),
    pair_columns=("pair", "symbol", "market", "trading pair", "coin pair"),
    quote_asset_columns=("quote_asset", "quote asset", "quote", "counter asset"),
    quote_quantity_columns=("quote_quantity", "quote amount", "quote_amount", "total", "value"),
    fee_asset_columns=("fee_asset", "fee asset", "fee coin"),
    fee_quantity_columns=("fee_quantity", "fee amount", "fee_amount", "fee"),
    tx_id_columns=("txid", "tx_id", "hash", "transaction hash"),
    account_columns=("account", "exchange", "wallet"),
    source_ref_columns=("id", "orderid", "order id", "txid", "tx_id", "hash"),
)

PROFILES: dict[str, SourceProfile] = {
    "mexc": SourceProfile(
        source="mexc", label="MEXC Account Data Export",
        time_columns=("Creation Time(UTC+01:00)", "Time(UTC+01:00)", "Time"),
        asset_columns=("Crypto",), quantity_columns=("Quantity", "Amount"),
        type_columns=("Transaction Type", "Type", "Fund Type"),
    ),
    GENERIC_PROFILE.source: GENERIC_PROFILE,
    "manual": GENERIC_PROFILE,
    "demo": SourceProfile(
        **{
            **GENERIC_PROFILE.__dict__,
            "source": "demo",
            "label": "Demo",
            "default_account": "demo",
        }
    ),
    "pionex": SourceProfile(
        source="pionex",
        label="Pionex CSV",
        time_columns=("time", "date", "date(UTC+0)", "created time", "created_at", "timestamp", "timestamp_utc"),
        asset_columns=("asset", "coin", "currency", "base coin", "received currency", "buy currency"),
        quantity_columns=(
            "amount",
            "quantity",
            "qty",
            "change",
            "filled amount",
            "executed_qty",
            "received quantity",
            "buy amount",
            "amount_usdt",
        ),
        type_columns=("type", "operation", "side", "action", "tx_type", "tag", "direction"),
        pair_columns=("pair", "symbol", "market", "trading pair", "coin pair"),
        quote_asset_columns=("quote_asset", "quote asset", "quote coin", "quote", "sent currency", "sell currency"),
        quote_quantity_columns=(
            "quote_quantity",
            "quote amount",
            "total",
            "value",
            "deal amount",
            "filled total",
            "filled value",
            "sent quantity",
            "sell amount",
        ),
        fee_asset_columns=("fee_asset", "fee asset", "fee coin", "fee currency"),
        fee_quantity_columns=("fee_quantity", "fee amount", "fee"),
        tx_id_columns=("txid", "tx_id", "tx-id", "hash", "transaction id", "order id", "tax_id"),
        account_columns=("account", "exchange", "wallet", "to_address", "from_address"),
        source_ref_columns=("id", "order id", "transaction id", "txid", "tx_id", "tx-id", "tax_id"),
        default_account="pionex",
    ),
    "binance": SourceProfile(
        source="binance",
        label="Binance CSV",
        time_columns=("utc time", "utc_time", "time", "date", "date(UTC)", "date(UTC+2)", "timestamp"),
        asset_columns=("coin", "asset", "currency", "receive amount"),
        quantity_columns=("change", "amount", "quantity", "qty", "receive amount"),
        type_columns=("operation", "type", "side", "category", "status"),
        pair_columns=("pair", "symbol", "market", "trading pair", "coin pair"),
        quote_asset_columns=("quote_asset", "quote asset", "quote coin"),
        quote_quantity_columns=("quote_quantity", "quote amount", "total", "value", "spend amount", "indicated amount"),
        fee_asset_columns=("fee_asset", "fee asset", "fee coin"),
        fee_quantity_columns=("fee_quantity", "fee amount", "fee"),
        tx_id_columns=("txid", "tx_id", "transaction id", "hash"),
        account_columns=("account", "wallet"),
        source_ref_columns=("id", "order id", "transaction id", "txid", "tx_id"),
        default_account="binance",
    ),
    "coinbase": SourceProfile(
        source="coinbase",
        label="Coinbase Transaction History CSV",
        time_columns=("timestamp", "time", "date", "created at", "created_at"),
        asset_columns=("asset", "currency", "coin"),
        quantity_columns=("quantity transacted", "quantity", "amount"),
        type_columns=("transaction type", "type", "operation"),
        quote_asset_columns=("spot price currency", "native currency", "quote asset"),
        quote_quantity_columns=("subtotal", "quote quantity", "native amount"),
        fee_asset_columns=("spot price currency", "native currency", "fee asset"),
        fee_quantity_columns=("fees and/or spread", "fees", "fee"),
        tx_id_columns=("transaction id", "txid", "transaction hash", "hash"),
        account_columns=("account", "portfolio"),
        source_ref_columns=("transaction id", "id", "order id", "trade id"),
        default_account="coinbase",
    ),
    "binance_simple_earn_api": SourceProfile(
        source="binance_simple_earn_api",
        label="Binance Simple Earn API",
        time_columns=("time_iso", "time"),
        asset_columns=("asset",),
        quantity_columns=("amount", "rewards", "principal"),
        type_columns=("record_type", "type", "status"),
        tx_id_columns=("purchase_id", "redeem_id", "position_id"),
        account_columns=("account",),
        source_ref_columns=("source_ref", "purchase_id", "redeem_id", "position_id"),
        default_account="Binance",
    ),
    "binance_withdrawal_api": SourceProfile(
        source="binance_withdrawal_api",
        label="Binance Capital Withdrawal API",
        time_columns=("complete_time", "complete time", "apply_time", "apply time", "time"),
        asset_columns=("coin", "asset"),
        quantity_columns=("gross_amount", "gross amount", "amount"),
        type_columns=("record_type", "operation", "status"),
        fee_asset_columns=("fee_asset", "fee asset", "coin"),
        fee_quantity_columns=("transaction_fee", "transaction fee", "transactionFee"),
        tx_id_columns=("tx_id", "txid", "txId"),
        account_columns=("account",),
        source_ref_columns=("source_ref", "id", "tx_id", "txid", "txId"),
        default_account="Binance Withdrawal Evidence",
    ),
    "binance_asset_dividend_api": SourceProfile(
        source="binance_asset_dividend_api",
        label="Binance Asset Dividend API",
        time_columns=("time_iso", "div_time", "time"),
        asset_columns=("asset",),
        quantity_columns=("amount",),
        type_columns=("record_type", "en_info"),
        tx_id_columns=("tran_id", "dividend_id"),
        account_columns=("account",),
        source_ref_columns=("source_ref", "dividend_id", "tran_id"),
        default_account="Spot",
    ),
    "bitget": SourceProfile(
        source="bitget",
        label="Bitget CSV",
        time_columns=(
            "time",
            "date",
            "timestamp utc+8 (completion)",
            "timestamp utc+8 (created)",
            "timestamp utc+8 (order)",
            "creation timestamp (+8 utc)",
            "timestamp utc+8 (submission)",
            "ctime",
            "utime",
        ),
        asset_columns=("asset", "coin", "currency"),
        quantity_columns=(
            "surplus/deduction (after fee)",
            "surplus/deduction (before fee)",
            "amount",
            "quantity",
            "executed",
            "size",
        ),
        type_columns=("type", "action", "action (english)", "status", "sub category"),
        pair_columns=("trading pair", "trading pair"),
        quote_asset_columns=("quote_asset", "quote asset", "fee deducted in"),
        quote_quantity_columns=(
            "quote_quantity",
            "amount in usdt",
            "amount (usdt)",
            "transacted amount",
            "executed amount (usdt)",
        ),
        fee_asset_columns=("fee_asset", "fee asset", "fee deducted in"),
        fee_quantity_columns=(
            "fee_quantity",
            "fee",
            "fee (coin quantity)",
            "withdrawal fee",
        ),
        tx_id_columns=("transaction hash(txid)", "txid", "tx_id", "order no.", "order number", "id"),
        account_columns=("account",),
        source_ref_columns=("source_ref", "order no.", "order number", "id", "transaction hash(txid)"),
        default_account="bitget",
    ),
    "blockpit": SourceProfile(
        source="blockpit",
        label="Blockpit CSV",
        time_columns=("date (utc)", "date", "time", "timestamp"),
        asset_columns=("incoming asset", "outgoing asset", "fee asset (optional)"),
        quantity_columns=("incoming amount", "outgoing amount", "fee amount (optional)"),
        type_columns=("label", "type"),
        quote_asset_columns=("outgoing asset", "incoming asset"),
        quote_quantity_columns=("outgoing amount", "incoming amount"),
        fee_asset_columns=("fee asset (optional)",),
        fee_quantity_columns=("fee amount (optional)",),
        tx_id_columns=("trx. id (optional)", "txid", "transaction id"),
        account_columns=("integration name", "source name"),
        source_ref_columns=("trx. id (optional)", "comment (optional)"),
        default_account="blockpit",
    ),
    "blockpit-solana": SourceProfile(
        source="blockpit-solana",
        label="Blockpit Solana CSV",
        time_columns=("date (utc)", "date", "time", "timestamp"),
        asset_columns=("incoming asset", "outgoing asset", "fee asset (optional)"),
        quantity_columns=("incoming amount", "outgoing amount", "fee amount (optional)"),
        type_columns=("label", "type"),
        quote_asset_columns=("outgoing asset", "incoming asset"),
        quote_quantity_columns=("outgoing amount", "incoming amount"),
        fee_asset_columns=("fee asset (optional)",),
        fee_quantity_columns=("fee amount (optional)",),
        tx_id_columns=("trx. id (optional)", "txid", "transaction id"),
        account_columns=("integration name", "source name"),
        source_ref_columns=("trx. id (optional)", "comment (optional)"),
        default_account="blockpit-solana",
    ),
    "solana_rpc": SourceProfile(
        source="solana_rpc",
        label="Solana RPC Primaerdaten",
        time_columns=("timestamp_utc", "timestamp", "time", "date"),
        asset_columns=("asset", "symbol", "mint"),
        quantity_columns=("quantity", "amount"),
        type_columns=("event_type", "type", "side"),
        fee_asset_columns=("fee_asset",),
        fee_quantity_columns=("fee", "fee_quantity", "fee_amount"),
        tx_id_columns=("tx_id", "signature", "transaction_hash"),
        account_columns=("wallet_address", "account", "wallet"),
        source_ref_columns=("tx_id", "signature", "transaction_hash"),
        default_account="solana_rpc",
    ),
    "helium": SourceProfile(
        source="helium",
        label="Helium Legacy/Fairspot",
        time_columns=("time", "date", "timestamp", "block time", "created_at", "period start (utc)"),
        asset_columns=("asset", "coin", "currency", "token", "buyCurrency"),
        quantity_columns=(
            "amount",
            "quantity",
            "hnt",
            "reward",
            "rewards",
            "buyAmount",
            "hnt_amount",
            "iot_amount",
            "mobile_amount",
            "iot tokens",
            "mobile tokens",
            "mining rewards",
            "mining rewards hnt",
            "mining rewards iot",
            "mining rewards mobile",
            "commissions hnt",
            "commissions iot",
            "commissions mobile",
        ),
        type_columns=("type", "operation", "category", "reward type"),
        pair_columns=("pair", "symbol", "market", "trading pair", "coin pair"),
        quote_asset_columns=("quote_asset", "quote asset"),
        quote_quantity_columns=("quote_quantity", "quote amount", "value", "eur value"),
        fee_asset_columns=("fee_asset", "fee asset"),
        fee_quantity_columns=("fee_quantity", "fee amount", "fee"),
        tx_id_columns=("txid", "tx_id", "txId", "hash", "transaction hash", "transaction_hash"),
        account_columns=(
            "wallet",
            "account",
            "hotspot",
            "hotspot name",
            "gateway address",
            "address",
            "payer",
            "payee",
            "receiver",
            "sender",
        ),
        source_ref_columns=(
            "id",
            "txid",
            "tx_id",
            "txId",
            "hash",
            "transaction hash",
            "transaction_hash",
            "block",
            "gateway address",
        ),
        default_account="helium",
    ),
}


def profile_for_source(source: str) -> SourceProfile:
    normalized = source.strip().lower()
    return PROFILES.get(normalized, GENERIC_PROFILE)


def list_profiles() -> list[dict[str, object]]:
    unique_profiles = {profile.source: profile for profile in PROFILES.values()}
    return [
        {
            "source": profile.source,
            "label": profile.label,
            "required_any": {
                "time": list(profile.time_columns),
                "asset": list(profile.asset_columns),
                "quantity": list(profile.quantity_columns),
            },
            "pair_columns": list(profile.pair_columns),
            "type_columns": list(profile.type_columns),
        }
        for profile in sorted(unique_profiles.values(), key=lambda item: item.source)
    ]
