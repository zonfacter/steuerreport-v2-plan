from __future__ import annotations

import json
import calendar
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from steuerreport_v2.contracts.events import CanonicalEvent, CanonicalEventCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup
from steuerreport_v2.importers.source_profiles import (
    SourceProfile,
    normalize_column_name,
    profile_for_source,
)

DEFAULT_PRICE_CONFIG = Path("/workspace/steuerreport-v2-plan/configs/crypto_price_sources.json")


@dataclass(frozen=True)
class NormalizationReport:
    batch_id: str
    raw_objects: int
    created_events: int
    skipped_raw_objects: int


class RawNormalizer:
    HELIUM_MAIN_LEGACY_WALLET = "1362Z4gXFbBuUp22PtwNhdNc3iR6Tjc7ty5S8CPjSwVH6F7BsHV"
    HELIUM_FAIRSPOT_STAKING_WALLET = "13xfSeV2UcVgUiTKmd9V1Htunc6N7wsAgkGRHtquN9hpCbA78Yp"

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store
        self._asset_aliases = self._load_asset_aliases(DEFAULT_PRICE_CONFIG)

    def normalize_batch(self, batch_id: str) -> list[CanonicalEvent]:
        return self.normalize_batch_with_report(batch_id)[0]

    def normalize_batch_with_report(
        self,
        batch_id: str,
    ) -> tuple[list[CanonicalEvent], NormalizationReport]:
        batch = self.store.get_import_batch(batch_id)
        if batch is None:
            raise ValueError(f"unknown import batch: {batch_id}")

        self.store.delete_canonical_events_for_batch(batch_id)
        events: list[CanonicalEvent] = []
        event_payloads: list[CanonicalEventCreate] = []
        raw_objects = self.store.list_raw_objects(batch_id, limit=None)
        skipped = 0
        event_rows: list[tuple[CanonicalEventCreate, dict[str, str | None]]] = []
        for raw in raw_objects:
            row = json.loads(raw.payload_json)
            event = self._row_to_event(batch.source, raw.raw_object_id, row)
            if event is not None:
                event_rows.append((event, row))
            else:
                skipped += 1
        event_rows = self._merge_binance_small_assets_exchange_bnb(batch.source, event_rows)
        event_rows = self._merge_binance_sol_staking_purchase_quotes(batch.source, event_rows)
        event_rows = self._split_binance_simple_earn_flexible_redemption_yield(batch.source, event_rows)
        event_rows = self._merge_binance_transaction_related_quotes(batch.source, event_rows)
        event_rows = self._merge_binance_same_asset_trade_fees(batch.source, event_rows)
        event_rows = self._merge_binance_transaction_spend_quotes(batch.source, event_rows)
        event_rows = self._merge_binance_same_asset_trade_fees(batch.source, event_rows)
        event_rows = self._merge_solana_rpc_swap_quotes(batch.source, event_rows)
        event_payloads = [event for event, _row in event_rows]
        events = self.store.add_canonical_events(event_payloads)
        return events, NormalizationReport(
            batch_id=batch_id,
            raw_objects=len(raw_objects),
            created_events=len(events),
            skipped_raw_objects=skipped,
        )

    def _row_to_event(
        self,
        source: str,
        raw_object_id: str,
        row: dict[str, str | None],
    ) -> CanonicalEventCreate | None:
        profile = profile_for_source(source)
        normalized = {self._normalize_key(key): value for key, value in row.items()}
        if profile.source == "pionex" and str(normalized.get("state") or "").strip().upper() == "CANCELED":
            return None
        if (
            profile.source == "bitget"
            and str(normalized.get("record type") or normalized.get("record_type") or "").strip().lower()
            == "bitget_withdrawal_evidence"
        ):
            return None
        if profile.source == "binance_simple_earn_api":
            return self._binance_simple_earn_event(source, raw_object_id, normalized)
        if profile.source == "binance_withdrawal_api":
            return self._binance_withdrawal_evidence_event(source, raw_object_id, normalized, profile)
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
        if profile.source in {"blockpit", "blockpit-solana"} and derived_quantity_raw is not None:
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
        account = self._event_account(normalized, profile, event_type)
        if profile.source == "helium" and event_type == "transfer":
            sign_context = self._helium_transfer_sign_context(normalized, account, raw_type)
        quantity = self._signed_quantity(quantity, event_type, sign_context)
        if (
            profile.source == "solana_rpc"
            and event_type == "transfer"
            and raw_type.strip().lower() == "token_transfer"
            and quantity > 0
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
        fee_quantity = self._decimal_or_none(
            self._first_value(normalized, list(profile.fee_quantity_columns))
        )
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
            event_time=self._parse_event_datetime_for_row(str(time_raw), profile, normalized),
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
    ) -> CanonicalEventCreate | None:
        asset = self._first_value(row, list(profile.asset_columns))
        time_raw = self._first_value(row, list(profile.time_columns))
        if asset is None or time_raw is None:
            return None
        return CanonicalEventCreate(
            source=source,
            source_ref=self._first_value(row, list(profile.source_ref_columns)),
            event_time=self._parse_event_datetime_for_row(str(time_raw), profile, row),
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
                    price = price_lookup.at_or_before(event.asset, event.event_time)
                except TypeError:
                    price = price_lookup.at_or_before(
                        event.asset,
                        event.event_time.replace(tzinfo=None),
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
            if event.event_type in {"trade", "transfer", "income"} and event.tx_id:
                grouped.setdefault(event.tx_id, []).append((index, event, row))

        rewritten: dict[int, CanonicalEventCreate] = {}
        for _tx_id, items in grouped.items():
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
        if profile.source == "bitget":
            return self._bitget_event_type(row, lowered)
        if profile.source == "binance":
            return self._binance_event_type(row, lowered)
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
        if (
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
            account = self._binance_simple_earn_account(row)
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
        return configured_account or profile.default_account

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
        if any(token in combined for token in ("open_long", "close_long", "open_short", "close_short")):
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

    def _parse_event_datetime(self, value: str, profile: SourceProfile) -> datetime:
        if profile.source != "bitget":
            return self._parse_datetime(value)
        return self._parse_datetime(value, default_timezone=timezone(timedelta(hours=8)))

    def _parse_event_datetime_for_row(
        self,
        value: str,
        profile: SourceProfile,
        row: dict[str, str | None],
    ) -> datetime:
        parsed = self._parse_event_datetime(value, profile)
        if profile.source == "helium" and row.get("period start (utc)"):
            last_day = calendar.monthrange(parsed.year, parsed.month)[1]
            return parsed.replace(day=last_day, hour=23, minute=59, second=59, microsecond=0)
        return parsed

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

    def _parse_datetime(self, value: str, default_timezone: timezone = timezone.utc) -> datetime:
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

    def _normalize_decimal_text(self, value: str) -> str:
        normalized = value.strip().replace(",", ".")
        # Some legacy Fairspot/Helium CSV exports encode scientific notation as
        # "8,7e.7" instead of "8.7e-7". Without this correction the parser
        # falls through to mobile_amount, which is an oracle/helper column in
        # those old rows.
        return re.sub(r"([eE])\.(\d+)$", r"\1-\2", normalized)

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
