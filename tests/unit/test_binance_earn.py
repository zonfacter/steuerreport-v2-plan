from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.binance_earn import (
    BinanceAssetDividendPreview,
    BinanceAssetDividendRecord,
    BinanceCapitalWithdrawalPreview,
    BinanceCapitalWithdrawalRecord,
    BinanceEarnHistoryApiPreview,
    BinanceEarnHistoryApiRecord,
)
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.portfolio import PortfolioLiveBalanceSnapshot
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.binance_earn import BinanceEarnHistoryService
from steuerreport_v2.domain.binance_earn_fifo import (
    locked_redemption_clawback_reward_event_ids,
)
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer


def _seed_earn_products(store: DuckDbStore) -> None:
    priced_at = datetime(2026, 5, 30, tzinfo=timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("0.2"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="binance:JUP:earn",
                connector_id="binance",
                asset="JUP",
                quantity=Decimal("40"),
                source="v1_connector:binance",
                fetched_at=priced_at,
                account_type="simple_earn_flexible",
                product_id="JUP001",
            )
        ]
    )


def _seed_locked_earn_product(store: DuckDbStore) -> None:
    priced_at = datetime(2026, 5, 30, tzinfo=timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("70"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="binance:SOL:locked",
                connector_id="binance",
                asset="SOL",
                quantity=Decimal("9.84"),
                source="v1_connector:binance",
                fetched_at=priced_at,
                account_type="simple_earn_locked",
                product_id="Sol*120",
                position_id="current-position",
            )
        ]
    )


def test_binance_earn_history_api_preview_reports_missing_credentials(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _seed_earn_products(store)

    report = BinanceEarnHistoryService(store).api_preview()

    assert report.credential_status == "missing"
    assert report.records_returned == 0
    assert report.requests == []


def test_binance_withdraw_history_api_preview_fetches_capital_records(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(BinanceEarnHistoryService, "_credentials", lambda _self: ("key", "secret"))

    def fake_signed_get_any(_self, _api_key, _secret_key, endpoint, params):
        assert endpoint == "/sapi/v1/capital/withdraw/history"
        assert params["coin"] == "JUP"
        return [
            {
                "coin": "JUP",
                "amount": "5532.275703",
                "address": "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY",
                "txId": "withdraw-tx",
                "network": "SOL",
                "applyTime": "2025-03-23 15:49:42",
            }
        ]

    monkeypatch.setattr(BinanceEarnHistoryService, "_signed_get_any", fake_signed_get_any)

    report = BinanceEarnHistoryService(store).withdrawal_history_api_preview(
        since=datetime(2025, 3, 23, tzinfo=timezone.utc),
        until=datetime(2025, 3, 24, tzinfo=timezone.utc),
        assets=["JUP"],
    )

    assert report.credential_status == "configured"
    assert report.records_returned == 1
    assert report.records[0].payload["txId"] == "withdraw-tx"
    assert report.requests[0].status == "ok"


def test_binance_earn_history_api_preview_fetches_flexible_history(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _seed_earn_products(store)
    monkeypatch.setattr(BinanceEarnHistoryService, "_credentials", lambda _self: ("key", "secret"))

    def fake_signed_get(_self, _api_key, _secret_key, endpoint, params):
        assert params["asset"] == "JUP"
        if endpoint.endswith("/subscriptionRecord"):
            return {
                "total": 1,
                "rows": [
                    {
                        "asset": "JUP",
                        "amount": "40",
                        "productId": "JUP001",
                        "time": 1735689600000,
                    }
                ],
            }
        return {"total": 0, "rows": []}

    monkeypatch.setattr(BinanceEarnHistoryService, "_signed_get", fake_signed_get)

    report = BinanceEarnHistoryService(store).api_preview(
        since=datetime(2025, 1, 1, tzinfo=timezone.utc),
        until=datetime(2025, 1, 2, tzinfo=timezone.utc),
        max_pages=2,
    )

    assert report.credential_status == "configured"
    assert report.records_returned == 1
    assert len(report.requests) == 5
    assert report.records[0].record_type == "flexible_subscription"
    assert report.records[0].payload["amount"] == "40"


def test_binance_earn_history_api_preview_keeps_redeemed_historical_product_queryable(
    tmp_path, monkeypatch
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    CsvRawImporter(store).import_text(
        source="binance_simple_earn_api",
        filename="binance-simple-earn-api-20260101-20260613-JUP.json",
        content=(
            "time_iso,asset,rewards,record_type,account_type,product_id,source_ref\n"
            "2026-06-13T23:59:59Z,JUP,0.3,flexible_rewards_realtime,"
            "simple_earn_flexible,JUP001,reward-old\n"
        ),
    )
    monkeypatch.setattr(
        BinanceEarnHistoryService,
        "_credentials",
        lambda _self: ("key", "secret"),
    )

    def fake_signed_get(_self, _api_key, _secret_key, endpoint, params):
        assert params["asset"] == "JUP"
        assert params["productId"] == "JUP001"
        if endpoint.endswith("/rewardsRecord") and params.get("type") == "REALTIME":
            return {
                "total": 1,
                "rows": [
                    {
                        "asset": "JUP",
                        "rewards": "0.35",
                        "productId": "JUP001",
                        "time": 1781481599000,
                    }
                ],
            }
        return {"total": 0, "rows": []}

    monkeypatch.setattr(BinanceEarnHistoryService, "_signed_get", fake_signed_get)

    report = BinanceEarnHistoryService(store).api_preview(
        since=datetime(2026, 6, 14, tzinfo=timezone.utc),
        until=datetime(2026, 6, 15, tzinfo=timezone.utc),
        assets=["JUP"],
        max_pages=2,
    )

    assert report.assets == ["JUP"]
    assert len(report.requests) == 5
    assert report.records_returned == 1
    assert report.records[0].record_type == "flexible_rewards_realtime"


def test_binance_earn_history_api_preview_fetches_locked_redemptions_for_discovered_positions(
    tmp_path,
    monkeypatch,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _seed_locked_earn_product(store)
    monkeypatch.setattr(BinanceEarnHistoryService, "_credentials", lambda _self: ("key", "secret"))
    calls: list[tuple[str, str | None]] = []

    def fake_signed_get(_self, _api_key, _secret_key, endpoint, params):
        calls.append((endpoint, str(params.get("positionId")) if params.get("positionId") else None))
        if endpoint.endswith("/subscriptionRecord"):
            return {
                "total": 1,
                "rows": [
                    {
                        "asset": "SOL",
                        "amount": "1.4",
                        "productId": "Sol*120",
                        "positionId": "old-position",
                        "time": 1707463405000,
                    }
                ],
            }
        if endpoint.endswith("/redemptionRecord") and params.get("positionId") == "old-position":
            return {
                "total": 1,
                "rows": [
                    {
                        "asset": "SOL",
                        "amount": "1.4",
                        "positionId": "old-position",
                        "redeemId": 42,
                        "time": 1710000000000,
                    }
                ],
            }
        return {"total": 0, "rows": []}

    monkeypatch.setattr(BinanceEarnHistoryService, "_signed_get", fake_signed_get)

    report = BinanceEarnHistoryService(store).api_preview(
        since=datetime(2024, 1, 1, tzinfo=timezone.utc),
        until=datetime(2024, 1, 2, tzinfo=timezone.utc),
        max_pages=2,
    )

    assert ("https://api.binance.com", None) not in calls
    redemption_calls = [position_id for endpoint, position_id in calls if endpoint.endswith("/redemptionRecord")]
    assert redemption_calls == ["current-position", "old-position"]
    assert [record.record_type for record in report.records] == [
        "locked_subscription",
        "locked_redemption",
    ]


def test_binance_earn_history_api_preview_endpoint(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _seed_earn_products(store)
    monkeypatch.setattr(BinanceEarnHistoryService, "_credentials", lambda _self: ("key", "secret"))
    monkeypatch.setattr(
        BinanceEarnHistoryService,
        "_signed_get",
        lambda *_args, **_kwargs: {"total": 0, "rows": []},
    )

    response = TestClient(create_app(store)).get(
        "/api/v1/sources/binance/earn-history-api-preview?since=2025-01-01&assets=JUP"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["credential_status"] == "configured"
    assert data["assets"] == ["JUP"]


def test_binance_earn_harvest_import_preview_and_execute(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    harvest = tmp_path / "harvest.json"
    harvest.write_text(
        """
        {
          "records": [
            {
              "record_type": "flexible_subscription",
              "asset": "JUP",
              "product_id": "JUP001",
              "payload": {
                "asset": "JUP",
                "amount": "10",
                "productId": "JUP001",
                "purchaseId": 1,
                "status": "SUCCESS",
                "time": 1735689600000
              }
            },
            {
              "record_type": "flexible_rewards_realtime",
              "asset": "JUP",
              "product_id": "JUP001",
              "payload": {
                "asset": "JUP",
                "rewards": "0.5",
                "productId": "JUP001",
                "time": 1735776000000,
                "type": "REALTIME"
              }
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    service = BinanceEarnHistoryService(store)
    preview = service.preview_harvest_import(str(harvest))

    assert preview.can_execute is True
    assert preview.rows_prepared == 2
    assert preview.record_types == {
        "flexible_rewards_realtime": 1,
        "flexible_subscription": 1,
    }

    result = service.import_harvest(str(harvest), execute=True)

    assert result.batch is not None
    assert result.batch.source == "binance_simple_earn_api"
    assert result.run is not None
    assert result.run.normalized_events == 3
    events = store.list_canonical_events(result.batch.batch_id)
    transfers = [event for event in events if event.event_type == "transfer"]
    rewards = [event for event in events if event.event_type == "reward"]
    assert sum((event.quantity for event in transfers), Decimal("0")) == Decimal("0")
    assert {(event.account, event.quantity) for event in transfers} == {
        ("Binance Earn Flexible JUP001", Decimal("10")),
        ("Spot", Decimal("-10")),
    }
    assert [(event.asset, event.quantity) for event in rewards] == [
        ("JUP", Decimal("0.5")),
    ]


def test_binance_earn_harvest_import_skips_existing_source_refs(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    first = tmp_path / "first.json"
    first.write_text(
        """
        {"records": [{
          "record_type": "flexible_subscription",
          "asset": "JUP",
          "product_id": "JUP001",
          "payload": {"asset": "JUP", "amount": "10", "productId": "JUP001", "purchaseId": 1, "time": 1735689600000}
        }]}
        """,
        encoding="utf-8",
    )
    service = BinanceEarnHistoryService(store)
    first_result = service.import_harvest(str(first), execute=True)
    assert first_result.run is not None

    second = tmp_path / "second.json"
    second.write_text(
        """
        {"records": [
          {
            "record_type": "flexible_subscription",
            "asset": "JUP",
            "product_id": "JUP001",
            "payload": {"asset": "JUP", "amount": "10", "productId": "JUP001", "purchaseId": 1, "time": 1735689600000}
          },
          {
            "record_type": "flexible_rewards_realtime",
            "asset": "JUP",
            "product_id": "JUP001",
            "payload": {"asset": "JUP", "rewards": "0.5", "productId": "JUP001", "time": 1735776000000}
          }
        ]}
        """,
        encoding="utf-8",
    )

    preview = service.preview_harvest_import(str(second))

    assert preview.records_total == 2
    assert preview.rows_prepared == 1
    assert preview.can_execute is True
    assert preview.warnings == ["1 bereits importierte Simple-Earn-Records uebersprungen."]


def test_binance_earn_harvest_import_api_preview_only(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    harvest = tmp_path / "harvest.json"
    harvest.write_text('{"records": []}', encoding="utf-8")

    response = TestClient(create_app(store)).post(
        "/api/v1/sources/binance/earn-history-harvest/import",
        json={"harvest_path": str(harvest), "execute": False},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["preview"]["can_execute"] is False
    assert data["batch"] is None


def test_binance_earn_api_import_preview_and_execute(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    def fake_api_preview(self, **_kwargs):
        return BinanceEarnHistoryApiPreview(
            generated_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
            credential_status="configured",
            since=datetime(2025, 1, 1, tzinfo=timezone.utc),
            until=datetime(2025, 1, 2, tzinfo=timezone.utc),
            assets=["JUP"],
            records=[
                BinanceEarnHistoryApiRecord(
                    endpoint="/sapi/v1/simple-earn/flexible/history/rewardsRecord",
                    asset="JUP",
                    product_id="JUP001",
                    record_type="flexible_rewards_realtime",
                    payload={
                        "asset": "JUP",
                        "rewards": "0.5",
                        "productId": "JUP001",
                        "time": 1735689600000,
                    },
                )
            ],
            records_returned=1,
            records_available_hint=1,
            methodology="test",
        )

    monkeypatch.setattr(BinanceEarnHistoryService, "api_preview", fake_api_preview)

    preview = BinanceEarnHistoryService(store).import_api_history(execute=False)

    assert preview.api_preview.records_returned == 1
    assert preview.import_preview.can_execute is True
    assert preview.import_preview.rows_prepared == 1
    assert preview.batch is None

    result = BinanceEarnHistoryService(store).import_api_history(execute=True)

    assert result.batch is not None
    assert result.batch.source == "binance_simple_earn_api"
    assert result.run is not None
    assert result.run.normalized_events == 1


def test_binance_earn_api_import_endpoint_preview_only(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    def fake_api_preview(self, **_kwargs):
        return BinanceEarnHistoryApiPreview(
            generated_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
            credential_status="configured",
            since=datetime(2025, 1, 1, tzinfo=timezone.utc),
            until=datetime(2025, 1, 2, tzinfo=timezone.utc),
            assets=["JUP"],
            records=[],
            records_returned=0,
            records_available_hint=0,
            methodology="test",
        )

    monkeypatch.setattr(BinanceEarnHistoryService, "api_preview", fake_api_preview)

    response = TestClient(create_app(store)).post(
        "/api/v1/sources/binance/earn-history-api/import",
        json={"since": "2025-01-01", "assets": ["JUP"], "execute": False},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["api_preview"]["credential_status"] == "configured"
    assert data["import_preview"]["can_execute"] is False
    assert data["batch"] is None


def test_binance_withdrawal_api_import_preview_and_execute(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    def fake_withdrawal_preview(self, **_kwargs):
        return BinanceCapitalWithdrawalPreview(
            generated_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
            credential_status="configured",
            since=datetime(2025, 3, 23, tzinfo=timezone.utc),
            until=datetime(2025, 3, 24, tzinfo=timezone.utc),
            assets=["JUP"],
            records=[
                BinanceCapitalWithdrawalRecord(
                    endpoint="/sapi/v1/capital/withdraw/history",
                    asset="JUP",
                    payload={
                        "id": "withdraw-id",
                        "coin": "JUP",
                        "amount": "5530.555703",
                        "transactionFee": "1.72",
                        "address": "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY",
                        "txId": "withdraw-tx",
                        "network": "SOL",
                        "completeTime": "2025-03-23 13:49:42",
                    },
                )
            ],
            records_returned=1,
            methodology="test",
        )

    monkeypatch.setattr(BinanceEarnHistoryService, "withdrawal_history_api_preview", fake_withdrawal_preview)

    preview = BinanceEarnHistoryService(store).import_withdrawal_api_history(execute=False)

    assert preview.import_preview.can_execute is True
    assert preview.import_preview.rows_prepared == 1
    assert preview.batch is None

    result = BinanceEarnHistoryService(store).import_withdrawal_api_history(execute=True)

    assert result.batch is not None
    assert result.batch.source == "binance_withdrawal_api"
    assert result.run is not None
    assert result.run.normalized_events == 1
    event = store.list_canonical_events(result.batch.batch_id)[0]
    assert event.source == "binance_withdrawal_api"
    assert event.quantity == Decimal("0")
    assert event.tx_id == "withdraw-tx"


def test_binance_withdrawal_api_import_endpoint_preview_only(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    def fake_withdrawal_preview(self, **_kwargs):
        return BinanceCapitalWithdrawalPreview(
            generated_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
            credential_status="configured",
            since=datetime(2025, 3, 23, tzinfo=timezone.utc),
            until=datetime(2025, 3, 24, tzinfo=timezone.utc),
            assets=["JUP"],
            records=[],
            records_returned=0,
            methodology="test",
        )

    monkeypatch.setattr(BinanceEarnHistoryService, "withdrawal_history_api_preview", fake_withdrawal_preview)

    response = TestClient(create_app(store)).post(
        "/api/v1/sources/binance/withdraw-history-api/import",
        json={"since": "2025-03-23", "until": "2025-03-24", "assets": ["JUP"], "execute": False},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["api_preview"]["credential_status"] == "configured"
    assert data["import_preview"]["can_execute"] is False
    assert data["batch"] is None


def test_binance_asset_dividend_api_preview_fetches_signed_records(
    tmp_path, monkeypatch
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(
        BinanceEarnHistoryService,
        "_credentials",
        lambda _self: ("key", "secret"),
    )

    def fake_signed_get(_self, _api_key, _secret_key, endpoint, params):
        assert endpoint == "/sapi/v1/asset/assetDividend"
        assert params["asset"] == "SOL"
        assert params["limit"] == 500
        return {
            "rows": [
                {
                    "id": 11,
                    "amount": "0.00148283",
                    "asset": "SOL",
                    "divTime": 1778028900000,
                    "enInfo": "Locked",
                    "tranId": 21,
                    "direction": 1,
                }
            ],
            "total": 1,
        }

    monkeypatch.setattr(BinanceEarnHistoryService, "_signed_get", fake_signed_get)

    report = BinanceEarnHistoryService(store).asset_dividend_history_api_preview(
        since=datetime(2026, 5, 6, tzinfo=timezone.utc),
        until=datetime(2026, 5, 7, tzinfo=timezone.utc),
        assets=["SOL"],
    )

    assert report.credential_status == "configured"
    assert report.records_returned == 1
    assert report.truncated is False
    assert report.records[0].payload["enInfo"] == "Locked"
    assert report.requests[0].status == "ok"


def test_binance_asset_dividend_import_deduplicates_locked_rewards_by_utc_day(
    tmp_path, monkeypatch
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    existing_batch = CsvRawImporter(store).import_rows(
        source="binance_simple_earn_api",
        filename="existing-locked-reward.json",
        file_hash="sha256:existing-locked-reward",
        rows=[
            {
                "record_type": "locked_rewards",
                "asset": "SOL",
                "rewards": "0.00148283",
                "time_iso": "2026-05-05T00:11:00+00:00",
                "account_type": "simple_earn_locked",
                "product_id": "Sol*120",
                "position_id": "position-1",
                "source_ref": "locked_rewards:existing",
            }
        ],
    )
    PipelineService(store).rebuild_after_import(existing_batch.batch_id)
    assert store.list_canonical_events(existing_batch.batch_id)[0].account == "Spot"

    def fake_dividend_preview(self, **_kwargs):
        return BinanceAssetDividendPreview(
            generated_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
            credential_status="configured",
            since=datetime(2026, 5, 5, tzinfo=timezone.utc),
            until=datetime(2026, 5, 7, tzinfo=timezone.utc),
            assets=["SOL"],
            records=[
                BinanceAssetDividendRecord(
                    endpoint="/sapi/v1/asset/assetDividend",
                    asset="SOL",
                    payload={
                        "id": 11,
                        "amount": "0.00148283",
                        "asset": "SOL",
                        "divTime": 1777942500000,
                        "enInfo": "Locked",
                        "tranId": 21,
                        "direction": 1,
                    },
                ),
                BinanceAssetDividendRecord(
                    endpoint="/sapi/v1/asset/assetDividend",
                    asset="SOL",
                    payload={
                        "id": 12,
                        "amount": "0.00148283",
                        "asset": "SOL",
                        "divTime": 1778028900000,
                        "enInfo": "Locked",
                        "tranId": 22,
                        "direction": 1,
                    },
                ),
            ],
            records_returned=2,
            records_available_hint=2,
            methodology="test",
        )

    monkeypatch.setattr(
        BinanceEarnHistoryService,
        "asset_dividend_history_api_preview",
        fake_dividend_preview,
    )
    service = BinanceEarnHistoryService(store)

    preview = service.import_asset_dividend_api_history(execute=False)

    assert preview.import_preview.records_total == 2
    assert preview.import_preview.rows_prepared == 1
    assert any("semantisch uebersprungen" in item for item in preview.import_preview.warnings)

    result = service.import_asset_dividend_api_history(execute=True)

    assert result.batch is not None
    assert result.batch.source == "binance_asset_dividend_api"
    events = store.list_canonical_events(result.batch.batch_id)
    assert [(event.event_type, event.account, event.quantity) for event in events] == [
        ("reward", "Spot", Decimal("0.00148283"))
    ]


def test_binance_locked_redemption_loss_is_balance_and_fifo_adjustment_not_sale(
    tmp_path, monkeypatch
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                source_ref="sol-opening",
                event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="SOL",
                quantity=Decimal("10"),
                account="Spot",
            )
        ]
    )

    def fake_api_preview(self, **_kwargs):
        return BinanceEarnHistoryApiPreview(
            generated_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
            credential_status="configured",
            since=datetime(2026, 1, 1, tzinfo=timezone.utc),
            until=datetime(2026, 8, 24, tzinfo=timezone.utc),
            assets=["SOL"],
            records=[
                BinanceEarnHistoryApiRecord(
                    endpoint="/sapi/v1/simple-earn/locked/history/subscriptionRecord",
                    asset="SOL",
                    product_id="Sol*120",
                    position_id="current-position",
                    record_type="locked_subscription",
                    payload={
                        "asset": "SOL",
                        "amount": "10",
                        "productId": "Sol*120",
                        "positionId": "actual-position",
                        "purchaseId": 100,
                        "time": 1768003200000,
                        "type": "NORMAL",
                    },
                ),
                BinanceEarnHistoryApiRecord(
                    endpoint="/sapi/v1/simple-earn/locked/history/rewardsRecord",
                    asset="SOL",
                    product_id="Sol*120",
                    position_id="current-position",
                    record_type="locked_rewards",
                    payload={
                        "asset": "SOL",
                        "amount": "0.1",
                        "positionId": "actual-position",
                        "time": 1769003200000,
                        "type": "LOCKED_REWARD",
                    },
                ),
                BinanceEarnHistoryApiRecord(
                    endpoint="/sapi/v1/simple-earn/locked/history/redemptionRecord",
                    asset="SOL",
                    product_id="Sol*120",
                    position_id="current-position",
                    record_type="locked_redemption",
                    payload={
                        "asset": "SOL",
                        "amount": "9.9",
                        "positionId": "actual-position",
                        "redeemId": 200,
                        "time": 1770000000000,
                        "type": "AHEAD",
                        "status": "PAID",
                        "lossAmount": "0.1",
                        "originalAmount": "10",
                        "rewardAsset": "SOL",
                        "rewardAmt": "0.1",
                    },
                ),
            ],
            records_returned=3,
            records_available_hint=3,
            methodology="test",
        )

    monkeypatch.setattr(BinanceEarnHistoryService, "api_preview", fake_api_preview)
    result = BinanceEarnHistoryService(store).import_api_history(execute=True)

    assert result.import_preview.rows_prepared == 4
    assert result.run is not None
    events = store.list_canonical_events(result.batch.batch_id)
    loss_event = next(event for event in events if event.event_type == "fee")
    assert loss_event.quantity == Decimal("-0.1")
    assert loss_event.source_ref == "locked_redemption_loss:SOL:actual-position:200"
    assert all(
        "current-position" not in str(event.source_ref or "") for event in events
    )
    assert sum(
        (lot.quantity_remaining for lot in TaxService(store).list_tax_lots()),
        Decimal("0"),
    ) == Decimal("10")
    assert TaxService(store).list_tax_lines() == []

    fifo = WalletFifoPreviewService(store)._build_preview(year=2026)
    adjustment = next(
        trace
        for trace in fifo.transfer_traces
        if trace.status == "binance_locked_redemption_reward_clawback"
    )
    assert adjustment.quantity == Decimal("0.1")
    assert adjustment.basis_missing_quantity == Decimal("0")
    assert fifo.tax_lines_count == 0


def test_binance_asset_dividend_api_endpoint_preview_only(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    def fake_dividend_preview(self, **_kwargs):
        return BinanceAssetDividendPreview(
            generated_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
            credential_status="configured",
            since=datetime(2026, 5, 1, tzinfo=timezone.utc),
            until=datetime(2026, 5, 31, tzinfo=timezone.utc),
            assets=["SOL"],
            records=[],
            records_returned=0,
            records_available_hint=0,
            methodology="test",
        )

    monkeypatch.setattr(
        BinanceEarnHistoryService,
        "asset_dividend_history_api_preview",
        fake_dividend_preview,
    )
    response = TestClient(create_app(store)).post(
        "/api/v1/sources/binance/asset-dividend-api/import",
        json={"since": "2026-05-01", "assets": ["SOL"], "execute": False},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["api_preview"]["credential_status"] == "configured"
    assert data["import_preview"]["can_execute"] is False


def test_binance_redemption_clawback_falls_back_to_exact_ledger_reward_chain(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    subscription = CsvRawImporter(store).import_rows(
        source="binance_simple_earn_api",
        filename="subscription.json",
        file_hash="sha256:subscription",
        rows=[
            {
                "record_type": "locked_subscription",
                "asset": "SOL",
                "amount": "1.4",
                "time_iso": "2024-02-09T07:23:25Z",
                "account_type": "simple_earn_locked",
                "product_id": "Sol*120",
                "position_id": "wrapper-position",
                "purchase_id": "100",
                "source_ref": "locked_subscription:SOL:wrapper-position:100",
            }
        ],
    )
    rewards = CsvRawImporter(store).import_rows(
        source="binance",
        filename="binance-ledger-rewards.csv",
        file_hash="sha256:ledger-rewards",
        rows=[
            {
                "Time": "2024-02-11T01:28:37Z",
                "Coin": "SOL",
                "Change": "0.04",
                "Operation": "Simple Earn Locked Rewards",
                "Account": "Spot",
            },
            {
                "Time": "2024-02-12T01:28:45Z",
                "Coin": "SOL",
                "Change": "0.06",
                "Operation": "Simple Earn Locked Rewards",
                "Account": "Spot",
            },
        ],
    )
    loss = CsvRawImporter(store).import_rows(
        source="binance_simple_earn_api",
        filename="redemption-loss.json",
        file_hash="sha256:redemption-loss",
        rows=[
            {
                "record_type": "locked_redemption_loss",
                "asset": "SOL",
                "amount": "0.1",
                "time_iso": "2024-04-02T16:56:17Z",
                "account_type": "simple_earn_locked",
                "product_id": "Sol*120",
                "position_id": "actual-position",
                "redeem_id": "200",
                "original_amount": "1.4",
                "source_ref": "locked_redemption_loss:SOL:actual-position:200",
            }
        ],
    )
    normalizer = RawNormalizer(store)
    for batch in (subscription, rewards, loss):
        normalizer.normalize_batch(batch.batch_id)

    events = store.list_canonical_events()
    loss_event = next(event for event in events if event.event_type == "fee")
    selected = locked_redemption_clawback_reward_event_ids(store, events)
    selected_events = [
        event for event in events if event.event_id in selected[loss_event.event_id]
    ]

    assert len(selected_events) == 2
    assert sum((event.quantity for event in selected_events), Decimal("0")) == Decimal(
        "0.1"
    )
    assert {event.source for event in selected_events} == {"binance"}
