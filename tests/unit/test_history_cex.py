"""Isolierte Provider-Mocks; keine Schluessel, Netzwerkzugriffe oder produktive DB."""
from copy import deepcopy
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import hmac
import json

import httpx
import pytest

from steuerreport_v2.domain.cex_balances import CexBalanceService
from steuerreport_v2.domain.history_cex import CexHistoryCollector, requires_symbols
from steuerreport_v2.domain.history_types import HistoryFetchError, HistoryOptions, HistoryTarget
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.importers.source_profiles import inspect_profile_columns, profile_for_source


START = datetime(2026, 10, 1, tzinfo=timezone.utc)
MILLIS = int((START + timedelta(hours=1)).timestamp() * 1000)
SYMBOLS = {"binance": "BTCUSDT", "bitget": "BTCUSDT", "pionex": "BTC_USDT", "coinbase": "BTC-USD"}
REAL_CREDENTIALS = CexBalanceService._credentials
REAL_GET_JSON = CexBalanceService._get_json


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No real provider/credential access in adapter tests")
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(CexBalanceService, "_get_json", forbidden)
    monkeypatch.setattr(CexBalanceService, "_credentials", forbidden)
    monkeypatch.setattr("steuerreport_v2.domain.history_cex._bitget_retention_floor",
                        lambda: int((START - timedelta(days=30)).timestamp() * 1000))


def collector(provider="binance", *, symbols=None, account="My Spot", connection="conn-one", end=None):
    if symbols is None:
        symbols = (SYMBOLS[provider],)
    return CexHistoryCollector(
        object(), HistoryTarget("source-one", "Anzeige", provider, account, connection_id=connection),
        HistoryOptions(START, end or START + timedelta(days=1) - timedelta(milliseconds=1), symbols),
    )


def fill(provider, **updates):
    rows = {
        "binance": {"symbol": "BTCUSDT", "id": 0, "orderId": 7, "time": MILLIS,
                    "isBuyer": True, "qty": "0.1", "quoteQty": "3000",
                    "commission": "0.01", "commissionAsset": "BNB", "account": "binance"},
        "bitget": {"symbol": "BTCUSDT", "tradeId": "10", "orderId": "20", "cTime": str(MILLIS),
                   "side": "buy", "size": "0.1", "amount": "3000", "priceAvg": "30000",
                   "feeDetail": {"deduction": "no", "feeCoin": "BTC", "totalFee": "-0.0001",
                                 "totalDeductionFee": "0"}, "account": "bitget"},
        "pionex": {"symbol": "BTC_USDT", "id": 11, "orderId": 21, "timestamp": MILLIS,
                   "side": "BUY", "size": "0.1", "price": "30000", "fee": "0.1", "feeCoin": "USDT"},
        "coinbase": {"product_id": "BTC-USD", "entry_id": "entry-12", "trade_id": "trade-12",
                     "trade_time": datetime.fromtimestamp(MILLIS / 1000, timezone.utc).isoformat(),
                     "trade_type": "FILL", "size_in_quote": False, "side": "BUY",
                     "size": "0.1", "price": "30000", "commission": "3"},
    }
    return {**deepcopy(rows[provider]), **updates}


def envelope(provider, rows, **updates):
    return {"binance": rows, "bitget": {"code": "00000", "data": rows, **updates},
            "pionex": {"result": True, "data": {"fills": rows}, **updates},
            "coinbase": {"fills": rows, "cursor": "", **updates}}[provider]


def mocked(monkeypatch, instance, payloads, *, metadata=None, events=None):
    calls = []
    responses = iter(payloads)
    def credentials(service, provider):
        assert service.connection_id == instance.target.connection_id
        assert provider == instance.provider
        return "fake-key", "fake-secret", "fake-passphrase"
    monkeypatch.setattr(CexBalanceService, "_credentials", credentials)
    def request(path, *args):
        if events is not None:
            events.append("request")
        calls.append((path, args[-1]))
        return deepcopy(next(responses))
    monkeypatch.setattr(instance.service, "_" + instance.provider + "_get", request, raising=False)
    if instance.provider == "pionex":
        monkeypatch.setattr(instance, "_pionex_get", request)
    def public(url, headers):
        if events is not None:
            events.append("metadata")
        calls.append((url, headers))
        if metadata is not None:
            return deepcopy(metadata)
        return {"symbols": [{"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT"}]} if instance.provider == "binance" else {
            "code": "00000", "data": [{"symbol": "BTCUSDT", "baseCoin": "BTC", "quoteCoin": "USDT"}]}
    monkeypatch.setattr(instance.service, "_get_json", public)
    return calls


def normalize(record):
    # Test only the pure row mapper, without loading private settings or opening a store.
    normalizer = object.__new__(RawNormalizer)
    normalizer._asset_aliases = {}
    return normalizer._row_to_event(record.source, "raw-object", record.rows[0])


@pytest.mark.parametrize("provider", SYMBOLS)
@pytest.mark.parametrize("sell", [False, True])
def test_actual_fills_profile_account_fees_and_raw(monkeypatch, provider, sell):
    instance = collector(provider, account="Exact Mixed CASE Account")
    item = fill(provider)
    if provider == "binance":
        item["isBuyer"] = not sell
    else:
        item["side"] = "sElL" if sell else "bUy"
    original = deepcopy(item)
    body = envelope(provider, [item])
    events = []
    calls = mocked(monkeypatch, instance, [body], events=events)
    page = instance.fetch_page({}, lambda: events.append("check"))
    assert events == (["check", "request", "check", "metadata"] if provider in {"binance", "bitget"} else ["check", "request"])
    assert 1 <= page.requests == len(calls) <= 5
    assert len(page.records) == 1
    assert not page.complete_history_proven
    assert page.notes
    record = page.records[0]
    assert record.raw["payload"] == original and item == original
    assert page.extra["response"] == body
    assert record.source == provider
    profile = profile_for_source(record.source)
    assert inspect_profile_columns(profile, list(record.rows[0]))[1] == []
    event = normalize(record)
    assert event.account == "Exact Mixed CASE Account"
    assert event.event_type == "trade"
    assert event.asset == "BTC"
    assert event.quantity == Decimal("-0.1" if sell else "0.1")
    assert event.quote_asset == ("USD" if provider == "coinbase" else "USDT")
    assert event.quote_quantity == 3000
    assert event.event_time == START + timedelta(hours=1)
    assert event.source_ref == record.identity
    assert event.fee_asset == {"binance": "BNB", "bitget": "BTC", "pionex": "USDT", "coinbase": "USD"}[provider]
    assert event.fee_quantity == Decimal({"binance": "0.01", "bitget": "0.0001", "pionex": "0.1", "coinbase": "3"}[provider])
    assert json.loads(json.dumps(page.cursor)) == page.cursor


@pytest.mark.parametrize("provider", SYMBOLS)
def test_identity_and_rows_stable_across_response_envelopes(monkeypatch, provider):
    instance = collector(provider)
    mocked(monkeypatch, instance, [envelope(provider, [fill(provider)]), envelope(provider, [fill(provider)], requestTime=999)])
    first = instance.fetch_page({}, lambda: None).records[0]
    second = instance.fetch_page({}, lambda: None).records[0]
    assert asdict(first) == asdict(second)
    account = collector(provider, account="Other Account")
    mocked(monkeypatch, account, [envelope(provider, [fill(provider)])])
    assert account.fetch_page({}, lambda: None).records[0].identity != first.identity


@pytest.mark.parametrize("provider", [" Binance ", "PIONEX"])
def test_symbols_required_setup_without_any_credentials(provider):
    assert requires_symbols(provider)
    with pytest.raises(HistoryFetchError, match="symbols_required") as error:
        CexHistoryCollector(object(), HistoryTarget("ref", "label", provider, "account", connection_id="id"),
                            HistoryOptions(START, START + timedelta(days=1)))
    assert not error.value.resumable


@pytest.mark.parametrize("provider", ["coinbase", "bitget", "unknown"])
def test_symbol_requirement_is_narrow(provider):
    assert not requires_symbols(provider)


@pytest.mark.parametrize("connection", [None, "", "  "])
def test_never_activate_legacy_global_credentials(connection):
    with pytest.raises(HistoryFetchError, match="connection_required"):
        collector(connection=connection)


def test_explicit_missing_connection_does_not_fallback(monkeypatch):
    instance = collector(connection="missing-id")
    import steuerreport_v2.domain.connections as connections
    import steuerreport_v2.domain.cex_balances as balances
    def missing(service, connection_id, provider):
        assert (connection_id, provider) == ("missing-id", "binance")
        raise RuntimeError("connection_not_found")
    def global_secret(*args):
        pytest.fail("must not consult global secrets")
    monkeypatch.setattr(CexBalanceService, "_credentials", REAL_CREDENTIALS)
    monkeypatch.setattr(connections.ConnectionService, "credentials", missing)
    monkeypatch.setattr(balances, "resolve_secret_value", global_secret)
    with pytest.raises(RuntimeError, match="connection_not_found"):
        instance.fetch_page({}, lambda: None)


@pytest.mark.parametrize("provider", SYMBOLS)
def test_check_cancels_before_external_call(monkeypatch, provider):
    instance = collector(provider)
    calls = mocked(monkeypatch, instance, [])
    def cancel():
        raise RuntimeError("cancelled")
    with pytest.raises(RuntimeError, match="cancelled"):
        instance.fetch_page({}, cancel)
    assert calls == []


def test_check_before_metadata_cancels_without_cursor_commit(monkeypatch):
    instance = collector()
    calls = mocked(monkeypatch, instance, [envelope("binance", [fill("binance")])])
    checks = 0
    def cancel():
        nonlocal checks
        checks += 1
        if checks == 2:
            raise RuntimeError("cancelled")
    cursor = {}
    with pytest.raises(RuntimeError, match="cancelled"):
        instance.fetch_page(cursor, cancel)
    assert cursor == {} and len(calls) == 1


@pytest.mark.parametrize("provider,updates", [
    ("binance", {"id": None}), ("pionex", {"id": ""}),
    ("bitget", {"tradeId": None}), ("coinbase", {"entry_id": None}),
    ("binance", {"isBuyer": "true"}), ("pionex", {"side": "out"}),
    ("bitget", {"side": ""}), ("coinbase", {"side": "UNKNOWN"}),
    ("binance", {"qty": "NaN"}), ("binance", {"quoteQty": "0"}),
    ("pionex", {"size": "-1"}), ("pionex", {"price": "Infinity"}),
    ("bitget", {"amount": "not-numeric"}), ("coinbase", {"size_in_quote": "false"}),
    ("coinbase", {"commission": None}), ("binance", {"commissionAsset": ""}),
    ("coinbase", {"trade_time": "2026-10-01 01:00:00"}),
    ("coinbase", {"trade_type": "REVERSAL"}), ("coinbase", {"future_legs": [{}]}),
])
def test_fail_closed_whole_page_before_next_cursor(monkeypatch, provider, updates):
    instance = collector(provider)
    mocked(monkeypatch, instance, [envelope(provider, [fill(provider), fill(provider, **updates)])])
    cursor = instance._state({})
    original = deepcopy(cursor)
    with pytest.raises(HistoryFetchError):
        instance.fetch_page(cursor, lambda: None)
    assert cursor == original


@pytest.mark.parametrize("provider,payload", [
    ("binance", {"code": -2015, "msg": "secret must not appear"}),
    ("bitget", {"code": "40001", "data": []}),
    ("pionex", {"result": False, "data": {"fills": []}}),
    ("coinbase", {"error": "auth"}), ("coinbase", {"fills": [], "proof_token_required": True}),
    ("binance", [None]), ("bitget", {"code": "00000", "data": {"fillList": []}}),
])
def test_provider_errors_and_wrong_envelopes(monkeypatch, provider, payload):
    instance = collector(provider)
    mocked(monkeypatch, instance, [payload])
    with pytest.raises(HistoryFetchError) as error:
        instance.fetch_page({}, lambda: None)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("provider", ["binance", "pionex"])
def test_full_time_page_splits_durably_not_timestamp_plus_one(monkeypatch, provider):
    instance = collector(provider)
    rows = [fill(provider, id=i) for i in range(100)]
    calls = mocked(monkeypatch, instance, [envelope(provider, rows), envelope(provider, [])])
    cursor = {}
    page = instance.fetch_page(cursor, lambda: None)
    assert cursor == {} and len(page.records) == 100 and not page.done
    assert page.cursor["pending"] == [[(instance.start + instance.end - 1) // 2 + 1, instance.end - 1]]
    assert "fromId" not in calls[0][1]
    restored = json.loads(json.dumps(page.cursor))
    next_page = instance.fetch_page(restored, lambda: None)
    assert next_page.cursor["lo"] == page.cursor["pending"][0][0]
    assert next_page.cursor["pending"] == []
    assert "limit" not in calls[0][1] if provider == "pionex" else calls[0][1]["limit"] == "100"


@pytest.mark.parametrize("provider", ["binance", "pionex"])
def test_single_millisecond_saturation_never_advances(monkeypatch, provider):
    instance = collector(provider)
    mocked(monkeypatch, instance, [envelope(provider, [fill(provider, id=i) for i in range(100)])])
    cursor = instance._state({})
    cursor.update(lo=MILLIS, hi=MILLIS)
    before = deepcopy(cursor)
    with pytest.raises(HistoryFetchError, match="timestamp_saturated"):
        instance.fetch_page(cursor, lambda: None)
    assert cursor == before


def test_coinbase_cursor_and_filters_survive_recreated_collector(monkeypatch):
    instance = collector("coinbase")
    calls = mocked(monkeypatch, instance, [envelope("coinbase", [fill("coinbase")], cursor="opaque-next")])
    page = instance.fetch_page({}, lambda: None)
    assert not page.done and page.cursor["token"] == "opaque-next"
    params = calls[0][1]
    assert params["product_ids"] == "BTC-USD" and params["product_types"] == "SPOT"
    assert params["start_sequence_timestamp"] == (START - timedelta(milliseconds=1)).isoformat()
    assert params["end_sequence_timestamp"] == (instance.options.end + timedelta(milliseconds=1)).isoformat()
    restored = collector("coinbase")
    calls = mocked(monkeypatch, restored, [envelope("coinbase", [])])
    final = restored.fetch_page(json.loads(json.dumps(page.cursor)), lambda: None)
    assert calls[0][1]["cursor"] == "opaque-next" and final.done
    assert restored.fetch_page(final.cursor, lambda: pytest.fail("no call")).requests == 0


@pytest.mark.parametrize("payload", [
    {"fills": [fill("coinbase")], "cursor": "same"},
    {"fills": [], "cursor": "other"},
    {"fills": [fill("coinbase")] * 100, "cursor": ""},
])
def test_coinbase_bad_cursor_does_not_commit(monkeypatch, payload):
    instance = collector("coinbase")
    mocked(monkeypatch, instance, [payload])
    cursor = instance._state({})
    cursor["token"] = "same"
    original = deepcopy(cursor)
    with pytest.raises(HistoryFetchError, match="cursor"):
        instance.fetch_page(cursor, lambda: None)
    assert cursor == original


@pytest.mark.parametrize("quote_size,price,expected", [("30", "3", "10"), ("2", "3", None)])
def test_coinbase_quote_size_requires_exact_quantity(monkeypatch, quote_size, price, expected):
    instance = collector("coinbase")
    mocked(monkeypatch, instance, [envelope("coinbase", [fill("coinbase", size_in_quote=True, size=quote_size, price=price)])])
    if expected is None:
        with pytest.raises(HistoryFetchError, match="quantity_inexact"):
            instance.fetch_page({}, lambda: None)
    else:
        assert normalize(instance.fetch_page({}, lambda: None).records[0]).quantity == Decimal(expected)


def test_bitget_trade_pagination_uses_trade_id_not_order_id(monkeypatch):
    instance = collector("bitget", symbols=())
    rows = [fill("bitget", tradeId=str(i), orderId="99999") for i in range(100, 200)]
    calls = mocked(monkeypatch, instance, [envelope("bitget", rows), envelope("bitget", [])])
    page = instance.fetch_page({}, lambda: None)
    assert page.cursor["token"] == "100"
    assert "symbol" not in calls[0][1]
    instance.fetch_page(page.cursor, lambda: None)
    assert calls[2][1]["idLessThan"] == "100"


@pytest.mark.parametrize("provider", SYMBOLS)
def test_more_than_100_records_rejected(monkeypatch, provider):
    instance = collector(provider)
    mocked(monkeypatch, instance, [envelope(provider, [fill(provider)] * 101)])
    with pytest.raises(HistoryFetchError, match="response_invalid"):
        instance.fetch_page({}, lambda: None)


def funding(provider, deposit=True, **updates):
    if provider == "binance":
        item = {"id": "transfer-1", "coin": "USDT", "amount": "10", "insertTime": MILLIS,
                "applyTime": "2026-10-01 01:00:00", "status": 1 if deposit else 6,
                "transactionFee": "0.1", "txId": "chain-hash"}
    else:
        item = {"orderId": "100", "coin": "USDT", "size": "10", "cTime": str(MILLIS),
                "type": "deposit" if deposit else "withdraw", "status": "success",
                "fee": "-0.1", "tradeId": "chain-hash", "dest": "on_chain"}
    return {**item, **updates}


def funding_cursor(instance, deposit=True):
    state = instance._state({})
    state["stream"] = len(instance.symbols or ("",)) + (0 if deposit else 1)
    return state


@pytest.mark.parametrize("provider", ["binance", "bitget"])
@pytest.mark.parametrize("deposit", [True, False])
def test_funding_deposits_and_review_required_zero_withdrawals(monkeypatch, provider, deposit):
    instance = collector(provider)
    item = funding(provider, deposit)
    calls = mocked(monkeypatch, instance, [envelope(provider, [item])])
    page = instance.fetch_page(funding_cursor(instance, deposit), lambda: None)
    assert page.requests == 1 and len(calls) == 1 and not page.complete_history_proven
    record = page.records[0]
    assert record.raw["payload"] == item
    if deposit:
        event = normalize(record)
        assert event.event_type == "transfer" and event.quantity == 10
        assert event.asset == "USDT" and event.account == "My Spot"
        assert event.fee_quantity is None and event.quote_quantity is None
    else:
        event = normalize(record)
        assert event.event_type == "unknown" and event.quantity == 0
        assert event.asset == "USDT" and event.account == "My Spot"
        assert event.event_time == START + timedelta(hours=1)
        assert event.fee_quantity is None and event.quote_quantity is None
        assert record.rows[0]["history_classification_required"] == "1"
        assert page.done and any("Klassifikation" in note for note in page.notes)


@pytest.mark.parametrize("provider,status", [("binance", 0), ("binance", 2),
                                            ("bitget", "fail"), ("bitget", "pending")])
def test_unsuccessful_deposits_are_evidence_not_invented_balance(monkeypatch, provider, status):
    instance = collector(provider)
    item = funding(provider, status=status)
    mocked(monkeypatch, instance, [envelope(provider, [item])])
    record = instance.fetch_page(funding_cursor(instance), lambda: None).records[0]
    assert record.rows == [] and record.raw["payload"] == item


@pytest.mark.parametrize("provider", ["binance", "bitget"])
def test_funding_pagination_and_endpoint_scoped_identity(monkeypatch, provider):
    instance = collector(provider)
    rows = [funding(provider, **({"id": str(i)} if provider == "binance" else {"orderId": str(i)}))
            for i in range(100, 200)]
    mocked(monkeypatch, instance, [envelope(provider, rows), envelope(provider, [funding(provider, False)])])
    page = instance.fetch_page(funding_cursor(instance), lambda: None)
    assert len(page.records) == 100 and page.cursor["token"] == "100"
    withdrawal = instance.fetch_page(funding_cursor(instance, False), lambda: None).records[0]
    assert withdrawal.identity != page.records[0].identity


@pytest.mark.parametrize("change", [{"binding": "other"}, {"v": 2}, {"lo": -1},
                                    {"pending": [[1, 2]]}, {"stream": True}, {"token": None}])
def test_bad_or_other_account_cursor_rejected_before_io(change):
    instance = collector()
    cursor = {**instance._state({}), **change}
    with pytest.raises(HistoryFetchError, match="cursor"):
        instance.fetch_page(cursor, lambda: pytest.fail("must reject before calls"))


def test_cursor_cannot_move_between_connections_or_options():
    cursor = collector()._state({})
    for instance in [collector(connection="other"), collector(account="Other"), collector(symbols=("ETHUSDT",))]:
        with pytest.raises(HistoryFetchError, match="binding_mismatch"):
            instance.fetch_page(cursor, lambda: pytest.fail("must reject before calls"))


@pytest.mark.parametrize("metadata", [{"symbols": []}, {"symbols": [{"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USD"}]}])
def test_compact_pair_never_guessed_from_suffix_or_balance(monkeypatch, metadata):
    instance = collector()
    mocked(monkeypatch, instance, [[fill("binance")]], metadata=metadata)
    with pytest.raises(HistoryFetchError, match="market"):
        instance.fetch_page({}, lambda: None)


def test_pionex_signer_sorts_query_and_uses_central_transport(monkeypatch):
    instance = collector("pionex")
    monkeypatch.setattr("steuerreport_v2.domain.history_cex.time.time", lambda: 1234.5)
    observed = []
    def get_json(url, headers, *, signer):
        request = httpx.Request("GET", url, headers=headers)
        signer(request)
        observed.append(request)
        return {"result": True}
    monkeypatch.setattr(instance.service, "_get_json", get_json)
    params = {"symbol": "BTC_USDT", "startTime": "100", "endTime": "200"}
    instance._pionex_get("/api/v1/trade/fills", "key", "secret", params)
    query = "endTime=200&startTime=100&symbol=BTC_USDT&timestamp=1234500"
    request = observed[0]
    assert str(request.url) == "https://api.pionex.com/api/v1/trade/fills?" + query
    assert request.headers["PIONEX-KEY"] == "key"
    assert request.headers["PIONEX-SIGNATURE"] == hmac.new(b"secret", ("GET/api/v1/trade/fills?" + query).encode(), hashlib.sha256).hexdigest()
    assert params == {"symbol": "BTC_USDT", "startTime": "100", "endTime": "200"}


def test_zero_fee_and_bitget_discount_are_not_double_charged(monkeypatch):
    instance = collector("bitget")
    item = fill("bitget", feeDetail={"deduction": "yes", "feeCoin": "BGB", "totalFee": "-0.25", "totalDeductionFee": "-0.25"})
    mocked(monkeypatch, instance, [envelope("bitget", [item])])
    event = normalize(instance.fetch_page({}, lambda: None).records[0])
    assert event.fee_asset == "BGB" and event.fee_quantity == Decimal("0.25")


@pytest.mark.parametrize("details", [{"feeCoin": "BTC", "totalFee": "0.1"},
                                     {"newFees": {"d": "1"}}, [], None])
def test_bitget_rebates_and_ambiguous_fee_shapes_fail_closed(monkeypatch, details):
    instance = collector("bitget")
    mocked(monkeypatch, instance, [envelope("bitget", [fill("bitget", feeDetail=details)])])
    with pytest.raises(HistoryFetchError, match="fee"):
        instance.fetch_page({}, lambda: None)


def test_range_endpoints_and_symbol_input_validation():
    target = HistoryTarget("ref", "label", "coinbase", "account", connection_id="id")
    for options in [HistoryOptions(START, START), HistoryOptions(START.replace(tzinfo=None), START + timedelta(days=1)),
                    HistoryOptions(START, START + timedelta(microseconds=1))]:
        with pytest.raises(HistoryFetchError, match="range"):
            CexHistoryCollector(object(), target, options)
    with pytest.raises(HistoryFetchError, match="symbols_invalid"):
        collector("pionex", symbols=("BTC_USDT&timestamp=1",))


@pytest.mark.parametrize("provider", SYMBOLS)
@pytest.mark.parametrize("account", ["connection:11111111-2222-3333-4444-555555555555", "legacy"])
def test_new_connection_and_legacy_accounts_are_exact(monkeypatch, provider, account):
    account = provider if account == "legacy" else account
    base = collector(provider, account=account)
    instance = CexHistoryCollector(object(), replace(base.target, provider=provider.upper()), base.options)
    mocked(monkeypatch, instance, [envelope(provider, [fill(provider)])])
    record = instance.fetch_page({}, lambda: None).records[0]
    assert record.rows[0]["account"] == account
    assert normalize(record).account == account
    assert record.source == provider


@pytest.mark.parametrize("provider", SYMBOLS)
def test_zero_fees_are_not_invented_or_missing(monkeypatch, provider):
    item = fill(provider)
    if provider in {"binance", "coinbase"}:
        item["commission"] = "0"
    elif provider == "pionex":
        item["fee"] = "0"
    else:
        item["feeDetail"]["totalFee"] = "0"
    instance = collector(provider)
    mocked(monkeypatch, instance, [envelope(provider, [item])])
    assert normalize(instance.fetch_page({}, lambda: None).records[0]).fee_quantity == 0


def test_coinbase_local_filter_validates_then_skips_outside_inclusive_range(monkeypatch):
    instance = collector("coinbase")
    items = [fill("coinbase", entry_id=str(i), trade_time=when.isoformat()) for i, when in enumerate([
        START - timedelta(milliseconds=1), START, instance.options.end - timedelta(milliseconds=1), instance.options.end,
        instance.options.end + timedelta(milliseconds=1),
    ])]
    mocked(monkeypatch, instance, [envelope("coinbase", items)])
    page = instance.fetch_page({}, lambda: None)
    assert len(page.records) == 3 and page.done
    assert [r.raw["payload"]["entry_id"] for r in page.records] == ["1", "2", "3"]
    assert any("herausgefiltert" in note for note in page.notes)


@pytest.mark.parametrize("provider", ["binance", "bitget", "pionex"])
def test_response_outside_requested_window_fails_closed(monkeypatch, provider):
    instance = collector(provider)
    mocked(monkeypatch, instance, [envelope(provider, [fill(provider)])])
    cursor = instance._state({})
    cursor["hi"] = MILLIS - 1
    original = deepcopy(cursor)
    with pytest.raises(HistoryFetchError, match="outside_window"):
        instance.fetch_page(cursor, lambda: None)
    assert cursor == original


def test_bitget_seconds_timestamp_matches_millisecond_example(monkeypatch):
    instance = collector("bitget")
    mocked(monkeypatch, instance, [envelope("bitget", [fill("bitget", cTime=str(MILLIS // 1000))])])
    assert normalize(instance.fetch_page({}, lambda: None).records[0]).event_time == START + timedelta(hours=1)


def test_bitget_stalled_short_page_is_not_treated_as_end_of_window(monkeypatch):
    instance = collector("bitget")
    mocked(monkeypatch, instance, [envelope("bitget", [fill("bitget", tradeId="100")])])
    cursor = instance._state({})
    cursor["token"] = "100"
    with pytest.raises(HistoryFetchError, match="cursor_stalled"):
        instance.fetch_page(cursor, lambda: None)


def test_binance_offset_stall_does_not_loop_forever(monkeypatch):
    instance = collector()
    rows = [funding("binance", id=str(i)) for i in range(100)]
    calls = mocked(monkeypatch, instance, [rows, rows])
    page = instance.fetch_page(funding_cursor(instance), lambda: None)
    original = deepcopy(page.cursor)
    with pytest.raises(HistoryFetchError, match="cursor_stalled"):
        instance.fetch_page(page.cursor, lambda: None)
    assert page.cursor == original
    assert [call[1]["offset"] for call in calls] == ["0", "100"]


@pytest.mark.parametrize("provider", SYMBOLS)
def test_conflicting_same_page_identity_blocks_the_whole_page(monkeypatch, provider):
    instance = collector(provider)
    item = fill(provider)
    changed = deepcopy(item)
    changed["qty" if provider == "binance" else "size"] = "0.2"
    mocked(monkeypatch, instance, [envelope(provider, [item, changed])])
    with pytest.raises(HistoryFetchError, match="record_conflict"):
        instance.fetch_page({}, lambda: None)


@pytest.mark.parametrize("provider", SYMBOLS)
def test_transport_error_keeps_durable_checkpoint(monkeypatch, provider):
    instance = collector(provider)
    mocked(monkeypatch, instance, [])
    def timeout(*args):
        raise RuntimeError("cex_request_timeout")
    if provider == "pionex":
        monkeypatch.setattr(instance, "_pionex_get", timeout)
    else:
        monkeypatch.setattr(instance.service, "_" + provider + "_get", timeout)
    cursor = instance._state({})
    original = deepcopy(cursor)
    with pytest.raises(RuntimeError, match="cex_request_timeout"):
        instance.fetch_page(cursor, lambda: None)
    assert cursor == original


def test_optional_symbol_filters_never_apply_to_funding(monkeypatch):
    instance = collector("bitget", symbols=("BTCUSDT", "ETHUSDT"))
    calls = mocked(monkeypatch, instance, [envelope("bitget", []), envelope("bitget", []), envelope("bitget", [])])
    first = instance.fetch_page({}, lambda: None)
    second = instance.fetch_page(first.cursor, lambda: None)
    third = instance.fetch_page(second.cursor, lambda: None)
    assert [call[1].get("symbol") for call in calls] == ["BTCUSDT", "ETHUSDT", None]
    assert not third.done


@pytest.mark.parametrize("provider", ["binance", "bitget"])
def test_funding_unknown_status_or_direction_blocks(monkeypatch, provider):
    instance = collector(provider)
    item = funding(provider, status="unknown")
    mocked(monkeypatch, instance, [envelope(provider, [item])])
    with pytest.raises(HistoryFetchError, match="status_unknown"):
        instance.fetch_page(funding_cursor(instance), lambda: None)


def test_market_scoped_fill_id_cannot_collide_across_pairs(monkeypatch):
    instance = collector("pionex", symbols=("BTC_USDT", "ETH_USDT"))
    mocked(monkeypatch, instance, [envelope("pionex", [fill("pionex")]),
                                 envelope("pionex", [fill("pionex", symbol="ETH_USDT")])])
    first = instance.fetch_page({}, lambda: None)
    second = instance.fetch_page(first.cursor, lambda: None)
    assert first.records[0].identity != second.records[0].identity
    assert normalize(second.records[0]).asset == "ETH"


def test_parent_financial_digest_excludes_endpoint_provenance(monkeypatch):
    instance = collector("coinbase")
    mocked(monkeypatch, instance, [envelope("coinbase", [fill("coinbase")], requestTime=123)])
    record = instance.fetch_page({}, lambda: None).records[0]
    assert record.raw["payload"] == fill("coinbase")
    assert "requestTime" not in record.raw
    assert "cursor" not in record.raw
    assert "My Spot" in record.identity
    assert "conn-one" not in record.identity


def central_transport_mock(monkeypatch, response_for, attempts_for):
    import steuerreport_v2.domain.external_http as external
    monkeypatch.setattr(CexBalanceService, "_get_json", REAL_GET_JSON)
    monkeypatch.setattr(CexBalanceService, "_credentials", lambda self, provider: ("key", "secret", "pass"))
    sent = []
    class Client:
        def get(self, url, headers):
            request = httpx.Request("GET", url, headers=headers)
            for _ in range(attempts_for(url)):
                # ManagedTransport invokes the current signer inside lease.start(prepare=...).
                external._signer.get()(request)
                sent.append(request.url.path)
            return httpx.Response(200, json=response_for(url), request=request)
    @contextmanager
    def managed(**kwargs):
        yield Client()
    monkeypatch.setattr(external, "managed_client", managed)
    return sent


@pytest.mark.parametrize("attempts", [1, 3, 5, 6])
def test_central_retry_signers_check_every_attempt_and_cap_at_five(monkeypatch, attempts):
    instance = collector("coinbase")
    # JWT generation is not part of this no-key test.
    monkeypatch.setattr(instance.service, "_coinbase_jwt", lambda *args: "mock-jwt")
    sent = central_transport_mock(monkeypatch, lambda url: envelope("coinbase", []), lambda url: attempts)
    checks = []
    cursor = {}
    if attempts > 5:
        with pytest.raises(HistoryFetchError, match="page_request_budget") as error:
            instance.fetch_page(cursor, lambda: checks.append("check"))
        assert error.value.resumable and len(sent) == 5 and cursor == {}
    else:
        page = instance.fetch_page(cursor, lambda: checks.append("check"))
        assert page.requests == attempts == len(sent)
    assert len(checks) == attempts + 1  # helper call plus every transport prepare


def test_central_retry_budget_is_shared_by_financial_and_metadata_calls(monkeypatch):
    instance = collector()
    sent = central_transport_mock(monkeypatch,
        lambda url: {"symbols": [{"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT"}]}
        if "exchangeInfo" in url else [fill("binance")],
        lambda url: 3)
    with pytest.raises(HistoryFetchError, match="page_request_budget"):
        instance.fetch_page({}, lambda: None)
    assert len(sent) == 5
    assert sent.count("/api/v3/myTrades") == 3 and sent.count("/api/v3/exchangeInfo") == 2


def test_cancellation_is_checked_inside_retry_not_only_before_helper(monkeypatch):
    instance = collector("pionex")
    sent = central_transport_mock(monkeypatch, lambda url: envelope("pionex", []), lambda url: 3)
    checks = 0
    def check():
        nonlocal checks
        checks += 1
        if checks == 3:
            raise RuntimeError("cancelled-between-retries")
    with pytest.raises(RuntimeError, match="cancelled-between-retries"):
        instance.fetch_page({}, check)
    assert len(sent) == 1


@pytest.mark.parametrize("provider", ["binance", "bitget", "pionex"])
def test_millisecond_timestamps_and_window_boundaries_do_not_round(monkeypatch, provider):
    instance = collector(provider)
    timestamp = instance.end - 1
    key = {"binance": "time", "bitget": "cTime", "pionex": "timestamp"}[provider]
    mocked(monkeypatch, instance, [envelope(provider, [fill(provider, **{key: timestamp})])])
    event = normalize(instance.fetch_page({}, lambda: None).records[0])
    assert event.event_time == instance.options.end


def test_legacy_only_when_explicitly_resolved_and_exact_provider_account(monkeypatch):
    import steuerreport_v2.domain.cex_balances as balances
    base = collector(account="binance")
    target = replace(base.target, connection_id=None, legacy_credentials=True)
    instance = CexHistoryCollector(object(), target, base.options)
    calls = mocked(monkeypatch, instance, [[]])
    monkeypatch.setattr(CexBalanceService, "_credentials", REAL_CREDENTIALS)
    resolved = []
    def secret(store, name):
        resolved.append(name)
        return {"secret.cex.binance.api_key": "legacy-key", "secret.cex.binance.api_secret": "legacy-secret"}.get(name, "")
    monkeypatch.setattr(balances, "resolve_secret_value", secret)
    page = instance.fetch_page({}, lambda: None)
    assert len(calls) == page.requests == 1
    assert resolved == ["secret.cex.binance.api_key", "secret.cex.binance.api_secret", "secret.cex.binance.passphrase"]
    assert instance.service.connection_id is None


@pytest.mark.parametrize("account,connection,flag", [
    ("binance", None, False), ("BINANCE", None, True), ("Other", None, True),
    ("connection:uuid", None, True), ("binance", "", True), ("binance", " ", True),
])
def test_legacy_exception_does_not_widen_account_or_empty_connection(account, connection, flag):
    base = collector()
    with pytest.raises(HistoryFetchError, match="connection_required"):
        CexHistoryCollector(object(), replace(base.target, account=account, connection_id=connection,
                                             legacy_credentials=flag), base.options)


def test_legacy_flag_never_overrides_explicit_connection_failure(monkeypatch):
    import steuerreport_v2.domain.cex_balances as balances
    import steuerreport_v2.domain.connections as connections
    base = collector(account="binance", connection="missing")
    instance = CexHistoryCollector(object(), replace(base.target, legacy_credentials=True), base.options)
    monkeypatch.setattr(CexBalanceService, "_credentials", REAL_CREDENTIALS)
    def missing(*args):
        raise RuntimeError("connection_not_found")
    monkeypatch.setattr(connections.ConnectionService, "credentials", missing)
    monkeypatch.setattr(balances, "resolve_secret_value", lambda *args: pytest.fail("No explicit-connection fallback"))
    with pytest.raises(RuntimeError, match="connection_not_found"):
        instance.fetch_page({}, lambda: None)


def test_bitget_old_fill_start_clamped_but_funding_start_preserved(monkeypatch):
    from steuerreport_v2.domain.history_cex import _millis
    base = collector("bitget", symbols=("BTCUSDT", "ETHUSDT"))
    old_start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    cutoff = _millis(START - timedelta(days=89))
    monkeypatch.setattr("steuerreport_v2.domain.history_cex._bitget_retention_floor", lambda: cutoff)
    instance = CexHistoryCollector(object(), base.target, replace(base.options, start=old_start))
    calls = mocked(monkeypatch, instance, [envelope("bitget", [])] * 12)
    state = {}
    for _ in range(12):
        page = instance.fetch_page(state, lambda: None)
        state = json.loads(json.dumps(page.cursor))
        assert state["fill_start"] == cutoff
        assert any("Abdeckungsluecke" in note for note in page.notes)
        if calls[-1][0].endswith("deposit-records"):
            break
    else:
        pytest.fail("Retained fills should need only a few windows")
    fill_calls = [call for call in calls if call[0].endswith("/fills")]
    assert min(int(call[1]["startTime"]) for call in fill_calls) == cutoff
    assert calls[-1][1]["startTime"] == str(_millis(old_start))
    assert not page.complete_history_proven


def test_bitget_retention_checkpoint_does_not_drift_on_resume(monkeypatch):
    from steuerreport_v2.domain.history_cex import _millis
    base = collector("bitget")
    instance = CexHistoryCollector(object(), base.target, replace(base.options, start=START - timedelta(days=365)))
    original_cutoff = _millis(START - timedelta(days=30))
    assert instance._state({})["fill_start"] == original_cutoff
    calls = mocked(monkeypatch, instance, [envelope("bitget", [])])
    page = instance.fetch_page({}, lambda: None)
    monkeypatch.setattr("steuerreport_v2.domain.history_cex._bitget_retention_floor", lambda: original_cutoff + 60000)
    restored = CexHistoryCollector(object(), base.target, instance.options)
    assert restored._state(json.loads(json.dumps(page.cursor)))["fill_start"] == original_cutoff
    assert int(calls[0][1]["startTime"]) == original_cutoff


def test_bitget_wholly_expired_fills_are_skipped_not_requested(monkeypatch):
    from steuerreport_v2.domain.history_cex import _millis
    base = collector("bitget")
    old_start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    instance = CexHistoryCollector(object(), base.target,
        replace(base.options, start=old_start, end=old_start + timedelta(days=1)))
    calls = mocked(monkeypatch, instance, [envelope("bitget", [])])
    page = instance.fetch_page({}, lambda: None)
    assert calls[0][0].endswith("deposit-records")
    assert calls[0][1]["startTime"] == str(_millis(old_start))
    assert any("Abdeckungsluecke" in note for note in page.notes)
    assert not page.complete_history_proven


def test_pionex_sparse_long_history_needs_one_request_not_daily_empty_calls(monkeypatch):
    from steuerreport_v2.domain.history_cex import _millis
    base = collector("pionex")
    beginning = datetime(2009, 1, 1, tzinfo=timezone.utc)
    instance = CexHistoryCollector(object(), base.target, replace(base.options, start=beginning))
    calls = mocked(monkeypatch, instance, [envelope("pionex", [fill("pionex")])])
    page = instance.fetch_page({}, lambda: None)
    assert page.done and len(page.records) == 1 and len(calls) == 1
    assert calls[0][1]["startTime"] == str(_millis(beginning))
    assert calls[0][1]["endTime"] == str(instance.end - 1)
    assert not page.complete_history_proven


@pytest.mark.parametrize("provider,status", [("binance", 3), ("binance", 4),
                                            ("bitget", "fail"), ("bitget", "pending")])
def test_failed_pending_withdrawals_stay_raw_only_without_classification_event(monkeypatch, provider, status):
    instance = collector(provider)
    item = funding(provider, False, status=status)
    mocked(monkeypatch, instance, [envelope(provider, [item])])
    record = instance.fetch_page(funding_cursor(instance, False), lambda: None).records[0]
    assert record.rows == [] and record.raw["payload"] == item


@pytest.mark.parametrize("provider", SYMBOLS)
def test_zero_microsecond_start_is_supported(monkeypatch, provider):
    base = collector(provider)
    instance = CexHistoryCollector(object(), base.target, replace(base.options, start=START.replace(microsecond=0)))
    mocked(monkeypatch, instance, [envelope(provider, [])])
    assert instance.fetch_page({}, lambda: None).requests == 1


def test_binance_credited_but_restricted_deposit_requires_classification(monkeypatch):
    instance = collector()
    item = funding("binance", status=6)
    mocked(monkeypatch, instance, [[item]])
    record = instance.fetch_page(funding_cursor(instance), lambda: None).records[0]
    event = normalize(record)
    assert event.event_type == "unknown" and event.quantity == 0
    assert event.asset == "USDT" and event.fee_quantity is None
    assert record.rows[0]["history_classification_required"] == "1"
    assert record.raw["payload"] == item
