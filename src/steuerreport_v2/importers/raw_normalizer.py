from __future__ import annotations

from steuerreport_v2.private_settings import private_config_path, private_value

import ast
import json
import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from steuerreport_v2.contracts.events import CanonicalEvent, CanonicalEventCreate
from steuerreport_v2.contracts.installation import SolanaV1OwnershipScopeConfig
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup
from steuerreport_v2.domain.derivative_cash import BITGET_NEUTRAL_ACTIONS, bitget_financial_row
from steuerreport_v2.domain.import_context import timezone_from_name
from steuerreport_v2.importers.source_profiles import (
    SourceProfile,
    normalize_column_name,
    profile_for_source,
)
from steuerreport_v2.paths import PROJECT_ROOT

DEFAULT_PRICE_CONFIG = PROJECT_ROOT / "configs/crypto_price_sources.json"
DEFAULT_SOLANA_OWNERSHIP_CONFIG = private_config_path('solana_v1_ownership_scope.json')
DEFAULT_FAIRSPOT_STAKING_RECONCILIATION_CONFIG = (
    private_config_path('fairspot_hnt_staking_reconciliation.json')
)
DEFAULT_SOLANA_STAKING_POSITION_RECONCILIATIONS_CONFIG = (
    private_config_path('solana_staking_position_reconciliations.json')
)


@dataclass(frozen=True)
class NormalizationReport:
    batch_id: str
    raw_objects: int
    created_events: int
    skipped_raw_objects: int


class RawNormalizer:
    HELIUM_MAIN_LEGACY_WALLET = private_value('legacy_helium_wallet', '')
    HELIUM_FAIRSPOT_STAKING_WALLET = private_value('staking_route_wallet', '')
    HELIUM_VSR_POSITION_RECEIPTS = {key: asset for key, asset in {
        private_value("helium_mobile_position_receipt"): "MOBILE",
        private_value("helium_iot_position_receipt"): "IOT",
    }.items() if key}
    BITGET_INTERNAL_BLOCKPIT_LABELS = {
        "auto-balancing in",
        "auto-balancing out",
        "non-taxable in",
        "non-taxable out",
    }
    BITGET_BLOCKPIT_EVIDENCE_ONLY_RECORD_TYPES = {
        "bitget_fiat_conversion_out_evidence",
        "bitget_unmerged_trade_out_evidence",
    }

    def __init__(
        self,
        store: DuckDbStore,
        *,
        fairspot_staking_config_path: Path | None = None,
        solana_staking_config_path: Path | None = None,
    ) -> None:
        self.store = store
        self._asset_aliases = self._load_asset_aliases(DEFAULT_PRICE_CONFIG)
        self._solana_unowned_txids = self._load_solana_unowned_txids(
            DEFAULT_SOLANA_OWNERSHIP_CONFIG
        )
        self._fairspot_staking_config = self._load_fairspot_staking_config(
            fairspot_staking_config_path
            or DEFAULT_FAIRSPOT_STAKING_RECONCILIATION_CONFIG
        )
        self._solana_staking_config = self._load_fairspot_staking_config(
            solana_staking_config_path
            or DEFAULT_SOLANA_STAKING_POSITION_RECONCILIATIONS_CONFIG
        )

    def normalize_batch(self, batch_id: str) -> list[CanonicalEvent]:
        return self.normalize_batch_with_report(batch_id)[0]

    def normalize_batch_with_report(
        self,
        batch_id: str,
    ) -> tuple[list[CanonicalEvent], NormalizationReport]:
        batch = self.store.get_import_batch(batch_id)
        if batch is None:
            raise ValueError(f"unknown import batch: {batch_id}")

        with self.store.connect() as con:
            con.execute(
                "update raw_import_batches set status = 'loaded' where batch_id = ? and status = 'normalized'",
                [batch_id],
            )
        self.store.delete_canonical_events_for_batch(batch_id)
        events: list[CanonicalEvent] = []
        event_payloads: list[CanonicalEventCreate] = []
        raw_objects = self.store.list_raw_objects(batch_id, limit=None)
        if batch.source == "binance":
            batch_timezone = self._timezone_from_text(batch.filename)
        elif batch.source == "bitget":
            timezone_name = batch.import_context.get("export_timezone")
            batch_timezone = (
                timezone_from_name(timezone_name)
                if timezone_name
                else timezone(timedelta(hours=8))
            )
        else:
            batch_timezone = None
        bound_account = (
            f"connection:{batch.connection_id}"
            if batch.source in {"binance", "bitget"} and batch.connection_id is not None
            else None
        )
        skipped = 0
        event_rows: list[tuple[CanonicalEventCreate, dict[str, str | None]]] = []
        for raw in raw_objects:
            row = json.loads(raw.payload_json)
            if batch.source == "mexc":
                from steuerreport_v2.importers.mexc_native import event_from_raw
                event = event_from_raw(batch, raw)
            else:
                event = self._row_to_event(
                    batch.source,
                    raw.raw_object_id,
                    row,
                    default_timezone=batch_timezone,
                    bound_account=bound_account,
                )
            if event is not None:
                event_rows.append((event, row))
            else:
                skipped += 1
        event_rows = self._merge_binance_small_assets_exchange_bnb(batch.source, event_rows)
        event_rows = self._merge_binance_sol_staking_purchase_quotes(batch.source, event_rows)
        event_rows = self._add_binance_simple_earn_internal_mirrors(
            batch.source,
            event_rows,
        )
        event_rows = self._split_binance_simple_earn_flexible_redemption_yield(batch.source, event_rows)
        event_rows = self._merge_binance_transaction_related_quotes(batch.source, event_rows)
        event_rows = self._merge_binance_same_asset_trade_fees(batch.source, event_rows)
        event_rows = self._merge_binance_transaction_spend_quotes(batch.source, event_rows)
        event_rows = self._merge_binance_same_asset_trade_fees(batch.source, event_rows)
        event_rows = self._split_documented_fairspot_staking_reward(
            batch.source,
            batch.file_hash,
            event_rows,
        )
        event_rows = self._merge_solana_rpc_swap_quotes(batch.source, event_rows)
        event_rows = self._reconcile_solana_rpc_native_wallet_effects(batch.source, event_rows)
        event_rows = self._split_documented_solana_staking_reward(
            batch.source,
            batch.file_hash,
            event_rows,
        )
        event_payloads = [event for event, _row in event_rows]
        events = self.store.add_canonical_events(event_payloads)
        return events, NormalizationReport(
            batch_id=batch_id,
            raw_objects=len(raw_objects),
            created_events=len(events),
            skipped_raw_objects=skipped,
        )

    def _add_binance_simple_earn_internal_mirrors(
        self,
        source: str,
        event_rows: list[tuple[CanonicalEventCreate, dict[str, str | None]]],
    ) -> list[tuple[CanonicalEventCreate, dict[str, str | None]]]:
        if source != "binance_simple_earn_api":
            return event_rows
        transfer_rows = [
            (event, row)
            for event, row in event_rows
            if event.event_type == "transfer"
            and (
                "subscription"
                in str(row.get("record_type") or row.get("record type") or "").lower()
                or "redemption"
                in str(row.get("record_type") or row.get("record type") or "").lower()
            )
            and event.quantity != 0
        ]
        if not transfer_rows:
            return event_rows
        with self.store.connect() as con:
            existing_rows = con.execute(
                """
                select e.event_time, upper(e.asset), e.quantity, r.payload_json
                from canonical_events e
                left join raw_objects r on r.raw_object_id = e.raw_object_id
                where lower(e.source) = 'binance'
                  and lower(coalesce(e.account, '')) = 'spot'
                  and e.event_type in ('transfer', 'income', 'reward')
                  and e.quantity <> 0
                order by e.event_time
                """
            ).fetchall()
        result = list(event_rows)
        tolerance = Decimal("0.000000000001")
        delayed_counterpart_window = timedelta(hours=72)
        for event, raw_row in transfer_rows:
            expected_spot_quantity = -event.quantity
            existing_quantity = sum(
                (
                    quantity
                    for event_time, asset, quantity, _payload_json in existing_rows
                    if str(asset).upper() == event.asset.upper()
                    and abs(
                        (
                            self._utc_datetime(event_time)
                            - self._utc_datetime(event.event_time)
                        ).total_seconds()
                    )
                    <= 2
                    and quantity * expected_spot_quantity > 0
                ),
                Decimal("0"),
            )
            if abs(existing_quantity) <= tolerance:
                record_type = str(
                    raw_row.get("record_type") or raw_row.get("record type") or ""
                ).lower()
                counterpart_kind = (
                    "redemption" if "redemption" in record_type else "subscription"
                )
                existing_quantity = sum(
                    (
                        quantity
                        for event_time, asset, quantity, payload_json in existing_rows
                        if str(asset).upper() == event.asset.upper()
                        and quantity * expected_spot_quantity > 0
                        and timedelta(0)
                        < self._utc_datetime(event_time)
                        - self._utc_datetime(event.event_time)
                        <= delayed_counterpart_window
                        and self._binance_simple_earn_counterpart_kind(payload_json)
                        == counterpart_kind
                    ),
                    Decimal("0"),
                )
            if abs(existing_quantity - expected_spot_quantity) <= tolerance:
                continue
            if abs(existing_quantity) > tolerance:
                # A partial CEX-ledger counterpart needs evidence review. Adding the
                # complete mirror here would overstate the Spot balance.
                continue
            result.append(
                (
                    event.model_copy(
                        update={
                            "source_ref": f"{event.source_ref}:spot_mirror",
                            "quantity": expected_spot_quantity,
                            "account": "Spot",
                            "confidence": Decimal("0.99"),
                        }
                    ),
                    {
                        **raw_row,
                        "evidence_role": "simple_earn_internal_spot_mirror",
                    },
                )
            )
        return result

    @staticmethod
    def _binance_simple_earn_counterpart_kind(payload_json: str | None) -> str | None:
        if not payload_json:
            return None
        try:
            raw_row = json.loads(payload_json)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(raw_row, dict):
            return None
        normalized = {
            normalize_column_name(str(key)): str(value or "").strip().lower()
            for key, value in raw_row.items()
        }
        operation = next(
            (
                normalized[key]
                for key in ("operation", "type", "category")
                if normalized.get(key)
            ),
            "",
        )
        if "simple earn" not in operation:
            return None
        if "redemption" in operation:
            return "redemption"
        if "subscription" in operation:
            return "subscription"
        return None

    @staticmethod
    def _utc_datetime(value: datetime) -> datetime:
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )

    def _split_documented_fairspot_staking_reward(
        self,
        source: str,
        file_hash: str,
        rows: list[tuple[CanonicalEventCreate, dict[str, str | None]]],
    ) -> list[tuple[CanonicalEventCreate, dict[str, str | None]]]:
        config = self._fairspot_staking_config
        primary_source = config.get("primary_source", {})
        if (
            source.lower() != "helium"
            or config.get("review_status") != "approved_evidence_overlay"
            or not isinstance(primary_source, dict)
            or str(primary_source.get("file_hash") or "") != file_hash
        ):
            return rows
        rules = config.get("return_splits")
        if not isinstance(rules, list):
            return rows
        rules_by_tx_id: dict[str, dict[str, object]] = {}
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            tx_ids = [str(rule.get("tx_id") or "")]
            aliases = rule.get("tx_id_aliases")
            if isinstance(aliases, list):
                tx_ids.extend(str(value) for value in aliases)
            for tx_id in tx_ids:
                if tx_id:
                    rules_by_tx_id[tx_id] = rule
        result: list[tuple[CanonicalEventCreate, dict[str, str | None]]] = []
        for event, raw_row in rows:
            rule = rules_by_tx_id.get(str(event.tx_id or ""))
            if (
                rule is None
                or event.event_type != "transfer"
                or event.asset.upper() != "HNT"
                or event.quantity <= 0
                or event.account != str(config.get("main_wallet") or "")
            ):
                result.append((event, raw_row))
                continue
            received = Decimal(str(rule.get("received_quantity") or "0"))
            principal = Decimal(str(rule.get("principal_quantity") or "0"))
            reward = Decimal(str(rule.get("reward_quantity") or "0"))
            if (
                event.quantity != received
                or principal <= 0
                or reward <= 0
                or principal + reward != received
            ):
                result.append((event, raw_row))
                continue
            principal_quote = event.quote_quantity
            reward_quote = None
            if event.quote_quantity is not None:
                reward_quote = event.quote_quantity * reward / received
                principal_quote = event.quote_quantity - reward_quote
            result.append(
                (
                    event.model_copy(
                        update={
                            "quantity": principal,
                            "quote_quantity": principal_quote,
                            "confidence": Decimal("0.99"),
                        }
                    ),
                    raw_row,
                )
            )
            result.append(
                (
                    event.model_copy(
                        update={
                            "event_type": "reward",
                            "quantity": reward,
                            "quote_quantity": reward_quote,
                            "fee_asset": None,
                            "fee_quantity": None,
                            "confidence": Decimal("0.99"),
                        }
                    ),
                    raw_row,
                )
            )
        return result

    @staticmethod
    def _load_fairspot_staking_config(path: Path) -> dict[str, object]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _split_documented_solana_staking_reward(
        self,
        source: str,
        file_hash: str,
        rows: list[tuple[CanonicalEventCreate, dict[str, str | None]]],
    ) -> list[tuple[CanonicalEventCreate, dict[str, str | None]]]:
        config = self._solana_staking_config
        if (
            source.lower() != "solana_rpc"
            or config.get("review_status") != "approved_evidence_overlay"
        ):
            return rows
        positions = config.get("positions")
        if not isinstance(positions, list):
            return rows
        rules: dict[str, tuple[dict[str, object], dict[str, object]]] = {}
        for position in positions:
            if not isinstance(position, dict):
                continue
            position_return = position.get("position_return")
            if not isinstance(position_return, dict):
                continue
            tx_id = str(position_return.get("tx_id") or "")
            if tx_id and str(position_return.get("source_file_hash") or "") == file_hash:
                rules[tx_id] = (position, position_return)
        result: list[tuple[CanonicalEventCreate, dict[str, str | None]]] = []
        for event, raw_row in rows:
            rule = rules.get(str(event.tx_id or ""))
            if rule is None:
                result.append((event, raw_row))
                continue
            position, position_return = rule
            received = Decimal(str(position_return.get("received_quantity") or "0"))
            principal = Decimal(str(position_return.get("principal_quantity") or "0"))
            reward = Decimal(str(position_return.get("reward_quantity") or "0"))
            if (
                event.event_type != "transfer"
                or event.asset.upper() != str(position.get("asset") or "").upper()
                or event.account != str(position.get("wallet") or "")
                or event.quantity != received
                or principal <= 0
                or reward <= 0
                or principal + reward != received
            ):
                result.append((event, raw_row))
                continue
            principal_quote = event.quote_quantity
            reward_quote = None
            if event.quote_quantity is not None:
                reward_quote = event.quote_quantity * reward / received
                principal_quote = event.quote_quantity - reward_quote
            result.append(
                (
                    event.model_copy(
                        update={
                            "quantity": principal,
                            "quote_quantity": principal_quote,
                            "confidence": Decimal("0.99"),
                        }
                    ),
                    raw_row,
                )
            )
            result.append(
                (
                    event.model_copy(
                        update={
                            "event_type": "reward",
                            "quantity": reward,
                            "quote_quantity": reward_quote,
                            "fee_asset": None,
                            "fee_quantity": None,
                            "confidence": Decimal("0.99"),
                        }
                    ),
                    raw_row,
                )
            )
        return result

    def _row_to_event(
        self,
        source: str,
        raw_object_id: str,
        row: dict[str, str | None],
        *,
        default_timezone: tzinfo | None = None,
        bound_account: str | None = None,
    ) -> CanonicalEventCreate | None:
        if source.strip().lower() == "mexc":
            return None
        if row.get("history_evidence_only") == "1" and row.get("history_scope_identity"):
            return None
        profile = profile_for_source(source)
        normalized = {self._normalize_key(key): value for key, value in row.items()}
        if (
            profile.source == "pionex"
            and str(normalized.get("state") or "").strip().upper() == "CANCELED"
            and not self._pionex_row_has_execution(normalized)
        ):
            return None
        if (
            profile.source == "bitget"
            and str(normalized.get("record type") or normalized.get("record_type") or "").strip().lower()
            == "bitget_withdrawal_evidence"
        ):
            return None
        if self._is_bitget_non_balance_blockpit_evidence(normalized, profile):
            return self._bitget_non_balance_blockpit_evidence_event(
                source,
                raw_object_id,
                normalized,
                profile,
                default_timezone=default_timezone,
            )
        if profile.source == "binance_simple_earn_api":
            return self._binance_simple_earn_event(source, raw_object_id, normalized)
        if profile.source == "binance_asset_dividend_api":
            return self._binance_asset_dividend_event(
                source, raw_object_id, normalized
            )
        if profile.source == "binance_withdrawal_api":
            return self._binance_withdrawal_evidence_event(
                source,
                raw_object_id,
                normalized,
                profile,
                default_timezone=default_timezone,
            )
        is_bitget_spot_financial_quote_shadow = self._is_bitget_spot_financial_quote_shadow(normalized)
        is_failed_binance_status = (
            profile.source == "binance" and self._is_failed_binance_status(normalized)
        )
        raw_type = self._first_value(normalized, list(profile.type_columns)) or ""
        derived_trade = self._derived_trade_leg(normalized, profile)
        pair = self._first_value(normalized, list(profile.pair_columns))
        asset = self._first_value(normalized, list(profile.asset_columns))
        _, parsed_asset_from_asset_field = self._split_amount_asset(asset)
        if parsed_asset_from_asset_field is not None:
            asset = parsed_asset_from_asset_field
        if asset is None:
            asset = self._base_asset_from_pair(pair)
        quantity_raw = self._first_value(normalized, list(profile.quantity_columns))
        derived_quantity_raw, derived_asset = self._derived_quantity_asset(normalized, profile)
        if derived_trade is not None:
            asset = derived_trade[0]
            quantity_raw = derived_trade[1]
        quantity_raw = self._correct_scaled_quantity(normalized, profile, quantity_raw)
        if (
            profile.source in {"blockpit", "blockpit-solana"}
            and derived_trade is None
            and derived_quantity_raw is not None
        ):
            quantity_raw = derived_quantity_raw
        if quantity_raw is None or (
            derived_quantity_raw is not None and not self._has_decimal_value(quantity_raw)
        ):
            quantity_raw = derived_quantity_raw
        if asset is None:
            asset = derived_asset
        time_raw = self._first_value(normalized, list(profile.time_columns))
        quantity_raw, parsed_asset = self._split_amount_asset(quantity_raw)
        if asset is None:
            asset = parsed_asset
        if asset is None or quantity_raw is None or time_raw is None:
            return None

        try:
            quantity = Decimal(self._normalize_decimal_text(str(quantity_raw)))
        except InvalidOperation:
            return None

        event_type = self._event_type(normalized, profile)
        if derived_trade is not None:
            event_type = "trade"
        is_binance_card_buy_mirror = (
            profile.source == "binance"
            and str(raw_type).strip().lower() == "buy crypto with card"
        )
        is_binance_fiat_ocbs_mirror = (
            profile.source == "binance"
            and str(raw_type).strip().lower() == "fiat ocbs - add fiat and fees"
        )
        if derived_trade is not None and quantity > 0 and derived_trade[2]:
            quantity = -quantity
        sign_context = raw_type
        if profile.source == "solana_rpc" and normalized.get("side"):
            sign_context = f"{raw_type} {normalized.get('side')}"
        account = self._event_account(
            normalized, profile, event_type, bound_account=bound_account,
        )
        if profile.source == "helium" and event_type == "transfer":
            sign_context = self._helium_transfer_sign_context(normalized, account, raw_type)
        quantity = self._signed_quantity(quantity, event_type, sign_context)
        if (profile.source == "bitget" and bitget_financial_row(normalized)
                and raw_type.strip().lower() in BITGET_NEUTRAL_ACTIONS):
            quantity = Decimal("0")
        if profile.source == "solana_rpc" and raw_type.strip().lower() == "network_fee":
            quantity = -abs(quantity)
        if (
            profile.source == "coinbase"
            and event_type == "transfer"
            and quantity > 0
            and any(token in raw_type.strip().lower() for token in ("send", "withdraw"))
        ):
            quantity = -quantity
        if (
            profile.source == "solana_rpc"
            and event_type == "transfer"
            and raw_type.strip().lower() == "token_transfer"
            and quantity > 0
            and not self._is_direct_solana_history(row)
        ):
            event_type = (
                "reward"
                if self._is_solana_helium_reward_transfer(normalized, asset)
                else "income"
            )
        if is_failed_binance_status:
            event_type = "unknown"
            quantity = Decimal("0")
        elif is_binance_card_buy_mirror:
            if quantity > 0 and self._canonical_asset(asset) != "EUR":
                event_type = "transfer"
            else:
                event_type = "unknown"
                quantity = Decimal("0")
        elif is_binance_fiat_ocbs_mirror:
            event_type = "unknown"
            quantity = Decimal("0")
        elif is_bitget_spot_financial_quote_shadow:
            event_type = "unknown"
            quantity = Decimal("0")
        quote_raw = self._first_value(normalized, list(profile.quote_quantity_columns))
        if derived_trade is not None:
            quote_raw = derived_trade[4]
        quote_raw, parsed_quote_asset = self._split_amount_asset(quote_raw)
        if profile.source == "coinbase":
            quote_raw = self._coinbase_numeric_text(quote_raw)
        quote_quantity = self._decimal_or_none(quote_raw)
        quote_asset = self._first_value(normalized, list(profile.quote_asset_columns))
        if derived_trade is not None:
            quote_asset = derived_trade[3]
        if quote_asset is None:
            quote_asset = self._quote_asset_from_pair(pair)
        if quote_asset is None:
            quote_asset = parsed_quote_asset
        if (
            profile.source == "bitget"
            and quote_asset is None
            and quote_quantity is not None
            and (
                normalized.get("amount in usdt") is not None
                or normalized.get("amount (usdt)") is not None
                or normalized.get("executed amount (usdt)") is not None
            )
            and asset is not None
            and self._canonical_asset(asset) != "USDT"
        ):
            quote_asset = "USDT"
        if profile.source in {"blockpit", "blockpit-solana"} and derived_trade is None:
            quote_asset = None
            quote_quantity = None
        if (
            is_failed_binance_status
            or is_binance_card_buy_mirror
            or is_binance_fiat_ocbs_mirror
            or is_bitget_spot_financial_quote_shadow
        ):
            quote_asset = None
            quote_quantity = None
        fee_asset = self._first_value(normalized, list(profile.fee_asset_columns))
        if profile.source == "bitget" and fee_asset is None:
            fee_asset = asset
        fee_raw = self._first_value(normalized, list(profile.fee_quantity_columns))
        if profile.source == "coinbase":
            fee_raw = self._coinbase_numeric_text(fee_raw)
        fee_quantity = self._decimal_or_none(fee_raw)
        if (
            is_failed_binance_status
            or is_binance_card_buy_mirror
            or is_binance_fiat_ocbs_mirror
            or is_bitget_spot_financial_quote_shadow
        ):
            fee_asset = None
            fee_quantity = None
        return CanonicalEventCreate(
            source=source,
            source_ref=self._first_value(normalized, list(profile.source_ref_columns)),
            event_time=self._parse_event_datetime_for_row(
                str(time_raw),
                profile,
                normalized,
                default_timezone=default_timezone,
            ),
            event_type=event_type,
            asset=self._canonical_asset(asset),
            quantity=quantity,
            quote_asset=self._upper_or_none(quote_asset),
            quote_quantity=quote_quantity,
            fee_asset=self._upper_or_none(fee_asset),
            fee_quantity=fee_quantity,
            tx_id=self._first_value(normalized, list(profile.tx_id_columns)),
            account=account,
            confidence=Decimal("0.70") if event_type == "unknown" else Decimal("0.90"),
            raw_object_id=raw_object_id,
        )

    def _binance_withdrawal_evidence_event(
        self,
        source: str,
        raw_object_id: str,
        row: dict[str, str | None],
        profile: SourceProfile,
        *,
        default_timezone: timezone | None = None,
    ) -> CanonicalEventCreate | None:
        asset = self._first_value(row, list(profile.asset_columns))
        time_raw = self._first_value(row, list(profile.time_columns))
        if asset is None or time_raw is None:
            return None
        return CanonicalEventCreate(
            source=source,
            source_ref=self._first_value(row, list(profile.source_ref_columns)),
            event_time=self._parse_event_datetime_for_row(
                str(time_raw),
                profile,
                row,
                default_timezone=default_timezone,
            ),
            event_type="unknown",
            asset=self._canonical_asset(asset),
            quantity=Decimal("0"),
            tx_id=self._first_value(row, list(profile.tx_id_columns)),
            account=self._event_account(row, profile, "unknown"),
            confidence=Decimal("0.95"),
            raw_object_id=raw_object_id,
        )

    def _is_bitget_non_balance_blockpit_evidence(
        self,
        row: dict[str, str | None],
        profile: SourceProfile,
    ) -> bool:
        if profile.source != "blockpit":
            return False
        integration = str(
            row.get("integration name") or row.get("source name") or ""
        ).strip().lower()
        if integration != "bitget":
            return False
        label = str(row.get("label") or "").strip().lower()
        record_type = str(
            row.get("record type") or row.get("record_type") or ""
        ).strip().lower()
        return (
            label in self.BITGET_INTERNAL_BLOCKPIT_LABELS
            or record_type in self.BITGET_BLOCKPIT_EVIDENCE_ONLY_RECORD_TYPES
        )

    def _bitget_non_balance_blockpit_evidence_event(
        self,
        source: str,
        raw_object_id: str,
        row: dict[str, str | None],
        profile: SourceProfile,
        *,
        default_timezone: timezone | None = None,
    ) -> CanonicalEventCreate | None:
        time_raw = self._first_value(row, list(profile.time_columns))
        amount_raw, asset = self._derived_quantity_asset(row, profile)
        if time_raw is None or amount_raw is None or asset is None:
            return None
        return CanonicalEventCreate(
            source=source,
            source_ref=self._first_value(row, list(profile.source_ref_columns)),
            event_time=self._parse_event_datetime_for_row(
                str(time_raw),
                profile,
                row,
                default_timezone=default_timezone,
            ),
            event_type="unknown",
            asset=self._canonical_asset(asset),
            quantity=Decimal("0"),
            tx_id=self._first_value(row, list(profile.tx_id_columns)),
            account=self._event_account(row, profile, "unknown"),
            confidence=Decimal("0.95"),
            raw_object_id=raw_object_id,
        )

    def _merge_binance_transaction_related_quotes(
        self,
        source: str,
        event_rows: list[tuple[CanonicalEventCreate, dict[str, str | None]]],
    ) -> list[tuple[CanonicalEventCreate, dict[str, str | None]]]:
        if source != "binance":
            return event_rows

        grouped: dict[
            tuple[datetime, str, str],
            list[tuple[int, CanonicalEventCreate, dict[str, str | None]]],
        ] = {}
        passthrough: list[tuple[int, CanonicalEventCreate, dict[str, str | None]]] = []
        for index, (event, row) in enumerate(event_rows):
            operation = self._binance_operation(row)
            if operation == "transaction related":
                remark = str(row.get("Remark") or row.get("remark") or "")
                grouped.setdefault((event.event_time, event.account or "", remark), []).append(
                    (index, event, row)
                )
            else:
                passthrough.append((index, event, row))

        if not grouped:
            return event_rows

        rewritten: list[tuple[int, CanonicalEventCreate, dict[str, str | None]]] = passthrough
        for _key, items in grouped.items():
            spend_items = [(index, event, row) for index, event, row in items if event.quantity < 0]
            buy_items = [(index, event, row) for index, event, row in items if event.quantity > 0]
            spend_assets = {event.asset for _index, event, _row in spend_items}
            total_spend = sum((abs(event.quantity) for _index, event, _row in spend_items), Decimal("0"))
            total_quantity = sum((event.quantity for _index, event, _row in buy_items), Decimal("0"))
            if len(spend_assets) != 1 or total_spend <= 0 or total_quantity <= 0:
                rewritten.extend(items)
                continue

            spend_asset = next(iter(spend_assets))
            spend_indexes = {index for index, _event, _row in spend_items}
            buy_indexes = {index for index, _event, _row in buy_items}
            for index, event, row in items:
                if index in spend_indexes:
                    rewritten.append(
                        (
                            index,
                            event.model_copy(
                                update={
                                    "event_type": "unknown",
                                    "quantity": Decimal("0"),
                                    "quote_asset": None,
                                    "quote_quantity": None,
                                    "confidence": Decimal("0.70"),
                                }
                            ),
                            row,
                        )
                    )
                    continue
                if index in buy_indexes:
                    quote_quantity = total_spend * (event.quantity / total_quantity)
                    rewritten.append(
                        (
                            index,
                            event.model_copy(
                                update={
                                    "event_type": "trade",
                                    "quote_asset": spend_asset,
                                    "quote_quantity": quote_quantity,
                                    "confidence": Decimal("0.90"),
                                }
                            ),
                            row,
                        )
                    )
                    continue
                rewritten.append((index, event, row))

        return [(event, row) for _index, event, row in sorted(rewritten, key=lambda item: item[0])]

    def _merge_binance_sol_staking_purchase_quotes(
        self,
        source: str,
        event_rows: list[tuple[CanonicalEventCreate, dict[str, str | None]]],
    ) -> list[tuple[CanonicalEventCreate, dict[str, str | None]]]:
        if source != "binance":
            return event_rows

        grouped: dict[
            tuple[datetime, str, str],
            list[tuple[int, CanonicalEventCreate, dict[str, str | None]]],
        ] = {}
        passthrough: list[tuple[int, CanonicalEventCreate, dict[str, str | None]]] = []
        for index, (event, row) in enumerate(event_rows):
            operation = self._binance_operation(row)
            if operation == "sol staking - purchase":
                grouped.setdefault((event.event_time, event.account or "", operation), []).append(
                    (index, event, row)
                )
            else:
                passthrough.append((index, event, row))

        if not grouped:
            return event_rows

        rewritten: list[tuple[int, CanonicalEventCreate, dict[str, str | None]]] = passthrough
        for _key, items in grouped.items():
            spend_items = [
                (index, event, row)
                for index, event, row in items
                if event.asset == "SOL" and event.quantity < 0
            ]
            buy_items = [
                (index, event, row)
                for index, event, row in items
                if event.asset == "BNSOL" and event.quantity > 0
            ]
            total_spend = sum((abs(event.quantity) for _index, event, _row in spend_items), Decimal("0"))
            total_quantity = sum((event.quantity for _index, event, _row in buy_items), Decimal("0"))
            if total_spend <= 0 or total_quantity <= 0:
                rewritten.extend(items)
                continue

            spend_indexes = {index for index, _event, _row in spend_items}
            buy_indexes = {index for index, _event, _row in buy_items}
            for index, event, row in items:
                if index in spend_indexes:
                    rewritten.append(
                        (
                            index,
                            event.model_copy(
                                update={
                                    "event_type": "unknown",
                                    "quantity": Decimal("0"),
                                    "quote_asset": None,
                                    "quote_quantity": None,
                                    "confidence": Decimal("0.70"),
                                }
                            ),
                            row,
                        )
                    )
                    continue
                if index in buy_indexes:
                    quote_quantity = total_spend * (event.quantity / total_quantity)
                    rewritten.append(
                        (
                            index,
                            event.model_copy(
                                update={
                                    "event_type": "trade",
                                    "quote_asset": "SOL",
                                    "quote_quantity": quote_quantity,
                                    "confidence": Decimal("0.90"),
                                }
                            ),
                            row,
                        )
                    )
                    continue
                rewritten.append((index, event, row))

        return [(event, row) for _index, event, row in sorted(rewritten, key=lambda item: item[0])]

    def _split_binance_simple_earn_flexible_redemption_yield(
        self,
        source: str,
        event_rows: list[tuple[CanonicalEventCreate, dict[str, str | None]]],
    ) -> list[tuple[CanonicalEventCreate, dict[str, str | None]]]:
        if source != "binance":
            return event_rows

        principal_by_key: dict[tuple[str, str], Decimal] = {}
        rewritten: list[
            tuple[tuple[datetime, int, int], CanonicalEventCreate, dict[str, str | None]]
        ] = []
        chronological = sorted(
            enumerate(event_rows),
            key=lambda item: (item[1][0].event_time, item[0]),
        )
        for index, (event, row) in chronological:
            operation = self._binance_operation(row)
            key = (event.account or "", event.asset)
            if operation == "simple earn flexible subscription" and event.quantity < 0:
                principal_by_key[key] = principal_by_key.get(key, Decimal("0")) + abs(event.quantity)
                rewritten.append(((event.event_time, index, 0), event, row))
                continue

            if operation == "simple earn flexible redemption" and event.quantity > 0:
                available = principal_by_key.get(key, Decimal("0"))
                if available <= 0:
                    rewritten.append(((event.event_time, index, 0), event, row))
                    continue
                transfer_quantity = min(event.quantity, available)
                yield_quantity = event.quantity - transfer_quantity
                principal_by_key[key] = available - transfer_quantity
                if transfer_quantity > 0:
                    rewritten.append(
                        (
                            (event.event_time, index, 0),
                            event.model_copy(
                                update={
                                    "quantity": transfer_quantity,
                                    "event_type": "transfer",
                                    "quote_asset": None,
                                    "quote_quantity": None,
                                    "confidence": Decimal("0.90"),
                                }
                            ),
                            row,
                        )
                    )
                if yield_quantity > 0:
                    rewritten.append(
                        (
                            (event.event_time, index, 1),
                            event.model_copy(
                                update={
                                    "quantity": yield_quantity,
                                    "event_type": "income",
                                    "quote_asset": None,
                                    "quote_quantity": None,
                                    "confidence": Decimal("0.85"),
                                }
                            ),
                            row,
                        )
                    )
                continue

            rewritten.append(((event.event_time, index, 0), event, row))

        return [(event, row) for _sort_key, event, row in sorted(rewritten, key=lambda item: item[0])]

    def _merge_binance_same_asset_trade_fees(
        self,
        source: str,
        event_rows: list[tuple[CanonicalEventCreate, dict[str, str | None]]],
    ) -> list[tuple[CanonicalEventCreate, dict[str, str | None]]]:
        if source != "binance":
            return event_rows

        grouped: dict[
            tuple[datetime, str, str],
            list[tuple[int, CanonicalEventCreate, dict[str, str | None]]],
        ] = {}
        passthrough: list[tuple[int, CanonicalEventCreate, dict[str, str | None]]] = []
        for index, (event, row) in enumerate(event_rows):
            operation = self._binance_operation(row)
            if operation in {"fee", "transaction fee"} or (
                event.event_type == "trade" and event.quantity > 0
            ):
                grouped.setdefault((event.event_time, event.account or "", event.asset), []).append(
                    (index, event, row)
                )
            else:
                passthrough.append((index, event, row))

        if not grouped:
            return event_rows

        rewritten: list[tuple[int, CanonicalEventCreate, dict[str, str | None]]] = passthrough
        for _key, items in grouped.items():
            fee_items = [
                (index, event, row)
                for index, event, row in items
                if self._binance_operation(row) in {"fee", "transaction fee"} and event.quantity < 0
            ]
            trade_items = [
                (index, event, row)
                for index, event, row in items
                if event.event_type == "trade" and event.quantity > 0
            ]
            total_fee = sum((abs(event.quantity) for _index, event, _row in fee_items), Decimal("0"))
            total_trade = sum((event.quantity for _index, event, _row in trade_items), Decimal("0"))
            if total_fee <= 0 or total_trade <= total_fee:
                rewritten.extend(items)
                continue

            fee_indexes = {index for index, _event, _row in fee_items}
            trade_indexes = {index for index, _event, _row in trade_items}
            for index, event, row in items:
                if index in fee_indexes:
                    rewritten.append(
                        (
                            index,
                            event.model_copy(
                                update={
                                    "event_type": "unknown",
                                    "quantity": Decimal("0"),
                                    "quote_asset": None,
                                    "quote_quantity": None,
                                    "fee_asset": None,
                                    "fee_quantity": None,
                                    "confidence": Decimal("0.70"),
                                }
                            ),
                            row,
                        )
                    )
                    continue
                if index in trade_indexes:
                    fee_share = total_fee * (event.quantity / total_trade)
                    rewritten.append(
                        (
                            index,
                            event.model_copy(
                                update={
                                    "quantity": event.quantity - fee_share,
                                    "confidence": Decimal("0.90"),
                                }
                            ),
                            row,
                        )
                    )
                    continue
                rewritten.append((index, event, row))

        return [(event, row) for _index, event, row in sorted(rewritten, key=lambda item: item[0])]

    def _merge_binance_transaction_spend_quotes(
        self,
        source: str,
        event_rows: list[tuple[CanonicalEventCreate, dict[str, str | None]]],
    ) -> list[tuple[CanonicalEventCreate, dict[str, str | None]]]:
        if source != "binance":
            return event_rows

        grouped: dict[tuple[datetime, str], list[tuple[int, CanonicalEventCreate, dict[str, str | None]]]] = {}
        passthrough: list[tuple[int, CanonicalEventCreate, dict[str, str | None]]] = []
        for index, (event, row) in enumerate(event_rows):
            operation = self._binance_operation(row)
            if operation in {
                "transaction buy",
                "transaction revenue",
                "transaction spend",
                "transaction sold",
            }:
                grouped.setdefault((event.event_time, event.account or ""), []).append((index, event, row))
            else:
                passthrough.append((index, event, row))

        rewritten: list[tuple[int, CanonicalEventCreate, dict[str, str | None]]] = passthrough
        for _key, items in grouped.items():
            spend_items = [
                (index, event, row)
                for index, event, row in items
                if event.quantity < 0
                and self._binance_operation(row) in {"transaction spend", "transaction sold"}
            ]
            buy_items = [
                (index, event, row)
                for index, event, row in items
                if event.quantity > 0
                and self._binance_operation(row)
                in {"transaction buy", "transaction revenue", "transaction sold"}
            ]
            if not spend_items or not buy_items:
                rewritten.extend(items)
                continue

            spend_assets = {event.asset for _index, event, _row in spend_items}
            if len(spend_assets) != 1:
                rewritten.extend(items)
                continue
            spend_asset = next(iter(spend_assets))
            total_spend = sum((abs(event.quantity) for _index, event, _row in spend_items), Decimal("0"))
            total_quantity = sum((event.quantity for _index, event, _row in buy_items), Decimal("0"))
            if total_spend <= 0 or total_quantity <= 0:
                rewritten.extend(items)
                continue

            spend_indexes = {index for index, _event, _row in spend_items}
            buy_indexes = {index for index, _event, _row in buy_items}
            for index, event, row in items:
                if index in spend_indexes:
                    rewritten.append(
                        (
                            index,
                            event.model_copy(
                                update={
                                    "event_type": "unknown",
                                    "quantity": Decimal("0"),
                                    "quote_asset": None,
                                    "quote_quantity": None,
                                    "confidence": Decimal("0.70"),
                                }
                            ),
                            row,
                        )
                    )
                    continue
                if index in buy_indexes:
                    quote_quantity = total_spend * (event.quantity / total_quantity)
                    rewritten.append(
                        (
                            index,
                            event.model_copy(
                                update={
                                    "event_type": "trade",
                                    "quote_asset": spend_asset,
                                    "quote_quantity": quote_quantity,
                                    "confidence": Decimal("0.90"),
                                }
                            ),
                            row,
                        )
                    )
                    continue
                rewritten.append((index, event, row))

        return [
            (event, row)
            for _index, event, row in sorted(rewritten, key=lambda item: item[0])
        ]

    def _binance_operation(self, row: dict[str, str | None]) -> str:
        return str(row.get("Operation") or row.get("operation") or "").strip().lower()

    def _merge_binance_small_assets_exchange_bnb(
        self,
        source: str,
        event_rows: list[tuple[CanonicalEventCreate, dict[str, str | None]]],
    ) -> list[tuple[CanonicalEventCreate, dict[str, str | None]]]:
        if source != "binance":
            return event_rows

        grouped: dict[tuple[datetime, str], list[tuple[int, CanonicalEventCreate, dict[str, str | None]]]] = {}
        passthrough: list[tuple[int, CanonicalEventCreate, dict[str, str | None]]] = []
        for index, (event, row) in enumerate(event_rows):
            if self._binance_operation(row) == "small assets exchange bnb":
                grouped.setdefault((event.event_time, event.account or ""), []).append((index, event, row))
            else:
                passthrough.append((index, event, row))

        if not grouped:
            return event_rows

        price_lookup = HistoricalPriceLookup(self.store)
        rewritten: list[tuple[int, CanonicalEventCreate, dict[str, str | None]]] = passthrough
        for _key, items in grouped.items():
            bnb_in = [
                (index, event, row)
                for index, event, row in items
                if event.asset == "BNB" and event.quantity > 0
            ]
            dust_out = [
                (index, event, row)
                for index, event, row in items
                if event.asset != "BNB" and event.quantity < 0
            ]
            total_bnb = sum((event.quantity for _index, event, _row in bnb_in), Decimal("0"))
            if total_bnb <= 0 or not dust_out:
                rewritten.extend(items)
                continue

            weighted_out: list[tuple[int, CanonicalEventCreate, dict[str, str | None], Decimal]] = []
            for index, event, row in dust_out:
                try:
                    price = price_lookup.at_or_before(
                        event.asset,
                        event.event_time,
                        allow_derived=False,
                    )
                except TypeError:
                    price = price_lookup.at_or_before(
                        event.asset,
                        event.event_time.replace(tzinfo=None),
                        allow_derived=False,
                    )
                value = abs(event.quantity) * price.price_eur if price is not None else Decimal("0")
                weighted_out.append((index, event, row, value))

            total_weight = sum((value for _index, _event, _row, value in weighted_out), Decimal("0"))
            if total_weight <= 0:
                weighted_out = [
                    (index, event, row, abs(event.quantity))
                    for index, event, row, _value in weighted_out
                ]
                total_weight = sum((value for _index, _event, _row, value in weighted_out), Decimal("0"))
            if total_weight <= 0:
                rewritten.extend(items)
                continue

            rewritten_indexes = {index for index, _event, _row in bnb_in}
            rewritten_indexes.update(index for index, _event, _row, _value in weighted_out)
            for index, event, row, value in weighted_out:
                quote_quantity = total_bnb * (value / total_weight)
                rewritten.append(
                    (
                        index,
                        event.model_copy(
                            update={
                                "event_type": "trade",
                                "quote_asset": "BNB",
                                "quote_quantity": quote_quantity,
                                "confidence": Decimal("0.90"),
                            }
                        ),
                        row,
                    )
                )
            for index, event, row in bnb_in:
                rewritten.append(
                    (
                        index,
                        event.model_copy(
                            update={
                                "event_type": "unknown",
                                "quantity": Decimal("0"),
                                "quote_asset": None,
                                "quote_quantity": None,
                                "confidence": Decimal("0.70"),
                            }
                        ),
                        row,
                    )
                )
            rewritten.extend(item for item in items if item[0] not in rewritten_indexes)

        return [(event, row) for _index, event, row in sorted(rewritten, key=lambda item: item[0])]

    def _merge_solana_rpc_swap_quotes(
        self,
        source: str,
        event_rows: list[tuple[CanonicalEventCreate, dict[str, str | None]]],
    ) -> list[tuple[CanonicalEventCreate, dict[str, str | None]]]:
        if source != "solana_rpc":
            return event_rows

        grouped: dict[str, list[tuple[int, CanonicalEventCreate, dict[str, str | None]]]] = {}
        for index, (event, row) in enumerate(event_rows):
            if self._is_direct_solana_history(row):
                continue
            if event.event_type in {"trade", "transfer", "income"} and event.tx_id:
                grouped.setdefault(event.tx_id, []).append((index, event, row))

        rewritten: dict[int, CanonicalEventCreate] = {}
        for _tx_id, items in grouped.items():
            vsr_position = next(
                (
                    (event.asset, self.HELIUM_VSR_POSITION_RECEIPTS[event.asset])
                    for _index, event, _row in items
                    if event.quantity > 0 and event.asset in self.HELIUM_VSR_POSITION_RECEIPTS
                ),
                None,
            )
            if vsr_position is not None:
                receipt_asset, principal_asset = vsr_position
                principal_rows = [
                    (index, event)
                    for index, event, _row in items
                    if event.asset == principal_asset and event.quantity < 0
                ]
                if principal_rows:
                    for index, event, _row in items:
                        if event.asset == principal_asset and event.quantity < 0:
                            rewritten[index] = event.model_copy(
                                update={
                                    "event_type": "transfer",
                                    "quote_asset": None,
                                    "quote_quantity": None,
                                    "confidence": Decimal("0.98"),
                                }
                            )
                        elif event.asset == receipt_asset and event.quantity > 0:
                            rewritten[index] = event.model_copy(
                                update={
                                    "event_type": "unknown",
                                    "quantity": Decimal("0"),
                                    "quote_asset": None,
                                    "quote_quantity": None,
                                    "fee_asset": None,
                                    "fee_quantity": None,
                                    "confidence": Decimal("0.98"),
                                }
                            )
                    continue
            if any(self._contains_solana_claim_or_airdrop_instruction(row) for _index, _event, row in items):
                continue
            incoming = [(index, event) for index, event, _row in items if event.quantity > 0]
            outgoing = [(index, event) for index, event, _row in items if event.quantity < 0]
            if not incoming or not outgoing:
                continue

            incoming_by_asset = self._sum_by_asset(event for _index, event in incoming)
            outgoing_by_asset = self._sum_by_asset(
                event.model_copy(update={"quantity": abs(event.quantity)})
                for _index, event in outgoing
            )
            if len(incoming_by_asset) != 1:
                continue
            if len(outgoing_by_asset) != 1:
                outgoing_by_asset = self._solana_rpc_collapse_dust_outgoing(outgoing_by_asset)
                if len(outgoing_by_asset) != 1:
                    continue

            incoming_asset, incoming_quantity = next(iter(incoming_by_asset.items()))
            outgoing_asset, outgoing_quantity = next(iter(outgoing_by_asset.items()))
            if incoming_asset == outgoing_asset:
                continue
            for index, event in incoming:
                base_update = {
                    "event_type": "trade",
                    "confidence": max(event.confidence, Decimal("0.90")),
                }
                if (
                    not self._is_configured_asset(incoming_asset)
                    and self._is_configured_asset(outgoing_asset)
                ):
                    rewritten[index] = event.model_copy(
                        update={
                            **base_update,
                            "asset": outgoing_asset,
                            "quantity": -(outgoing_quantity * (event.quantity / incoming_quantity)),
                            "quote_asset": None,
                            "quote_quantity": None,
                            "confidence": Decimal("0.70"),
                        }
                    )
                    continue
                if (
                    self._is_configured_asset(incoming_asset)
                    and not self._is_configured_asset(outgoing_asset)
                ):
                    rewritten[index] = event.model_copy(
                        update={
                            **base_update,
                            "event_type": "income",
                            "quote_asset": None,
                            "quote_quantity": None,
                            "confidence": Decimal("0.70"),
                        }
                    )
                    continue
                if self._is_cash_or_stable(incoming_asset) and not self._is_cash_or_stable(outgoing_asset):
                    rewritten[index] = event.model_copy(
                        update={
                            **base_update,
                            "asset": outgoing_asset,
                            "quantity": -(outgoing_quantity * (event.quantity / incoming_quantity)),
                            "quote_asset": incoming_asset,
                            "quote_quantity": event.quantity,
                        }
                    )
                    continue
                rewritten[index] = event.model_copy(
                    update={
                        **base_update,
                        "quote_asset": outgoing_asset,
                        "quote_quantity": outgoing_quantity * (event.quantity / incoming_quantity),
                    }
                )
            for index, event in outgoing:
                rewritten[index] = event.model_copy(
                    update={
                        "event_type": "unknown",
                        "quantity": Decimal("0"),
                        "quote_asset": None,
                        "quote_quantity": None,
                        "confidence": Decimal("0.70"),
                    }
                )

        return [
            (rewritten.get(index, event), row)
            for index, (event, row) in enumerate(event_rows)
        ]

    def _solana_rpc_collapse_dust_outgoing(
        self,
        outgoing_by_asset: dict[str, Decimal],
    ) -> dict[str, Decimal]:
        non_dust = {
            asset: quantity
            for asset, quantity in outgoing_by_asset.items()
            if not (
                asset.upper() == "SOL"
                and quantity <= Decimal("0.01")
                and len(outgoing_by_asset) > 1
            )
        }
        return non_dust or outgoing_by_asset

    def _reconcile_solana_rpc_native_wallet_effects(
        self,
        source: str,
        event_rows: list[tuple[CanonicalEventCreate, dict[str, str | None]]],
    ) -> list[tuple[CanonicalEventCreate, dict[str, str | None]]]:
        if source != "solana_rpc":
            return event_rows

        grouped: dict[
            tuple[str, str],
            list[tuple[int, CanonicalEventCreate, dict[str, str | None]]],
        ] = {}
        for index, (event, row) in enumerate(event_rows):
            if event.tx_id and event.account:
                grouped.setdefault((event.tx_id, event.account), []).append((index, event, row))

        rewritten: dict[int, CanonicalEventCreate] = {}
        additions: list[tuple[CanonicalEventCreate, dict[str, str | None]]] = []
        for (_tx_id, wallet), items in grouped.items():
            if _tx_id in self._solana_unowned_txids:
                for index, event, _row in items:
                    rewritten[index] = event.model_copy(
                        update={
                            "event_type": "unknown",
                            "quantity": Decimal("0"),
                            "quote_asset": None,
                            "quote_quantity": None,
                            "fee_asset": None,
                            "fee_quantity": None,
                            "account": "solana_rpc_unowned_evidence",
                            "confidence": Decimal("0.98"),
                        }
                    )
                continue
            if all(self._is_direct_solana_history(row) for _index, _event, row in items):
                # This mapper already separates the actual payer fee. Reapplying
                # native reconciliation would count it a second time.
                continue
            state = next(
                (
                    parsed
                    for _index, _event, row in items
                    if (parsed := self._solana_rpc_raw_wallet_state(row, wallet)) is not None
                ),
                None,
            )
            if state is None:
                continue
            if not bool(state["wallet_owned_transaction"]):
                continue

            group_events: list[tuple[int, CanonicalEventCreate, dict[str, str | None]]] = []
            for index, event, row in items:
                if event.fee_asset == "SOL":
                    event = event.model_copy(update={"fee_asset": None, "fee_quantity": None})
                group_events.append((index, event, row))

            wallet_fee = abs(Decimal(str(state["wallet_fee_sol"])))
            if wallet_fee:
                fee_index = next(
                    (
                        index
                        for index, event, _row in group_events
                        if event.fee_asset is None and event.event_type != "unknown"
                    ),
                    group_events[0][0],
                )
                group_events = [
                    (
                        index,
                        event.model_copy(
                            update={"fee_asset": "SOL", "fee_quantity": wallet_fee}
                        )
                        if index == fee_index
                        else event,
                        row,
                    )
                    for index, event, row in group_events
                ]

            normalized_effect = sum(
                (self._canonical_event_asset_effect(event, "SOL") for _index, event, _row in group_events),
                Decimal("0"),
            )
            exact_effect = Decimal(str(state["wallet_native_sol_delta"]))
            residual = exact_effect - normalized_effect
            for index, event, _row in group_events:
                rewritten[index] = event
            if residual:
                _index, primary, row = group_events[0]
                additions.append(
                    (
                        primary.model_copy(
                            update={
                                "source_ref": primary.tx_id,
                                "event_type": "transfer",
                                "asset": "SOL",
                                "quantity": residual,
                                "quote_asset": None,
                                "quote_quantity": None,
                                "fee_asset": None,
                                "fee_quantity": None,
                                "confidence": Decimal("0.98"),
                            }
                        ),
                        row,
                    )
                )

        return [
            (rewritten.get(index, event), row)
            for index, (event, row) in enumerate(event_rows)
        ] + additions

    @staticmethod
    def _is_direct_solana_history(row: dict[str, object]) -> bool:
        return str(row.get("history_mapper_version") or row.get("history mapper version") or "") == "2"

    def _solana_rpc_raw_wallet_state(
        self,
        row: dict[str, object],
        wallet: str,
    ) -> dict[str, object] | None:
        raw_value = row.get("raw_row") or row.get("raw row")
        transaction = self._structured_solana_rpc_row(raw_value)
        if transaction is None:
            return None
        tx = transaction.get("transaction") if isinstance(transaction.get("transaction"), dict) else {}
        message = tx.get("message") if isinstance(tx.get("message"), dict) else {}
        account_values = message.get("accountKeys") if isinstance(message.get("accountKeys"), list) else []
        account_keys = [
            str(value.get("pubkey") or "") if isinstance(value, dict) else str(value)
            for value in account_values
        ]
        meta = transaction.get("meta") if isinstance(transaction.get("meta"), dict) else {}
        token_owners = {
            str(value.get("owner") or "")
            for value in [
                *(meta.get("preTokenBalances") or []),
                *(meta.get("postTokenBalances") or []),
            ]
            if isinstance(value, dict)
        }
        wallet_owned_transaction = wallet in account_keys or wallet in token_owners
        native_delta = Decimal("0")
        if wallet in account_keys:
            index = account_keys.index(wallet)
            pre = meta.get("preBalances") if isinstance(meta.get("preBalances"), list) else []
            post = meta.get("postBalances") if isinstance(meta.get("postBalances"), list) else []
            if index < len(pre) and index < len(post):
                native_delta = (
                    Decimal(int(post[index])) - Decimal(int(pre[index]))
                ) / Decimal("1000000000")
        wallet_paid_fee = bool(account_keys) and account_keys[0] == wallet
        fee = (
            Decimal(int(meta.get("fee") or 0)) / Decimal("1000000000")
            if wallet_paid_fee
            else Decimal("0")
        )
        return {
            "wallet_owned_transaction": wallet_owned_transaction,
            "wallet_native_sol_delta": native_delta,
            "wallet_fee_sol": fee,
        }

    @staticmethod
    def _structured_solana_rpc_row(value: object) -> dict[str, object] | None:
        if isinstance(value, dict):
            return value
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            try:
                parsed = ast.literal_eval(value)
            except (SyntaxError, ValueError):
                return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _canonical_event_asset_effect(event: CanonicalEventCreate, asset: str) -> Decimal:
        target = asset.upper()
        effect = event.quantity if event.asset == target else Decimal("0")
        if event.quote_asset == target and event.quote_quantity is not None:
            quote = abs(event.quote_quantity)
            effect += -quote if event.quantity > 0 else quote
        if event.fee_asset == target and event.fee_quantity is not None:
            effect -= abs(event.fee_quantity)
        return effect

    @staticmethod
    def _load_solana_unowned_txids(path: Path) -> set[str]:
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return set()
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError("solana_ownership_scope_config_unreadable") from exc
        try:
            payload = json.loads(content)
        except ValueError as exc:
            raise ValueError("solana_ownership_scope_config_invalid") from exc
        try:
            config = SolanaV1OwnershipScopeConfig.model_validate(payload)
        except (ValueError, TypeError) as exc:
            raise ValueError("solana_ownership_scope_config_invalid") from exc
        return set(config.outside_owned_wallet_scope_txids)

    def _is_solana_helium_reward_transfer(
        self,
        row: dict[str, object],
        asset: str | None,
    ) -> bool:
        if asset is None or self._canonical_asset(asset) not in {"HNT", "IOT", "MOBILE"}:
            return False
        if self._contains_solana_helium_reward_instruction(row):
            return True
        defi_label = str(row.get("defi label") or row.get("defi_label") or "").strip().lower()
        return defi_label == "staking"

    def _contains_solana_helium_reward_instruction(self, value: object) -> bool:
        reward_instructions = {
            "setcurrentrewardswrapperv1",
            "setcurrentrewardsv0",
            "distributecompressionrewardsv0",
        }
        if isinstance(value, dict):
            return any(self._contains_solana_helium_reward_instruction(item) for item in value.values())
        if isinstance(value, (list, tuple, set)):
            return any(self._contains_solana_helium_reward_instruction(item) for item in value)
        if value is None:
            return False
        normalized = re.sub(r"[^a-z0-9]", "", str(value).lower())
        return any(instruction in normalized for instruction in reward_instructions)

    def _contains_solana_claim_or_airdrop_instruction(self, value: object) -> bool:
        claim_instructions = {
            "newclaim",
            "creatednewclaim",
            "claimstatus",
            "airdrop",
        }
        if isinstance(value, dict):
            return any(self._contains_solana_claim_or_airdrop_instruction(item) for item in value.values())
        if isinstance(value, (list, tuple, set)):
            return any(self._contains_solana_claim_or_airdrop_instruction(item) for item in value)
        if value is None:
            return False
        normalized = re.sub(r"[^a-z0-9]", "", str(value).lower())
        return any(instruction in normalized for instruction in claim_instructions)

    def _is_configured_asset(self, asset: str) -> bool:
        normalized = asset.strip().upper()
        return normalized in self._asset_aliases or self._is_cash_or_stable(normalized)

    def _sum_by_asset(self, events: object) -> dict[str, Decimal]:
        result: dict[str, Decimal] = {}
        for event in events:
            result[event.asset] = result.get(event.asset, Decimal("0")) + event.quantity
        return result

    def _is_failed_binance_status(self, row: dict[str, str | None]) -> bool:
        status = str(row.get("status") or "").strip().lower()
        return status in {
            "failed",
            "canceled",
            "cancelled",
            "expired",
            "rejected",
        }

    def _event_type(self, row: dict[str, str | None], profile: SourceProfile) -> str:
        raw_type = str(self._first_value(row, list(profile.type_columns)) or "")
        lowered = raw_type.strip().lower()
        if lowered == "derivative":
            return "derivative"
        if profile.source == "bitget":
            return self._bitget_event_type(row, lowered)
        if profile.source == "binance":
            return self._binance_event_type(row, lowered)
        if profile.source == "coinbase":
            if any(token in lowered for token in ("send", "receive", "deposit", "withdraw")):
                return "transfer"
            if "staking" in lowered:
                return "staking"
            if any(token in lowered for token in ("reward", "coinbase earn", "learning reward")):
                return "reward"
            if any(token in lowered for token in ("buy", "sell", "trade", "convert")):
                return "trade"
            if any(token in lowered for token in ("income", "distribution")):
                return "income"
            return "unknown"
        if profile.source in {"blockpit", "blockpit-solana"}:
            return self._blockpit_event_type(lowered)
        if profile.source == "solana_rpc":
            return self._solana_rpc_event_type(lowered)
        if (
            profile.source == "helium"
            and self._has_decimal_value(row.get(self._normalize_key("hnt_fee")))
            and not self._has_decimal_value(row.get(self._normalize_key("hnt_amount")))
            and any(token in lowered for token in ("assert_location", "add_gateway", "fee"))
        ):
            return "fee"
        if profile.source == "helium" and self._is_helium_payment_transfer(row, lowered):
            return "transfer"
        if profile.source == "helium" and any(
            self._has_decimal_value(row.get(self._normalize_key(key)))
            for key in (
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
            )
        ):
            return "mining"
        if profile.source == "helium" and row.get("sender") and row.get("receiver") and row.get("amount"):
            return "transfer"
        if profile.source == "pionex" and row.get("direction"):
            return "transfer"
        if profile.source == "pionex" and (
            row.get("received quantity")
            or row.get("sent quantity")
            or row.get("buy amount")
            or row.get("sell amount")
        ):
            has_received = bool(row.get("received quantity") or row.get("buy amount"))
            has_sent = bool(row.get("sent quantity") or row.get("sell amount"))
            return "trade" if has_received and has_sent else "transfer"
        if any(token in lowered for token in ("deposit", "withdrawal", "withdraw", "transfer")):
            return "transfer"
        if "mining" in lowered:
            return "mining"
        if "staking" in lowered:
            return "staking"
        if "reward" in lowered:
            return "mining" if profile.source == "helium" else "reward"
        if any(token in lowered for token in ("buy", "sell", "trade", "convert")):
            return "trade"
        if "successful" in lowered or "completed" in lowered:
            return "transfer"
        if "fee" in lowered:
            return "fee"
        if any(token in lowered for token in ("income", "earn", "distribution")):
            return "income"
        return "unknown"

    def _binance_event_type(self, row: dict[str, str | None], lowered: str) -> str:
        asset = self._canonical_asset(str(row.get("coin") or ""))
        if lowered == "airdrop assets":
            return "transfer" if asset == "BTTC" else "reward"
        if lowered == "crypto box":
            return "reward"
        if lowered == "auto-invest transaction":
            return "transfer"
        if lowered == "index-auto-investment - redeem positions":
            return "transfer"
        if lowered in {
            "simple earn flexible subscription",
            "simple earn flexible redemption",
        }:
            return "transfer"
        if lowered == "sol staking - purchase":
            return "trade"
        if lowered in {"staking purchase", "staking redemption"}:
            return "transfer"
        if lowered == "asset recovery":
            return "transfer"
        if lowered == "token swap - redenomination/rebranding":
            return "transfer"
        if any(token in lowered for token in ("deposit", "withdrawal", "withdraw", "transfer")):
            return "transfer"
        if "mining" in lowered:
            return "mining"
        if "staking" in lowered:
            return "staking"
        if "reward" in lowered:
            return "reward"
        if any(token in lowered for token in ("buy", "sell", "trade", "convert")):
            return "trade"
        if "successful" in lowered or "completed" in lowered:
            return "transfer"
        if "fee" in lowered:
            return "fee"
        if any(token in lowered for token in ("income", "earn", "distribution")):
            return "income"
        return "unknown"

    def _binance_simple_earn_event(
        self,
        source: str,
        raw_object_id: str,
        row: dict[str, str | None],
    ) -> CanonicalEventCreate | None:
        record_type = str(row.get("record type") or row.get("record_type") or "").strip().lower()
        asset = self._canonical_asset(str(row.get("asset") or ""))
        quantity_raw = row.get("amount") or row.get("rewards") or row.get("principal")
        time_raw = row.get("time iso") or row.get("time_iso") or row.get("time")
        if not record_type or not asset or not quantity_raw or not time_raw:
            return None
        quantity = self._decimal_or_none(quantity_raw)
        if quantity is None:
            return None
        event_type = "reward" if "reward" in record_type else "transfer"
        record_subtype = str(row.get("type") or "").strip().upper()
        if record_type == "locked_redemption_loss":
            event_type = "fee"
            signed_quantity = -abs(quantity)
            account = self._binance_simple_earn_account(row)
        elif (
            record_type == "locked_subscription"
            and record_subtype == "AUTO"
        ):
            signed_quantity = Decimal("0")
            account = self._binance_simple_earn_account(row)
        elif "redemption" in record_type:
            signed_quantity = -quantity
            account = self._binance_simple_earn_account(row)
        elif "subscription" in record_type:
            signed_quantity = quantity
            account = self._binance_simple_earn_account(row)
        else:
            signed_quantity = quantity
            account = (
                "Spot"
                if record_type == "locked_rewards"
                else self._binance_simple_earn_account(row)
            )
        return CanonicalEventCreate(
            source=source,
            source_ref=(
                row.get("source ref")
                or row.get("source_ref")
                or row.get("purchase id")
                or row.get("purchase_id")
                or row.get("redeem id")
                or row.get("redeem_id")
                or row.get("position id")
                or row.get("position_id")
            ),
            event_time=self._parse_event_datetime_for_row(str(time_raw), profile_for_source(source), row),
            event_type=event_type,
            asset=asset,
            quantity=signed_quantity,
            tx_id=(
                row.get("purchase id")
                or row.get("purchase_id")
                or row.get("redeem id")
                or row.get("redeem_id")
                or row.get("position id")
                or row.get("position_id")
            ),
            account=account,
            confidence=Decimal("0.95"),
            raw_object_id=raw_object_id,
        )

    def _binance_asset_dividend_event(
        self,
        source: str,
        raw_object_id: str,
        row: dict[str, str | None],
    ) -> CanonicalEventCreate | None:
        asset = self._canonical_asset(str(row.get("asset") or ""))
        quantity = self._decimal_or_none(row.get("amount"))
        time_raw = row.get("time iso") or row.get("time_iso") or row.get("div time") or row.get("div_time")
        if not asset or quantity is None or not time_raw:
            return None
        direction = self._decimal_or_none(row.get("direction")) or Decimal("1")
        signed_quantity = abs(quantity) if direction >= 0 else -abs(quantity)
        en_info = str(row.get("en info") or row.get("en_info") or "").lower()
        if signed_quantity < 0:
            event_type = "fee"
        elif any(token in en_info for token in ("locked", "simple earn", "staking", "reward")):
            event_type = "reward"
        else:
            event_type = "income"
        return CanonicalEventCreate(
            source=source,
            source_ref=(
                row.get("source ref")
                or row.get("source_ref")
                or row.get("dividend id")
                or row.get("dividend_id")
                or row.get("tran id")
                or row.get("tran_id")
            ),
            event_time=self._parse_event_datetime_for_row(
                str(time_raw), profile_for_source(source), row
            ),
            event_type=event_type,
            asset=asset,
            quantity=signed_quantity,
            tx_id=(
                row.get("tran id")
                or row.get("tran_id")
                or row.get("dividend id")
                or row.get("dividend_id")
            ),
            account="Spot",
            confidence=Decimal("0.99"),
            raw_object_id=raw_object_id,
        )

    def _binance_simple_earn_account(self, row: dict[str, str | None]) -> str:
        account_type = str(row.get("account type") or row.get("account_type") or "").strip()
        product_id = str(row.get("product id") or row.get("product_id") or "").strip()
        if account_type == "simple_earn_flexible":
            return f"Binance Earn Flexible {product_id}".strip()
        if account_type == "simple_earn_locked":
            return f"Binance Earn Locked {product_id}".strip()
        return f"Binance Earn {product_id}".strip()

    def _is_helium_payment_transfer(self, row: dict[str, str | None], lowered_type: str) -> bool:
        has_parties = bool(
            (row.get("payer") and row.get("payee"))
            or (row.get("sender") and row.get("receiver"))
        )
        has_amount = any(
            self._has_decimal_value(row.get(self._normalize_key(key)))
            for key in ("amount", "hnt_amount", "hnt")
        )
        return has_parties and has_amount and (
            "payment" in lowered_type
            or lowered_type == "transfer"
            or lowered_type.startswith("payment_")
        )

    def _event_account(
        self,
        row: dict[str, str | None],
        profile: SourceProfile,
        event_type: str,
        *,
        bound_account: str | None = None,
    ) -> str:
        if profile.source == "helium" and event_type == "transfer":
            transfer_account = self._helium_transfer_account(row)
            if transfer_account is not None:
                return transfer_account
        configured_account = self._first_value(row, list(profile.account_columns))
        if (
            profile.source == "helium"
            and event_type in {"mining", "fee"}
            and configured_account is None
        ):
            return self.HELIUM_MAIN_LEGACY_WALLET
        return bound_account or configured_account or profile.default_account

    def _helium_transfer_account(self, row: dict[str, str | None]) -> str | None:
        payer = row.get("payer") or row.get("sender")
        payee = row.get("payee") or row.get("receiver")
        if payer == self.HELIUM_MAIN_LEGACY_WALLET:
            return self.HELIUM_MAIN_LEGACY_WALLET
        if payee == self.HELIUM_MAIN_LEGACY_WALLET:
            return self.HELIUM_MAIN_LEGACY_WALLET
        return None

    def _helium_transfer_sign_context(
        self,
        row: dict[str, str | None],
        account: str,
        raw_type: str,
    ) -> str:
        payer = row.get("payer") or row.get("sender")
        if payer == account:
            return f"{raw_type} out"
        return raw_type

    def _blockpit_event_type(self, lowered: str) -> str:
        if lowered in {"derivative fee", "derivative loss", "derivative profit"}:
            return "derivative"
        if lowered in {"trade", "swap"}:
            return "trade"
        if lowered in {"interest", "reward", "airdrop"}:
            return "reward"
        if lowered == "mining":
            return "mining"
        if lowered == "fee":
            return "fee"
        if lowered in {
            "deposit",
            "withdrawal",
            "auto-balancing in",
            "auto-balancing out",
            "non-taxable in",
            "non-taxable out",
        }:
            return "transfer"
        return "unknown"

    def _bitget_event_type(self, row: dict[str, str | None], lowered: str) -> str:
        action = str(row.get("action") or row.get("action (english)") or "").strip().lower()
        combined = " ".join(part for part in (lowered, action) if part)
        if any(
            token in combined
            for token in ("deposit", "withdrawal", "withdraw", "recharge", "fund transfer")
        ):
            return "transfer"
        if "order_dealt" in combined or "spot trade" in combined or any(
            token in combined for token in ("buy", "sell")
        ):
            return "trade"
        if any(token in combined for token in ("open_long", "close_long", "open_short", "close_short", "contract_margin_settle_fee")):
            return "derivative"
        if lowered in BITGET_NEUTRAL_ACTIONS and bitget_financial_row(row):
            return "derivative"
        if any(token in combined for token in ("trans_from", "trans_to", "strategy")):
            return "transfer"
        if "fee" in combined:
            return "fee"
        return "unknown"

    def _is_bitget_spot_financial_quote_shadow(self, row: dict[str, str | None]) -> bool:
        if not {"amount (usdt)", "balance before action (usdt)", "balance after action (usdt)"} <= set(row):
            return False
        coin = str(row.get("coin") or "").strip().upper()
        action = str(row.get("action") or "").strip().lower()
        return coin == "USDT" and action.startswith("order_dealt")

    def _solana_rpc_event_type(self, lowered: str) -> str:
        if lowered in {"swap_in_aggregated", "swap_out_aggregated"}:
            return "trade"
        if lowered in {"token_transfer", "sol_transfer", "transfer"}:
            return "transfer"
        if "reward" in lowered or "claim" in lowered:
            return "reward"
        if "fee" in lowered:
            return "fee"
        return "unknown"

    def _signed_quantity(
        self,
        quantity: Decimal,
        event_type: str,
        raw_type: str,
    ) -> Decimal:
        if event_type == "trade" and quantity > 0 and "sell" in raw_type.lower():
            return -quantity
        if event_type == "trade" and quantity > 0 and "swap_out" in raw_type.lower():
            return -quantity
        raw_tokens = set(raw_type.lower().replace("_", " ").split())
        if (
            event_type == "transfer"
            and quantity > 0
            and (
                raw_type.lower() in {"out", "withdraw", "withdrawal"}
                or raw_tokens & {"out", "withdraw", "withdrawal"}
            )
        ):
            return -quantity
        if quantity > 0 and raw_type.lower() == "out":
            return -quantity
        return quantity

    def _parse_event_datetime(
        self,
        value: str,
        profile: SourceProfile,
        *,
        default_timezone: tzinfo | None = None,
    ) -> datetime:
        if default_timezone is not None:
            return self._parse_datetime(value, default_timezone=default_timezone)
        if profile.source != "bitget":
            return self._parse_datetime(value)
        return self._parse_datetime(value, default_timezone=timezone(timedelta(hours=8)))

    def _parse_event_datetime_for_row(
        self,
        value: str,
        profile: SourceProfile,
        row: dict[str, str | None],
        *,
        default_timezone: tzinfo | None = None,
    ) -> datetime:
        row_timezone = self._timezone_from_column_names(row) or default_timezone
        parsed = self._parse_event_datetime(
            value,
            profile,
            default_timezone=row_timezone,
        )
        if profile.source == "helium" and row.get("period start (utc)"):
            last_day = calendar.monthrange(parsed.year, parsed.month)[1]
            return parsed.replace(day=last_day, hour=23, minute=59, second=59, microsecond=0)
        return parsed

    @classmethod
    def _timezone_from_column_names(cls, row: dict[str, str | None]) -> timezone | None:
        for key in row:
            parsed = cls._timezone_from_text(str(key))
            if parsed is not None:
                return parsed
        return None

    @staticmethod
    def _timezone_from_text(value: str) -> timezone | None:
        match = re.search(r"utc\s*([+-])\s*(\d{1,2})(?::(\d{2}))?", value, flags=re.IGNORECASE)
        if match is None:
            return None
        hours = int(match.group(2))
        minutes = int(match.group(3) or "0")
        if hours > 14 or minutes > 59:
            return None
        offset = timedelta(hours=hours, minutes=minutes)
        if match.group(1) == "-":
            offset = -offset
        return timezone(offset)

    def _base_asset_from_pair(self, pair: str | None) -> str | None:
        parts = self._pair_parts(pair)
        if parts is None:
            return None
        return parts[0]

    def _quote_asset_from_pair(self, pair: str | None) -> str | None:
        parts = self._pair_parts(pair)
        if parts is None:
            return None
        return parts[1]

    def _pair_parts(self, pair: str | None) -> tuple[str, str] | None:
        if pair is None:
            return None
        normalized = pair.strip().upper().replace("-", "_").replace("/", "_")
        parts = [part for part in normalized.split("_") if part]
        if len(parts) != 2:
            for quote in (
                "USDT",
                "USDC",
                "BUSD",
                "EUR",
                "BTC",
                "ETH",
                "BNB",
                "TRY",
                "GBP",
            ):
                if normalized.endswith(quote) and len(normalized) > len(quote):
                    return normalized[: -len(quote)], quote
            return None
        return parts[0], parts[1]

    def _parse_datetime(self, value: str, default_timezone: tzinfo = timezone.utc) -> datetime:
        normalized = value.strip().replace("\xa0", " ").replace("Z", "+00:00")
        normalized = normalized.replace(" at ", " ")
        for suffix in (" UTC", " GMT"):
            if normalized.endswith(suffix):
                normalized = normalized.removesuffix(suffix) + "+00:00"
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            for pattern in (
                "%Y-%m-%d %H:%M:%S",
                "%Y/%m/%d %H:%M:%S",
                "%d.%m.%Y %H:%M:%S",
                "%d.%m.%Y %H:%M",
                "%m/%d/%Y %H:%M:%S",
                "%y-%m-%d %H:%M:%S",
                "%Y-%m-%d %I:%M%p",
                "%Y-%m-%d",
                "%d.%m.%y",
            ):
                try:
                    parsed = datetime.strptime(normalized, pattern)
                    break
                except ValueError:
                    continue
            else:
                raise
        if parsed.tzinfo is None:
            if isinstance(default_timezone, ZoneInfo):
                first = parsed.replace(tzinfo=default_timezone, fold=0)
                second = parsed.replace(tzinfo=default_timezone, fold=1)
                first_valid = first.astimezone(timezone.utc).astimezone(default_timezone).replace(tzinfo=None) == parsed
                second_valid = second.astimezone(timezone.utc).astimezone(default_timezone).replace(tzinfo=None) == parsed
                if not first_valid and not second_valid:
                    raise ValueError("bitget_local_time_does_not_exist_in_selected_timezone")
                if first_valid and second_valid and first.utcoffset() != second.utcoffset():
                    raise ValueError("bitget_local_time_is_ambiguous_in_selected_timezone")
            return parsed.replace(tzinfo=default_timezone).astimezone(timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _first_value(
        self,
        row: dict[str, str | None],
        keys: list[str],
    ) -> str | None:
        for key in keys:
            value = row.get(self._normalize_key(key))
            if value not in (None, ""):
                return str(value)
        return None

    def _decimal_or_none(self, value: str | None) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(self._normalize_decimal_text(value))
        except InvalidOperation:
            return None

    def _pionex_row_has_execution(self, row: dict[str, str | None]) -> bool:
        return any(
            (quantity := self._decimal_or_none(row.get(key))) is not None and quantity != 0
            for key in (
                "executed qty",
                "executed quantity",
                "executed amount",
                "filled amount",
                "filled quantity",
                "filled size",
            )
        )

    def _normalize_decimal_text(self, value: str) -> str:
        normalized = value.strip().replace(",", ".")
        # Some legacy Fairspot/Helium CSV exports encode scientific notation as
        # "8,7e.7" instead of "8.7e-7". Without this correction the parser
        # falls through to mobile_amount, which is an oracle/helper column in
        # those old rows.
        return re.sub(r"([eE])\.(\d+)$", r"\1-\2", normalized)

    @staticmethod
    def _coinbase_numeric_text(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = re.sub(r"[^0-9,.-]", "", str(value)).strip()
        if not normalized:
            return None
        if "," in normalized and "." in normalized:
            if normalized.rfind(".") > normalized.rfind(","):
                return normalized.replace(",", "")
            return normalized.replace(".", "").replace(",", ".")
        if "," in normalized:
            return normalized.replace(",", ".")
        return normalized

    def _has_decimal_value(self, value: str | None) -> bool:
        decimal_value = self._decimal_or_none(value)
        return decimal_value is not None and decimal_value != 0

    def _derived_quantity_asset(
        self,
        row: dict[str, str | None],
        profile: SourceProfile,
    ) -> tuple[str | None, str | None]:
        if profile.source == "pionex":
            if row.get("amount usdt"):
                return row.get("amount usdt"), "USDT"
            if row.get("received quantity") and row.get("received currency"):
                return row.get("received quantity"), row.get("received currency")
            if row.get("buy amount") and row.get("buy currency"):
                return row.get("buy amount"), row.get("buy currency")
            return None, None
        if profile.source in {"blockpit", "blockpit-solana"}:
            label = str(row.get("label") or "").strip().lower()
            incoming_amount = row.get("incoming amount")
            incoming_asset = row.get("incoming asset")
            outgoing_amount = row.get("outgoing amount")
            outgoing_asset = row.get("outgoing asset")
            fee_amount = row.get("fee amount (optional)")
            fee_asset = row.get("fee asset (optional)")
            if label in {"derivative profit"} and self._has_decimal_value(incoming_amount):
                return incoming_amount, incoming_asset
            if label in {"derivative loss", "derivative fee"} and self._has_decimal_value(outgoing_amount):
                return f"-{outgoing_amount}", outgoing_asset
            if label in {"derivative fee"} and self._has_decimal_value(fee_amount):
                return f"-{fee_amount}", fee_asset
            if self._has_decimal_value(incoming_amount):
                return incoming_amount, incoming_asset
            if self._has_decimal_value(outgoing_amount):
                return f"-{outgoing_amount}", outgoing_asset
            if self._has_decimal_value(fee_amount):
                return f"-{fee_amount}", fee_asset
            return None, None
        if profile.source != "helium":
            return None, None
        hnt_amount = row.get(self._normalize_key("hnt_amount"))
        hnt_fee = row.get(self._normalize_key("hnt_fee"))
        raw_type = str(row.get(self._normalize_key("type")) or "").strip().lower()
        if (
            self._has_decimal_value(hnt_fee)
            and not self._has_decimal_value(hnt_amount)
            and any(token in raw_type for token in ("assert_location", "add_gateway", "fee"))
        ):
            return f"-{hnt_fee}", "HNT"
        # Wallet-month exports reuse the IOT/MOBILE quantity columns after
        # the Helium migration. The adjacent token column is authoritative;
        # e.g. `IOT Tokens=0.05` with `IOT Token=HNT` is an HNT reward.
        for quantity_key, token_key, default_asset in (
            ("iot tokens", "iot token", "IOT"),
            ("mobile tokens", "mobile token", "MOBILE"),
        ):
            value = row.get(self._normalize_key(quantity_key))
            if self._has_decimal_value(value):
                token = row.get(self._normalize_key(token_key))
                return value, (token.strip().upper() if token and token.strip() else default_asset)
        for key, asset in (
            ("hnt_amount", "HNT"),
            ("iot_amount", "IOT"),
            ("mobile_amount", "MOBILE"),
            ("iot tokens", "IOT"),
            ("mobile tokens", "MOBILE"),
            ("mining rewards hnt", "HNT"),
            ("mining rewards iot", "IOT"),
            ("mining rewards mobile", "MOBILE"),
            ("commissions hnt", "HNT"),
            ("commissions iot", "IOT"),
            ("commissions mobile", "MOBILE"),
            ("mining rewards", "HNT"),
        ):
            value = row.get(self._normalize_key(key))
            if self._has_decimal_value(value):
                return value, asset
        if (row.get("sender") and row.get("receiver")) or (row.get("payer") and row.get("payee")):
            value = row.get("amount")
            if self._has_decimal_value(value):
                return value, "HNT"
        return None, None

    def _derived_trade_leg(
        self,
        row: dict[str, str | None],
        profile: SourceProfile,
    ) -> tuple[str, str, bool, str | None, str | None] | None:
        if profile.source == "bitget":
            pair = row.get("trading pair")
            pair_parts = self._pair_parts(pair)
            action = (row.get("action") or row.get("action (english)") or "").strip().lower()
            quantity = row.get("quantity") or row.get("executed")
            quote_quantity = row.get("transacted amount") or row.get("amount (usdt)") or row.get(
                "executed amount (usdt)"
            )
            if pair_parts is not None and quantity and quote_quantity and action in {"buy", "sell"}:
                base_asset, quote_asset = pair_parts
                return base_asset, quantity, action == "sell", quote_asset, quote_quantity
            return None
        if profile.source in {"blockpit", "blockpit-solana"}:
            if (row.get("label") or "").strip().lower() != "trade":
                return None
            incoming_quantity = row.get("incoming amount")
            incoming_asset = row.get("incoming asset")
            outgoing_quantity = row.get("outgoing amount")
            outgoing_asset = row.get("outgoing asset")
            if not incoming_quantity or not incoming_asset or not outgoing_quantity or not outgoing_asset:
                return None
            if self._is_cash_or_stable(incoming_asset) and not self._is_cash_or_stable(outgoing_asset):
                return outgoing_asset, outgoing_quantity, True, incoming_asset, incoming_quantity
            return incoming_asset, incoming_quantity, False, outgoing_asset, outgoing_quantity
        if profile.source != "pionex":
            return None
        if row.get("swap value") and row.get("amount") and row.get("coin"):
            return row["coin"], row["amount"], True, "USDT", row["swap value"]
        pair = row.get("symbol")
        executed_quantity = row.get("executed qty")
        amount = row.get("amount")
        side = (row.get("side") or "").strip().lower()
        pair_parts = self._pair_parts(pair)
        if pair_parts is not None and executed_quantity and amount and side in {"buy", "sell"}:
            base_asset, quote_asset = pair_parts
            return base_asset, executed_quantity, side == "sell", quote_asset, amount
        received_quantity = row.get("received quantity") or row.get("buy amount")
        received_asset = row.get("received currency") or row.get("buy currency")
        sent_quantity = row.get("sent quantity") or row.get("sell amount")
        sent_asset = row.get("sent currency") or row.get("sell currency")
        if not received_quantity or not received_asset or not sent_quantity or not sent_asset:
            return None
        if self._is_cash_or_stable(received_asset) and not self._is_cash_or_stable(sent_asset):
            return sent_asset, sent_quantity, True, received_asset, received_quantity
        return received_asset, received_quantity, False, sent_asset, sent_quantity

    def _is_cash_or_stable(self, asset: str | None) -> bool:
        if asset is None:
            return False
        return asset.strip().upper() in {"EUR", "USD", "USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD"}

    def _correct_scaled_quantity(
        self,
        row: dict[str, str | None],
        profile: SourceProfile,
        quantity_raw: str | None,
    ) -> str | None:
        if profile.source != "binance" or quantity_raw is None:
            return quantity_raw
        quantity = self._decimal_or_none(quantity_raw)
        remark = self._decimal_or_none(row.get("remark"))
        if quantity is None or remark is None:
            return quantity_raw
        if abs(quantity) >= Decimal("1000000") and remark != 0:
            return str(remark)
        return quantity_raw

    def _split_amount_asset(self, value: str | None) -> tuple[str | None, str | None]:
        if value is None:
            return None, None
        parts = value.strip().split()
        if len(parts) == 2:
            try:
                Decimal(parts[0].replace(",", "."))
            except InvalidOperation:
                return value, None
            return parts[0], parts[1].upper()
        return value, None

    def _upper_or_none(self, value: str | None) -> str | None:
        if value is None:
            return None
        return value.upper()

    def _canonical_asset(self, value: str) -> str:
        upper = str(value).strip().upper()
        if upper == "HNT2":
            return "HNT"
        alias = self._asset_aliases.get(upper)
        if alias is not None:
            return alias
        return upper

    def _load_asset_aliases(self, config_path: Path) -> dict[str, str]:
        if not config_path.exists():
            return {}
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        result: dict[str, str] = {}
        for item in payload.get("assets", []):
            symbol = str(item.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            for value in [symbol, *item.get("aliases", []), *item.get("store_keys", [])]:
                alias = str(value or "").strip().upper()
                if alias:
                    result[alias] = symbol
        return result

    def _normalize_key(self, key: str) -> str:
        return normalize_column_name(key)
