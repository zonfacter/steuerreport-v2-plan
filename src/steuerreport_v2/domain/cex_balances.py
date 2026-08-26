from __future__ import annotations

import base64
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import secrets
import time
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

    def __init__(self, store: DuckDbStore, *, timeout_seconds: int = 20) -> None:
        self.store = store
        self.timeout_seconds = timeout_seconds

    def fetch(
        self,
        connector_id: str,
        fetched_at: datetime,
    ) -> list[PortfolioLiveBalanceSnapshot]:
        connector = connector_id.strip().lower()
        if connector == "binance":
            return self._binance_snapshots(fetched_at)
        if connector == "bitget":
            return self._bitget_snapshots(fetched_at)
        if connector == "pionex":
            return self._pionex_snapshots(fetched_at)
        if connector == "coinbase":
            return self._coinbase_snapshots(fetched_at)
        raise ValueError(f"unsupported_cex_connector:{connector}")

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
            raise RuntimeError(
                f"bitget_balance_api_error:{str(payload.get('code') if isinstance(payload, dict) else '')}"
            )
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
            raise RuntimeError(
                f"pionex_balance_api_error:{str(payload.get('code') if isinstance(payload, dict) else '')}"
            )
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
        signed = {
            **params,
            "timestamp": str(int(time.time() * 1000)),
            "recvWindow": "5000",
        }
        query = urlencode(signed)
        signature = hmac.new(
            api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return self._get_json(
            f"{self.BINANCE_BASE_URL}{path}?{query}&signature={signature}",
            {"X-MBX-APIKEY": api_key},
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
        timestamp = str(int(time.time() * 1000))
        prehash = f"{timestamp}GET{request_path}"
        signature = base64.b64encode(
            hmac.new(
                api_secret.encode("utf-8"),
                prehash.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("ascii")
        return self._get_json(
            f"{self.BITGET_BASE_URL}{request_path}",
            {
                "ACCESS-KEY": api_key,
                "ACCESS-SIGN": signature,
                "ACCESS-TIMESTAMP": timestamp,
                "ACCESS-PASSPHRASE": passphrase,
                "Content-Type": "application/json",
            },
        )

    def _pionex_get(
        self,
        path: str,
        api_key: str,
        api_secret: str,
    ) -> object:
        params = {"timestamp": str(int(time.time() * 1000))}
        signing_query = "&".join(f"{key}={params[key]}" for key in sorted(params))
        signature = hmac.new(
            api_secret.encode("utf-8"),
            f"GET{path}?{signing_query}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return self._get_json(
            f"{self.PIONEX_BASE_URL}{path}?{urlencode(params)}",
            {
                "PIONEX-KEY": api_key,
                "PIONEX-SIGNATURE": signature,
            },
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
        token = self._coinbase_jwt("GET", path, api_key, api_secret)
        return self._get_json(
            f"{self.COINBASE_BASE_URL}{request_path}",
            {"Authorization": f"Bearer {token}"},
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

    def _get_json(self, url: str, headers: dict[str, str]) -> object:
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.get(url, headers=headers)
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(
                    f"cex_balance_http_error:{response.status_code}"
                ) from exc
            return response.json()

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
