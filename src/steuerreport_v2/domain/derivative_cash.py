"""Quellengebundene Geldbeine, keine steuerliche Freigabe eines Derivats."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import json

from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.importers.source_profiles import normalize_column_name


BITGET_NEUTRAL_ACTIONS = frozenset({"adjust_margin_ifm", "adjust_down_leverage", "adjust_up_leverage"})
BITGET_DERIVATIVE_ACTIONS = frozenset({"open_long", "close_long", "open_short", "close_short", "contract_margin_settle_fee"})


def normalized_row(row: dict) -> dict:
    return {normalize_column_name(str(key)): value for key, value in row.items()}


def bitget_financial_row(row: dict) -> bool:
    return ({"amount", "fee", "coin", "type", "wallet balance"} <= row.keys()
            and bool({"futures", "margin mode"} & row.keys()))


def derivative_raw_rows(store: DuckDbStore) -> dict[str, dict]:
    with store.connect() as con:
        rows = con.execute("""select e.event_id,r.payload_json from canonical_events e
            left join raw_objects r on r.raw_object_id=e.raw_object_id
            where e.event_type='derivative' or lower(e.source)='bitget'""").fetchall()
    result = {}
    for event_id, payload in rows:
        try:
            row = json.loads(payload) if payload else {}
        except (ValueError, TypeError):
            row = {}
        result[event_id] = normalized_row(row) if isinstance(row, dict) else {}
    return result


@dataclass(frozen=True)
class DerivativeCash:
    legs: tuple[tuple[str, Decimal], ...]
    policy: str
    review_reason: str | None = None


def derivative_cash(event: CanonicalEvent, row: dict | None) -> DerivativeCash:
    primary = (event.asset, event.quantity)
    row = row or {}
    if event.source.lower() == "bitget":
        raw_value = None
        for key in ("surplus/deduction (after fee)", "surplus/deduction (before fee)", "amount"):
            if row.get(key) not in (None, ""):
                raw_value = row[key]
                break
        if raw_value is not None and (bitget_financial_row(row) or any(
                row.get(key) not in (None, "") for key in ("surplus/deduction (after fee)", "surplus/deduction (before fee)"))):
            try:
                with localcontext() as context:
                    context.prec = 80
                    expected = Decimal(str(raw_value).strip().replace(",", "."))
                    if not expected.is_finite():
                        raise InvalidOperation
                    if (bitget_financial_row(row)
                            and str(row.get("type") or "").strip().lower() in BITGET_NEUTRAL_ACTIONS):
                        expected = Decimal("0")
                    # Genau die bestehende DECIMAL(38,18)-Speicherpraezision, keine EUR-Rundung.
                    expected = expected.quantize(Decimal("0.000000000000000001"), rounding=ROUND_HALF_UP)
                if expected != event.quantity:
                    return DerivativeCash((primary,), "unresolved", "principal_raw_mismatch")
            except InvalidOperation:
                return DerivativeCash((primary,), "unresolved", "principal_raw_invalid")
    fee = event.fee_quantity
    if fee is None or fee == 0:
        return DerivativeCash((primary,), "no_fee")
    if not event.fee_asset:
        return DerivativeCash((primary,), "unresolved", "fee_asset_missing")
    same_asset = event.fee_asset.upper() == event.asset.upper()
    if event.source.lower() == "bitget":
        if row.get("surplus/deduction (after fee)") not in (None, ""):
            if same_asset:
                return DerivativeCash((primary,), "bitget_after_fee")
            return DerivativeCash((primary,), "unresolved", "after_fee_currency_conflict")
        if bitget_financial_row(row) or row.get("surplus/deduction (before fee)") not in (None, ""):
            return DerivativeCash((primary, (event.fee_asset, fee)), "bitget_signed_separate_fee",
                                  None if same_asset else "foreign_fee_lot_review")
    if (str(row.get("type") or row.get("operation") or "").strip().lower() == "derivative"
            and row.get("fee asset") not in (None, "")
            and any(row.get(key) not in (None, "") for key in ("fee quantity", "fee amount", "fee"))):
        return DerivativeCash((primary, (event.fee_asset, -abs(fee))), "generic_separate_fee",
                              None if same_asset else "foreign_fee_lot_review")
    # Alte unbewiesene Nettokonvention nicht durch einen geratenen Doppelabzug ersetzen.
    return DerivativeCash((primary,), "unresolved", "fee_convention_missing")
