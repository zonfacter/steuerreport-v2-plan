from __future__ import annotations

import os
from uuid import uuid4

from pydantic import SecretStr
import pytest

from steuerreport_v2.contracts.connections import ConnectionCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.binance_earn import BinanceEarnHistoryService
from steuerreport_v2.domain.connections import ConnectionError, ConnectionService
from steuerreport_v2.domain.secret_vault import KEY_FILE_ENV


@pytest.fixture
def store(tmp_path, monkeypatch):
    key_path = tmp_path / "vault.key"
    key_path.write_bytes(os.urandom(32))
    key_path.chmod(0o600)
    monkeypatch.setenv(KEY_FILE_ENV, str(key_path))
    return DuckDbStore(tmp_path / "isolated.duckdb")


def create_connection(service: ConnectionService, label: str, marker: str):
    return service.create(ConnectionCreate(
        provider="binance",
        label=label,
        account=f"synthetic-{marker}",
        budget_group="budget:synthetic-binance",
        api_key=SecretStr(f"mock-key-{marker}"),
        api_secret=SecretStr(f"mock-secret-{marker}"),
    ))


def test_earn_adapter_uses_only_selected_connection_credentials(store, monkeypatch):
    connections = ConnectionService(store)
    first = create_connection(connections, "Binance", "first")
    second = create_connection(connections, "Binance", "second")
    monkeypatch.setenv("BINANCE_API_KEY", "legacy-global-key")
    monkeypatch.setenv("BINANCE_SECRET_KEY", "legacy-global-secret")

    assert BinanceEarnHistoryService(store, connection_id=str(first.id))._credentials() == (
        "mock-key-first", "mock-secret-first",
    )
    assert BinanceEarnHistoryService(store, connection_id=str(second.id))._credentials() == (
        "mock-key-second", "mock-secret-second",
    )


def test_selected_connection_never_falls_back_to_global_credentials(store, monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "legacy-global-key")
    monkeypatch.setenv("BINANCE_SECRET_KEY", "legacy-global-secret")

    with pytest.raises(ConnectionError, match="^connection_not_found$"):
        BinanceEarnHistoryService(store, connection_id=str(uuid4()))._credentials()


@pytest.mark.parametrize(
    ("method", "kwargs", "error"),
    [
        ("import_api_history", {}, "binance_earn_connection_import_requires_history_job"),
        ("import_harvest", {"harvest_path": "synthetic.json"}, "binance_earn_connection_import_requires_history_job"),
        ("import_withdrawal_api_history", {}, "binance_withdrawal_connection_import_requires_history_job"),
        ("import_asset_dividend_api_history", {}, "binance_dividend_connection_import_requires_history_job"),
    ],
)
def test_connection_bound_adapter_cannot_use_legacy_direct_import(store, method, kwargs, error):
    service = BinanceEarnHistoryService(store, connection_id=str(uuid4()))

    with pytest.raises(RuntimeError, match=f"^{error}$"):
        getattr(service, method)(execute=True, **kwargs)
