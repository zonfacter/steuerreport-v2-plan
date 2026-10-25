from datetime import datetime, timezone
from decimal import Decimal
import json

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.portfolio import PortfolioLiveBalanceSnapshot
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.source_registry import SourceRegistryService
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


WALLET = "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"


def _config(
    path,
    *,
    coverage_status="complete",
    include_legacy=False,
    ledger_adjustments=None,
    portfolio_policy="include",
    source_id="main-wallet",
    account=WALLET,
):
    entries = [
        {
            "source_id": source_id,
            "label": "Main Wallet",
            "source_type": "wallet",
            "ownership": "owned",
            "role": "portfolio",
            "portfolio_policy": portfolio_policy,
            "fifo_policy": "owned_pool",
            "valid_from": "2025-01-01T00:00:00Z",
            "valid_to": None,
            "coverage_status": coverage_status,
            "coverage_from": "2025-01-01T00:00:00Z",
            "coverage_to": "2025-12-31T23:59:59Z",
            "identifiers": [{"kind": "account", "value": account}],
            "evidence_refs": ["test-evidence"],
        }
    ]
    if include_legacy:
        entries.append(
            {
                "source_id": "legacy",
                "label": "Legacy",
                "source_type": "legacy_wallet",
                "ownership": "infrastructure",
                "role": "historical_transfer",
                "portfolio_policy": "exclude",
                "fifo_policy": "evidence_only",
                "valid_from": "2025-01-01T00:00:00Z",
                "valid_to": None,
                "coverage_status": "evidence_only",
                "coverage_from": None,
                "coverage_to": None,
                "identifiers": [{"kind": "account", "value": "legacy"}],
                "evidence_refs": ["legacy-evidence"],
            }
        )
    path.write_text(
        json.dumps(
            {
                "registry_version": "test-v1",
                "entries": entries,
                "ledger_adjustments": ledger_adjustments or [],
            }
        ),
        encoding="utf-8",
    )
    return path


def _store(tmp_path, *, account=WALLET, quantity="1"):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="JUP",
                quantity=Decimal(quantity),
                account=account,
            )
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("1"),
            priced_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            source="test",
        )
    )
    BalanceLedgerBuilder(store).rebuild()
    return store


def test_source_registry_is_strict_only_for_registered_complete_matching_source(tmp_path):
    store = _store(tmp_path)
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="solana_wallet:JUP:matching",
                connector_id="solana_wallet",
                source="test",
                asset="JUP",
                quantity=Decimal("1"),
                fetched_at=datetime.now(timezone.utc),
            )
        ]
    )
    config_path = _config(tmp_path / "source_registry.json")
    service = SourceRegistryService(
        store,
        config_path=config_path,
        artifact_root=tmp_path / "registry-runs",
    )

    report = service.run()

    assert report.status == "strict_ready"
    assert report.strict_ready is True
    assert report.unregistered_observations_count == 0
    assert report.portfolio_policy_violations_count == 0
    assert report.entries[0].observed_events_count == 1
    assert report.entries[0].quantity_gate_status == "matched"
    assert service.latest() == report


def test_source_registry_separates_provider_user_and_documented_route_gaps(
    tmp_path,
):
    store = _store(tmp_path)
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="solana_wallet:JUP:matching",
                connector_id="solana_wallet",
                source="test",
                asset="JUP",
                quantity=Decimal("1"),
                fetched_at=datetime.now(timezone.utc),
            )
        ]
    )
    config_path = _config(tmp_path / "source_registry.json")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["entries"].extend(
        [
            {
                "source_id": "provider-limited-exchange",
                "label": "Provider Limited Exchange",
                "source_type": "exchange",
                "ownership": "owned",
                "role": "exchange_account",
                "portfolio_policy": "exclude",
                "fifo_policy": "owned_pool",
                "valid_from": "2024-01-01T00:00:00Z",
                "coverage_status": "partial",
                "coverage_limitation": "provider_api_history_boundary",
                "additional_user_evidence_required": False,
                "identifiers": [{"kind": "account", "value": "provider-limited"}],
                "evidence_refs": ["provider-doc"],
            },
            {
                "source_id": "missing-history-exchange",
                "label": "Missing History Exchange",
                "source_type": "exchange",
                "ownership": "owned",
                "role": "exchange_account",
                "portfolio_policy": "exclude",
                "fifo_policy": "owned_pool",
                "valid_from": "2025-01-01T00:00:00Z",
                "coverage_status": "partial",
                "coverage_limitation": "missing_original_account_history",
                "additional_user_evidence_required": True,
                "identifiers": [{"kind": "account", "value": "missing-history"}],
                "evidence_refs": ["bank-payment-only"],
            },
            {
                "source_id": "historical-service-route",
                "label": "Historical Service Route",
                "source_type": "service",
                "ownership": "infrastructure",
                "role": "historical_staking_transfer",
                "portfolio_policy": "exclude",
                "fifo_policy": "transfer_bridge",
                "valid_from": "2021-01-01T00:00:00Z",
                "valid_to": "2021-02-01T00:00:00Z",
                "coverage_status": "evidence_only",
                "coverage_limitation": "documented_transfer_route_only",
                "additional_user_evidence_required": False,
                "identifiers": [{"kind": "account", "value": "service-route"}],
                "evidence_refs": ["transfer-proof"],
            },
        ]
    )
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    report = SourceRegistryService(
        store,
        config_path=config_path,
        artifact_root=tmp_path / "registry-runs",
    ).run()

    rows = {row.source_id: row for row in report.entries}
    assert report.strict_ready is False
    assert report.invalid_entries == []
    assert report.provider_coverage_gap_entries_count == 1
    assert report.user_evidence_gap_entries_count == 1
    assert report.documented_route_entries_count == 1
    assert rows["provider-limited-exchange"].coverage_gate_status == "provider_gap"
    assert rows["provider-limited-exchange"].additional_user_evidence_required is False
    assert rows["missing-history-exchange"].coverage_gate_status == "missing_evidence"
    assert rows["missing-history-exchange"].additional_user_evidence_required is True
    assert rows["historical-service-route"].coverage_gate_status == "documented_route"
    assert rows["historical-service-route"].strict_ready is True
    assert any("identische bereits gelieferte" in item for item in report.next_actions)
    assert any("originale Account-History" in item for item in report.next_actions)


def test_source_registry_blocks_material_live_vs_ledger_quantity_delta(tmp_path):
    store = _store(tmp_path, quantity="100")
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="solana_wallet:JUP:test",
                connector_id="solana_wallet",
                source="test",
                asset="JUP",
                quantity=Decimal("1"),
                fetched_at=datetime.now(timezone.utc),
            )
        ]
    )
    service = SourceRegistryService(
        store,
        config_path=_config(tmp_path / "source_registry.json"),
        artifact_root=tmp_path / "registry-runs",
    )

    report = service.run()

    assert report.strict_ready is False
    assert report.quantity_blocker_entries_count == 1
    assert report.entries[0].quantity_gate_status == "blocked"
    assert report.entries[0].quantity_deltas[0].asset == "JUP"
    assert report.entries[0].quantity_deltas[0].quantity_delta == Decimal("-99")


def test_source_registry_explains_expected_zero_live_balance_without_false_delta(
    tmp_path,
):
    store = _store(tmp_path, quantity="2")
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="solana_wallet:JUP:test",
                connector_id="solana_wallet",
                source="test",
                asset="JUP",
                quantity=Decimal("2"),
                fetched_at=datetime.now(timezone.utc),
            )
        ]
    )
    service = SourceRegistryService(
        store,
        config_path=_config(
            tmp_path / "source_registry.json",
            portfolio_policy="expected_zero",
        ),
        artifact_root=tmp_path / "registry-runs",
    )

    report = service.run()

    row = report.entries[0]
    assert row.quantity_gate_status == "review"
    assert row.current_value_delta_eur == Decimal("0")
    assert row.quantity_deltas == []
    assert row.findings == [
        "Live-Bestand ueber 1 EUR widerspricht der Registry-Policy expected_zero."
    ]
    assert report.next_actions == [
        "Main Wallet: erwarteten Nullbestand gegen aktuellen Plattformbeleg "
        "pruefen oder Registry-Policy fachlich anpassen."
    ]


def test_source_registry_marks_stale_cex_snapshot_as_ledger_fallback(tmp_path):
    store = _store(tmp_path, account="pionex", quantity="2")
    stale_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="pionex:JUP:stale",
                connector_id="pionex",
                source="pionex_api_v2",
                asset="JUP",
                quantity=Decimal("2"),
                fetched_at=stale_at,
            )
        ]
    )
    service = SourceRegistryService(
        store,
        config_path=_config(
            tmp_path / "source_registry.json",
            portfolio_policy="expected_zero",
            source_id="pionex-account",
            account="pionex",
        ),
        artifact_root=tmp_path / "registry-runs",
    )

    report = service.run()

    row = report.entries[0]
    assert row.live_snapshot_status == "stale"
    assert row.latest_live_snapshot_at == stale_at
    assert row.live_balance_basis == "ledger_fallback"
    assert row.quantity_gate_status == "review"
    assert row.current_live_anchored_value_eur == row.current_reconciled_ledger_value_eur
    assert row.current_value_delta_eur == Decimal("0")
    assert row.quantity_deltas == []
    assert "der angezeigte Wert ist nur der Ledger-Fallback" in row.findings[0]
    assert report.next_actions == [
        "Main Wallet: Connector-Live-Snapshot aktualisieren; "
        "Ledger-Fallback nicht als Livebestand auslegen."
    ]


def test_source_registry_surfaces_failed_refresh_instead_of_refresh_loop(tmp_path):
    store = _store(tmp_path, account="pionex", quantity="2")
    stale_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
    attempted_at = datetime.now(timezone.utc)
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="pionex:JUP:stale-before-error",
                connector_id="pionex",
                source="pionex_api_v2",
                asset="JUP",
                quantity=Decimal("2"),
                fetched_at=stale_at,
            )
        ]
    )
    with store.connect() as con:
        con.execute(
            """
            insert into portfolio_live_connector_runs (
                run_id, connector_id, fetched_at, status, snapshots_count,
                source, message
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                "pionex-expired-key-registry-test",
                "pionex",
                attempted_at,
                "connector_error",
                0,
                "pionex_api_v2",
                "V2-pionex-Liveabruf fehlgeschlagen: APIKEY_EXPIRED",
            ],
        )
    service = SourceRegistryService(
        store,
        config_path=_config(
            tmp_path / "source_registry.json",
            portfolio_policy="expected_zero",
            source_id="pionex-account",
            account="pionex",
        ),
        artifact_root=tmp_path / "registry-runs",
    )

    report = service.run()

    row = report.entries[0]
    assert row.last_connector_attempt is not None
    assert row.last_connector_attempt.status == "connector_error"
    assert any("APIKEY_EXPIRED" in finding for finding in row.findings)
    assert report.next_actions == [
        "Main Wallet: API-Key/Secret fuer diese Quelle im V2 Secret Store "
        "erneuern und danach den Sammelabruf erneut starten; alten Snapshot nur "
        "als historische Referenz behandeln."
    ]


def test_source_registry_applies_evidence_bound_transfer_adjustment_without_hiding_raw_ledger(tmp_path):
    store = _store(tmp_path, quantity="100")
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="solana_wallet:JUP:test",
                connector_id="solana_wallet",
                source="test",
                asset="JUP",
                quantity=Decimal("1"),
                fetched_at=datetime.now(timezone.utc),
            )
        ]
    )
    adjustment = {
        "adjustment_id": "main-to-cex-jup",
        "source_id": "main-wallet",
        "event_time": "2025-06-01T00:00:00Z",
        "asset": "JUP",
        "quantity_delta": "-99",
        "tx_id": "solana-transfer-tx",
        "reason": "missing_transfer_counterpart",
        "review_status": "approved_evidence_overlay",
        "evidence_refs": ["evidence.json"],
    }
    service = SourceRegistryService(
        store,
        config_path=_config(
            tmp_path / "source_registry.json",
            ledger_adjustments=[adjustment],
        ),
        artifact_root=tmp_path / "registry-runs",
    )

    report = service.run()

    row = report.entries[0]
    assert report.ledger_adjustments_count == 1
    assert report.applied_ledger_adjustments_count == 1
    assert row.current_ledger_value_eur == Decimal("100")
    assert row.current_ledger_adjustment_value_eur == Decimal("-99")
    assert row.current_reconciled_ledger_value_eur == Decimal("1")
    assert row.current_live_anchored_value_eur == Decimal("1")
    assert row.current_value_delta_eur == Decimal("0")
    assert row.quantity_gate_status == "matched"
    assert row.quantity_deltas == []
    assert row.ledger_adjustments[0].tx_id == "solana-transfer-tx"


def test_source_registry_blocks_excluded_legacy_account_in_portfolio(tmp_path):
    store = _store(tmp_path, account="legacy", quantity="20")
    config_path = _config(tmp_path / "source_registry.json", include_legacy=True)
    service = SourceRegistryService(
        store,
        config_path=config_path,
        artifact_root=tmp_path / "registry-runs",
    )

    report = service.run()

    assert report.strict_ready is False
    assert report.portfolio_policy_violations_count == 1
    assert "Ausgeschlossene Quelle im Portfolio" in report.portfolio_policy_violations[0]


def test_source_registry_api_exposes_config_run_and_latest(tmp_path, monkeypatch):
    store = _store(tmp_path)
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="solana_wallet:JUP:api",
                connector_id="solana_wallet",
                source="test",
                asset="JUP",
                quantity=Decimal("1"),
                fetched_at=datetime.now(timezone.utc),
            )
        ]
    )
    config_path = _config(tmp_path / "source_registry.json")
    monkeypatch.setattr(SourceRegistryService, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(SourceRegistryService, "DEFAULT_ARTIFACT_ROOT", tmp_path / "registry-runs")
    client = TestClient(create_app(store))

    config = client.get("/api/v1/sources/registry/config")
    run = client.post("/api/v1/sources/registry/runs")
    latest = client.get("/api/v1/sources/registry/runs/latest")

    assert config.status_code == 200
    assert config.json()["data"]["registry_version"] == "test-v1"
    assert run.status_code == 200
    assert run.json()["data"]["strict_ready"] is True
    assert latest.status_code == 200
    assert latest.json()["data"]["semantic_sha256"] == run.json()["data"]["semantic_sha256"]


def test_source_registry_separates_binance_uncredited_earn_accrual(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2026, 7, 17, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("10"),
                account="Spot",
            )
        ]
    )
    priced_at = datetime.now(timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("70"),
            priced_at=priced_at,
            source="test",
        )
    )
    BalanceLedgerBuilder(store).rebuild()
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="binance:SOL:locked",
                connector_id="binance",
                source="binance_api",
                asset="SOL",
                quantity=Decimal("10"),
                fetched_at=priced_at,
                account_type="simple_earn_locked",
                product_id="Sol*120",
                event_type="balance_snapshot",
            ),
            PortfolioLiveBalanceSnapshot(
                snapshot_id="binance:SOL:accrual",
                connector_id="binance",
                source="binance_api",
                asset="SOL",
                quantity=Decimal("0.1"),
                fetched_at=priced_at,
                account_type="simple_earn_locked",
                product_id="Sol*120",
                event_type="earn_accrued_reward_snapshot",
            ),
        ]
    )
    config_path = tmp_path / "source_registry.json"
    config_path.write_text(
        json.dumps(
            {
                "registry_version": "test-binance-accrual-v1",
                "entries": [
                    {
                        "source_id": "binance-account",
                        "label": "Binance Account",
                        "source_type": "exchange",
                        "ownership": "owned",
                        "role": "exchange_account",
                        "portfolio_policy": "include",
                        "fifo_policy": "owned_pool",
                        "valid_from": "2021-01-01T00:00:00Z",
                        "coverage_status": "complete",
                        "coverage_from": "2021-01-01T00:00:00Z",
                        "coverage_to": "2026-07-18T23:59:59Z",
                        "identifiers": [
                            {"kind": "canonical_source", "value": "binance"},
                            {"kind": "account", "value": "Spot"},
                            {
                                "kind": "account",
                                "value": "Binance Earn Locked Sol*120",
                            },
                            {
                                "kind": "account",
                                "value": "Binance Earn Rewards Sol*120",
                            },
                        ],
                        "evidence_refs": ["binance-api-test"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    service = SourceRegistryService(
        store,
        config_path=config_path,
        artifact_root=tmp_path / "registry-runs",
    )

    report = service.run()

    row = report.entries[0]
    assert row.quantity_gate_status == "matched"
    assert row.current_ledger_value_eur == Decimal("700.0000000000000000000000000")
    assert row.current_live_anchored_value_eur == Decimal("707.0000000000000000000000000")
    assert row.current_live_nonledger_accrual_value_eur == Decimal("7.0000000000000000000")
    assert row.current_reconciliation_live_value_eur == Decimal(
        "700.0000000000000000000000000"
    )
    assert row.current_value_delta_eur == Decimal("0E-25")
    assert len(row.quantity_deltas) == 1
    delta = row.quantity_deltas[0]
    assert delta.raw_live_anchored_quantity == Decimal("10.100000000000000000")
    assert delta.live_nonledger_accrual_quantity == Decimal("0.100000000000000000")
    assert delta.live_anchored_quantity == Decimal("10.000000000000000000")
    assert delta.quantity_delta == Decimal("0E-18")
