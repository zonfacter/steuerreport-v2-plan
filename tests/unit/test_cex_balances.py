from datetime import datetime, timezone
from decimal import Decimal
import base64
import json

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from steuerreport_v2.contracts.portfolio import PortfolioLiveBalanceSnapshot
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.cex_balances import CexBalanceService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.secrets import upsert_secret


def _credentials(store: DuckDbStore, connector_id: str, *, passphrase: bool = False) -> None:
    upsert_secret(store, f"secret.cex.{connector_id}.api_key", "api-key")
    upsert_secret(store, f"secret.cex.{connector_id}.api_secret", "api-secret")
    if passphrase:
        upsert_secret(store, f"secret.cex.{connector_id}.passphrase", "passphrase")


def test_cex_balance_service_parses_binance_spot_and_earn_components(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _credentials(store, "binance")
    service = CexBalanceService(store)

    def fake_get(path, _api_key, _api_secret, _params):
        if path == "/api/v3/account":
            return {
                "balances": [
                    {"asset": "SOL", "free": "1", "locked": "0.1"},
                    {"asset": "EUR", "free": "0", "locked": "0"},
                ]
            }
        if path.endswith("flexible/position"):
            return {
                "rows": [
                    {
                        "asset": "JUP",
                        "totalAmount": "2",
                        "productId": "JUP001",
                    }
                ]
            }
        if path.endswith("locked/position"):
            return {
                "rows": [
                    {
                        "asset": "SOL",
                        "amount": "3",
                        "rewardAsset": "SOL",
                        "rewardAmt": "0.01",
                        "projectId": "Sol*120",
                        "positionId": "position-1",
                    }
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(service, "_binance_get", fake_get)

    rows = service.fetch("binance", datetime(2026, 7, 18, tzinfo=timezone.utc))

    assert [
        (row.asset, row.quantity, row.account_type, row.event_type)
        for row in rows
    ] == [
        ("SOL", Decimal("1.1"), "spot", "balance_snapshot"),
        ("JUP", Decimal("2"), "simple_earn_flexible", "balance_snapshot"),
        ("SOL", Decimal("3"), "simple_earn_locked", "balance_snapshot"),
    ]


def test_cex_balance_service_parses_bitget_balance_buckets(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _credentials(store, "bitget", passphrase=True)
    service = CexBalanceService(store)
    monkeypatch.setattr(
        service,
        "_bitget_get",
        lambda *_args: {
            "code": "00000",
            "data": [
                {
                    "coin": "USDT",
                    "available": "1",
                    "frozen": "0.2",
                    "locked": "0.3",
                }
            ],
        },
    )

    rows = service.fetch("bitget", datetime(2026, 7, 18, tzinfo=timezone.utc))

    assert [(row.asset, row.quantity, row.source) for row in rows] == [
        ("USDT", Decimal("1.5"), "bitget_api_v2")
    ]


def test_cex_balance_service_parses_pionex_balances(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _credentials(store, "pionex")
    service = CexBalanceService(store)
    monkeypatch.setattr(
        service,
        "_pionex_get",
        lambda *_args: {
            "result": True,
            "data": {
                "balances": [
                    {"coin": "USDT", "free": "0.8", "frozen": "0.1"}
                ]
            },
        },
    )

    rows = service.fetch("pionex", datetime(2026, 7, 18, tzinfo=timezone.utc))

    assert [(row.asset, row.quantity, row.source) for row in rows] == [
        ("USDT", Decimal("0.9"), "pionex_api_v2")
    ]


def test_cex_balance_service_parses_paginated_coinbase_accounts(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _credentials(store, "coinbase")
    service = CexBalanceService(store)
    pages = []

    def fake_get(_path, _api_key, _api_secret, params):
        pages.append(dict(params))
        if "cursor" not in params:
            return {
                "accounts": [
                    {
                        "currency": "SOL",
                        "available_balance": {"value": "1.2", "currency": "SOL"},
                        "hold": {"value": "0.3", "currency": "SOL"},
                    }
                ],
                "has_next": True,
                "cursor": "next-page",
            }
        return {
            "accounts": [
                {
                    "currency": "SOL",
                    "available_balance": {"value": "0.5", "currency": "SOL"},
                    "hold": {"value": "0", "currency": "SOL"},
                },
                {
                    "currency": "EUR",
                    "available_balance": {"value": "10", "currency": "EUR"},
                    "hold": {"value": "0", "currency": "EUR"},
                },
            ],
            "has_next": False,
        }

    monkeypatch.setattr(service, "_coinbase_get", fake_get)

    rows = service.fetch("coinbase", datetime(2026, 7, 18, tzinfo=timezone.utc))

    assert pages == [{"limit": "250"}, {"limit": "250", "cursor": "next-page"}]
    assert [(row.asset, row.quantity, row.source) for row in rows] == [
        ("EUR", Decimal("10"), "coinbase_api_v2"),
        ("SOL", Decimal("2.0"), "coinbase_api_v2"),
    ]


def test_coinbase_jwt_is_es256_signed_and_bound_to_request_path(tmp_path):
    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode("ascii")

    token = CexBalanceService._coinbase_jwt(
        "GET",
        "/api/v3/brokerage/accounts",
        "organizations/org/apiKeys/key",
        private_pem,
    )

    encoded_header, encoded_payload, encoded_signature = token.split(".")
    def decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    header = json.loads(decode(encoded_header))
    payload = json.loads(decode(encoded_payload))
    raw_signature = decode(encoded_signature)
    der_signature = encode_dss_signature(
        int.from_bytes(raw_signature[:32], "big"),
        int.from_bytes(raw_signature[32:], "big"),
    )
    private_key.public_key().verify(
        der_signature,
        f"{encoded_header}.{encoded_payload}".encode("ascii"),
        ec.ECDSA(hashes.SHA256()),
    )
    assert header["alg"] == "ES256"
    assert header["kid"] == "organizations/org/apiKeys/key"
    assert payload["iss"] == "cdp"
    assert payload["uri"] == "GET api.coinbase.com/api/v3/brokerage/accounts"
    assert payload["exp"] - payload["nbf"] == 120


def test_portfolio_refresh_prefers_direct_v2_cex_connector(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _credentials(store, "binance")
    fetched = []

    def direct_fetch(_self, connector_id, fetched_at):
        fetched.append(connector_id)
        return [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="binance:SOL:direct",
                connector_id="binance",
                asset="SOL",
                quantity=Decimal("1.25"),
                source="binance_api_v2",
                fetched_at=fetched_at,
                account_type="spot",
                event_type="balance_snapshot",
            )
        ]

    monkeypatch.setattr(CexBalanceService, "fetch", direct_fetch)
    monkeypatch.setattr(
        PortfolioService,
        "_v1_cex_live_balance_snapshots",
        lambda *_args: (_ for _ in ()).throw(AssertionError("V1 bridge used")),
    )

    result = PortfolioService(store).refresh_reconciliation_snapshots(
        connectors=["binance"]
    )

    assert fetched == ["binance"]
    assert result.imported_snapshots == 1
    assert result.connector_results[0].status == "refreshed"
    assert result.snapshots[0].source == "binance_api_v2"
