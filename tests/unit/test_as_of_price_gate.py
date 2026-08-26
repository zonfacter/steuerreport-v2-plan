from datetime import date, datetime, timezone
from decimal import Decimal
import json
import sqlite3

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.prices import (
    AsOfPriceGateBackfillRequest,
    AsOfTokenValuationDecisionRequest,
    PricePointCreate,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.as_of_price_gate import AsOfPriceGateService
from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


AS_OF = datetime(2025, 6, 13, 23, 59, 59, tzinfo=timezone.utc)


def _store(tmp_path, asset="BTC"):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="test",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset=asset,
                quantity=Decimal("1"),
                account="wallet",
            )
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset=asset,
            price_eur=Decimal("50"),
            priced_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            source="old-test-price",
        )
    )
    BalanceLedgerBuilder(store).rebuild()
    return store


def _fx_db(path):
    with sqlite3.connect(path) as con:
        con.execute(
            "create table fx_cache (rate_date text, base_ccy text, quote_ccy text, rate text, source text)"
        )
        con.execute(
            "insert into fx_cache values (?, 'USD', 'EUR', '0.9', 'test')",
            ("2025-06-13",),
        )
    return path


def _insert_token_metadata(
    store,
    *,
    mint,
    symbol,
    risk_status,
    is_verified,
):
    with store.connect() as con:
        con.execute(
            """
            insert into jupiter_token_metadata_cache (
                mint, symbol, name, decimals, icon, token_program, is_verified,
                organic_score, organic_score_label, holder_count, liquidity_usd,
                usd_price, market_cap_usd, risk_status, source,
                discovered_sources_json, refreshed_at, jupiter_updated_at
            ) values (?, ?, ?, 2, null, null, ?, 1, 'low', 10, 1000, 0.1, 1000,
                      ?, 'jupiter_tokens_v2', '[]', ?, null)
            """,
            [
                mint,
                symbol,
                symbol,
                is_verified,
                risk_status,
                datetime.now(timezone.utc),
            ],
        )


def test_as_of_price_gate_marks_stale_material_asset_as_fetchable(tmp_path):
    service = AsOfPriceGateService(_store(tmp_path))

    report = service.report(as_of=AS_OF)

    assert report.strict_ready is False
    assert report.fetchable_count == 1
    assert report.candidates[0].asset == "BTC"
    assert report.candidates[0].current_price_status == "stale"
    assert report.candidates[0].provider_id == "bitcoin"


def test_as_of_price_gate_backfill_adds_same_day_price_without_pipeline_rebuild(
    tmp_path, monkeypatch
):
    store = _store(tmp_path)
    fx_path = _fx_db(tmp_path / "fx.db")
    monkeypatch.setattr(
        ExternalPriceBackfillService,
        "_fetch_price_usd",
        lambda self, **_kwargs: (Decimal("100"), "defillama_test"),
    )
    service = AsOfPriceGateService(store, artifact_root=tmp_path / "price-gate-runs")

    result = service.backfill(
        AsOfPriceGateBackfillRequest(
            as_of=AS_OF,
            v1_fx_db_path=str(fx_path),
            dry_run=False,
        )
    )

    assert result.imported_prices == 1
    assert result.jobs[0].price_eur == Decimal("90.0")
    assert result.gate_before.strict_ready is False
    assert result.gate_after.strict_ready is True
    assert result.gate_after.candidates[0].current_price_status == "same_day"
    assert TaxService(store).list_tax_lines() == []


def test_as_of_price_gate_backfill_supports_defillama_only_asset(tmp_path, monkeypatch):
    store = _store(tmp_path, asset="JLWSOL")
    fx_path = _fx_db(tmp_path / "fx.db")
    config_path = tmp_path / "prices.json"
    config_path.write_text(
        json.dumps(
            {
                "assets": [
                    {
                        "symbol": "JLWSOL",
                        "defillama_id": "solana:jlwsol-mint",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_fetch(self, **kwargs):
        calls.append(kwargs)
        return Decimal("110"), "defillama_token_history"

    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_price_usd", fake_fetch)
    service = AsOfPriceGateService(store, artifact_root=tmp_path / "price-gate-runs")

    result = service.backfill(
        AsOfPriceGateBackfillRequest(
            as_of=AS_OF,
            config_path=str(config_path),
            v1_fx_db_path=str(fx_path),
            provider="defillama",
            dry_run=False,
        )
    )

    assert result.imported_prices == 1
    assert result.gate_before.candidates[0].provider_id == "solana:jlwsol-mint"
    assert result.gate_after.strict_ready is True
    assert calls[0]["coingecko_id"] is None
    assert calls[0]["defillama_id"] == "solana:jlwsol-mint"


def test_as_of_price_gate_keeps_risk_token_in_review_even_with_same_day_price(tmp_path):
    store = _store(tmp_path, asset="CBDC")
    _insert_token_metadata(
        store,
        mint="2KFZCkfxj1Us8YRQZa5vktSxy3GPzFZvVhWj91n8Fv2J",
        symbol="CBDC",
        risk_status="spam_review",
        is_verified=False,
    )
    store.add_price_point(
        PricePointCreate(
            asset="CBDC",
            price_eur=Decimal("55"),
            priced_at=AS_OF,
            source="same-day-test",
        )
    )

    report = AsOfPriceGateService(store).report(as_of=AS_OF)

    assert report.strict_ready is False
    assert report.review_only_count == 1
    assert report.candidates[0].status == "review_only"
    assert report.candidates[0].token_review_status == "pending"


def test_as_of_price_gate_normalizes_verified_dollar_prefixed_symbol(tmp_path):
    store = _store(tmp_path, asset="CWIF")
    _insert_token_metadata(
        store,
        mint="7atgF8KQo4wJrD5ATGX7t1V2zVvykPJbFfNeVf1icFv1",
        symbol="$CWIF",
        risk_status="verified",
        is_verified=True,
    )
    store.add_price_point(
        PricePointCreate(
            asset="CWIF",
            price_eur=Decimal("5"),
            priced_at=AS_OF,
            source="same-day-test",
        )
    )

    report = AsOfPriceGateService(store).report(as_of=AS_OF)

    assert report.strict_ready is True
    assert report.review_only_count == 0
    assert report.candidates[0].token_mint.startswith("7atgF8")
    assert report.candidates[0].token_review_status == "not_required"
    assert report.candidates[0].status == "satisfied"


def test_as_of_price_gate_accepts_risk_token_only_with_same_day_price(tmp_path):
    store = _store(tmp_path, asset="CBDC")
    _insert_token_metadata(
        store,
        mint="2KFZCkfxj1Us8YRQZa5vktSxy3GPzFZvVhWj91n8Fv2J",
        symbol="CBDC",
        risk_status="spam_review",
        is_verified=False,
    )
    store.add_price_point(
        PricePointCreate(
            asset="CBDC",
            price_eur=Decimal("5"),
            priced_at=datetime(2025, 6, 13, tzinfo=timezone.utc),
            source="defillama-test:usd_eur:test",
        )
    )
    service = AsOfPriceGateService(store)
    request = AsOfTokenValuationDecisionRequest(
        as_of_date=date(2025, 6, 13),
        asset="CBDC",
    )

    result = service.accept_token_valuation(request)
    repeated = service.accept_token_valuation(request)

    assert result.already_recorded is False
    assert result.gate_after.strict_ready is True
    assert result.gate_after.gate.accepted_review_asset_count == 1
    assert result.gate_after.candidates[0].token_review_status == "accepted"
    assert repeated.already_recorded is True
    assert repeated.decision.decision_id == result.decision.decision_id
    csv_text = service.token_valuation_decisions_csv(
        separation_date=date(2025, 6, 13),
        end_asset_date=date(2026, 7, 24),
    )
    assert result.decision.decision_id in csv_text
    assert "include_with_documented_same_day_price" in csv_text


def test_as_of_price_gate_api_supports_preview(tmp_path):
    store = _store(tmp_path)
    response = TestClient(create_app(store)).get(
        "/api/v1/prices/as-of-gate?as_of=2025-06-13T23:59:59Z&materiality_threshold_eur=1"
    )

    assert response.status_code == 200
    assert response.json()["data"]["fetchable_count"] == 1


def test_as_of_price_gate_token_review_api_and_csv(tmp_path):
    store = _store(tmp_path, asset="CBDC")
    _insert_token_metadata(
        store,
        mint="2KFZCkfxj1Us8YRQZa5vktSxy3GPzFZvVhWj91n8Fv2J",
        symbol="CBDC",
        risk_status="spam_review",
        is_verified=False,
    )
    store.add_price_point(
        PricePointCreate(
            asset="CBDC",
            price_eur=Decimal("5"),
            priced_at=datetime(2025, 6, 13, tzinfo=timezone.utc),
            source="same-day-api-test",
        )
    )
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/prices/as-of-gate/token-review-decisions",
        json={"as_of_date": "2025-06-13", "asset": "CBDC"},
    )
    csv_response = client.get(
        "/api/v1/prices/as-of-gate/token-review-decisions.csv"
        "?separation_date=2025-06-13&end_asset_date=2026-07-24"
    )

    assert response.status_code == 200
    assert response.json()["data"]["gate_after"]["strict_ready"] is True
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert response.json()["data"]["decision"]["decision_id"] in csv_response.text


def test_as_of_price_gate_accepts_berlin_calendar_date(tmp_path):
    store = _store(tmp_path)

    report = AsOfPriceGateService(store).report(as_of_date=date(2025, 6, 13))

    assert report.as_of == datetime(
        2025, 6, 13, 21, 59, 59, 999999, tzinfo=timezone.utc
    )

    response = TestClient(create_app(store)).get(
        "/api/v1/prices/as-of-gate?as_of_date=2025-06-13&materiality_threshold_eur=1"
    )
    assert response.status_code == 200
    assert response.json()["data"]["as_of"] == "2025-06-13T21:59:59.999999Z"
