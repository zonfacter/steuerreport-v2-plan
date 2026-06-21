from datetime import datetime, timezone

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.bitget import BitgetWalletHistoryService


def test_bitget_withdraw_history_api_preview_reports_missing_credentials(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    report = BitgetWalletHistoryService(store).withdrawal_history_api_preview()

    assert report.credential_status == "missing"
    assert report.records_returned == 0
    assert report.requests == []


def test_bitget_withdraw_history_api_preview_fetches_records(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(BitgetWalletHistoryService, "_credentials", lambda _self: ("key", "secret", "passphrase"))

    def fake_signed_get(_self, _api_key, _api_secret, _passphrase, endpoint, params):
        assert endpoint == "/api/v2/spot/wallet/withdrawal-records"
        assert params["coin"] == "JUP"
        assert params["limit"] == 100
        assert "pageNo" not in params
        return {
            "code": "00000",
            "msg": "success",
            "data": [
                {
                    "orderId": "bitget-order-1",
                    "tradeId": "bitget-withdraw-tx",
                    "coin": "JUP",
                    "type": "withdraw",
                    "dest": "on_chain",
                    "size": "4680.175116",
                    "status": "success",
                    "toAddress": "Ftf2dgeRpBrPFmbd4wQWWqSjCmRjGes1GzNXtxKETeLW",
                    "fee": "0.1",
                    "chain": "SOL",
                    "cTime": "1749972612000",
                    "uTime": "1749972612000",
                }
            ],
        }

    monkeypatch.setattr(BitgetWalletHistoryService, "_signed_get", fake_signed_get)

    report = BitgetWalletHistoryService(store).withdrawal_history_api_preview(
        since=datetime(2025, 6, 15, tzinfo=timezone.utc),
        until=datetime(2025, 6, 16, tzinfo=timezone.utc),
        assets=["JUP"],
    )

    assert report.credential_status == "configured"
    assert report.records_returned == 1
    assert report.records[0].payload["tradeId"] == "bitget-withdraw-tx"
    assert report.requests[0].status == "ok"


def test_bitget_withdraw_history_api_import_dry_run_and_execute(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    def fake_preview(self, **_kwargs):
        from steuerreport_v2.contracts.bitget import BitgetWithdrawalPreview, BitgetWithdrawalRecord

        return BitgetWithdrawalPreview(
            generated_at=datetime.now(timezone.utc),
            credential_status="configured",
            since=datetime(2025, 6, 15, tzinfo=timezone.utc),
            until=datetime(2025, 6, 16, tzinfo=timezone.utc),
            assets=["SOL"],
            records=[
                BitgetWithdrawalRecord(
                    endpoint="/api/v2/spot/wallet/withdrawal-records",
                    asset="SOL",
                    payload={
                        "orderId": "bitget-order-2",
                        "tradeId": "bitget-sol-tx",
                        "coin": "SOL",
                        "type": "withdraw",
                        "dest": "on_chain",
                        "size": "7.0700475",
                        "status": "success",
                        "toAddress": "Ftf2dgeRpBrPFmbd4wQWWqSjCmRjGes1GzNXtxKETeLW",
                        "fee": "0.0001",
                        "chain": "SOL",
                        "cTime": "1749973521000",
                        "uTime": "1749973521000",
                    },
                )
            ],
            records_returned=1,
            methodology="test",
        )

    monkeypatch.setattr(BitgetWalletHistoryService, "withdrawal_history_api_preview", fake_preview)

    dry_run = BitgetWalletHistoryService(store).import_withdrawal_api_history(execute=False)
    assert dry_run.import_preview.can_execute is True
    assert dry_run.batch is None

    result = BitgetWalletHistoryService(store).import_withdrawal_api_history(execute=True)
    assert result.batch is not None
    assert result.run is not None
    assert result.import_preview.rows_prepared == 1
    raw_objects = store.list_raw_objects(result.batch.batch_id, limit=None)
    events = store.list_canonical_events()
    assert len(raw_objects) == 1
    assert events == []


def test_bitget_withdraw_history_api_import_endpoint(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(BitgetWalletHistoryService, "_credentials", lambda _self: ("", "", ""))

    response = TestClient(create_app(store)).post(
        "/api/v1/sources/bitget/withdraw-history-api/import",
        json={
            "since": "2025-06-15T00:00:00Z",
            "until": "2025-06-16T00:00:00Z",
            "assets": ["JUP", "SOL"],
            "execute": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["api_preview"]["credential_status"] == "missing"
