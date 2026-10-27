"""Synthetische RPC-Seiten: keine echten Wallets, Secrets oder Netzwerkaufrufe."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from steuerreport_v2.domain.history_solana import SolanaHistoryCollector
from steuerreport_v2.domain.history_types import HistoryFetchError, HistoryOptions, HistoryTarget
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.request_limits import RequestCancelled


def base58(number, size=32):
    data = number.to_bytes(size, "big")
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    text = ""
    while number:
        number, remainder = divmod(number, 58)
        text = alphabet[remainder] + text
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + text


WALLET, TOKEN, TOKEN_2022, MINT, OTHER = [base58(100_000 + i) for i in range(1, 6)]
PROGRAM, PROGRAM_2022 = PortfolioService.SOLANA_TOKEN_PROGRAM_IDS
TIME = 1735689600
TARGET = HistoryTarget("wallet:synthetic", "Testwallet", "solana", "synthetic-account", WALLET)
OPTIONS = HistoryOptions(
    datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 1, 2, tzinfo=timezone.utc),
    public_rpc_only=True,
)


def signature(number):
    return base58(number, 64)


def signature_info(number, **kwargs):
    return {"signature": signature(number), "blockTime": TIME, "err": None,
            "confirmationStatus": "finalized", **kwargs}


def owner_account(address=TOKEN, *, owner=WALLET, mint=MINT, program=PROGRAM):
    return {
        "pubkey": address,
        "account": {"owner": program, "executable": False, "data": {
            "program": "spl-token", "parsed": {"type": "account", "info": {
                "owner": owner, "mint": mint, "tokenAmount": {"amount": "1", "decimals": 0},
            }},
        }},
    }


def transaction(number=1, *, timestamp=TIME, failed=False, fee=5000, token=False,
                payer=WALLET, owner=WALLET, mint=MINT):
    keys = [payer, TOKEN]
    return {
        "blockTime": timestamp, "slot": 1,
        "transaction": {"signatures": [signature(number)], "message": {
            "accountKeys": [{"pubkey": key} for key in keys],
        }},
        "meta": {
            "err": {"InstructionError": [0, "Custom"]} if failed else None,
            "fee": fee, "preBalances": [2_000_000_000, 2_039_280],
            "postBalances": [2_000_000_000 - fee, 2_039_280],
            "preTokenBalances": [],
            "postTokenBalances": [{"accountIndex": 1, "owner": owner, "mint": mint,
                                   "uiTokenAmount": {"amount": "42", "decimals": 0}}] if token else [],
        },
    }


class NoStore:
    def __getattr__(self, name):
        raise AssertionError("Collector must not read or write store: " + name)


@pytest.fixture
def collector(monkeypatch):
    monkeypatch.setattr(PortfolioService, "_solana_history_mint_symbols", lambda self: {MINT: "TEST"})
    for method in ("_solana_wallet_history_direct", "import_jup_wallet_history"):
        def forbidden(*args, **kwargs):
            pytest.fail("Whole legacy importer called")
        monkeypatch.setattr(PortfolioService, method, forbidden)
    return SolanaHistoryCollector(NoStore(), TARGET, OPTIONS)


def install_rpc(monkeypatch, collector, *, pages=None, txs=None, owners=None):
    pages, txs, owners = pages or {}, txs or {}, owners or {}
    calls = []
    def rpc(method, params, timeout_seconds):
        calls.append((method, deepcopy(params)))
        assert timeout_seconds == 30
        if method == "getTokenAccountsByOwner":
            assert params[0] == WALLET
            return {"context": {"slot": 1}, "value": deepcopy(owners.get(params[1]["programId"], []))}
        if method == "getSignaturesForAddress":
            assert params[1]["limit"] == 25
            return deepcopy(pages.get((params[0], params[1].get("before")), []))
        assert method == "getTransaction"
        value = txs[params[0]]
        if isinstance(value, Exception):
            raise value
        return deepcopy(value)
    monkeypatch.setattr(collector, "_solana_rpc", rpc)
    return calls


def roundtrip(cursor):
    return json.loads(json.dumps(cursor))


def test_multiple_signature_pages_and_more_than_five_pending_survive_restart(collector, monkeypatch):
    pages = {
        (WALLET, None): [signature_info(n) for n in range(1, 26)],
        (WALLET, signature(25)): [signature_info(n) for n in range(26, 33)],
    }
    txs = {signature(n): transaction(n) for n in range(1, 33)}
    cursor, all_records, all_calls = {}, [], []
    for iteration in range(20):
        restarted = SolanaHistoryCollector(NoStore(), TARGET, OPTIONS)
        calls = install_rpc(monkeypatch, restarted, pages=pages, txs=txs)
        previous = deepcopy(cursor)
        page = restarted.fetch_page(cursor, lambda: None)
        assert cursor == previous
        assert len([call for call in calls if call[0] == "getTransaction"]) <= 5
        assert len([call for call in calls if call[0] == "getSignaturesForAddress"]) <= 1
        assert page.requests == len(calls)
        assert page.complete_history_proven is False
        all_records.extend(page.records)
        all_calls.extend(calls)
        cursor = roundtrip(page.cursor)
        if iteration == 0:
            assert len(cursor["pending"]) == 20
            assert cursor["pending"][0]["signature"] == signature(6)
            assert cursor["before"] is None
            assert cursor["scan_index"] == 0
        if iteration == 1:
            assert [call[0] for call in calls] == ["getTransaction"] * 5
        if iteration == 4:
            assert not cursor["pending"] and cursor["before"] == signature(25)
        if page.done:
            break
    else:
        pytest.fail("Collector never reached the explicit empty RPC page")
    assert [record.identity for record in all_records] == ["solana:" + signature(n) for n in range(1, 33)]
    assert len([call for call in all_calls if call[0] == "getTokenAccountsByOwner"]) == 2
    assert [(params[0], params[1].get("before")) for method, params in all_calls
            if method == "getSignaturesForAddress"] == [(WALLET, None), (WALLET, signature(25)), (WALLET, signature(32))]
    done = restarted.fetch_page(cursor, lambda: None)
    assert done.done and done.requests == 0 and done.records == [] and done.cursor == cursor


def test_owner_discovery_both_programs_and_cross_address_dedup(collector, monkeypatch):
    owners = {PROGRAM: [owner_account()], PROGRAM_2022: [owner_account(TOKEN_2022, program=PROGRAM_2022)]}
    pages = {(WALLET, None): [signature_info(1)],
             (TOKEN, None): [signature_info(1), signature_info(2)],
             (TOKEN_2022, None): [signature_info(2), signature_info(3)]}
    txs = {signature(1): transaction(), signature(2): transaction(2, token=True, payer=OTHER),
           signature(3): transaction(3, token=True, owner=OTHER, payer=OTHER)}
    calls = install_rpc(monkeypatch, collector, owners=owners, pages=pages, txs=txs)
    cursor, records = {}, []
    for _ in range(10):
        page = collector.fetch_page(cursor, lambda: None)
        cursor = roundtrip(page.cursor)
        records.extend(page.records)
        if page.done:
            break
    assert page.done
    assert len(records) == 3
    assert [params[0] for method, params in calls if method == "getTransaction"] == [signature(n) for n in (1, 2, 3)]
    assert {params[0] for method, params in calls if method == "getSignaturesForAddress"} == {WALLET, TOKEN, TOKEN_2022}
    assert [params[1]["programId"] for method, params in calls if method == "getTokenAccountsByOwner"] == [PROGRAM, PROGRAM_2022]
    assert [(row["asset"], row["quantity"], row["wallet_address"]) for row in records[1].rows] == [("TEST", "42", WALLET)]
    assert records[1].raw["address_evidence"]["owner_account"] == owners[PROGRAM][0]
    assert records[1].raw["transaction"] == txs[signature(2)]
    assert records[2].rows == []  # Kein Uebernehmen einer fremden Meta-Ownership.
    assert all(record.source == "solana_rpc" and record.raw["source_ref"] == TARGET.source_ref for record in records)
    assert "geschlossene" in " ".join(page.notes) and not page.complete_history_proven


@pytest.mark.parametrize("field,value", [
    ("owner", OTHER), ("owner", WALLET.upper()), ("owner", None),
    ("mint", None), ("mint", "not-a-mint"), ("mint", " " + MINT),
    ("pubkey", "not-an-address"), ("pubkey", WALLET),
    ("program", PROGRAM_2022), ("type", "mint"),
])
def test_discovery_rejects_unverified_account_without_scanning(collector, monkeypatch, field, value):
    entry = owner_account()
    if field == "pubkey":
        entry["pubkey"] = value
    elif field == "program":
        entry["account"]["owner"] = value
    elif field == "type":
        entry["account"]["data"]["parsed"]["type"] = value
    else:
        entry["account"]["data"]["parsed"]["info"][field] = value
    calls = install_rpc(monkeypatch, collector, owners={PROGRAM: [entry]})
    cursor = {}
    with pytest.raises(HistoryFetchError, match="solana_owner_accounts_invalid"):
        collector.fetch_page(cursor, lambda: None)
    assert cursor == {} and [call[0] for call in calls] == ["getTokenAccountsByOwner"]


def test_discovery_guard_fails_instead_of_silently_truncating(collector, monkeypatch):
    monkeypatch.setattr(collector, "MAX_ADDRESSES", 2)
    calls = install_rpc(monkeypatch, collector, owners={PROGRAM: [owner_account(), owner_account(TOKEN_2022)]})
    with pytest.raises(HistoryFetchError, match="solana_address_limit") as exc:
        collector.fetch_page({}, lambda: None)
    assert not exc.value.resumable
    assert all(call[0] == "getTokenAccountsByOwner" for call in calls)


@pytest.mark.parametrize("missing", [None, {}, {"blockTime": None},
    {**transaction(7), "meta": None},
    {**transaction(7), "meta": {**transaction(7)["meta"], "postBalances": []}},
    RuntimeError("https://provider.invalid/?api-key=secret-from-provider"),
])
def test_missing_or_incomplete_detail_resume_is_atomic(collector, monkeypatch, missing):
    txs = {signature(n): transaction(n) for n in range(1, 9)}
    pages = {(WALLET, None): [signature_info(n) for n in range(1, 9)]}
    install_rpc(monkeypatch, collector, pages=pages, txs=txs)
    first = collector.fetch_page({}, lambda: None)
    cursor = roundtrip(first.cursor)
    before = deepcopy(cursor)
    txs[signature(7)] = missing
    calls = install_rpc(monkeypatch, collector, pages=pages, txs=txs)
    with pytest.raises(HistoryFetchError) as exc:
        collector.fetch_page(cursor, lambda: None)
    assert exc.value.code in {"solana_transaction_missing", "solana_transaction_incomplete", "solana_transaction_fetch_failed"}
    assert "secret" not in str(exc.value) and exc.value.__cause__ is None
    assert cursor == before
    assert [params[0] for method, params in calls] == [signature(6), signature(7)]
    txs[signature(7)] = transaction(7)
    resumed = SolanaHistoryCollector(NoStore(), TARGET, OPTIONS)
    install_rpc(monkeypatch, resumed, pages=pages, txs=txs)
    retry = resumed.fetch_page(cursor, lambda: None)
    assert [record.identity for record in retry.records] == ["solana:" + signature(n) for n in (6, 7, 8)]
    assert retry.cursor["before"] == signature(8) and retry.cursor["pending"] == []


def test_raw_evidence_preserves_success_null_status_failed_and_no_effect_transactions(collector, monkeypatch):
    txs = {signature(1): transaction(fee=0), signature(2): transaction(2, failed=True),
           signature(3): transaction(3, failed=True, payer=OTHER)}
    install_rpc(monkeypatch, collector, pages={(WALLET, None): [signature_info(n) for n in (1, 2, 3)]}, txs=txs)
    page = collector.fetch_page({}, lambda: None)
    assert [len(record.rows) for record in page.records] == [0, 1, 0]
    assert page.records[1].rows[0]["event_type"] == "network_fee"
    for number, record in enumerate(page.records, 1):
        assert record.raw["transaction"] == txs[signature(number)]
    assert page.records[0].raw["transaction"]["meta"]["err"] is None
    assert page.records[0].raw["signature_info"]["err"] is None


def test_public_only_url_selection_never_resolves_paid_keys_profile_or_env(collector, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Secret/profile URL resolver reached in public-only mode")
    monkeypatch.setattr(PortfolioService, "_solana_rpc_urls", forbidden)
    monkeypatch.setattr(PortfolioService, "_alchemy_api_key", forbidden)
    monkeypatch.setattr("steuerreport_v2.domain.portfolio.resolve_secret_value", forbidden)
    monkeypatch.setenv("SOLANA_RPC_URL", "https://paid.invalid/?api-key=secret")
    monkeypatch.setenv("SOLANA_RPC_URLS", "https://paid.invalid/second")
    monkeypatch.setattr(PortfolioService, "SOLANA_RPC_URLS", ["https://profile-secret.invalid/"])
    assert collector._solana_rpc_urls() == ["https://api.mainnet.solana.com"]
    calls = install_rpc(monkeypatch, collector)
    def asserting_rpc(method, params, timeout_seconds):
        assert collector._solana_rpc_urls() == ["https://api.mainnet.solana.com"]
        return {"value": []} if method == "getTokenAccountsByOwner" else []
    monkeypatch.setattr(collector, "_solana_rpc", asserting_rpc)
    assert collector.fetch_page({}, lambda: None).done
    assert not calls


def test_non_public_mode_delegates_url_selection(monkeypatch):
    monkeypatch.setattr(PortfolioService, "_solana_rpc_urls", lambda self: ["https://configured.invalid/"])
    collector = SolanaHistoryCollector(NoStore(), TARGET, replace(OPTIONS, public_rpc_only=False))
    assert collector._solana_rpc_urls() == ["https://configured.invalid/"]


def test_utc_date_bounds_are_inclusive_details_authoritative_and_all_reads_finalized(collector, monkeypatch):
    local = timezone(timedelta(hours=2))
    options = replace(OPTIONS, start=datetime(2025, 1, 1, 2, tzinfo=local), end=datetime(2025, 1, 1, 2, 0, 2, tzinfo=local))
    collector = SolanaHistoryCollector(NoStore(), TARGET, options)
    timestamps = [TIME - 1, TIME, TIME + 1, TIME + 2, TIME + 3]
    txs = {signature(n): transaction(n, timestamp=value) for n, value in enumerate(timestamps, 1)}
    calls = install_rpc(monkeypatch, collector, pages={(WALLET, None): [signature_info(n, blockTime=None) for n in range(1, 6)]}, txs=txs)
    page = collector.fetch_page({}, lambda: None)
    assert [record.identity for record in page.records] == ["solana:" + signature(n) for n in (2, 3, 4)]
    assert len([call for call in calls if call[0] == "getTransaction"]) == 5
    assert all(params[-1]["commitment"] == "finalized" for _, params in calls)
    assert all(params[-1]["encoding"] == "jsonParsed" and params[-1]["maxSupportedTransactionVersion"] == 0
               for method, params in calls if method == "getTransaction")
    assert page.cursor["before"] == signature(5)


@pytest.mark.parametrize("wallet", [None, "", " " + WALLET, "not-a-wallet"])
def test_explicit_exact_wallet_required_without_primary_profile_fallback(monkeypatch, wallet):
    monkeypatch.setattr(PortfolioService, "PRIMARY_SOLANA_WALLET", WALLET)
    with pytest.raises(HistoryFetchError, match="solana_wallet_address_required"):
        SolanaHistoryCollector(NoStore(), replace(TARGET, wallet_address=wallet), OPTIONS)


@pytest.mark.parametrize("start,end", [
    (datetime(2025, 1, 1), OPTIONS.end), (OPTIONS.end, OPTIONS.start),
    (OPTIONS.start, datetime(2025, 1, 2)),
])
def test_invalid_time_window_is_not_silently_normalized(start, end):
    with pytest.raises(HistoryFetchError, match="solana_time_window_invalid"):
        SolanaHistoryCollector(NoStore(), TARGET, replace(OPTIONS, start=start, end=end))


@pytest.mark.parametrize("payload", [None, {}, [None], [{}], [{"signature": ""}],
    [{"signature": " " + signature(1)}], [{"signature": "malformed"}],
    [{"signature": True}], [signature_info(1, blockTime=True)],
    [signature_info(1, confirmationStatus="confirmed")],
    [signature_info(1), signature_info(1)], [signature_info(n) for n in range(1, 27)],
])
def test_malformed_provider_signature_pages_fail_closed(collector, monkeypatch, payload):
    calls = install_rpc(monkeypatch, collector, pages={(WALLET, None): payload})
    cursor = {}
    with pytest.raises(HistoryFetchError):
        collector.fetch_page(cursor, lambda: None)
    assert cursor == {} and not any(call[0] == "getTransaction" for call in calls)


def test_repeated_before_signature_and_longer_cursor_cycles_fail_closed(collector, monkeypatch):
    pages = {(WALLET, None): [signature_info(1)], (WALLET, signature(1)): [signature_info(2)],
             (WALLET, signature(2)): [signature_info(1)]}
    txs = {signature(n): transaction(n) for n in (1, 2)}
    calls = install_rpc(monkeypatch, collector, pages=pages, txs=txs)
    first = collector.fetch_page({}, lambda: None)
    second = collector.fetch_page(first.cursor, lambda: None)
    cursor = roundtrip(second.cursor)
    before = deepcopy(cursor)
    with pytest.raises(HistoryFetchError, match="solana_signature_cursor_loop"):
        collector.fetch_page(cursor, lambda: None)
    assert cursor == before
    assert len([call for call in calls if call[0] == "getTransaction"]) == 2
    pages[(WALLET, signature(2))] = [signature_info(2)]
    with pytest.raises(HistoryFetchError, match="solana_signature_cursor_loop"):
        collector.fetch_page(cursor, lambda: None)


def test_check_runs_before_each_request_and_cancellation_does_not_commit_cursor(collector, monkeypatch):
    checks, calls = [], []
    def check():
        checks.append(len(calls))
        if len(calls) == 4:
            raise RequestCancelled("request_cancelled")
    def rpc(method, params, timeout_seconds):
        assert checks[-1] == len(calls)
        calls.append(method)
        if method == "getTokenAccountsByOwner":
            return {"value": []}
        if method == "getSignaturesForAddress":
            return [signature_info(1), signature_info(2)]
        return transaction()
    monkeypatch.setattr(collector, "_solana_rpc", rpc)
    cursor = {}
    with pytest.raises(RequestCancelled):
        collector.fetch_page(cursor, check)
    assert cursor == {} and calls == ["getTokenAccountsByOwner"] * 2 + ["getSignaturesForAddress", "getTransaction"]


def test_transport_cancellation_propagates_without_provider_error_wrapping(collector, monkeypatch):
    def rpc(*args, **kwargs):
        raise RequestCancelled("request_cancelled")
    monkeypatch.setattr(collector, "_solana_rpc", rpc)
    with pytest.raises(RequestCancelled):
        collector.fetch_page({}, lambda: None)


def test_incomplete_out_of_window_transaction_is_not_skipped(collector, monkeypatch):
    tx = transaction(timestamp=TIME - 1)
    del tx["meta"]["postBalances"]
    install_rpc(monkeypatch, collector, pages={(WALLET, None): [signature_info(1, blockTime=TIME - 1)]}, txs={signature(1): tx})
    with pytest.raises(HistoryFetchError, match="solana_transaction_incomplete"):
        collector.fetch_page({}, lambda: None)


def test_detail_signature_mismatch_is_not_adopted(collector, monkeypatch):
    install_rpc(monkeypatch, collector, pages={(WALLET, None): [signature_info(1)]}, txs={signature(1): transaction(2)})
    with pytest.raises(HistoryFetchError, match="solana_transaction_incomplete"):
        collector.fetch_page({}, lambda: None)


def test_mapper_failure_is_safe_and_does_not_commit_cursor(collector, monkeypatch):
    install_rpc(monkeypatch, collector, pages={(WALLET, None): [signature_info(1)]}, txs={signature(1): transaction()})
    def fail(*args):
        raise RuntimeError("mapper-provider-secret")
    monkeypatch.setattr(collector, "_solana_transaction_rows", fail)
    cursor = {}
    with pytest.raises(HistoryFetchError, match="^solana_transaction_incomplete$") as exc:
        collector.fetch_page(cursor, lambda: None)
    assert cursor == {} and exc.value.__cause__ is None


@pytest.mark.parametrize("symbols", [("TEST",), ("SOL",), ("TEST", "SOL"), ("*",)])
def test_solana_symbol_filters_are_rejected_before_any_rpc(monkeypatch, symbols):
    def forbidden(*args, **kwargs):
        pytest.fail("Unsupported symbol filter reached RPC")
    monkeypatch.setattr(SolanaHistoryCollector, "_solana_rpc", forbidden)
    with pytest.raises(HistoryFetchError, match="^solana_asset_filter_not_supported$") as exc:
        SolanaHistoryCollector(NoStore(), TARGET, replace(OPTIONS, symbols=symbols))
    assert exc.value.resumable is False


def test_all_swap_transfer_legs_and_network_fee_are_kept(collector, monkeypatch):
    other_mint = base58(100_006)
    monkeypatch.setattr(collector, "_solana_history_mint_symbols", lambda: {MINT: "OUT", other_mint: "IN"})
    tx = transaction(token=True)
    tx["transaction"]["message"]["accountKeys"].append({"pubkey": TOKEN_2022})
    tx["meta"]["preBalances"].append(2_039_280)
    tx["meta"]["postBalances"].append(2_039_280)
    tx["meta"]["postBalances"][0] -= 1_000_000_000
    outgoing = tx["meta"]["postTokenBalances"].pop()
    tx["meta"]["preTokenBalances"] = [outgoing]
    tx["meta"]["postTokenBalances"] = [
        {**outgoing, "uiTokenAmount": {"amount": "0", "decimals": 0}},
        {"accountIndex": 2, "owner": WALLET, "mint": other_mint,
         "uiTokenAmount": {"amount": "7", "decimals": 0}},
    ]
    install_rpc(monkeypatch, collector, pages={(WALLET, None): [signature_info(1)]}, txs={signature(1): tx})
    record, = collector.fetch_page({}, lambda: None).records
    assert len(record.rows) == 4
    assert {(row["event_type"], row["asset"], row["side"], row["quantity"]) for row in record.rows} == {
        ("sol_transfer", "SOL", "out", "1"),
        ("token_transfer", "OUT", "out", "42"),
        ("token_transfer", "IN", "in", "7"),
        ("network_fee", "SOL", "out", "0.000005"),
    }
    assert all(json.loads(row["raw_transaction"]) == tx for row in record.rows)
    assert record.raw["transaction"] == tx


def test_current_scan_provenance_can_change_without_changing_transaction_or_rows(collector, monkeypatch):
    tx = transaction(token=True)
    first_owner = owner_account()
    install_rpc(monkeypatch, collector, owners={PROGRAM: [first_owner]},
                pages={(TOKEN, None): [signature_info(1)]}, txs={signature(1): tx})
    empty_main = collector.fetch_page({}, lambda: None)
    first, = collector.fetch_page(empty_main.cursor, lambda: None).records

    changed_owner = deepcopy(first_owner)
    changed_owner["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"] = "999"
    install_rpc(monkeypatch, collector, owners={PROGRAM: [changed_owner]},
                pages={(TOKEN, None): [signature_info(1, memo="new scan metadata")]}, txs={signature(1): tx})
    changed_main = collector.fetch_page({}, lambda: None)
    changed, = collector.fetch_page(changed_main.cursor, lambda: None).records

    install_rpc(monkeypatch, collector, pages={(WALLET, None): [signature_info(1)]}, txs={signature(1): tx})
    direct, = collector.fetch_page({}, lambda: None).records
    assert first.raw["address_evidence"] != changed.raw["address_evidence"]
    assert first.raw["signature_info"] != changed.raw["signature_info"]
    assert first.raw["scan_address"] != direct.raw["scan_address"]
    assert first.raw != changed.raw and first.raw != direct.raw
    for record in (first, changed, direct):
        assert record.identity == "solana:" + signature(1)
        assert record.rows == first.rows
        assert record.raw["transaction"] == tx


def test_cursor_cannot_resume_for_other_wallet_window_or_public_mode(collector, monkeypatch):
    install_rpc(monkeypatch, collector)
    cursor = collector.fetch_page({}, lambda: None).cursor
    for target, options in [
        (replace(TARGET, wallet_address=OTHER), OPTIONS),
        (TARGET, replace(OPTIONS, end=OPTIONS.end + timedelta(seconds=1))),
        (TARGET, replace(OPTIONS, public_rpc_only=False)),
    ]:
        resumed = SolanaHistoryCollector(NoStore(), target, options)
        with pytest.raises(HistoryFetchError, match="solana_cursor_invalid"):
            resumed.fetch_page(cursor, lambda: None)


def test_corrupted_pending_cursor_fails_before_request(collector, monkeypatch):
    install_rpc(monkeypatch, collector, pages={(WALLET, None): [signature_info(n) for n in range(1, 7)]},
                txs={signature(n): transaction(n) for n in range(1, 7)})
    cursor = collector.fetch_page({}, lambda: None).cursor
    cursor["pending_before"] = signature(7)
    def forbidden(*args, **kwargs):
        pytest.fail("Corrupted cursor reached RPC")
    monkeypatch.setattr(collector, "_solana_rpc", forbidden)
    with pytest.raises(HistoryFetchError, match="solana_cursor_invalid"):
        collector.fetch_page(cursor, lambda: None)
