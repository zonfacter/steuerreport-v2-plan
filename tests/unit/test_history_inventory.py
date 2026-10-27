"""Nur lokale, synthetische Inventarbelege und Mock-RPC; keine Finanzimporte."""
from copy import deepcopy
from dataclasses import replace
import errno
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from steuerreport_v2.contracts.history import HistoryProgress
from steuerreport_v2.domain import history_inventory as inventory
from steuerreport_v2.domain.history_solana import SolanaHistoryCollector
from steuerreport_v2.domain.history_types import HistoryFetchError
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.request_limits import RequestCancelled, RequestDeadlineExceeded

from test_history_solana import (
    MINT, OPTIONS, PROGRAM, PROGRAM_2022, TARGET, TIME, TOKEN, TOKEN_2022, WALLET,
    owner_account, roundtrip, signature, signature_info, transaction,
)


class FileOnlyStore:
    def __init__(self, path):
        self.path = path

    def __getattr__(self, name):
        pytest.fail("Inventar darf keine Finanzdaten lesen/schreiben: " + name)


@pytest.fixture
def make_collector(tmp_path, monkeypatch):
    store = FileOnlyStore(tmp_path / "synthetic.duckdb")
    options = replace(OPTIONS, rpc_provider="public", inventory_job_id=str(uuid4()))
    monkeypatch.setattr(PortfolioService, "_solana_history_mint_symbols", lambda self: {MINT: "TEST"})

    def make(**changes):
        return SolanaHistoryCollector(store, TARGET, replace(options, **changes))
    return make


def mock_rpc(monkeypatch, collector, *, pages=None, txs=None, owners=None):
    pages, txs, owners = pages or {}, txs or {}, owners or {}
    calls = []

    def rpc(method, params, timeout_seconds):
        calls.append((method, deepcopy(params)))
        assert timeout_seconds == 30 and params[-1]["commitment"] == "finalized"
        if method == "getTokenAccountsByOwner":
            return {"value": deepcopy(owners.get(params[1]["programId"], []))}
        if method == "getSignaturesForAddress":
            expected = 1000 if collector.options.rpc_provider in ("helius", "alchemy") else 100
            assert params[1]["limit"] == expected
            return deepcopy(pages.get((params[0], params[1].get("before")), []))
        assert method == "getTransaction"
        value = txs[params[0]]
        if isinstance(value, Exception):
            raise value
        return deepcopy(value)

    monkeypatch.setattr(collector, "_solana_rpc", rpc)
    return calls


def discover(collector, cursor=None, check=lambda: None):
    cursor = cursor or {}
    for _ in range(100):
        page = collector.fetch_page(cursor, check)
        assert not page.records
        HistoryProgress.model_validate(page.extra["progress"])
        cursor = roundtrip(page.cursor)
        if cursor["inventory_complete"]:
            return page
    pytest.fail("Inventar nicht abgeschlossen")


def root(collector):
    return collector.store.path.parent / "source_history_previews" / str(collector.options.inventory_job_id) / "inventory"


def test_two_phases_unique_total_and_original_owner_provenance(make_collector, monkeypatch):
    collector = make_collector()
    owners = {PROGRAM: [owner_account()], PROGRAM_2022: [owner_account(TOKEN_2022, program=PROGRAM_2022)]}
    pages = {(WALLET, None): [signature_info(1)],
             (TOKEN, None): [signature_info(1), signature_info(2, memo="original")],
             (TOKEN_2022, None): [signature_info(2), signature_info(3)]}
    txs = {signature(n): transaction(n) for n in (1, 2, 3)}
    calls = mock_rpc(monkeypatch, collector, owners=owners, pages=pages, txs=txs)
    first = collector.fetch_page({}, lambda: None)
    assert first.extra["progress"] == {
        "phase": "discovery", "references_discovered": 1, "signatures_discovered": None,
        "signatures_total": None, "signatures_completed": 0, "addresses_completed": 0,
        "addresses_total": 3, "inventory_complete": False,
    }
    complete = discover(collector, first.cursor)
    assert not complete.done and complete.requests == 1
    assert complete.extra["progress"]["references_discovered"] == 5
    assert complete.extra["progress"]["signatures_total"] == 3
    assert complete.extra["progress"]["signatures_discovered"] == 3
    assert complete.extra["progress"]["addresses_completed"] == 3
    assert complete.extra["progress"]["phase"] == "discovery"
    assert not any(method == "getTransaction" for method, _ in calls)
    result = collector.fetch_page(complete.cursor, lambda: None)
    assert result.done and result.extra["progress"]["signatures_completed"] == 3
    assert [record.identity for record in result.records] == ["solana:" + signature(n) for n in (1, 2, 3)]
    assert [params[0] for method, params in calls if method == "getTransaction"] == [signature(n) for n in (1, 2, 3)]
    assert result.records[1].raw["signature_info"] == pages[(TOKEN, None)][1]
    assert result.records[1].raw["scan_address"] == TOKEN
    assert result.records[1].raw["address_evidence"]["owner_account"] == owners[PROGRAM][0]
    assert result.records[1].raw["transaction"] == txs[signature(2)]
    assert not result.complete_history_proven
    assert "geschlossene" in " ".join(result.notes)
    again = collector.fetch_page(roundtrip(result.cursor), lambda: None)
    assert again.done and again.requests == 0 and again.cursor == result.cursor and again.records == []


@pytest.mark.parametrize("provider,limit", [("public", 100), ("custom", 100), ("helius", 1000), ("alchemy", 1000)])
def test_documented_inventory_page_sizes_keep_legacy_constant(make_collector, monkeypatch, provider, limit):
    collector = make_collector(rpc_provider=provider, public_rpc_only=provider == "public")
    calls = mock_rpc(monkeypatch, collector)
    page = collector.fetch_page({}, lambda: None)
    assert page.done and page.extra["progress"]["signatures_total"] == 0
    assert calls[-1][1][1]["limit"] == limit
    assert SolanaHistoryCollector.PAGE_SIZE == 25


def test_restart_each_page_and_cross_chunk_fetch(make_collector, monkeypatch):
    monkeypatch.setattr(inventory, "DETAIL_CHUNK_SIZE", 2)
    pages = {(WALLET, None): [signature_info(n) for n in range(1, 8)]}
    txs = {signature(n): transaction(n) for n in range(1, 8)}
    cursor, records, all_calls = {}, [], []
    for _ in range(10):
        collector = make_collector()
        calls = mock_rpc(monkeypatch, collector, pages=pages, txs=txs)
        old = deepcopy(cursor)
        page = collector.fetch_page(cursor, lambda: None)
        assert cursor == old
        cursor = roundtrip(page.cursor)
        records.extend(page.records)
        all_calls.extend(calls)
        if page.done:
            break
    assert page.done and len(cursor["chunks"]) == 4
    assert [record.identity for record in records] == ["solana:" + signature(n) for n in range(1, 8)]
    assert sum(method == "getTokenAccountsByOwner" for method, _ in all_calls) == 2
    assert sum(method == "getTransaction" for method, _ in all_calls) == 7


def test_large_inventory_cursor_only_hashes_not_duplicate_signature_json(make_collector, monkeypatch):
    collector = make_collector(rpc_provider="helius", public_rpc_only=False)
    metadata = [signature_info(n, memo="original-metadata-" + "x" * 100) for n in range(1, 1001)]
    mock_rpc(monkeypatch, collector, pages={(WALLET, None): metadata})
    page = discover(collector)
    encoded = json.dumps(page.cursor)
    assert len(encoded) < 3000 and "original-metadata" not in encoded
    assert "items" not in encoded and "seen" not in encoded
    chunks = [json.loads((root(collector) / (digest + ".json")).read_text()) for digest in page.cursor["chunks"]]
    assert chunks[0]["entries"] == [[0, n] for n in range(1000)]
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in root(collector).iterdir())
    assert root(collector).stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("kind", ["owners", "signatures", "details"])
@pytest.mark.parametrize("restart", [False, True])
def test_cancel_after_file_append_does_not_make_orphan_a_dedupe_commit(make_collector, monkeypatch, kind, restart):
    collector = make_collector()
    pages = {(WALLET, None): [signature_info(1)]}
    txs = {signature(1): transaction()}
    mock_rpc(monkeypatch, collector, pages=pages, txs=txs)
    cursor = {}
    if kind == "details":
        cursor = collector.fetch_page({}, lambda: None).cursor
    old = deepcopy(cursor)
    original = inventory.InventoryFiles.write
    cancelled = False

    def write(self, value):
        nonlocal cancelled
        digest = original(self, value)
        if value["kind"] == kind:
            cancelled = True
        return digest

    def check():
        if cancelled:
            raise RequestCancelled("request_cancelled")

    monkeypatch.setattr(inventory.InventoryFiles, "write", write)
    with pytest.raises(RequestCancelled):
        collector.fetch_page(cursor, check)
    assert cursor == old
    assert list(root(collector).glob("*.json"))
    monkeypatch.setattr(inventory.InventoryFiles, "write", original)
    if restart:
        collector = make_collector()
    calls = mock_rpc(monkeypatch, collector, pages=pages, txs=txs)
    complete = discover(collector, cursor)
    assert complete.cursor["signatures_total"] == 1
    page = collector.fetch_page(complete.cursor, lambda: None)
    assert page.done and len(page.records) == 1
    assert sum(method == "getTransaction" for method, _ in calls) == 1


@pytest.mark.parametrize("error", [RequestCancelled, RequestDeadlineExceeded])
def test_interrupted_detail_page_is_repeatable_without_cursor_commit(make_collector, monkeypatch, error):
    collector = make_collector()
    pages = {(WALLET, None): [signature_info(n) for n in (1, 2)]}
    txs = {signature(n): transaction(n) for n in (1, 2)}
    mock_rpc(monkeypatch, collector, pages=pages, txs=txs)
    cursor = roundtrip(discover(collector).cursor)
    before = deepcopy(cursor)
    calls = mock_rpc(monkeypatch, collector, txs=txs)

    def check():
        if len(calls) == 2:
            raise error("synthetic_stop")

    with pytest.raises(error):
        collector.fetch_page(cursor, check)
    assert cursor == before
    collector = make_collector()
    calls = mock_rpc(monkeypatch, collector, txs=txs)
    page = collector.fetch_page(cursor, lambda: None)
    assert page.done and len(page.records) == 2 and len(calls) == 2


@pytest.mark.parametrize("tx", [None, {}, {"blockTime": None},
    {**transaction(2), "meta": None}, {**transaction(2), "transaction": {"signatures": [signature(7)]}},
    RuntimeError("https://provider.invalid/?api-key=secret")])
def test_bad_details_do_not_commit_prior_records_or_leak_provider_error(make_collector, monkeypatch, tx):
    collector = make_collector()
    pages = {(WALLET, None): [signature_info(n) for n in (1, 2, 3)]}
    txs = {signature(n): transaction(n) for n in (1, 2, 3)}
    mock_rpc(monkeypatch, collector, pages=pages)
    cursor = roundtrip(discover(collector).cursor)
    before = deepcopy(cursor)
    txs[signature(2)] = tx
    calls = mock_rpc(monkeypatch, collector, txs=txs)
    with pytest.raises(HistoryFetchError) as exc:
        collector.fetch_page(cursor, lambda: None)
    assert cursor == before and "secret" not in str(exc.value) and exc.value.__cause__ is None
    assert len(calls) == 2
    txs[signature(2)] = transaction(2)
    mock_rpc(monkeypatch, collector, txs=txs)
    assert len(collector.fetch_page(cursor, lambda: None).records) == 3


@pytest.mark.parametrize("field", ["owners", "pages", "chunks"])
@pytest.mark.parametrize("damage", ["tamper", "missing", "symlink", "permissions", "hardlink"])
def test_persisted_evidence_damage_fails_closed_before_rpc(make_collector, monkeypatch, tmp_path, field, damage):
    collector = make_collector()
    mock_rpc(monkeypatch, collector, pages={(WALLET, None): [signature_info(1)]})
    cursor = discover(collector).cursor
    digest = cursor[field] if field == "owners" else cursor[field][0]
    path = root(collector) / (digest + ".json")
    if damage == "tamper":
        path.write_bytes(b"{}")
    elif damage == "missing":
        path.unlink()
    elif damage == "symlink":
        other = tmp_path / "external.json"
        path.rename(other)
        path.symlink_to(other)
    elif damage == "permissions":
        path.chmod(0o644)
    else:
        (tmp_path / "hardlink.json").hardlink_to(path)
    collector = make_collector()
    calls = mock_rpc(monkeypatch, collector)
    with pytest.raises(HistoryFetchError) as exc:
        collector.fetch_page(cursor, lambda: None)
    assert not exc.value.resumable and not calls


@pytest.mark.parametrize("component", ["source_history_previews", "job", "inventory"])
def test_symlink_directory_is_never_followed(make_collector, monkeypatch, tmp_path, component):
    collector = make_collector()
    target = root(collector)
    path = target if component == "inventory" else target.parent if component == "job" else target.parent.parent
    path.parent.mkdir(parents=True, exist_ok=True)
    external = tmp_path / "outside"
    external.mkdir()
    path.symlink_to(external, target_is_directory=True)
    mock_rpc(monkeypatch, collector)
    with pytest.raises(HistoryFetchError):
        collector.fetch_page({}, lambda: None)
    assert list(external.iterdir()) == []


@pytest.mark.parametrize("updates", [
    {"signatures_total": 999}, {"references_discovered": 999}, {"signatures_completed": 1},
    {"fetch_page": 1}, {"fetch_offset": True}, {"scan_index": True},
    {"inventory_complete": False}, {"pages": []}, {"chunks": []}, {"version": 1},
])
def test_cursor_metadata_cannot_invent_totals_or_skip_details(make_collector, monkeypatch, updates):
    collector = make_collector()
    mock_rpc(monkeypatch, collector, pages={(WALLET, None): [signature_info(1)]})
    cursor = roundtrip(discover(collector).cursor)
    cursor.update(updates)
    calls = mock_rpc(monkeypatch, collector)
    with pytest.raises(HistoryFetchError):
        collector.fetch_page(cursor, lambda: None)
    assert not calls


def test_rehashed_chunk_cannot_omit_or_duplicate_unique_references(make_collector, monkeypatch):
    collector = make_collector()
    mock_rpc(monkeypatch, collector, pages={(WALLET, None): [signature_info(n) for n in (1, 2)]})
    cursor = discover(collector).cursor
    path = root(collector) / (cursor["chunks"][0] + ".json")
    chunk = json.loads(path.read_text())
    chunk["entries"] = [[0, 1], [0, 1]]
    digest = collector._history_inventory.files.write(chunk)
    cursor["chunks"] = [digest]
    collector = make_collector()
    calls = mock_rpc(monkeypatch, collector)
    with pytest.raises(HistoryFetchError):
        collector.fetch_page(cursor, lambda: None)
    assert not calls


@pytest.mark.parametrize("payload", [None, {}, [None], [signature_info(1), signature_info(1)],
    [signature_info(1, blockTime=True)], [signature_info(1, confirmationStatus=None)],
    [signature_info(1, slot=True)], [signature_info(1, memo={})], [signature_info(1, err=42)],
    [signature_info(n) for n in range(1, 102)]])
def test_invalid_signature_metadata_never_counts_as_inventory(make_collector, monkeypatch, payload):
    collector = make_collector()
    calls = mock_rpc(monkeypatch, collector, pages={(WALLET, None): payload})
    cursor = {}
    with pytest.raises(HistoryFetchError):
        collector.fetch_page(cursor, lambda: None)
    assert cursor == {} and not any(method == "getTransaction" for method, _ in calls)


def test_long_signature_cursor_loop_is_not_global_dedupe(make_collector, monkeypatch):
    collector = make_collector()
    pages = {(WALLET, None): [signature_info(1)], (WALLET, signature(1)): [signature_info(2)],
             (WALLET, signature(2)): [signature_info(1)]}
    calls = mock_rpc(monkeypatch, collector, pages=pages)
    first = collector.fetch_page({}, lambda: None)
    second = collector.fetch_page(first.cursor, lambda: None)
    with pytest.raises(HistoryFetchError, match="solana_signature_cursor_loop"):
        collector.fetch_page(second.cursor, lambda: None)
    assert not any(method == "getTransaction" for method, _ in calls)


@pytest.mark.parametrize("bound,value", [("MAX_REFERENCES", 1), ("MAX_PAGES", 1),
                                        ("MAX_FILE_BYTES", 100), ("MAX_BYTES", 100)])
def test_fixed_safety_limits_error_instead_of_truncating(make_collector, monkeypatch, bound, value):
    monkeypatch.setattr(inventory, bound, value)
    collector = make_collector()
    calls = mock_rpc(monkeypatch, collector, pages={(WALLET, None): [signature_info(1), signature_info(2)]})
    with pytest.raises(HistoryFetchError, match="solana_inventory_limit") as exc:
        discover(collector)
    assert not exc.value.resumable and not any(method == "getTransaction" for method, _ in calls)


def test_signature_time_null_or_outside_window_never_skips_detail_validation(make_collector, monkeypatch):
    collector = make_collector()
    pages = {(WALLET, None): [signature_info(1, blockTime=None), signature_info(2, blockTime=TIME - 100)]}
    mock_rpc(monkeypatch, collector, pages=pages)
    cursor = discover(collector).cursor
    bad = transaction(2, timestamp=TIME - 100)
    del bad["meta"]["postBalances"]
    calls = mock_rpc(monkeypatch, collector, txs={signature(1): transaction(), signature(2): bad})
    with pytest.raises(HistoryFetchError, match="solana_transaction_incomplete"):
        collector.fetch_page(cursor, lambda: None)
    assert len(calls) == 2
    calls = mock_rpc(monkeypatch, collector, txs={signature(1): transaction(), signature(2): transaction(2, timestamp=TIME - 100)})
    page = collector.fetch_page(cursor, lambda: None)
    assert page.done and len(page.records) == 1
    assert page.extra["progress"]["signatures_completed"] == 2
    assert page.extra["progress"]["signatures_total"] == 2 and len(calls) == 2


def test_rpc_pin_shared_by_urls_and_limiter_provider_never_serialized(make_collector, monkeypatch):
    from steuerreport_v2.domain import history_rpc
    collector = make_collector(rpc_provider="helius", public_rpc_only=False)
    endpoint = SimpleNamespace(url="https://private.invalid/?api-key=secret", provider_id="helius",
                               label="Test", kind="configured", binding_hash="private-binding")
    calls = []

    def resolve(store, choice):
        calls.append(choice)
        return endpoint

    monkeypatch.setattr(history_rpc, "resolve_rpc", resolve)
    monkeypatch.setattr(PortfolioService, "_solana_rpc_urls", lambda *_: pytest.fail("Legacy resolver called"))
    assert collector._solana_rpc_provider() == "helius"
    assert collector._solana_rpc_urls() == [endpoint.url]
    assert collector._solana_rpc_provider() == "helius" and calls == ["helius"]
    mock_rpc(monkeypatch, collector)
    page = collector.fetch_page({}, lambda: None)
    output = json.dumps({"cursor": page.cursor, "extra": page.extra})
    assert "secret" not in output and "private-binding" not in output and endpoint.url not in output
    assert all(b"secret" not in path.read_bytes() for path in root(collector).iterdir())


def test_no_inventory_job_id_uses_existing_inline_collector(make_collector, monkeypatch):
    collector = make_collector(inventory_job_id=None, rpc_provider=None)
    calls = []

    def rpc(method, params, timeout_seconds):
        calls.append(method)
        if method == "getTokenAccountsByOwner":
            return {"value": []}
        if method == "getSignaturesForAddress":
            assert params[1]["limit"] == 25
            return [signature_info(1)]
        return transaction()

    monkeypatch.setattr(collector, "_solana_rpc", rpc)
    page = collector.fetch_page({}, lambda: None)
    assert page.cursor["version"] == 1 and len(page.records) == 1
    assert calls == ["getTokenAccountsByOwner"] * 2 + ["getSignaturesForAddress", "getTransaction"]
    assert not (collector.store.path.parent / "source_history_previews").exists()
    assert "progress" not in page.extra
    monkeypatch.setattr(PortfolioService, "_solana_rpc_provider", lambda _: None)
    assert collector._solana_rpc_provider() is None


def test_invalid_uuid_cannot_escape_private_job_directory(make_collector, monkeypatch):
    collector = make_collector(inventory_job_id="../escape")
    calls = mock_rpc(monkeypatch, collector)
    with pytest.raises(HistoryFetchError, match="history_job_id_invalid"):
        collector.fetch_page({}, lambda: None)
    assert not calls


def test_discovery_transition_is_not_counted_as_active_detail_fetch_time(make_collector, monkeypatch):
    from steuerreport_v2.domain.history_progress import record_progress
    collector = make_collector()
    mock_rpc(monkeypatch, collector, pages={(WALLET, None): [signature_info(1)]})
    complete = discover(collector)
    job = {}
    record_progress(job, complete, 40)
    assert job["_progress"]["inventory_complete"] is True
    assert job["_progress"]["signatures_total"] == 1
    assert "_fetch_elapsed_seconds" not in job and "_detail_rate_ema" not in job
    mock_rpc(monkeypatch, collector, txs={signature(1): transaction()})
    fetched = collector.fetch_page(complete.cursor, lambda: None)
    record_progress(job, fetched, 2)
    assert job["_fetch_elapsed_seconds"] == 2
    assert job["_detail_rate_ema"] == 0.5 and job["_detail_samples"] == 1


@pytest.mark.parametrize("published", [False, True])
def test_crash_leftover_temporary_file_or_link_is_recoverable(make_collector, monkeypatch, published):
    collector = make_collector()
    pages = {(WALLET, None): [signature_info(1)]}
    mock_rpc(monkeypatch, collector, pages=pages)
    first = collector.fetch_page({}, lambda: None)
    pending = root(collector) / (".pending-" + uuid4().hex)
    if published:
        pending.hardlink_to(root(collector) / (first.cursor["pages"][0] + ".json"))
    else:
        pending.write_bytes(b'{"incomplete":')
        pending.chmod(0o600)
    collector = make_collector()
    mock_rpc(monkeypatch, collector, pages=pages, txs={signature(1): transaction()})
    complete = discover(collector, first.cursor)
    fetched = collector.fetch_page(complete.cursor, lambda: None)
    assert fetched.done and len(fetched.records) == 1 and not pending.exists()


def test_steady_collector_does_not_reparse_entire_manifest_on_each_detail_page(make_collector, monkeypatch):
    collector = make_collector()
    pages = {(WALLET, None): [signature_info(n) for n in range(1, 22)]}
    txs = {signature(n): transaction(n) for n in range(1, 22)}
    mock_rpc(monkeypatch, collector, pages=pages, txs=txs)
    complete = discover(collector)
    read = collector._history_inventory.files.read
    calls = []

    def counted(digest):
        calls.append(digest)
        return read(digest)

    monkeypatch.setattr(collector._history_inventory.files, "read", counted)
    monkeypatch.setattr(collector._history_inventory, "_signature_items",
                        lambda *_: pytest.fail("Hash-identische Rohseite erneut semantisch geprueft"))
    cursor = complete.cursor
    for _ in range(5):
        page = collector.fetch_page(cursor, lambda: None)
        cursor = roundtrip(page.cursor)
    assert page.done
    assert len(calls) == 15  # Pro Seite Owner-Beleg, aktiver Chunk und aktive Rohseite.


def test_semantic_hash_cache_still_rehashes_every_used_raw_page(make_collector, monkeypatch):
    collector = make_collector()
    mock_rpc(monkeypatch, collector, pages={(WALLET, None): [signature_info(1)]})
    complete = discover(collector)
    path = root(collector) / (complete.cursor["pages"][0] + ".json")
    path.write_bytes(b"{}")
    calls = mock_rpc(monkeypatch, collector)
    with pytest.raises(HistoryFetchError, match="solana_inventory_evidence_changed"):
        collector.fetch_page(complete.cursor, lambda: None)
    assert not calls


def test_ten_thousand_signature_scaling_reads_only_active_proofs(make_collector, monkeypatch, record_property):
    collector = make_collector(rpc_provider="helius", public_rpc_only=False)
    size = 10_000
    pages = {}
    for start in range(1, size + 1, 1000):
        pages[(WALLET, None if start == 1 else signature(start - 1))] = [
            signature_info(n) for n in range(start, start + 1000)
        ]
    txs = {signature(n): transaction(n) for n in range(1, size + 1)}
    calls = mock_rpc(monkeypatch, collector, pages=pages, txs=txs)
    started = time.monotonic()
    complete = discover(collector)
    discovery_seconds = time.monotonic() - started
    assert complete.cursor["signatures_total"] == size
    read = collector._history_inventory.files.read
    reads = 0

    def counted(digest):
        nonlocal reads
        reads += 1
        return read(digest)

    monkeypatch.setattr(collector._history_inventory.files, "read", counted)
    cursor, fetched = complete.cursor, 0
    started = time.monotonic()
    while True:
        page = collector.fetch_page(cursor, lambda: None)
        cursor = page.cursor
        fetched += len(page.records)
        if page.done:
            break
    fetch_seconds = time.monotonic() - started
    assert fetched == size and cursor["signatures_completed"] == size
    assert reads == 3 * (size // collector.DETAILS_PER_PAGE)
    assert sum(method == "getSignaturesForAddress" for method, _ in calls) == 11
    assert sum(method == "getTransaction" for method, _ in calls) == size
    assert len(json.dumps(cursor)) < 5000
    record_property("inventory_signatures", size)
    record_property("inventory_discovery_seconds", round(discovery_seconds, 3))
    record_property("inventory_fetch_seconds", round(fetch_seconds, 3))
    record_property("inventory_fetch_file_reads", reads)


@pytest.mark.parametrize("provider", ["public", "helius", "alchemy", "custom"])
def test_explicit_rpc_redaction_never_exposes_even_private_hostname(make_collector, monkeypatch, provider):
    collector = make_collector(rpc_provider=provider, public_rpc_only=provider == "public")
    monkeypatch.setattr(PortfolioService, "_redacted_solana_rpc_url",
                        lambda *_: pytest.fail("Explizite Auswahl darf Legacy-Hostnamen nicht offenlegen"))
    assert collector._redacted_solana_rpc_url("https://customer-secret.internal/private?key=secret") == "https://rpc.invalid/"


def test_legacy_rpc_redaction_delegates_unchanged(make_collector, monkeypatch):
    collector = make_collector(rpc_provider=None, inventory_job_id=None)
    url = "https://legacy.invalid/?key=secret"
    calls = []

    def redacted(self, value):
        calls.append(value)
        return "legacy-redaction"

    monkeypatch.setattr(PortfolioService, "_redacted_solana_rpc_url", redacted)
    assert collector._redacted_solana_rpc_url(url) == "legacy-redaction" and calls == [url]


@pytest.mark.parametrize("entry", [None, {}, owner_account(owner=TOKEN), owner_account(mint="invalid")])
def test_inventory_never_scans_unverified_owner_accounts(make_collector, monkeypatch, entry):
    collector = make_collector()
    calls = mock_rpc(monkeypatch, collector, owners={PROGRAM: [entry]})
    with pytest.raises(HistoryFetchError, match="solana_owner_accounts_invalid"):
        collector.fetch_page({}, lambda: None)
    assert [method for method, _ in calls] == ["getTokenAccountsByOwner"]
    assert not root(collector).exists()


@pytest.mark.parametrize("error", [RequestCancelled, RequestDeadlineExceeded])
def test_inventory_transport_stop_propagates_without_error_reclassification(make_collector, monkeypatch, error):
    collector = make_collector()

    def stopped(*args, **kwargs):
        raise error("synthetic_stop")

    monkeypatch.setattr(collector, "_solana_rpc", stopped)
    with pytest.raises(error):
        collector.fetch_page({}, lambda: None)


def test_inventory_scope_cannot_resume_for_different_window_or_provider(make_collector, monkeypatch):
    collector = make_collector()
    mock_rpc(monkeypatch, collector)
    cursor = collector.fetch_page({}, lambda: None).cursor
    for changes in ({"end": OPTIONS.start}, {"rpc_provider": "helius", "public_rpc_only": False}):
        changed = make_collector(**changes)
        calls = mock_rpc(monkeypatch, changed)
        with pytest.raises(HistoryFetchError, match="solana_cursor_invalid"):
            changed.fetch_page(cursor, lambda: None)
        assert not calls


@pytest.mark.parametrize("error_number", [errno.ENOSPC, errno.EMFILE])
@pytest.mark.parametrize("stage", ["directory", "temporary", "read", "file_fsync", "directory_fsync", "published_read"])
def test_resource_failures_are_resumable_and_retry_preserves_evidence(make_collector, monkeypatch, error_number, stage):
    collector = make_collector()
    files = inventory.InventoryFiles(collector.store, collector.options.inventory_job_id)
    original = {"test": "original"}
    updated = {"test": "updated"}
    digest = files.write(original)
    updated_digest = inventory.hashlib.sha256(inventory._encode(updated)).hexdigest()
    real_open, real_fsync = inventory.os.open, inventory.os.fsync

    def limited_open(path, *args, **kwargs):
        if (stage == "directory" and path == "/"
                or stage == "temporary" and str(path).startswith(".pending-")
                or stage == "read" and path == digest + ".json"
                or stage == "published_read" and path == updated_digest + ".json"):
            raise OSError(error_number, "private-storage-error")
        return real_open(path, *args, **kwargs)

    def limited_fsync(fd):
        directory = inventory.stat.S_ISDIR(inventory.os.fstat(fd).st_mode)
        if stage == ("directory_fsync" if directory else "file_fsync"):
            raise OSError(error_number, "private-storage-error")
        return real_fsync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(inventory.os, "open", limited_open)
        patch.setattr(inventory.os, "fsync", limited_fsync)
        with pytest.raises(HistoryFetchError, match="^solana_inventory_storage_unavailable$") as exc:
            if stage in {"directory", "read"}:
                files.read(digest)
            else:
                files.write(updated)
    assert exc.value.resumable and exc.value.__suppress_context__
    assert "private-storage-error" not in str(exc.value)
    assert files._usage is None
    assert files.read(digest) == original
    assert files.write(updated) == updated_digest
    assert files.read(updated_digest) == updated
    assert files._usage[0] == len(list(files.path.glob("*.json"))) == 2
    assert not list(files.path.glob(".pending-*"))


@pytest.mark.parametrize("error_number", [errno.EDQUOT, errno.ENFILE, errno.ENOMEM, errno.EAGAIN, errno.EINTR])
def test_other_resource_errors_from_opened_remain_resumable(make_collector, error_number):
    collector = make_collector()
    files = inventory.InventoryFiles(collector.store, collector.options.inventory_job_id)
    with pytest.raises(HistoryFetchError, match="solana_inventory_storage_unavailable") as exc:
        with files.opened():
            raise OSError(error_number, "private-storage-error")
    assert exc.value.resumable and files._usage is None


@pytest.mark.parametrize("error_number", [errno.ELOOP, errno.ENOTDIR, errno.EACCES, errno.ENOENT])
@pytest.mark.parametrize("stage", ["directory", "read"])
def test_integrity_and_path_errors_stay_permanent(make_collector, monkeypatch, error_number, stage):
    collector = make_collector()
    files = inventory.InventoryFiles(collector.store, collector.options.inventory_job_id)
    digest = files.write({"test": "original"})
    real_open = inventory.os.open

    def invalid_open(path, *args, **kwargs):
        if path == ("/" if stage == "directory" else digest + ".json"):
            raise OSError(error_number, "private-storage-error")
        return real_open(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(inventory.os, "open", invalid_open)
        with pytest.raises(HistoryFetchError) as exc:
            files.read(digest)
    assert not exc.value.resumable and exc.value.__suppress_context__
    expected = "solana_inventory_storage_invalid" if stage == "directory" else "solana_inventory_evidence_missing"
    assert exc.value.code == expected


def test_unchanged_manifest_cache_hit_skips_hash_and_set_validation(make_collector, monkeypatch):
    collector = make_collector()
    mock_rpc(monkeypatch, collector, pages={(WALLET, None): [signature_info(1)]})
    complete = discover(collector)
    helper = collector._history_inventory
    state = roundtrip(complete.cursor)
    cached = helper._summary

    def forbidden(*args, **kwargs):
        pytest.fail("Unveraendertes Cachemanifest darf keine Vollvalidation starten")

    monkeypatch.setattr(inventory, "_hash", forbidden)
    monkeypatch.setattr(inventory, "set", forbidden, raising=False)
    monkeypatch.setattr(helper, "_raw", forbidden)
    monkeypatch.setattr(helper, "_detail_chunks", forbidden)
    assert helper._manifest(state, [], forbidden) is cached


@pytest.mark.parametrize("field", ["pages", "chunks"])
@pytest.mark.parametrize("damage", ["bad_hash", "duplicate"])
def test_changed_manifest_cannot_reuse_validated_cache(make_collector, monkeypatch, field, damage):
    collector = make_collector()
    mock_rpc(monkeypatch, collector, pages={(WALLET, None): [signature_info(1)]})
    complete = discover(collector)
    state = roundtrip(complete.cursor)
    helper = collector._history_inventory
    cached = helper._summary
    state[field].append("invalid" if damage == "bad_hash" else state[field][0])
    with pytest.raises(HistoryFetchError) as exc:
        helper._manifest(state, [], lambda: None)
    assert not exc.value.resumable and helper._summary is cached


def test_cache_hit_fetch_only_checks_hashes_of_used_files(make_collector, monkeypatch):
    collector = make_collector()
    mock_rpc(monkeypatch, collector, pages={(WALLET, None): [signature_info(1)]})
    complete = discover(collector)
    real_hash = inventory._hash
    checked = []

    def counted(value):
        checked.append(value)
        return real_hash(value)

    monkeypatch.setattr(inventory, "_hash", counted)
    mock_rpc(monkeypatch, collector, txs={signature(1): transaction()})
    fetched = collector.fetch_page(complete.cursor, lambda: None)
    assert fetched.done
    assert checked == [complete.cursor["owners"], complete.cursor["chunks"][0], complete.cursor["pages"][0]]
