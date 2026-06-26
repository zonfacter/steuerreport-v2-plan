import json
from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.valuation import PriceQualityService


def _add_tax_line(store: DuckDbStore, *, asset: str, disposed_at: datetime) -> None:
    with store.connect() as con:
        con.execute(
            """
            insert into tax_lines (
                tax_line_id, asset, disposed_at, quantity,
                acquisition_cost_eur, disposal_proceeds_eur, gain_loss_eur,
                holding_days, source_event_id, lot_id, created_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                f"tax-{asset}-{disposed_at.year}",
                asset,
                disposed_at,
                Decimal("1"),
                Decimal("10"),
                Decimal("12"),
                Decimal("2"),
                30,
                "event-1",
                "lot-1",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            ],
        )


def test_price_quality_groups_low_confidence_proxy_and_tax_relevance(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("2.50"),
            priced_at=datetime(2024, 5, 1, tzinfo=timezone.utc),
            source="derived:hnt_proxy",
            confidence=Decimal("0.75"),
        )
    )
    _add_tax_line(store, asset="HNT", disposed_at=datetime(2024, 6, 1, tzinfo=timezone.utc))

    report = PriceQualityService(store).report()

    assert report.price_points_count == 1
    assert report.low_confidence_count == 1
    assert report.proxy_count == 1
    assert report.tax_relevant_issue_groups == 1
    assert report.high_risk_groups == 1
    group = report.groups[0]
    assert group.asset == "HNT"
    assert group.year == 2024
    assert group.risk_level == "high"
    assert group.tax_lines_count == 1
    assert group.status == "low_confidence+proxy_or_derived"


def test_price_quality_marks_non_tax_proxy_as_medium(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_price_point(
        PricePointCreate(
            asset="IOT",
            price_eur=Decimal("0.001"),
            priced_at=datetime(2023, 2, 1, tzinfo=timezone.utc),
            source="manual-proxy",
            confidence=Decimal("1.0"),
        )
    )

    report = PriceQualityService(store).report()

    assert report.high_risk_groups == 0
    assert report.medium_risk_groups == 1
    assert report.groups[0].risk_level == "medium"
    assert report.groups[0].tax_lines_count == 0


def test_price_quality_api(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("80"),
            priced_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source="coingecko",
            confidence=Decimal("0.95"),
        )
    )
    client = TestClient(create_app(store))

    response = client.get("/api/v1/prices/quality")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["price_points_count"] == 1
    assert data["low_confidence_count"] == 1
    assert data["groups"][0]["asset"] == "SOL"


def test_price_quality_group_detail_links_price_event_and_tax_samples(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    event = store.add_canonical_event(
        CanonicalEventCreate(
            source="pionex",
            source_ref="s_1",
            event_time=datetime(2022, 1, 1, tzinfo=timezone.utc),
            event_type="trade",
            asset="HNT",
            quantity=Decimal("1"),
            quote_asset="USDT",
            quote_quantity=Decimal("2"),
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("1.70"),
            priced_at=datetime(2022, 1, 1, tzinfo=timezone.utc),
            source="derived:event_quote",
            confidence=Decimal("0.85"),
        )
    )
    _add_tax_line(store, asset="HNT", disposed_at=datetime(2022, 2, 1, tzinfo=timezone.utc))

    detail = PriceQualityService(store).group_detail(
        asset="hnt",
        year=2022,
        source="derived:event_quote",
    )

    assert detail.group is not None
    assert detail.group.risk_level == "high"
    assert detail.price_samples[0].event_id == event.event_id
    assert detail.price_samples[0].quote_asset == "USDT"
    assert detail.event_sources == {"pionex": 1}
    assert detail.quote_assets == {"USDT": 1}
    assert detail.tax_line_samples[0].asset == "HNT"


def test_price_quality_decision_marks_group_without_changing_prices(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("1.70"),
            priced_at=datetime(2022, 1, 1, tzinfo=timezone.utc),
            source="derived:event_quote",
            confidence=Decimal("0.85"),
        )
    )
    _add_tax_line(store, asset="HNT", disposed_at=datetime(2022, 2, 1, tzinfo=timezone.utc))
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/prices/quality/decisions",
        json={
            "asset": "HNT",
            "year": 2022,
            "source": "derived:event_quote",
            "decision_status": "accepted_event_quote",
            "title": "HNT 2022 Event-Quotes akzeptiert",
            "rationale": "Pionex HNT/USDT Trades liefern direkte Quote-Evidenz.",
            "evidence_ref": "api:/api/v1/prices/quality/group?asset=HNT&year=2022&source=derived:event_quote",
        },
    )
    quality = client.get("/api/v1/prices/quality").json()["data"]
    prices = store.list_price_points()

    assert response.status_code == 200
    assert response.json()["data"]["decision_status"] == "accepted_event_quote"
    assert quality["groups"][0]["decision_status"] == "accepted_event_quote"
    assert quality["groups"][0]["decision_id"] == response.json()["data"]["decision_id"]
    assert prices[0].source == "derived:event_quote"
    assert prices[0].confidence == Decimal("0.85000000")


def test_price_quality_manual_review_report_prioritizes_tax_lines(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_price_point(
        PricePointCreate(
            asset="BTC",
            price_eur=Decimal("40000"),
            priced_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
            source="derived:event_quote",
            confidence=Decimal("0.85"),
        )
    )
    _add_tax_line(store, asset="BTC", disposed_at=datetime(2021, 2, 1, tzinfo=timezone.utc))
    client = TestClient(create_app(store))
    client.post(
        "/api/v1/prices/quality/decisions",
        json={
            "asset": "BTC",
            "year": 2021,
            "source": "derived:event_quote",
            "decision_status": "manual_review_required",
            "title": "BTC manuell pruefen",
            "rationale": "Binance-Quotes fehlen im Sample.",
            "evidence_ref": "unit-test",
        },
    )

    response = client.get("/api/v1/prices/quality/manual-review")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["manual_groups_count"] == 1
    assert data["tax_relevant_groups_count"] == 1
    assert data["groups"][0]["asset"] == "BTC"
    assert data["groups"][0]["priority_rank"] == 1
    assert data["groups"][0]["review_bucket"] == "event_quote_evidence_review"
    assert data["groups"][0]["evidence_ref"] == (
        "/api/v1/prices/quality/group?asset=BTC&year=2021&source=derived:event_quote"
    )
    assert "read-only" in data["methodology"]


def test_price_quality_stablecoin_fx_review_groups_fx_work(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="binance",
            event_time=datetime(2022, 1, 1, tzinfo=timezone.utc),
            event_type="unknown",
            asset="USDT",
            quantity=Decimal("0"),
            quote_asset="HNT",
            quote_quantity=Decimal("2"),
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.92"),
            priced_at=datetime(2022, 1, 1, tzinfo=timezone.utc),
            source="derived:event_quote",
            confidence=Decimal("0.85"),
        )
    )
    _add_tax_line(store, asset="USDT", disposed_at=datetime(2022, 2, 1, tzinfo=timezone.utc))
    client = TestClient(create_app(store))
    client.post(
        "/api/v1/prices/quality/decisions",
        json={
            "asset": "USDT",
            "year": 2022,
            "source": "derived:event_quote",
            "decision_status": "manual_review_required",
            "title": "USDT FX pruefen",
            "rationale": "Stablecoin braucht FX-Evidenz.",
            "evidence_ref": "unit-test",
        },
    )

    response = client.get("/api/v1/prices/quality/stablecoin-fx-review")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["groups_count"] == 1
    assert data["tax_relevant_groups_count"] == 1
    assert data["assets"] == ["USDT"]
    assert data["groups"][0]["expected_price_basis"].startswith("USD/EUR-FX")
    assert "FX-Evidenz" in data["groups"][0]["recommended_action"]


def test_price_quality_stablecoin_fx_replacement_preview_marks_fx_backed_day(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    event_time = datetime(2022, 1, 1, 12, tzinfo=timezone.utc)
    store.add_canonical_event(
        CanonicalEventCreate(
            source="binance",
            source_ref="stable-trade-1",
            event_time=event_time,
            event_type="unknown",
            asset="USDT",
            quantity=Decimal("0"),
            quote_asset="HNT",
            quote_quantity=Decimal("2"),
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.50"),
            priced_at=event_time,
            source="derived:event_quote",
            confidence=Decimal("0.85"),
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.91"),
            priced_at=datetime(2022, 1, 1, tzinfo=timezone.utc),
            source="v1_fx_cache:coingecko_history:usd_eur:ecb",
            confidence=Decimal("1.0"),
        )
    )
    _add_tax_line(store, asset="USDT", disposed_at=datetime(2022, 2, 1, tzinfo=timezone.utc))
    client = TestClient(create_app(store))
    client.post(
        "/api/v1/prices/quality/decisions",
        json={
            "asset": "USDT",
            "year": 2022,
            "source": "derived:event_quote",
            "decision_status": "manual_review_required",
            "title": "USDT FX pruefen",
            "rationale": "Stablecoin braucht FX-Evidenz.",
            "evidence_ref": "unit-test",
        },
    )

    response = client.get("/api/v1/prices/quality/stablecoin-fx-replacement-preview")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["groups_count"] == 1
    assert data["days_count"] == 1
    assert data["days_needing_replacement"] == 0
    assert data["fx_backed_days_count"] == 1
    day = data["groups"][0]["days"][0]
    assert day["replacement_status"] == "fx_backed_available"
    assert day["selected_alternative_price_eur"] == "0.910000000000000000"
    assert day["sample_event_refs"] == ["stable-trade-1"]


def test_price_quality_stablecoin_fx_replacement_preview_marks_missing_replacement(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="binance",
            event_time=datetime(2024, 5, 1, tzinfo=timezone.utc),
            event_type="unknown",
            asset="BUSD",
            quantity=Decimal("0"),
            quote_asset="BNB",
            quote_quantity=Decimal("1"),
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="BUSD",
            price_eur=Decimal("0.70"),
            priced_at=datetime(2024, 5, 1, tzinfo=timezone.utc),
            source="derived:event_quote",
            confidence=Decimal("0.85"),
        )
    )
    _add_tax_line(store, asset="BUSD", disposed_at=datetime(2024, 6, 1, tzinfo=timezone.utc))
    client = TestClient(create_app(store))
    client.post(
        "/api/v1/prices/quality/decisions",
        json={
            "asset": "BUSD",
            "year": 2024,
            "source": "derived:event_quote",
            "decision_status": "manual_review_required",
            "title": "BUSD FX pruefen",
            "rationale": "Stablecoin braucht FX-Evidenz.",
            "evidence_ref": "unit-test",
        },
    )

    response = client.get("/api/v1/prices/quality/stablecoin-fx-replacement-preview")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["groups_count"] == 1
    assert data["days_needing_replacement"] == 1
    assert data["fx_backed_days_count"] == 0
    day = data["groups"][0]["days"][0]
    assert day["replacement_status"] == "replacement_needed"
    assert day["selected_alternative_source"] is None
    assert "Stablecoin-EUR-Preisanker" in day["recommended_action"]


def test_price_quality_stablecoin_fx_replacement_impact_marks_ready_rows(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    event_time = datetime(2024, 3, 9, 12, tzinfo=timezone.utc)
    store.add_canonical_event(
        CanonicalEventCreate(
            source="binance",
            source_ref="usdt-2024-trade",
            event_time=event_time,
            event_type="trade",
            asset="USDT",
            quantity=Decimal("10"),
            quote_asset="SOL",
            quote_quantity=Decimal("0.1"),
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.94"),
            priced_at=event_time,
            source="derived:event_quote",
            confidence=Decimal("0.85"),
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.92"),
            priced_at=datetime(2024, 3, 9, tzinfo=timezone.utc),
            source="v1_fx_cache:coingecko_history:usd_eur:ecb",
            confidence=Decimal("1.0"),
        )
    )
    _add_tax_line(store, asset="USDT", disposed_at=datetime(2024, 4, 1, tzinfo=timezone.utc))
    client = TestClient(create_app(store))

    response = client.get(
        "/api/v1/prices/quality/stablecoin-fx-replacement-impact",
        params={"asset": "USDT", "year": 2024},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["asset"] == "USDT"
    assert data["derived_price_rows"] == 1
    assert data["replacement_ready_rows"] == 1
    assert data["missing_replacement_rows"] == 0
    assert data["all_replacement_ready"] is True
    assert data["tax_lines_count"] == 1
    row = data["rows"][0]
    assert row["replacement_status"] == "ready"
    assert row["replacement_price_eur"] == "0.920000000000000000"
    assert row["abs_delta_eur"] == "0.020000000000000000"
    assert row["sample_event_refs"] == ["usdt-2024-trade"]


def test_price_quality_stablecoin_fx_replacement_impact_marks_missing_rows(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_price_point(
        PricePointCreate(
            asset="BUSD",
            price_eur=Decimal("0.70"),
            priced_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
            source="derived:event_quote",
            confidence=Decimal("0.85"),
        )
    )
    client = TestClient(create_app(store))

    response = client.get(
        "/api/v1/prices/quality/stablecoin-fx-replacement-impact",
        params={"asset": "BUSD", "year": 2023},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["derived_price_rows"] == 1
    assert data["replacement_ready_rows"] == 0
    assert data["missing_replacement_rows"] == 1
    assert data["all_replacement_ready"] is False
    assert data["rows"][0]["replacement_status"] == "missing_replacement"
    assert data["rows"][0]["replacement_price_eur"] is None


def test_price_quality_stablecoin_fx_tax_impact_latest_reads_artifact(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "impact"
    artifact_dir.mkdir()
    (artifact_dir / "latest_USDT_2024_tax_impact.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-26T20:55:53+00:00",
                "asset": "USDT",
                "year": 2024,
                "source": "derived:event_quote",
                "replacement_plan": {
                    "rows_count": 6,
                    "ready_rows": 6,
                    "missing_rows": 0,
                    "applied_rows": 6,
                },
                "baseline": {
                    "taxable_gain_loss_eur": "17187.535700018292083739",
                    "stablecoin_gain_loss_eur": "448.568882903768959597",
                },
                "patched": {
                    "taxable_gain_loss_eur": "17164.365258034450328223",
                    "stablecoin_gain_loss_eur": "420.843483359799231191",
                },
                "delta": {
                    "taxable_gain_loss_eur": "-23.170441983841755516",
                    "stablecoin_gain_loss_eur": "-27.725399543969728406",
                    "unmatched_disposals": 0,
                },
                "conclusion": "replacement_changes_tax_result_review_required",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(PriceQualityService, "TAX_IMPACT_ARTIFACT_DIR", artifact_dir)
    client = TestClient(create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb")))

    response = client.get("/api/v1/prices/quality/stablecoin-fx-tax-impact-latest")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["artifact_found"] is True
    assert data["replacement_rows_count"] == 6
    assert data["taxable_gain_loss_delta_eur"] == "-23.170441983841755516"
    assert data["stablecoin_gain_loss_delta_eur"] == "-27.725399543969728406"
    assert data["decision_scope"] == "stablecoin_fx_replacement:asset:USDT:year:2024:source:derived:event_quote"
    assert data["decision_options"][0]["action"] == "document_delta_only"
    assert data["decision_options"][0]["recommended"] is True
    assert "Steuerdelta" in data["recommended_next_action"]


def test_price_quality_stablecoin_fx_tax_impact_decision_writes_review_only(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "impact"
    artifact_dir.mkdir()
    artifact_path = artifact_dir / "latest_USDT_2024_tax_impact.json"
    artifact_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-26T20:55:53+00:00",
                "replacement_plan": {
                    "rows_count": 6,
                    "ready_rows": 6,
                    "missing_rows": 0,
                    "applied_rows": 6,
                },
                "baseline": {"taxable_gain_loss_eur": "10", "stablecoin_gain_loss_eur": "2"},
                "patched": {"taxable_gain_loss_eur": "8", "stablecoin_gain_loss_eur": "1"},
                "delta": {
                    "taxable_gain_loss_eur": "-2",
                    "stablecoin_gain_loss_eur": "-1",
                    "unmatched_disposals": 0,
                },
                "conclusion": "replacement_changes_tax_result_review_required",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(PriceQualityService, "TAX_IMPACT_ARTIFACT_DIR", artifact_dir)
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/prices/quality/stablecoin-fx-tax-impact-decisions",
        json={
            "asset": "USDT",
            "year": 2024,
            "action": "document_delta_only",
            "rationale": "Delta ist dokumentiert; Live-Preise bleiben unveraendert.",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["action"] == "document_delta_only"
    assert data["writes_prices"] is False
    assert data["writes_fifo"] is False
    assert data["writes_tax_lines"] is False
    decisions = store.list_review_decisions()
    assert len(decisions) == 1
    assert decisions[0].decision_type == "stablecoin_fx_replacement_tax_impact"
    assert decisions[0].evidence_ref == str(artifact_path)
    assert decisions[0].payload["price_write_effect"] == "none"
    assert decisions[0].payload["fifo_effect"] == "none"
    assert decisions[0].payload["tax_lines_effect"] == "none"


def test_price_quality_solscan_signature_review_separates_signature_refs(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    signature = "3YTtgWxaXt8hf9N2ja69r1rpvfozBK7vyrkmZDy8EvtBCSg3YcCrujEFJc4mDQW1pnCTLFaWLHaofD3zdaZGdcQ"
    store.add_canonical_event(
        CanonicalEventCreate(
            source="solana_rpc",
            source_ref=signature,
            event_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            event_type="trade",
            asset="IOT",
            quantity=Decimal("100"),
            quote_asset="SOL",
            quote_quantity=Decimal("0.1"),
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="IOT",
            price_eur=Decimal("0.01"),
            priced_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source="derived:event_quote",
            confidence=Decimal("0.85"),
        )
    )
    _add_tax_line(store, asset="IOT", disposed_at=datetime(2024, 2, 1, tzinfo=timezone.utc))
    client = TestClient(create_app(store))
    client.post(
        "/api/v1/prices/quality/decisions",
        json={
            "asset": "IOT",
            "year": 2024,
            "source": "derived:event_quote",
            "decision_status": "manual_review_required",
            "title": "IOT Solscan pruefen",
            "rationale": "Solana-RPC Signatur braucht Solscan-Abgleich.",
            "evidence_ref": "unit-test",
        },
    )

    response = client.get("/api/v1/prices/quality/solscan-signature-review")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["groups_count"] == 1
    assert data["tax_relevant_groups_count"] == 1
    assert data["total_signature_refs"] == 1
    assert data["groups"][0]["asset"] == "IOT"
    assert data["groups"][0]["signature_refs"] == [signature]
    assert "Solscan" in data["groups"][0]["recommended_action"]


def test_price_quality_binance_normalizer_review_marks_missing_quotes(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="binance",
            event_time=datetime(2021, 1, 1, tzinfo=timezone.utc),
            event_type="trade",
            asset="HNT",
            quantity=Decimal("2"),
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("2.5"),
            priced_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
            source="derived:event_quote",
            confidence=Decimal("0.85"),
        )
    )
    _add_tax_line(store, asset="HNT", disposed_at=datetime(2021, 2, 1, tzinfo=timezone.utc))
    client = TestClient(create_app(store))
    client.post(
        "/api/v1/prices/quality/decisions",
        json={
            "asset": "HNT",
            "year": 2021,
            "source": "derived:event_quote",
            "decision_status": "manual_review_required",
            "title": "HNT Binance pruefen",
            "rationale": "Quote-Felder fehlen.",
            "evidence_ref": "unit-test",
        },
    )

    response = client.get("/api/v1/prices/quality/binance-normalizer-review")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["groups_count"] == 1
    assert data["tax_relevant_groups_count"] == 1
    assert data["missing_quote_groups_count"] == 1
    assert data["missing_sample_ref_groups_count"] == 1
    assert data["groups"][0]["asset"] == "HNT"
    assert data["groups"][0]["has_missing_quote_fields"] is True
    assert "Normalizer-Mapping" in data["groups"][0]["recommended_action"]


def test_price_quality_event_quote_evidence_review_classifies_stable_quotes(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="pionex",
            source_ref="s_1",
            event_time=datetime(2023, 1, 1, tzinfo=timezone.utc),
            event_type="trade",
            asset="DOGE",
            quantity=Decimal("10"),
            quote_asset="USDT",
            quote_quantity=Decimal("1"),
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="DOGE",
            price_eur=Decimal("0.1"),
            priced_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
            source="derived:event_quote",
            confidence=Decimal("0.85"),
        )
    )
    _add_tax_line(store, asset="DOGE", disposed_at=datetime(2023, 2, 1, tzinfo=timezone.utc))
    client = TestClient(create_app(store))
    client.post(
        "/api/v1/prices/quality/decisions",
        json={
            "asset": "DOGE",
            "year": 2023,
            "source": "derived:event_quote",
            "decision_status": "manual_review_required",
            "title": "DOGE Event-Quote pruefen",
            "rationale": "Stabile Quote muss belegt werden.",
            "evidence_ref": "unit-test",
        },
    )

    response = client.get("/api/v1/prices/quality/event-quote-evidence-review")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["groups_count"] == 1
    assert data["stable_quote_groups_count"] == 1
    assert data["groups"][0]["evidence_class"] == "stable_quote_sample"
    assert data["groups"][0]["stable_quote_evidence"] is True
    assert "fachlich akzeptiert" in data["groups"][0]["recommended_action"]


def test_price_quality_closure_candidates_marks_stable_quote_as_auto_close(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="pionex",
            source_ref="trade-1",
            event_time=datetime(2023, 1, 1, tzinfo=timezone.utc),
            event_type="trade",
            asset="DOGE",
            quantity=Decimal("10"),
            quote_asset="USDT",
            quote_quantity=Decimal("1"),
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="DOGE",
            price_eur=Decimal("0.1"),
            priced_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
            source="derived:event_quote",
            confidence=Decimal("0.85"),
        )
    )
    _add_tax_line(store, asset="DOGE", disposed_at=datetime(2023, 2, 1, tzinfo=timezone.utc))
    client = TestClient(create_app(store))
    client.post(
        "/api/v1/prices/quality/decisions",
        json={
            "asset": "DOGE",
            "year": 2023,
            "source": "derived:event_quote",
            "decision_status": "manual_review_required",
            "title": "DOGE Event-Quote pruefen",
            "rationale": "Stabile Quote muss belegt werden.",
            "evidence_ref": "unit-test",
        },
    )

    response = client.get("/api/v1/prices/quality/closure-candidates")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["groups_count"] == 1
    assert data["auto_close_candidates_count"] == 1
    assert data["groups"][0]["closure_class"] == "accepted_event_quote_candidate"
    assert data["groups"][0]["recommended_decision_status"] == "accepted_event_quote"
    assert data["groups"][0]["can_auto_close_with_evidence"] is True


def test_price_quality_closure_candidates_keeps_stablecoin_fx_as_replacement(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="binance",
            event_time=datetime(2022, 1, 1, tzinfo=timezone.utc),
            event_type="unknown",
            asset="USDT",
            quantity=Decimal("0"),
            quote_asset="HNT",
            quote_quantity=Decimal("2"),
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.92"),
            priced_at=datetime(2022, 1, 1, tzinfo=timezone.utc),
            source="derived:event_quote",
            confidence=Decimal("0.85"),
        )
    )
    _add_tax_line(store, asset="USDT", disposed_at=datetime(2022, 2, 1, tzinfo=timezone.utc))
    client = TestClient(create_app(store))
    client.post(
        "/api/v1/prices/quality/decisions",
        json={
            "asset": "USDT",
            "year": 2022,
            "source": "derived:event_quote",
            "decision_status": "manual_review_required",
            "title": "USDT FX pruefen",
            "rationale": "Stablecoin braucht FX-Evidenz.",
            "evidence_ref": "unit-test",
        },
    )

    response = client.get("/api/v1/prices/quality/closure-candidates")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["auto_close_candidates_count"] == 0
    assert data["stablecoin_fx_replacement_candidates_count"] == 1
    assert data["groups"][0]["closure_class"] == "stablecoin_fx_replacement_candidate"
    assert data["groups"][0]["recommended_decision_status"] == "external_price_required"
    assert data["groups"][0]["can_auto_close_with_evidence"] is False
