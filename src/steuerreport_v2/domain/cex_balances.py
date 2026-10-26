from __future__ import annotations

import base64
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable
from urllib.parse import urlencode

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
import httpx

from steuerreport_v2.contracts.portfolio import PortfolioLiveBalanceSnapshot
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.secrets import resolve_secret_value


class CexBalanceService:
    BINANCE_BASE_URL = "https://api.binance.com"
    BITGET_BASE_URL = "https://api.bitget.com"
    PIONEX_BASE_URL = "https://api.pionex.com"
    COINBASE_BASE_URL = "https://api.coinbase.com"

    def __init__(
        self, store: DuckDbStore, *, timeout_seconds: int = 20,
        connection_id: str | None = None,
    ) -> None:
        self.store = store
        self.timeout_seconds = timeout_seconds
        self.connection_id = connection_id

    def fetch(
        self,
        connector_id: str,
        fetched_at: datetime,
        *,
        connection_id: str | None = None,
    ) -> list[PortfolioLiveBalanceSnapshot]:
        if connection_id is not None:
            return CexBalanceService(
                self.store, timeout_seconds=self.timeout_seconds,
                connection_id=connection_id,
            ).fetch(connector_id, fetched_at)
        connector = connector_id.strip().lower()
        handlers = {
            "binance": self._binance_snapshots, "bitget": self._bitget_snapshots,
            "pionex": self._pionex_snapshots, "coinbase": self._coinbase_snapshots,
        }
        if connector not in handlers:
            raise ValueError("unsupported_cex_connector")
        rows = handlers[connector](fetched_at)
        if self.connection_id is not None:
            rows = [row.model_copy(update={
                "snapshot_id": f"connection:{self.connection_id}:{row.snapshot_id}",
                "source": f"{row.source}:connection:{self.connection_id}",
            }) for row in rows]
        return rows

    def test_connection(self, connector_id: str) -> None:
        """Ein authentifizierter Lesezugriff; keine Historie und kein Snapshot."""
        key, secret, passphrase = self._credentials(connector_id)
        if connector_id == "binance":
            body = self._binance_get("/api/v3/account", key, secret, {"omitZeroBalances": "true"})
            valid = isinstance(body, dict) and isinstance(body.get("balances"), list)
        elif connector_id == "bitget":
            body = self._bitget_get("/api/v2/spot/account/assets", key, secret, passphrase, {"assetType": "hold_only"})
            valid = isinstance(body, dict) and body.get("code") == "00000" and isinstance(body.get("data"), list)
        elif connector_id == "pionex":
            body = self._pionex_get("/api/v1/account/balances", key, secret)
            valid = isinstance(body, dict) and body.get("result") is True and isinstance(body.get("data"), dict)
        elif connector_id == "coinbase":
            body = self._coinbase_get("/api/v3/brokerage/accounts", key, secret, {"limit": "1"})
            valid = isinstance(body, dict) and isinstance(body.get("accounts"), list)
        else:
            raise ValueError("unsupported_cex_connector")
        if not valid:
            raise RuntimeError("cex_connection_response_invalid")

    def _binance_snapshots(
        self,
        fetched_at: datetime,
    ) -> list[PortfolioLiveBalanceSnapshot]:
        api_key, api_secret, _passphrase = self._credentials("binance")
        account = self._binance_get(
            "/api/v3/account",
            api_key,
            api_secret,
            {"omitZeroBalances": "true"},
        )
        balances = account.get("balances") if isinstance(account, dict) else None
        if not isinstance(balances, list):
            raise RuntimeError("binance_account_balances_missing")
        rows: list[dict[str, object]] = []
        for item in balances:
            if not isinstance(item, dict):
                continue
            quantity = self._decimal(item.get("free")) + self._decimal(item.get("locked"))
            asset = str(item.get("asset") or "").strip().upper()
            if asset and quantity > 0:
                rows.append(
                    {
                        "asset": asset,
                        "quantity": quantity,
                        "account_type": "spot",
                        "product_id": None,
                        "position_id": None,
                        "event_type": "balance_snapshot",
                    }
                )

        earn_specs = (
            (
                "simple_earn_flexible",
                "/sapi/v1/simple-earn/flexible/position",
                "totalAmount",
            ),
            (
                "simple_earn_locked",
                "/sapi/v1/simple-earn/locked/position",
                "amount",
            ),
        )
        for account_type, path, amount_key in earn_specs:
            for page in range(1, 101):
                payload = self._binance_get(
                    path,
                    api_key,
                    api_secret,
                    {"size": "100", "current": str(page)},
                )
                items = payload.get("rows") if isinstance(payload, dict) else None
                if not isinstance(items, list):
                    raise RuntimeError(f"binance_earn_rows_missing:{account_type}")
                if not items:
                    break
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    asset = str(item.get("asset") or "").strip().upper()
                    quantity = self._decimal(item.get(amount_key))
                    product_id = str(
                        item.get("productId") or item.get("projectId") or ""
                    ).strip()
                    position_id = str(item.get("positionId") or "").strip()
                    if asset and quantity > 0:
                        rows.append(
                            {
                                "asset": asset,
                                "quantity": quantity,
                                "account_type": account_type,
                                "product_id": product_id or None,
                                "position_id": position_id or None,
                                "event_type": "balance_snapshot",
                            }
                        )
                if len(items) < 100:
                    break
        return self._snapshots("binance", "binance_api_v2", fetched_at, rows)

    def _bitget_snapshots(
        self,
        fetched_at: datetime,
    ) -> list[PortfolioLiveBalanceSnapshot]:
        api_key, api_secret, passphrase = self._credentials("bitget")
        payload = self._bitget_get(
            "/api/v2/spot/account/assets",
            api_key,
            api_secret,
            passphrase,
            {"assetType": "hold_only"},
        )
        if not isinstance(payload, dict) or str(payload.get("code") or "") != "00000":
            raise RuntimeError("bitget_balance_api_error")
        items = payload.get("data")
        if not isinstance(items, list):
            raise RuntimeError("bitget_balance_rows_missing")
        rows: list[dict[str, object]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            asset = str(item.get("coin") or "").strip().upper()
            quantity = (
                self._decimal(item.get("available"))
                + self._decimal(item.get("frozen"))
                + self._decimal(item.get("locked"))
            )
            if asset and quantity > 0:
                rows.append(
                    {
                        "asset": asset,
                        "quantity": quantity,
                        "account_type": "spot",
                        "product_id": None,
                        "position_id": None,
                        "event_type": "balance_snapshot",
                    }
                )
        return self._snapshots("bitget", "bitget_api_v2", fetched_at, rows)

    def _pionex_snapshots(
        self,
        fetched_at: datetime,
    ) -> list[PortfolioLiveBalanceSnapshot]:
        api_key, api_secret, _passphrase = self._credentials("pionex")
        payload = self._pionex_get(
            "/api/v1/account/balances",
            api_key,
            api_secret,
        )
        if not isinstance(payload, dict) or payload.get("result") is not True:
            raise RuntimeError("pionex_balance_api_error")
        data = payload.get("data")
        items = data.get("balances") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise RuntimeError("pionex_balance_rows_missing")
        rows: list[dict[str, object]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            asset = str(item.get("coin") or "").strip().upper()
            quantity = self._decimal(item.get("free")) + self._decimal(item.get("frozen"))
            if asset and quantity > 0:
                rows.append(
                    {
                        "asset": asset,
                        "quantity": quantity,
                        "account_type": "spot",
                        "product_id": None,
                        "position_id": None,
                        "event_type": "balance_snapshot",
                    }
                )
        return self._snapshots("pionex", "pionex_api_v2", fetched_at, rows)

    def _coinbase_snapshots(
        self,
        fetched_at: datetime,
    ) -> list[PortfolioLiveBalanceSnapshot]:
        api_key, api_secret, _passphrase = self._credentials("coinbase")
        balances: dict[str, Decimal] = {}
        cursor: str | None = None
        for _page in range(100):
            params = {"limit": "250"}
            if cursor:
                params["cursor"] = cursor
            payload = self._coinbase_get(
                "/api/v3/brokerage/accounts",
                api_key,
                api_secret,
                params,
            )
            accounts = payload.get("accounts") if isinstance(payload, dict) else None
            if not isinstance(accounts, list):
                raise RuntimeError("coinbase_account_balances_missing")
            for item in accounts:
                if not isinstance(item, dict):
                    continue
                available = item.get("available_balance")
                hold = item.get("hold")
                asset = str(
                    (available.get("currency") if isinstance(available, dict) else None)
                    or item.get("currency")
                    or ""
                ).strip().upper()
                quantity = self._decimal(
                    available.get("value") if isinstance(available, dict) else None
                ) + self._decimal(hold.get("value") if isinstance(hold, dict) else None)
                if asset and quantity > 0:
                    balances[asset] = balances.get(asset, Decimal("0")) + quantity
            has_next = payload.get("has_next") is True if isinstance(payload, dict) else False
            next_cursor = str(payload.get("cursor") or "") if isinstance(payload, dict) else ""
            if not has_next or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        rows = [
            {
                "asset": asset,
                "quantity": quantity,
                "account_type": "spot",
                "product_id": None,
                "position_id": None,
                "event_type": "balance_snapshot",
            }
            for asset, quantity in sorted(balances.items())
        ]
        return self._snapshots("coinbase", "coinbase_api_v2", fetched_at, rows)

    def _credentials(self, connector_id: str) -> tuple[str, str, str]:
        if self.connection_id is not None:
            from steuerreport_v2.domain.connections import ConnectionService

            return ConnectionService(self.store).credentials(self.connection_id, connector_id)
        api_key = resolve_secret_value(
            self.store,
            f"secret.cex.{connector_id}.api_key",
        )
        api_secret = resolve_secret_value(
            self.store,
            f"secret.cex.{connector_id}.api_secret",
        )
        passphrase = resolve_secret_value(
            self.store,
            f"secret.cex.{connector_id}.passphrase",
        )
        if not api_key or not api_secret:
            raise RuntimeError(f"missing_v2_credentials:{connector_id}")
        if connector_id == "bitget" and not passphrase:
            raise RuntimeError("missing_v2_credentials:bitget:passphrase")
        return api_key, api_secret, passphrase

    def _binance_get(
        self,
        path: str,
        api_key: str,
        api_secret: str,
        params: dict[str, str],
    ) -> object:
        def sign(request: httpx.Request) -> None:
            signed = {**params, "timestamp": str(int(time.time() * 1000)), "recvWindow": "5000"}
            query = urlencode(signed)
            signature = hmac.new(api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
            request.url = httpx.URL(f"{self.BINANCE_BASE_URL}{path}?{query}&signature={signature}")
            request.headers["X-MBX-APIKEY"] = api_key

        return self._get_json(
            f"{self.BINANCE_BASE_URL}{path}", {}, signer=sign,
        )

    def _bitget_get(
        self,
        path: str,
        api_key: str,
        api_secret: str,
        passphrase: str,
        params: dict[str, str],
    ) -> object:
        query = urlencode(params)
        request_path = path if not query else f"{path}?{query}"
        def sign(request: httpx.Request) -> None:
            timestamp = str(int(time.time() * 1000))
            signature = base64.b64encode(hmac.new(api_secret.encode(), f"{timestamp}GET{request_path}".encode(), hashlib.sha256).digest()).decode("ascii")
            request.headers.update({
                "ACCESS-KEY": api_key, "ACCESS-SIGN": signature,
                "ACCESS-TIMESTAMP": timestamp, "ACCESS-PASSPHRASE": passphrase,
                "Content-Type": "application/json",
            })

        return self._get_json(
            f"{self.BITGET_BASE_URL}{request_path}", {}, signer=sign,
        )

    def _pionex_get(
        self,
        path: str,
        api_key: str,
        api_secret: str,
    ) -> object:
        def sign(request: httpx.Request) -> None:
            query = urlencode({"timestamp": str(int(time.time() * 1000))})
            request.url = httpx.URL(f"{self.PIONEX_BASE_URL}{path}?{query}")
            request.headers["PIONEX-KEY"] = api_key
            request.headers["PIONEX-SIGNATURE"] = hmac.new(api_secret.encode(), f"GET{path}?{query}".encode(), hashlib.sha256).hexdigest()

        return self._get_json(
            f"{self.PIONEX_BASE_URL}{path}", {}, signer=sign,
        )

    def _coinbase_get(
        self,
        path: str,
        api_key: str,
        api_secret: str,
        params: dict[str, str],
    ) -> object:
        query = urlencode(params)
        request_path = path if not query else f"{path}?{query}"
        def sign(request: httpx.Request) -> None:
            token = self._coinbase_jwt("GET", path, api_key, api_secret)
            request.headers["Authorization"] = f"Bearer {token}"

        return self._get_json(
            f"{self.COINBASE_BASE_URL}{request_path}", {}, signer=sign,
        )

    @classmethod
    def _coinbase_jwt(
        cls,
        method: str,
        path: str,
        api_key: str,
        api_secret: str,
    ) -> str:
        secret = api_secret.replace("\\n", "\n").encode("utf-8")
        try:
            private_key = serialization.load_pem_private_key(secret, password=None)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("coinbase_api_secret_invalid_ecdsa_private_key") from exc
        if not isinstance(private_key, ec.EllipticCurvePrivateKey) or not isinstance(
            private_key.curve, ec.SECP256R1
        ):
            raise RuntimeError("coinbase_api_secret_requires_es256_key")
        now = int(time.time())
        header = {
            "alg": "ES256",
            "typ": "JWT",
            "kid": api_key,
            "nonce": secrets.token_hex(16),
        }
        payload = {
            "sub": api_key,
            "iss": "cdp",
            "nbf": now,
            "exp": now + 120,
            "uri": f"{method.upper()} api.coinbase.com{path}",
        }
        encoded_header = cls._base64url_json(header)
        encoded_payload = cls._base64url_json(payload)
        signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
        der_signature = private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        r_value, s_value = decode_dss_signature(der_signature)
        signature = r_value.to_bytes(32, "big") + s_value.to_bytes(32, "big")
        return f"{encoded_header}.{encoded_payload}.{cls._base64url(signature)}"

    @classmethod
    def _base64url_json(cls, value: dict[str, object]) -> str:
        return cls._base64url(
            json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        )

    @staticmethod
    def _base64url(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    def _get_json(
        self, url: str, headers: dict[str, str], *,
        signer: Callable[[httpx.Request], None] | None = None,
    ) -> object:
        try:
            from steuerreport_v2.domain.external_http import managed_client, request_signer
        except ImportError:
            raise RuntimeError("external_http_unavailable") from None
        try:
            with request_signer(signer), managed_client(timeout=self.timeout_seconds) as client:
                response = client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            code = "cex_authentication_failed" if exc.response.status_code in {401, 403} else "cex_provider_request_failed"
            raise RuntimeError(code) from None
        except httpx.TimeoutException:
            raise RuntimeError("cex_request_timeout") from None
        except (httpx.RequestError, ValueError):
            raise RuntimeError("cex_provider_request_failed") from None

    @staticmethod
    def _snapshots(
        connector_id: str,
        source: str,
        fetched_at: datetime,
        rows: list[dict[str, object]],
    ) -> list[PortfolioLiveBalanceSnapshot]:
        snapshots: list[PortfolioLiveBalanceSnapshot] = []
        for index, row in enumerate(rows):
            account_type = str(row.get("account_type") or "spot")
            product_id = str(row.get("product_id") or "")
            position_id = str(row.get("position_id") or "")
            event_type = str(row.get("event_type") or "balance_snapshot")
            asset = str(row["asset"])
            snapshots.append(
                PortfolioLiveBalanceSnapshot(
                    snapshot_id=(
                        f"{connector_id}:{asset}:{account_type}:{product_id}:"
                        f"{position_id}:{event_type}:{fetched_at.isoformat()}:{index}"
                    ),
                    connector_id=connector_id,
                    asset=asset,
                    quantity=Decimal(str(row["quantity"])),
                    source=source,
                    fetched_at=fetched_at,
                    account_type=account_type,
                    product_id=product_id or None,
                    position_id=position_id or None,
                    event_type=event_type,
                )
            )
        return snapshots

    @staticmethod
    def _decimal(value: object) -> Decimal:
        try:
            return Decimal(str(value or "0"))
        except (InvalidOperation, ValueError):
            return Decimal("0")
