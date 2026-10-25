import json
import gzip
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.bmf_event_evidence import (
    BmfCanonicalEventEvidence,
    BmfEventSourceEvidence,
    BmfFifoEventEvidenceRunRequest,
    BmfOriginResolution,
)
from steuerreport_v2.contracts.bmf_fifo_staging import (
    BmfCombinedFifoEventRow,
    BmfFifoStagingRunRequest,
)
from steuerreport_v2.contracts.bmf_event_price_remediation import (
    BmfEventPriceRemediationRunRequest,
)
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.bmf_event_evidence import BmfFifoEventEvidenceService
from steuerreport_v2.domain.bmf_event_price_remediation import (
    BmfEventPriceRemediationService,
    _CryptoResult,
    _FxResult,
)
from steuerreport_v2.domain.bmf_fifo_staging import BmfCombinedFifoStagingService
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup
from steuerreport_v2.domain.tax import TaxService


def test_event_evidence_request_supports_full_price_review_worklists():
    request = BmfFifoEventEvidenceRunRequest(issue_limit=10_000)

    assert request.issue_limit == 10_000


def _event_evidence_store(
    tmp_path,
    *,
    with_raw: bool = True,
    jup_price_source: str = "unit:independent",
) -> DuckDbStore:
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    mining_at = datetime(2024, 12, 1, tzinfo=timezone.utc)
    swap_at = datetime(2024, 12, 15, tzinfo=timezone.utc)
    raw_ids: list[str | None] = [None, None]
    if with_raw:
        batch = store.create_import_batch(
            ImportBatchCreate(
                source="solana_rpc",
                filename="solana-events.json",
                file_hash="sha256:solana-events",
            )
        )
        raw = store.add_raw_objects(
            batch.batch_id,
            [
                RawObjectCreate(
                    row_number=1,
                    payload_json=json.dumps({"kind": "mining", "tx": "mining-tx"}),
                ),
                RawObjectCreate(
                    row_number=2,
                    payload_json=json.dumps({"kind": "swap", "tx": "swap-tx"}),
                ),
            ],
        )
        raw_ids = [raw[0].raw_object_id, raw[1].raw_object_id]
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                source_ref="mining-tx",
                event_time=mining_at,
                event_type="mining",
                asset="HNT",
                quantity=Decimal("10"),
                wallet="own-wallet",
                tx_id="mining-tx",
                raw_object_id=raw_ids[0],
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                source_ref="swap-tx",
                event_time=swap_at,
                event_type="trade",
                asset="JUP",
                quantity=Decimal("10"),
                quote_asset="HNT",
                quote_quantity=Decimal("5"),
                wallet="own-wallet",
                tx_id="swap-tx",
                raw_object_id=raw_ids[1],
            ),
        ]
    )
    for point in (
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("1"),
            priced_at=mining_at,
            source="unit:independent",
        ),
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("2"),
            priced_at=swap_at,
            source="unit:independent",
        ),
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("1.5"),
            priced_at=swap_at,
            source=jup_price_source,
            confidence=(
                Decimal("0.85")
                if jup_price_source.startswith("derived:")
                else Decimal("1")
            ),
        ),
    ):
        store.add_price_point(point)
    TaxService(store).rebuild_fifo()
    return store


def _run_staging(store: DuckDbStore, tmp_path) -> BmfCombinedFifoStagingService:
    service = BmfCombinedFifoStagingService(
        store,
        artifact_root=tmp_path / "bmf-fifo-staging",
    )
    service.run(
        BmfFifoStagingRunRequest(
            years=[2024],
            as_of=datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        )
    )
    return service


def test_bmf_fifo_event_evidence_binds_raw_price_and_origin_without_writes(tmp_path):
    store = _event_evidence_store(tmp_path)
    staging = _run_staging(store, tmp_path)
    service = BmfFifoEventEvidenceService(
        store,
        artifact_root=tmp_path / "bmf-event-evidence",
        staging_service=staging,
    )
    before_lots = TaxService(store).list_tax_lots()
    before_lines = TaxService(store).list_tax_lines()

    report = service.run(BmfFifoEventEvidenceRunRequest())

    assert report.status == "review"
    assert report.read_only is True
    assert report.strict_ready is False
    assert report.productive_tax_tables_unchanged is True
    assert report.staging_matches_current_tax_component is True
    assert report.staging_matches_current_input is True
    assert report.selected_discrepancy_rows_count == 1
    assert report.unique_events_count == 2
    assert report.ready_events_count == 2
    assert report.review_events_count == 0
    assert report.blocked_events_count == 0
    assert report.raw_evidence_ready_count == 2
    assert report.independent_price_ready_count == 2
    assert report.unresolved_origin_rows_count == 1
    row = report.discrepancy_rows[0]
    assert row.scope_key == "hnt_solana_2024"
    assert row.status == "review"
    assert "origin:potential_business_inventory" in row.issue_codes
    assert row.acquisition_raw_ready_count == 1
    assert report.event_issues == []
    assert service.latest() is not None
    assert TaxService(store).list_tax_lots() == before_lots
    assert TaxService(store).list_tax_lines() == before_lines


def test_bmf_fifo_event_evidence_blocks_missing_raw_evidence(tmp_path):
    store = _event_evidence_store(tmp_path, with_raw=False)
    staging = _run_staging(store, tmp_path)
    report = BmfFifoEventEvidenceService(
        store,
        artifact_root=tmp_path / "bmf-event-evidence",
        staging_service=staging,
    ).run(BmfFifoEventEvidenceRunRequest())

    assert report.status == "blocked"
    assert report.blocked_events_count == 2
    assert report.missing_raw_evidence_count == 2
    assert all(
        "missing_raw_evidence" in row.issue_codes for row in report.event_issues
    )


def test_bmf_fifo_event_evidence_api_run_and_latest(tmp_path):
    store = _event_evidence_store(tmp_path)
    client = TestClient(create_app(store))
    staging = client.post(
        "/api/v1/tax/bmf-combined-fifo-staging/run",
        json={
            "years": [2024],
            "as_of": "2024-12-31T23:59:59Z",
            "limit": 20,
        },
    )

    response = client.post(
        "/api/v1/tax/bmf-fifo-event-evidence/run",
        json={
            "limit": 20,
            "issue_limit": 20,
            "min_abs_delta_eur": "0.01",
            "scope_mode": "full_ledger",
        },
    )
    latest = client.get("/api/v1/tax/bmf-fifo-event-evidence/latest")
    artifact = client.get(
        "/api/v1/tax/bmf-fifo-event-evidence/events.jsonl.gz"
    )

    assert staging.status_code == 200
    assert response.status_code == 200
    assert response.json()["data"]["unique_events_count"] == 2
    assert response.json()["data"]["full_ledger_scope"] is True
    assert latest.status_code == 200
    assert latest.json()["data"]["run_id"] == response.json()["data"]["run_id"]
    assert artifact.status_code == 200
    assert artifact.headers["content-type"] == "application/gzip"
    assert artifact.content.startswith(b"\x1f\x8b")
    assert artifact.headers["x-content-sha256"]


def test_bmf_fifo_event_evidence_full_ledger_archives_every_canonical_event(
    tmp_path,
):
    store = _event_evidence_store(tmp_path)
    staging = _run_staging(store, tmp_path)
    service = BmfFifoEventEvidenceService(
        store,
        artifact_root=tmp_path / "bmf-event-evidence",
        staging_service=staging,
    )

    report = service.run(
        BmfFifoEventEvidenceRunRequest(
            scope_mode="full_ledger",
            limit=1,
            issue_limit=20,
        )
    )

    assert report.full_ledger_scope is True
    assert report.scope_complete_for_staging_artifact is True
    assert report.ledger_events_count == 2
    assert report.tax_graph_events_count == 2
    assert report.tax_graph_missing_events_count == 0
    assert report.unique_events_count == 2
    assert report.documented_business_inventory_rows_count == 1
    assert report.unclassified_origin_rows_count == 0
    business = next(
        row
        for row in report.origin_evidence_groups
        if row.classification == "potential_business_inventory"
    )
    assert business.status == "documented"
    assert business.tax_sphere == "business_inventory"
    artifact = Path(report.all_event_evidence_artifact_path or "")
    assert artifact.exists()
    assert report.all_event_evidence_artifact_sha256
    assert report.all_event_evidence_artifact_bytes == artifact.stat().st_size
    with gzip.open(artifact, "rt", encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle]
    assert len(rows) == 2
    assert {row["event_id"] for row in rows} == {
        event.event_id for event in store.list_canonical_events()
    }
    assert all(row["tax_graph_roles"] for row in rows)


def test_bmf_fifo_event_evidence_documents_opening_balance_limit(tmp_path):
    store = _event_evidence_store(tmp_path)
    event_time = datetime(2024, 12, 1, tzinfo=timezone.utc)
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="opening-balance",
            filename="pionex_hnt_minimum_reconciliation_2022.csv",
            file_hash="sha256:opening-balance",
        )
    )
    raw = store.add_raw_objects(
        batch.batch_id,
        [
            RawObjectCreate(
                row_number=1,
                payload_json=json.dumps(
                    {
                        "asset": "HNT",
                        "amount": "0.16876807",
                        "note": "minimum reconstruction",
                    }
                ),
            )
        ],
    )[0]
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="opening-balance",
                source_ref="pionex-hnt-minimum-reconciliation-2022",
                event_time=event_time,
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("0.16876807"),
                account="pionex",
                tx_id="pionex-hnt-minimum-reconciliation-2022",
                raw_object_id=raw.raw_object_id,
            )
        ]
    )
    staging = _run_staging(store, tmp_path)
    report = BmfFifoEventEvidenceService(
        store,
        artifact_root=tmp_path / "bmf-event-evidence",
        staging_service=staging,
    ).run(
        BmfFifoEventEvidenceRunRequest(
            scope_mode="full_ledger",
            limit=20,
            issue_limit=20,
        )
    )

    assert report.opening_balance_events_count == 1
    opening = report.opening_balance_evidence[0]
    assert opening.documentation_status == "documented_minimum_reconstruction"
    assert opening.original_transaction_available is False
    assert opening.live_balance_effect == "none"
    assert opening.tax_event_effect == "none"
    issue = next(
        row
        for row in report.event_issues
        if row.event_id == opening.event_id
    )
    assert "opening_balance_minimum_reconstruction_documented" in issue.issue_codes
    assert issue.received_price is not None
    assert issue.received_price.quality == "not_required"


def test_bmf_fifo_event_evidence_does_not_require_price_for_zero_unknown_event(
    tmp_path,
):
    store = _event_evidence_store(tmp_path)
    event_time = datetime(2024, 12, 20, tzinfo=timezone.utc)
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="solana_rpc",
            filename="unknown-zero.json",
            file_hash="sha256:unknown-zero",
        )
    )
    raw = store.add_raw_objects(
        batch.batch_id,
        [RawObjectCreate(row_number=1, payload_json=json.dumps({"type": "unknown"}))],
    )[0]
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=event_time,
                event_type="unknown",
                asset="UNPRICED-MINT",
                quantity=Decimal("0"),
                wallet="own-wallet",
                tx_id="unknown-zero-tx",
                raw_object_id=raw.raw_object_id,
            )
        ]
    )
    staging = _run_staging(store, tmp_path)
    report = BmfFifoEventEvidenceService(
        store,
        artifact_root=tmp_path / "bmf-event-evidence",
        staging_service=staging,
    ).run(
        BmfFifoEventEvidenceRunRequest(
            scope_mode="full_ledger",
            limit=20,
            issue_limit=20,
        )
    )

    unknown = next(
        row for row in report.event_issues if row.tx_id == "unknown-zero-tx"
    )
    assert unknown.status == "review"
    assert unknown.received_price is not None
    assert unknown.received_price.quality == "not_required"
    assert "event_type_classification_review" in unknown.issue_codes
    assert "received_price_missing" not in unknown.issue_codes
    assert report.missing_price_count == 0
    assert report.blocked_events_count == 0
    assert report.unknown_event_type_count == 1
    assert report.unknown_tax_graph_events_count == 0


def test_bmf_event_evidence_resolves_raw_origin_markers(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    event_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    definitions = [
        (
            "solana_rpc",
            "solana-swap.json",
            {"defi_label": "swap"},
            "income",
            "HNT",
            "solana-swap",
        ),
        (
            "solana_rpc",
            "solana-reward.json",
            {
                "defi_label": "claim",
                "logs": ["Program log: Instruction: SetCurrentRewardsWrapperV1"],
            },
            "transfer",
            "IOT",
            "solana-reward",
        ),
        (
            "binance",
            "binance.xlsx",
            {"Operation": "Simple Earn Flexible Interest"},
            "income",
            "HNT",
            "binance-interest",
        ),
        (
            "binance",
            "binance.xlsx",
            {"Operation": "Simple Earn Flexible Redemption"},
            "transfer",
            "HNT",
            "binance-redemption",
        ),
        (
            "bitget",
            "Spot Financial Record.csv",
            {"Action": "STRATEGY_TRANSFER_IN", "Type": "Fund transfer"},
            "transfer",
            "HNT",
            "bitget-strategy-transfer",
        ),
        (
            "opening-balance",
            "pionex_hnt_minimum_reconciliation_2022.csv",
            {"type": "opening transfer"},
            "transfer",
            "HNT",
            "pionex-hnt-minimum-reconciliation-2022",
        ),
    ]
    for index, (
        source,
        filename,
        payload,
        event_type,
        asset,
        source_ref,
    ) in enumerate(definitions, start=1):
        batch = store.create_import_batch(
            ImportBatchCreate(
                source=source,
                filename=filename,
                file_hash=f"sha256:{source_ref}",
            )
        )
        raw = store.add_raw_objects(
            batch.batch_id,
            [RawObjectCreate(row_number=1, payload_json=json.dumps(payload))],
        )[0]
        store.add_canonical_events(
            [
                CanonicalEventCreate(
                    source=source,
                    source_ref=source_ref,
                    event_time=event_time,
                    event_type=event_type,
                    asset=asset,
                    quantity=Decimal(index),
                    tx_id=(
                        f"tx-{source_ref}"
                        if source in {"solana_rpc", "bitget"}
                        else None
                    ),
                    raw_object_id=raw.raw_object_id,
                )
            ]
        )

    service = BmfFifoEventEvidenceService(store)
    events = store.list_canonical_events()
    records = service._event_records({event.event_id for event in events})
    resolutions = {
        event.source_ref: service._resolve_origin(records[event.event_id])
        for event in events
    }

    assert resolutions["solana-swap"].classification == "documented_swap_acquisition"
    assert resolutions["solana-swap"].status == "documented"
    assert resolutions["solana-reward"].classification == "potential_business_inventory"
    assert "program:SetCurrentRewardsWrapperV1" in resolutions[
        "solana-reward"
    ].evidence_markers
    assert resolutions["binance-interest"].classification == "separate_income_review"
    assert (
        resolutions["binance-redemption"].classification
        == "internal_transfer_fifo_carry_review"
    )
    assert resolutions["binance-redemption"].fifo_carry_forward_required is True
    assert (
        resolutions["bitget-strategy-transfer"].classification
        == "internal_transfer_fifo_carry_review"
    )
    assert (
        resolutions["pionex-hnt-minimum-reconciliation-2022"].classification
        == "opening_reconstruction_limit"
    )


def test_bmf_event_evidence_uses_raw_resolution_over_staging_classification(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = BmfFifoEventEvidenceService(store)
    source_evidence = BmfEventSourceEvidence(
        raw_object_id="raw-1",
        batch_id="batch-1",
        identifier_kind="raw_batch_row",
        identifier_value="batch-1:1",
        status="ready",
    )
    acquisition = BmfCanonicalEventEvidence(
        event_id="acquisition",
        event_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        source="solana_rpc",
        event_type="income",
        asset="CBDC",
        quantity=Decimal("10"),
        source_evidence=source_evidence,
        origin_resolution=BmfOriginResolution(
            classification="documented_swap_acquisition",
            status="documented",
            tax_sphere="private_acquisition",
            evidence_markers=["raw:defi_label=swap"],
            decision_basis="Raw-Beleg kennzeichnet einen Swap.",
        ),
        status="ready",
        evidence_digest="acquisition-digest",
    )
    disposal = BmfCanonicalEventEvidence(
        event_id="disposal",
        event_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
        source="solana_rpc",
        event_type="trade",
        asset="HNT",
        quantity=Decimal("-5"),
        source_evidence=source_evidence,
        status="ready",
        evidence_digest="disposal-digest",
    )
    staging_row = BmfCombinedFifoEventRow(
        year=2024,
        asset="HNT",
        disposal_event_id="disposal",
        disposed_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
        acquisition_source_event_ids=["acquisition"],
        origin_classifications=["origin_classification_review"],
    )

    resolved = service._discrepancy_row(
        staging_row,
        {"acquisition": acquisition, "disposal": disposal},
    )

    assert resolved.origin_classifications == ["documented_swap_acquisition"]
    assert "origin:origin_classification_review" not in resolved.issue_codes
    assert resolved.status == "ready"
    groups = service._origin_evidence_groups(
        [staging_row],
        {"acquisition": acquisition, "disposal": disposal},
    )
    assert groups[0].asset == "HNT"
    assert groups[0].canonical_event_assets == ["CBDC"]


def _mock_fx(price_date):
    return _FxResult(
        rate=Decimal("0.92"),
        rate_date=price_date,
        request_url=f"https://fx.test/{price_date}",
        response_sha256="fx-sha256",
        payload=[{"date": price_date.isoformat(), "rate": 0.92}],
    )


def _mock_crypto(price_date):
    provider_timestamp = datetime.combine(
        price_date,
        datetime.min.time(),
        tzinfo=timezone.utc,
    )
    return (
        _CryptoResult(
            price_usd=Decimal("1.75"),
            provider_id="coingecko:jupiter-exchange-solana",
            provider_timestamp=provider_timestamp,
            confidence=Decimal("0.99"),
            request_url=f"https://coins.test/{price_date}/jup",
            response_sha256="crypto-sha256",
            payload={"coins": {"coingecko:jupiter-exchange-solana": {"price": 1.75}}},
        ),
        1,
    )


def test_bmf_event_price_remediation_dry_run_and_apply_are_tax_read_only(
    tmp_path,
    monkeypatch,
):
    store = _event_evidence_store(
        tmp_path,
        jup_price_source="derived:event_quote",
    )
    staging = _run_staging(store, tmp_path)
    event_service = BmfFifoEventEvidenceService(
        store,
        artifact_root=tmp_path / "bmf-event-evidence",
        staging_service=staging,
    )
    evidence_before = event_service.run(
        BmfFifoEventEvidenceRunRequest(scope_mode="full_ledger")
    )
    service = BmfEventPriceRemediationService(
        store,
        artifact_root=tmp_path / "bmf-event-price-remediation",
        event_evidence_service=event_service,
    )
    monkeypatch.setattr(service, "_fetch_fx", lambda _client, price_date: _mock_fx(price_date))
    monkeypatch.setattr(
        service,
        "_fetch_crypto",
        lambda _client, price_date, _config: _mock_crypto(price_date),
    )
    before_lots = TaxService(store).list_tax_lots()
    before_lines = TaxService(store).list_tax_lines()
    before_price_count = service._price_points_count()

    preview = service.run(BmfEventPriceRemediationRunRequest(execute=False))

    assert preview.status == "planned"
    assert preview.requirements_count == 1
    assert preview.planned_count == 1
    assert preview.imported_count == 0
    assert preview.price_points_count_after == before_price_count

    applied = service.run(BmfEventPriceRemediationRunRequest(execute=True))

    assert applied.status == "applied"
    assert applied.imported_count == 1
    assert applied.price_points_count_after == before_price_count + 1
    assert applied.productive_tax_tables_unchanged is True
    assert applied.after_derived_price_review_count == 0
    assert applied.after_stale_price_review_count == 0
    assert applied.after_review_events_count == 0
    assert applied.event_evidence_run_id_before == evidence_before.run_id
    assert TaxService(store).list_tax_lots() == before_lots
    assert TaxService(store).list_tax_lines() == before_lines
    after_evidence = event_service.latest()
    assert after_evidence is not None
    assert after_evidence.full_ledger_scope is True
    assert after_evidence.staging_matches_current_input is False
    assert after_evidence.status == "blocked"


def test_bmf_event_price_remediation_api_dry_run(tmp_path, monkeypatch):
    store = _event_evidence_store(
        tmp_path,
        jup_price_source="derived:event_quote",
    )
    BmfCombinedFifoStagingService(store).run(
        BmfFifoStagingRunRequest(
            years=[2024],
            as_of=datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        )
    )
    BmfFifoEventEvidenceService(store).run(BmfFifoEventEvidenceRunRequest())
    monkeypatch.setattr(
        BmfEventPriceRemediationService,
        "_fetch_fx",
        lambda _self, _client, price_date: _mock_fx(price_date),
    )
    monkeypatch.setattr(
        BmfEventPriceRemediationService,
        "_fetch_crypto",
        lambda _self, _client, price_date, _config: _mock_crypto(price_date),
    )
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/tax/bmf-event-price-remediation/run",
        json={"execute": False, "max_jobs": 20},
    )
    latest = client.get("/api/v1/tax/bmf-event-price-remediation/latest")

    assert response.status_code == 200
    assert response.json()["data"]["planned_count"] == 1
    assert latest.status_code == 200
    assert latest.json()["data"]["run_id"] == response.json()["data"]["run_id"]


def test_bmf_event_price_remediation_blocks_spam_review_token(tmp_path, monkeypatch):
    store = _event_evidence_store(
        tmp_path,
        jup_price_source="derived:event_quote",
    )
    with store.connect() as con:
        con.execute(
            """
            insert into jupiter_token_metadata_cache (
                mint, symbol, name, decimals, is_verified, organic_score,
                organic_score_label, holder_count, liquidity_usd, usd_price,
                market_cap_usd, risk_status, source, discovered_sources_json,
                refreshed_at
            ) values (
                'jup-test-mint', 'JUP', 'Risky JUP', 6, false, 0,
                'low', 1, 1, 1, 1, 'spam_review', 'unit', '[]', ?
            )
            """,
            [datetime.now(timezone.utc)],
        )
    staging = _run_staging(store, tmp_path)
    event_service = BmfFifoEventEvidenceService(
        store,
        artifact_root=tmp_path / "bmf-event-evidence",
        staging_service=staging,
    )
    event_service.run(BmfFifoEventEvidenceRunRequest())
    service = BmfEventPriceRemediationService(
        store,
        artifact_root=tmp_path / "bmf-event-price-remediation",
        event_evidence_service=event_service,
    )
    monkeypatch.setattr(
        service,
        "_fetch_fx",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("spam_review must be blocked before provider access")
        ),
    )

    report = service.run(BmfEventPriceRemediationRunRequest(execute=True))

    assert report.status == "blocked"
    assert report.token_risk_blocked_count == 1
    assert report.imported_count == 0
    assert report.jobs[0].status == "token_risk_blocked"
    assert report.jobs[0].token_risk_status == "spam_review"


def test_bmf_event_evidence_binds_synthetic_fee_to_parent_raw_event(tmp_path):
    store = _event_evidence_store(tmp_path)
    service = BmfFifoEventEvidenceService(store)
    disposed_at = datetime(2024, 12, 15, tzinfo=timezone.utc)
    synthetic_id = "external:swap-tx:fee"
    row = BmfCombinedFifoEventRow(
        year=2024,
        asset="JUP",
        disposal_event_id=synthetic_id,
        disposed_at=disposed_at,
        active_wallet_quantity=Decimal("0.25"),
        received_first_wallet_quantity=Decimal("0.25"),
    )

    parents = service._synthetic_fee_parent_records({synthetic_id: row})
    evidence = service._synthetic_fee_evidence(
        synthetic_id,
        row,
        parents[synthetic_id],
        HistoricalPriceLookup(store),
    )

    assert evidence.status == "review"
    assert evidence.event_type == "fee"
    assert evidence.quantity == Decimal("-0.25")
    assert evidence.synthetic_derivation == "wallet_fifo_explicit_transfer_fee"
    assert evidence.parent_event_ids
    assert evidence.source_evidence.raw_object_id is not None
    assert evidence.given_price is not None
    assert evidence.given_price.quality == "independent_current"
    assert "synthetic_fee_parent_evidence_review" in evidence.issue_codes
    assert "missing_canonical_event" not in evidence.issue_codes
