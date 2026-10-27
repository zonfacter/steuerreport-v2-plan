from __future__ import annotations

import copy
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.portfolio import PortfolioWalletHistoryImportRequest
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.importers.solana_history_identity import SolanaHistoryConflict
from steuerreport_v2.importers.solana_history_identity import exclusive_history_import
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


WALLET = "synthetic-history-wallet"
MINT = "SyntheticMintCaseSensitive"


def transaction(*, quantity="10", native_delta=-5000, failed=False):
    return {
        "blockTime": 1735689600,
        "slot": 1,
        "transaction": {"message": {"accountKeys": [{"pubkey": WALLET}, {"pubkey": "synthetic-token-account"}]}},
        "meta": {
            "err": {"InstructionError": [0, "Custom"]} if failed else None,
            "fee": 5000,
            "preBalances": [2_000_000_000, 2_039_280],
            "postBalances": [2_000_000_000 + native_delta, 2_039_280],
            "preTokenBalances": [],
            "postTokenBalances": [{
                "owner": WALLET, "mint": MINT, "accountIndex": 1,
                "uiTokenAmount": {"uiAmountString": quantity},
            }],
        },
    }


def install_rpc(monkeypatch, service, page, txs):
    def rpc(method, params, timeout_seconds):
        if method == "getSignaturesForAddress":
            return [{"signature": signature} for signature in page]
        assert method == "getTransaction"
        return copy.deepcopy(txs[params[0]])
    monkeypatch.setattr(service, "_solana_rpc", rpc)
    monkeypatch.setattr(service, "_solana_history_mint_symbols", lambda: {MINT: "TESTTOKEN"})


def import_page(service):
    return service.import_jup_wallet_history(PortfolioWalletHistoryImportRequest(
        wallet_address=WALLET, max_signatures=5, max_transactions=5,
    ))


def snapshot(store):
    with store.connect() as con:
        return {
            table: con.execute(f"select * from {table} order by 1").fetchall()
            for table in ("raw_import_batches", "raw_objects", "canonical_events", "balance_ledger", "tax_lines")
        }


def test_overlapping_pages_retry_and_rebuild_do_not_duplicate_financial_events(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "history.duckdb")
    service = PortfolioService(store)
    page = ["signature-a"]
    install_rpc(monkeypatch, service, page, {
        "signature-a": transaction(), "signature-b": transaction(quantity="20"),
    })
    first = import_page(service)
    assert first.normalized_events == 2
    before = snapshot(store)
    again = import_page(service)
    assert again.duplicate_batch and again.normalized_events == 0
    assert again.pipeline["skipped"] is True
    assert snapshot(store) == before

    page.append("signature-b")
    overlap = import_page(service)
    assert overlap.normalized_events == 2
    assert any(item["code"] == "solana_history_duplicate_transactions" for item in overlap.warnings)
    events = store.list_canonical_events()
    assert len(events) == 4
    assert not {event.event_type for event in events} & {"trade", "income", "reward"}
    assert sum(event.quantity for event in events if event.asset == "TESTTOKEN") == 30
    assert sum(event.quantity for event in events if event.asset == "SOL") == Decimal("-0.00001")
    assert all(event.fee_quantity is None for event in events)
    assert all(event.quote_quantity is None for event in events)
    assert not ReviewService(store).gate().allow_export
    issues = ReviewService(store).gate().issues
    assert sum(issue.code == "solana_history_classification_required" for issue in issues) == 2
    event_ids = {event.event_id for event in events}
    PipelineService(store).rebuild_all()
    assert {event.event_id for event in store.list_canonical_events()} == event_ids
    positions = {position.asset: position.quantity for position in BalanceLedgerBuilder(store).positions()}
    assert positions == {"SOL": Decimal("-0.00001"), "TESTTOKEN": Decimal("30")}
    final = snapshot(store)
    assert import_page(service).duplicate_batch
    assert snapshot(store) == final


def test_changed_prior_transaction_is_blocked_without_overwrite_or_partial_import(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "history.duckdb")
    service = PortfolioService(store)
    page = ["signature-a"]
    txs = {"signature-a": transaction(), "signature-b": transaction()}
    install_rpc(monkeypatch, service, page, txs)
    import_page(service)
    before = snapshot(store)
    page.append("signature-b")
    txs["signature-a"] = transaction(quantity="999")
    with pytest.raises(SolanaHistoryConflict, match="abweichenden"):
        import_page(service)
    assert snapshot(store) == before


@pytest.mark.parametrize("missing", [None, {}, {"blockTime": None}])
def test_missing_detail_never_imports_partial_page_or_returns_advanced_cursor(tmp_path, monkeypatch, missing):
    store = DuckDbStore(tmp_path / "history.duckdb")
    service = PortfolioService(store)
    install_rpc(monkeypatch, service, ["signature-a", "signature-b"], {
        "signature-a": transaction(), "signature-b": missing,
    })
    before = snapshot(store)
    with pytest.raises(RuntimeError, match="Historienseite"):
        import_page(service)
    assert snapshot(store) == before


def test_failed_transaction_records_only_single_negative_network_fee(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "history.duckdb")
    service = PortfolioService(store)
    install_rpc(monkeypatch, service, ["failed-signature"], {
        "failed-signature": transaction(failed=True),
    })
    assert import_page(service).normalized_events == 1
    event, = store.list_canonical_events()
    assert (event.event_type, event.asset, event.quantity) == ("fee", "SOL", Decimal("-0.000005"))
    assert event.fee_quantity is None
    assert event.quote_quantity is None


def test_api_conflict_is_explicit_and_does_not_leak_payload(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "history.duckdb")
    def conflict(*_args):
        raise SolanaHistoryConflict("Manuelle Pruefung erforderlich; kein Import.")
    monkeypatch.setattr(PortfolioService, "import_jup_wallet_history", conflict)
    response = TestClient(create_app(store)).post(
        "/api/v1/portfolio/jup-wallet/import-history", json={"wallet_address": WALLET},
    )
    assert response.status_code == 409
    assert "Manuelle Pruefung" in response.json()["detail"]


def test_separate_store_handles_cannot_bypass_import_lock(tmp_path):
    first = DuckDbStore(tmp_path / "history.duckdb")
    second = DuckDbStore(tmp_path / "history.duckdb")
    with exclusive_history_import(first):
        with pytest.raises(SolanaHistoryConflict, match="laeuft bereits"):
            with exclusive_history_import(second):
                pytest.fail("Concurrent history import escaped the shared lock")
    with exclusive_history_import(second):
        pass


def test_exact_known_mint_mapping_does_not_fold_base58_case(tmp_path):
    service = PortfolioService(DuckDbStore(tmp_path / "history.duckdb"))
    mints = service._solana_history_mint_symbols()
    mint = "hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux"
    assert mints[mint] == "HNT"
    assert mint.upper() not in mints


def test_duplicate_signatures_in_provider_page_are_fetched_only_once(tmp_path, monkeypatch):
    service = PortfolioService(DuckDbStore(tmp_path / "history.duckdb"))
    calls = []
    def rpc(method, params, timeout_seconds):
        calls.append(method)
        return [{"signature": "signature-a"}] * 2 if method == "getSignaturesForAddress" else transaction()
    monkeypatch.setattr(service, "_solana_rpc", rpc)
    payload = service._solana_wallet_history_direct(
        wallet_address=WALLET, before_signature=None, max_signatures=5, warning="test",
    )
    assert payload["signature_count"] == 1
    assert calls == ["getSignaturesForAddress", "getTransaction"]


def test_retry_after_interrupted_raw_load_is_not_reported_as_success(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "history.duckdb")
    service = PortfolioService(store)
    install_rpc(monkeypatch, service, ["signature-a"], {"signature-a": transaction()})
    original = store.add_raw_objects
    def fail(*_args):
        raise RuntimeError("synthetic interrupted write")
    monkeypatch.setattr(store, "add_raw_objects", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        import_page(service)
    monkeypatch.setattr(store, "add_raw_objects", original)
    before = snapshot(store)
    with pytest.raises(SolanaHistoryConflict, match="unvollstaendig"):
        import_page(service)
    assert snapshot(store) == before
    assert not store.list_canonical_events()


def test_failed_renormalization_invalidates_success_before_deleting_events(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "history.duckdb")
    service = PortfolioService(store)
    install_rpc(monkeypatch, service, ["signature-a"], {"signature-a": transaction()})
    result = import_page(service)
    assert store.get_import_batch(result.batch_id).status == "normalized"
    def fail(*_args, **_kwargs):
        raise RuntimeError("synthetic normalization failure")
    monkeypatch.setattr(RawNormalizer, "_row_to_event", fail)
    with pytest.raises(RuntimeError, match="normalization failure"):
        PipelineService(store).rebuild_all()
    assert store.get_import_batch(result.batch_id).status == "loaded"
    assert not store.list_canonical_events()
    before = snapshot(store)
    with pytest.raises(SolanaHistoryConflict, match="nicht als vollstaendig"):
        import_page(service)
    assert snapshot(store) == before


def test_unclassified_counterflows_do_not_create_assumed_token_price(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "history.duckdb")
    service = PortfolioService(store)
    store.add_price_point(PricePointCreate(
        asset="SOL", price_eur=Decimal("100"), source="synthetic-price-evidence",
        priced_at=datetime(2024, 12, 31, tzinfo=timezone.utc),
    ))
    install_rpc(monkeypatch, service, ["signature-a"], {
        "signature-a": transaction(native_delta=-1_000_005_000),
    })
    import_page(service)
    assert not any(price.asset == "TESTTOKEN" for price in store.list_price_points())
    assert all(event.event_type in {"transfer", "fee"} for event in store.list_canonical_events())
    assert sum(event.quantity for event in store.list_canonical_events() if event.asset == "SOL") == Decimal("-1.000005")
    assert any(issue.code == "solana_history_classification_required" for issue in ReviewService(store).gate().issues)


def test_successful_empty_page_is_retry_idempotent(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "history.duckdb")
    service = PortfolioService(store)
    install_rpc(monkeypatch, service, [], {})
    first = import_page(service)
    assert first.normalized_events == 0 and not first.duplicate_batch
    assert store.get_import_batch(first.batch_id).status == "normalized"
    before = snapshot(store)
    repeated = import_page(service)
    assert repeated.duplicate_batch and repeated.normalized_events == 0
    assert repeated.pipeline["skipped"] is True
    assert snapshot(store) == before
