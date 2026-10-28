"""Technische FX-Referenzregel, keine Freigabe einer steuerlichen Kursmethode."""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, DecimalException, localcontext
import json
import sqlite3
from urllib.parse import quote


FX_POLICY_ID = "fx_reference_on_or_before_max_7_calendar_days_v1"
MAX_REFERENCE_AGE_DAYS = 7


@dataclass(frozen=True)
class FxReference:
    rate_eur_per_usd: Decimal
    reference_date: date
    original_base: str
    original_quote: str
    original_rate: Decimal
    source: str = ""

    def source_suffix(self) -> str:
        metadata = {"policy_id": FX_POLICY_ID, "reference_date": self.reference_date.isoformat(),
                    "base": self.original_base, "quote": self.original_quote,
                    "rate": str(self.original_rate), "source": self.source}
        return "fxref:" + quote(json.dumps(metadata, sort_keys=True, separators=(",", ":")), safe="")


def select_fx_reference(payload: object, day: date) -> FxReference | None:
    """Use only supplied observations; never invent a weekend/holiday observation."""
    if not isinstance(payload, list) or not payload:
        return None
    candidates = []
    try:
        for row in payload:
            if not isinstance(row, dict):
                return None
            pair = (row.get("base"), row.get("quote"))
            if pair not in {("USD", "EUR"), ("EUR", "USD")}:
                return None
            observed = date.fromisoformat(row["date"])
            original = Decimal(str(row["rate"]))
            if not original.is_finite() or original <= 0:
                return None
            with localcontext() as arithmetic:
                arithmetic.prec = 60
                normalized = original if pair == ("USD", "EUR") else Decimal("1") / original
            if not normalized.is_finite() or not 0 < normalized < Decimal("1e19"):
                return None
            if 0 <= (day - observed).days <= MAX_REFERENCE_AGE_DAYS:
                candidates.append(FxReference(normalized, observed, pair[0], pair[1], original,
                                              str(row.get("source") or "")))
    except (KeyError, TypeError, ValueError, DecimalException):
        return None
    if not candidates:
        return None
    latest_day = max(item.reference_date for item in candidates)
    latest = [item for item in candidates if item.reference_date == latest_day]
    if len({item.rate_eur_per_usd for item in latest}) != 1:
        return None
    return min(latest, key=lambda item: (item.original_base, item.original_quote, item.source))


def cache_fx_reference(con: sqlite3.Connection, day: date) -> FxReference | None:
    """Read legacy observations without changing the SQLite file or its schema."""
    columns = {row[1] for row in con.execute("pragma table_info(fx_cache)").fetchall()}
    if not {"rate_date", "base_ccy", "quote_ccy", "rate", "source"} <= columns:
        return None
    source_day = "source_rate_date" if "source_rate_date" in columns else "null"
    rows = con.execute(f"""
        select rate_date, base_ccy, quote_ccy, rate, source, {source_day}
        from fx_cache where rate_date between ? and ?
          and ((base_ccy='USD' and quote_ccy='EUR') or (base_ccy='EUR' and quote_ccy='USD'))
        """, ((day - timedelta(days=MAX_REFERENCE_AGE_DAYS)).isoformat(), day.isoformat())).fetchall()
    payload = []
    try:
        for recorded, base, quote, rate, source, source_date in rows:
            if "source_rate_date" in columns and not source_date:
                return None
            observed = source_date or recorded
            if not source or date.fromisoformat(observed) > date.fromisoformat(recorded):
                return None
            payload.append({"date": observed, "base": base, "quote": quote, "rate": rate, "source": source})
    except (TypeError, ValueError):
        return None
    return select_fx_reference(payload, day)
