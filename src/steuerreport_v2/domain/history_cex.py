"""Begrenzte, read-only CEX-Historienseiten; keine Vollstaendigkeitszusage."""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
import hashlib
import hmac
import json
import re
import time
from typing import NoReturn
from urllib.parse import urlencode

import httpx

from steuerreport_v2.domain.cex_balances import CexBalanceService
from steuerreport_v2.domain.history_types import (
    HistoryFetchError, HistoryOptions, HistoryPage, HistoryRecord, HistoryTarget,
)
from steuerreport_v2.importers.source_profiles import profile_for_source


_DAY = 86_400_000
_LIMIT = 100
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_PATHS = {
    "binance": ("/api/v3/myTrades", "/sapi/v1/capital/deposit/hisrec",
                "/sapi/v1/capital/withdraw/history"),
    "bitget": ("/api/v2/spot/trade/fills", "/api/v2/spot/wallet/deposit-records",
               "/api/v2/spot/wallet/withdrawal-records"),
    "pionex": ("/api/v1/trade/fills",),
    "coinbase": ("/api/v3/brokerage/orders/historical/fills",),
}
_NOTES = {
    "binance": (
        "Nur Spot-Fills der angegebenen Symbole sowie Capital-Ein-/Auszahlungen; "
        "keine Earn-, Convert-, Fiat-, Margin-, Futures- oder internen Umbuchungshistorien.",
        "Erfolgreiche Auszahlungen erhalten unbekannte Null-Ereignisse mit Klassifikationspflicht: "
        "Brutto-/Nettobetrag und Gebuehrenwirkung muessen vor einer Buchung geprueft werden.",
    ),
    "bitget": (
        "Classic-Spot-Fills (API-Aufbewahrung nur 90 Tage) und Wallet-Ein-/Auszahlungen; "
        "keine UTA-, Earn-, Convert-, Margin-, Futures- oder Umbuchungshistorien. "
        "Aeltere Fills benoetigen einen Dateiexport; leere API-Seiten beweisen keine Historie.",
        "Erfolgreiche Auszahlungen erhalten unbekannte Null-Ereignisse mit Klassifikationspflicht: "
        "size/fee erlauben hier keine sichere Brutto-/Nettozuordnung.",
    ),
    "pionex": (
        "Nur Spot-Fills der angegebenen Symbole. Die gepruefte offizielle Trade-/Wallet-API "
        "dokumentiert keine Ein-/Auszahlungshistorie; Bot-, Earn- und Futures-Historien fehlen.",
    ),
    "coinbase": (
        "Nur Advanced-Trade-Spot-Fills des fuer den Schluessel freigegebenen Portfolios; "
        "keine Simple-Buy-, Convert-, Transfer-, Ein-/Auszahlungs- oder Reward-Historie. "
        "Die Advanced-Trade-API dokumentiert keine allgemeine Funding-Historie.",
        "Coinbase dokumentiert instabile Cursor-Paginierung; keine Vollstaendigkeitszusage.",
    ),
}


def requires_symbols(provider: str) -> bool:
    return provider.strip().lower() in {"binance", "pionex"}


def coverage_notes(provider: str) -> tuple[str, ...]:
    return _NOTES.get(provider.strip().lower(), ())


def _fail(code: str = "cex_history_record_invalid") -> NoReturn:
    raise HistoryFetchError(code, resumable=False)


def _text(value: object) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        _fail()
    result = str(value).strip()
    if not result:
        _fail()
    return result


def _asset(value: object) -> str:
    result = _text(value).upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9.]{0,39}", result):
        _fail("cex_history_asset_ambiguous")
    return result


def _number(value: object, *, zero: bool = False, signed: bool = False) -> Decimal:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        _fail("cex_history_quantity_invalid")
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        _fail("cex_history_quantity_invalid")
    if not result.is_finite() or len(result.as_tuple().digits) > 80 or abs(result.as_tuple().exponent) > 80:
        _fail("cex_history_quantity_invalid")
    if not signed and (result < 0 or (result == 0 and not zero)):
        _fail("cex_history_quantity_invalid")
    return result


def _integer(value: object) -> int:
    text = _text(value)
    if not re.fullmatch(r"[0-9]+", text):
        _fail("cex_history_cursor_invalid")
    return int(text)


def _when(value: object, *, bitget: bool = False, utc_text: bool = False) -> datetime:
    text = _text(value)
    try:
        if text.isdigit():
            number = int(text)
            # Bitget's table says seconds, but its response example uses milliseconds.
            return _EPOCH + (timedelta(seconds=number) if bitget and len(text) == 10
                             else timedelta(milliseconds=number))
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if result.tzinfo is None:
            if not utc_text or not re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?", text):
                _fail("cex_history_timestamp_invalid")
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        _fail("cex_history_timestamp_invalid")


def _millis(value: datetime) -> int:
    delta = value.astimezone(timezone.utc) - _EPOCH
    return delta.days * _DAY + delta.seconds * 1000 + delta.microseconds // 1000


def _bitget_retention_floor() -> int:
    # Keep a small margin so a request is not already outside retention on arrival.
    return _millis(datetime.now(timezone.utc) - timedelta(days=90) + timedelta(minutes=1))


class _HistoryBalanceService(CexBalanceService):
    """Prueft auch vom zentralen Transport wiederholte Requests vor dem Signieren."""

    page_check: Callable[[], None] = staticmethod(lambda: None)
    page_requests: int = 0

    def _get_json(self, url, headers, *, signer=None):
        def checked_sign(request):
            self.page_check()
            if self.page_requests >= 5:
                raise HistoryFetchError("cex_history_page_request_budget", resumable=True)
            self.page_requests += 1
            if signer is not None:
                signer(request)
        return super()._get_json(url, headers, signer=checked_sign)


class CexHistoryCollector:
    def __init__(self, store, target: HistoryTarget, options: HistoryOptions) -> None:
        self.target, self.options = target, options
        self.provider = target.provider.strip().lower()
        if self.provider not in _PATHS:
            _fail("cex_history_provider_unsupported")
        # Only the parent's explicitly resolved single legacy account may use None.
        if target.connection_id is None:
            if target.legacy_credentials is not True or target.account != self.provider:
                _fail("cex_history_connection_required")
        elif not target.connection_id.strip():
            _fail("cex_history_connection_required")
        if not target.account.strip():
            _fail("cex_history_account_required")
        if (options.start.tzinfo is None or options.end.tzinfo is None
                or options.end <= options.start):
            _fail("cex_history_range_invalid")
        if options.start.microsecond % 1000 or options.end.microsecond % 1000:
            _fail("cex_history_range_requires_milliseconds")
        self.start = _millis(options.start)
        self.end = _millis(options.end) + 1  # Internal half-open boundary; public end is inclusive.
        if self.start < 0 or self.end <= self.start:
            _fail("cex_history_range_invalid")
        self.symbols = tuple(sorted({_text(s).upper() for s in options.symbols}))
        pattern = {"binance": r"[A-Z0-9]+", "bitget": r"[A-Z0-9]+",
                   "pionex": r"[A-Z0-9]+_[A-Z0-9]+",
                   "coinbase": r"[A-Z0-9]+-[A-Z0-9]+"}[self.provider]
        if any(not re.fullmatch(pattern, s) for s in self.symbols):
            _fail("cex_history_symbols_invalid")
        if requires_symbols(self.provider) and not self.symbols:
            _fail("cex_history_symbols_required")
        self.service = _HistoryBalanceService(store, connection_id=target.connection_id)
        paths = _PATHS[self.provider]
        self.streams = [(paths[0], symbol) for symbol in (self.symbols or ("",))]
        self.streams.extend((path, "") for path in paths[1:])
        self.binding = hashlib.sha256(json.dumps([
            1, self.provider, target.source_ref, target.account, target.connection_id,
            target.legacy_credentials, self.start, self.end, self.symbols,
        ], ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()

    def _span(self, stream: int) -> int:
        if self.provider == "pionex":
            return self.end - self.start
        return _DAY if self.provider == "binance" and stream < len(self.symbols) else 30 * _DAY

    def _enter_stream(self, state: dict) -> None:
        start = self.start
        if self.provider == "bitget" and state["stream"] < len(self.symbols or ("",)):
            start = state["fill_start"]
            if start >= self.end:
                state["stream"] = len(self.symbols or ("",))
                start = self.start
        if self.provider == "pionex" and start == 0:
            if self.end == 1:
                state["stream"] = len(self.streams)
            else:
                start = 1  # The provider explicitly ignores zero-valued numeric filters.
        state["lo"] = start
        state["hi"] = min(start + self._span(state["stream"]), self.end) - 1

    def _state(self, cursor: dict) -> dict:
        if not cursor:
            state = {"v": 1, "binding": self.binding, "stream": 0,
                     "pending": [], "token": ""}
            if self.provider == "bitget":
                state["fill_start"] = min(max(self.start, _bitget_retention_floor()), self.end)
            self._enter_stream(state)
            return state
        if type(cursor.get("v")) is not int or cursor.get("v") != 1 or cursor.get("binding") != self.binding:
            _fail("cex_history_cursor_binding_mismatch")
        state = deepcopy(cursor)
        stream = state.get("stream")
        if type(stream) is not int or not 0 <= stream <= len(self.streams):
            _fail("cex_history_cursor_invalid")
        if self.provider == "bitget" and (type(state.get("fill_start")) is not int
                or not self.start <= state["fill_start"] <= self.end):
            _fail("cex_history_cursor_invalid")
        lo, hi = state.get("lo"), state.get("hi")
        pending = state.get("pending")
        if (type(lo) is not int or type(hi) is not int or not self.start <= lo <= hi < self.end
                or not isinstance(pending, list) or len(pending) > 64
                or not isinstance(state.get("token"), str)):
            _fail("cex_history_cursor_invalid")
        previous = hi
        for window in pending:
            if (not isinstance(window, list) or len(window) != 2
                    or any(type(x) is not int for x in window)
                    or not previous + 1 == window[0] <= window[1] < self.end):
                _fail("cex_history_cursor_invalid")
            previous = window[1]
        if stream < len(self.streams) and state["token"]:
            trade = self.streams[stream][0] == _PATHS[self.provider][0]
            if self.provider == "pionex" or (self.provider == "binance" and trade):
                _fail("cex_history_cursor_invalid")
            if self.provider in {"binance", "bitget"}:
                _integer(state["token"])
        return state

    def fetch_page(self, cursor: dict, check: Callable[[], None]) -> HistoryPage:
        state = self._state(cursor)
        notes = list(_NOTES[self.provider])
        if self.provider == "pionex" and self.start == 0:
            notes.append("Pionex ignoriert numerische Nullfilter; der Scan beginnt bei Unix-Millisekunde 1 statt 0.")
        if self.provider == "bitget" and state["fill_start"] > self.start:
            gap_end = (_EPOCH + timedelta(milliseconds=state["fill_start"])).isoformat()
            notes.append(f"Abdeckungsluecke: Bitget-Spot-Fills vor {gap_end} werden wegen der "
                         "90-Tage-Aufbewahrung (plus 1 Minute Sicherheitsabstand) nicht angefragt. "
                         "Funding startet unveraendert am gewuenschten Beginn; alte Fills erfordern einen Dateiexport.")
        if state["stream"] == len(self.streams):
            return HistoryPage([], state, True, tuple(notes))
        self.service.page_check = check
        self.service.page_requests = 0
        requests = 0

        def call(method, *args, **kwargs):
            nonlocal requests
            check()
            requests += 1
            return method(*args, **kwargs)

        credentials = self.service._credentials(self.provider)
        path, symbol = self.streams[state["stream"]]
        trade = path == _PATHS[self.provider][0]
        params = {"startTime": str(state["lo"]), "endTime": str(state["hi"]), "limit": "100"}
        if symbol:
            params["symbol"] = symbol
        if self.provider == "coinbase":
            params = {"start_sequence_timestamp": (self.options.start - timedelta(milliseconds=1)).astimezone(timezone.utc).isoformat(),
                      "end_sequence_timestamp": (self.options.end + timedelta(milliseconds=1)).astimezone(timezone.utc).isoformat(),
                      "product_types": "SPOT", "limit": "100"}
            if symbol:
                params["product_ids"] = symbol
            if state["token"]:
                params["cursor"] = state["token"]
            body = call(self.service._coinbase_get, path, *credentials[:2], params)
            if not isinstance(body, dict) or body.get("proof_token_required") is True:
                _fail("cex_history_coinbase_proof_required" if isinstance(body, dict)
                      else "cex_history_response_invalid")
            if body.get("error") or body.get("errors"):
                _fail("cex_history_provider_error")
            items = body.get("fills")
        elif self.provider == "binance":
            if not trade:
                params["offset"] = state["token"] or "0"
            body = call(self.service._binance_get, path, *credentials[:2], params)
            items = body
        elif self.provider == "bitget":
            if state["token"]:
                params["idLessThan"] = state["token"]
            body = call(self.service._bitget_get, path, *credentials, params)
            if not isinstance(body, dict) or body.get("code") != "00000":
                _fail("cex_history_provider_error")
            items = body.get("data")
        else:
            # Pionex has no limit parameter and silently truncates to the latest 100.
            params.pop("limit")
            body = call(self._pionex_get, path, *credentials[:2], params)
            if not isinstance(body, dict) or body.get("result") is not True:
                _fail("cex_history_provider_error")
            data = body.get("data")
            items = data.get("fills") if isinstance(data, dict) else None
        if (not isinstance(items, list) or len(items) > _LIMIT
                or any(not isinstance(item, dict) for item in items)):
            _fail("cex_history_response_invalid")
        if self.provider == "bitget" and state["token"]:
            key = "tradeId" if trade else "orderId"
            if any(_integer(item.get(key)) >= _integer(state["token"]) for item in items):
                _fail("cex_history_cursor_stalled")
        if self.provider == "binance" and not trade and len(items) == _LIMIT:
            page_ids = hashlib.sha256(json.dumps([_text(item.get("id")) for item in items]).encode()).hexdigest()
            if page_ids == state.get("last_page_ids"):
                _fail("cex_history_cursor_stalled")
            state["last_page_ids"] = page_ids

        markets = self._markets(call, items) if trade and items else {}
        records = []
        seen: dict[str, HistoryRecord] = {}
        for item in items:
            timestamp = self._timestamp(path, item)
            with localcontext() as context:
                context.prec = 200
                record = (self._fill(path, symbol, item, markets, timestamp) if trade
                          else self._funding(path, item, notes, timestamp))
            if self.provider != "coinbase" and not state["lo"] <= _millis(timestamp) <= state["hi"]:
                _fail("cex_history_timestamp_outside_window")
            if not self.options.start <= timestamp <= self.options.end:
                notes.append("Provider-Fill ausserhalb des angeforderten Zeitraums nach Validierung herausgefiltert.")
                continue
            if record.identity in seen and record != seen[record.identity]:
                _fail("cex_history_record_conflict")
            seen[record.identity] = record
            records.append(record)
        # All records have been validated before creating the next checkpoint.
        if self.provider == "coinbase":
            token = body.get("cursor", "")
            if not isinstance(token, str):
                _fail("cex_history_cursor_invalid")
            if token and (token == state["token"] or not items):
                _fail("cex_history_cursor_stalled")
            if token:
                state["token"] = token
            elif len(items) == _LIMIT:
                _fail("cex_history_cursor_missing")
            else:
                self._next_stream(state)
        elif len(items) == _LIMIT:
            if self.provider in {"binance", "pionex"} and trade:
                if state["lo"] == state["hi"]:
                    _fail("cex_history_timestamp_saturated")
                middle = (state["lo"] + state["hi"]) // 2
                state["pending"].insert(0, [middle + 1, state["hi"]])
                state["hi"] = middle
                notes.append("Volle Fill-Seite: Zeitfenster wird geteilt; Ueberlappungen nach externer ID deduplizieren.")
            elif self.provider == "binance":
                state["token"] = str(_integer(state["token"] or "0") + len(items))
            else:
                key = "tradeId" if trade else "orderId"
                token = str(min(_integer(item.get(key)) for item in items))
                if state["token"] and int(token) >= _integer(state["token"]):
                    _fail("cex_history_cursor_stalled")
                state["token"] = token
        else:
            self._advance(state)

        return HistoryPage(records, state, state["stream"] == len(self.streams),
                           tuple(dict.fromkeys(notes)), max(requests, self.service.page_requests), "CEX-Historie abrufen",
                           extra={"endpoint": path, "response": deepcopy(body)})

    def _next_stream(self, state: dict) -> None:
        state.pop("last_page_ids", None)
        state.update(stream=state["stream"] + 1, token="", pending=[])
        self._enter_stream(state)

    def _advance(self, state: dict) -> None:
        state.pop("last_page_ids", None)
        state["token"] = ""
        if state["pending"]:
            state["lo"], state["hi"] = state["pending"].pop(0)
        elif state["hi"] + 1 < self.end:
            state["lo"] = state["hi"] + 1
            state["hi"] = min(state["lo"] + self._span(state["stream"]), self.end) - 1
        else:
            self._next_stream(state)

    def _markets(self, call, items: list[dict]) -> dict[str, tuple[str, str]]:
        symbols = {_text(item.get("product_id" if self.provider == "coinbase" else "symbol")).upper()
                   for item in items}
        if self.provider in {"pionex", "coinbase"}:
            separator = "_" if self.provider == "pionex" else "-"
            result = {}
            for symbol in symbols:
                parts = symbol.split(separator)
                if len(parts) != 2:
                    _fail("cex_history_market_ambiguous")
                result[symbol] = (_asset(parts[0]), _asset(parts[1]))
            return result
        if self.provider == "binance":
            url = self.service.BINANCE_BASE_URL + "/api/v3/exchangeInfo?" + urlencode({
                "symbols": json.dumps(sorted(symbols), separators=(",", ":"))})
            body = call(self.service._get_json, url, {})
            entries = body.get("symbols") if isinstance(body, dict) else None
            base_key, quote_key = "baseAsset", "quoteAsset"
        else:
            body = call(self.service._get_json, self.service.BITGET_BASE_URL + "/api/v2/spot/public/symbols", {})
            entries = body.get("data") if isinstance(body, dict) and body.get("code") == "00000" else None
            base_key, quote_key = "baseCoin", "quoteCoin"
        if not isinstance(entries, list):
            _fail("cex_history_market_metadata_missing")
        result = {}
        for entry in entries:
            if not isinstance(entry, dict):
                _fail("cex_history_market_metadata_missing")
            symbol = _text(entry.get("symbol")).upper()
            if symbol not in symbols:
                continue
            pair = (_asset(entry.get(base_key)), _asset(entry.get(quote_key)))
            if symbol in result or "".join(pair) != symbol:
                _fail("cex_history_market_ambiguous")
            result[symbol] = pair
        if symbols != result.keys():
            _fail("cex_history_market_metadata_missing")
        return result

    def _timestamp(self, path: str, item: dict) -> datetime:
        if path == _PATHS[self.provider][0]:
            key = {"binance": "time", "bitget": "cTime", "pionex": "timestamp", "coinbase": "trade_time"}[self.provider]
            return _when(item.get(key), bitget=self.provider == "bitget")
        if self.provider == "binance":
            return _when(item.get("insertTime") if path == _PATHS[self.provider][1]
                         else item.get("applyTime"), utc_text=True)
        return _when(item.get("cTime"), bitget=True)

    def _fill(self, path: str, requested: str, item: dict, markets: dict, timestamp: datetime) -> HistoryRecord:
        provider = self.provider
        symbol = _text(item.get("product_id" if provider == "coinbase" else "symbol")).upper()
        if requested and symbol != requested:
            _fail("cex_history_symbol_mismatch")
        base, quote = markets[symbol]
        if base == quote:
            _fail("cex_history_market_ambiguous")
        if provider == "binance":
            if type(item.get("isBuyer")) is not bool:
                _fail("cex_history_direction_ambiguous")
            side = "buy" if item["isBuyer"] else "sell"
            external = _text(item.get("id"))
            quantity, total = _number(item.get("qty")), _number(item.get("quoteQty"))
            fee, fee_asset = _number(item.get("commission"), zero=True), _asset(item.get("commissionAsset"))
        else:
            side = _text(item.get("side")).lower()
            if side not in {"buy", "sell"}:
                _fail("cex_history_direction_ambiguous")
            if provider == "pionex":
                external = _text(item.get("id"))
                quantity = _number(item.get("size"))
                total = quantity * _number(item.get("price"))
                fee, fee_asset = _number(item.get("fee"), zero=True), _asset(item.get("feeCoin"))
            elif provider == "bitget":
                external = _text(item.get("tradeId"))
                quantity, total = _number(item.get("size")), _number(item.get("amount"))
                detail = item.get("feeDetail")
                if not isinstance(detail, dict) or detail.get("newFees") is not None:
                    _fail("cex_history_fee_ambiguous")
                paid = _number(detail.get("totalFee"), signed=True)
                if paid > 0:
                    _fail("cex_history_fee_rebate_unsupported")
                fee, fee_asset = -paid, _asset(detail.get("feeCoin"))
            else:
                if item.get("trade_type") != "FILL" or item.get("future_legs"):
                    _fail("cex_history_non_spot_fill")
                external = _text(item.get("entry_id"))
                quantity = _number(item.get("size"))
                price = _number(item.get("price"))
                if type(item.get("size_in_quote")) is not bool:
                    _fail("cex_history_quantity_ambiguous")
                if item["size_in_quote"]:
                    total, quantity = quantity, quantity / price
                    # Do not round a repeating quotient into an invented base quantity.
                    if Fraction(quantity) * Fraction(price) != Fraction(total):
                        _fail("cex_history_quantity_inexact")
                else:
                    total = quantity * price
                fee, fee_asset = _number(item.get("commission"), zero=True), quote
        row = self._row(timestamp, base, quantity if side == "buy" else -quantity,
                        side, quote, total, fee_asset, fee)
        # Binance/Pionex IDs are scoped to a market, not necessarily to the exchange.
        return self._record(path, [symbol, external], item, [row])

    def _funding(self, path: str, item: dict, notes: list[str], timestamp: datetime) -> HistoryRecord:
        deposit = path == _PATHS[self.provider][1]
        external = _text(item.get("id" if self.provider == "binance" else "orderId"))
        asset = _asset(item.get("coin"))
        quantity = _number(item.get("amount" if self.provider == "binance" else "size"))
        if self.provider == "binance":
            status = _text(item.get("status"))
            if status not in ({"0", "1", "2", "6", "7", "8"} if deposit else {"0", "1", "2", "3", "4", "5", "6"}):
                _fail("cex_history_status_unknown")
            success = status == ("1" if deposit else "6")
            classification_required = (success and not deposit) or (deposit and status == "6")
        else:
            status = _text(item.get("status")).lower()
            if status not in {"pending", "fail", "success"}:
                _fail("cex_history_status_unknown")
            if _text(item.get("type")).lower() != ("deposit" if deposit else "withdraw"):
                _fail("cex_history_direction_ambiguous")
            success = status == "success"
            classification_required = success and not deposit
        rows = []
        if classification_required:
            row = self._row(timestamp, asset, Decimal("0"), "unknown")
            row["history_classification_required"] = "1"
            rows = [row]
            notes.append("Finanzieller Funding-Beleg: unbekanntes Null-Ereignis ohne Mengen-/Gebuehrenannahme; "
                         "Klassifikation ueber das Review-Gate erforderlich.")
        elif success and deposit:
            rows = [self._row(timestamp, asset, quantity, "deposit")]
        else:
            notes.append("Nicht abgeschlossene Transfers bleiben Rohbelege ohne Bestandswirkung.")
        return self._record(path, [external], item, rows)

    def _row(self, timestamp, asset, quantity, kind, quote=None, total=None, fee_asset=None, fee=None) -> dict:
        profile = profile_for_source(self.provider)
        row = {profile.time_columns[0]: timestamp.isoformat(), profile.asset_columns[0]: asset,
               profile.quantity_columns[0]: str(quantity), profile.type_columns[0]: kind,
               profile.account_columns[0]: self.target.account}
        if quote is not None:
            row[profile.quote_asset_columns[0]] = quote
            row[profile.quote_quantity_columns[0]] = str(total)
        if fee is not None:
            # Coinbase's preferred fee asset column also supplies quote_asset.
            row[profile.fee_asset_columns[0]] = fee_asset
            row[profile.fee_quantity_columns[0]] = str(fee)
        return row

    def _record(self, path: str, external: list[str], item: dict, rows: list[dict]) -> HistoryRecord:
        identity = "cex:" + json.dumps([self.provider, self.target.account, path, *external],
                                      ensure_ascii=True, separators=(",", ":"))
        profile = profile_for_source(self.provider)
        for row in rows:
            row[profile.source_ref_columns[0]] = identity
        return HistoryRecord(identity, self.provider, rows,
                             {"payload": deepcopy(item), "endpoint": path})

    def _pionex_get(self, path: str, key: str, secret: str, params: dict[str, str]) -> object:
        def sign(request: httpx.Request) -> None:
            signed = sorted({**params, "timestamp": str(int(time.time() * 1000))}.items())
            # All accepted values are ASCII symbols/integers; signing uses unencoded values.
            query = "&".join(f"{key}={value}" for key, value in signed)
            request.url = httpx.URL(f"{self.service.PIONEX_BASE_URL}{path}?{urlencode(signed)}")
            request.headers["PIONEX-KEY"] = key
            request.headers["PIONEX-SIGNATURE"] = hmac.new(
                secret.encode(), f"GET{path}?{query}".encode(), hashlib.sha256,
            ).hexdigest()
        return self.service._get_json(f"{self.service.PIONEX_BASE_URL}{path}", {}, signer=sign)
