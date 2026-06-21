from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import sqlite3
import sys

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.jupiter import JupiterTokenSearchItem, JupiterTokenSearchResult
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.admin import AdminService
from steuerreport_v2.domain.jupiter import JupiterTokenService


def _call_get_route(app, path: str, **kwargs):
    route = next(route for route in app.routes if getattr(route, "path", None) == path)
    return route.endpoint(**kwargs)


def _call_post_route(app, path: str, payload):
    route = next(route for route in app.routes if getattr(route, "path", None) == path)
    return route.endpoint(payload)


def test_jupiter_token_search_reports_missing_api_key(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(JupiterTokenService, "_api_key", lambda _self: "")

    result = JupiterTokenService(store).search("JUP")

    assert result.configured is False
    assert result.status == "missing_api_key"
    assert result.tokens == []


def test_jupiter_token_search_maps_api_response(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(JupiterTokenService, "_api_key", lambda _self: "jup-key")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                {
                    "id": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
                    "name": "Jupiter",
                    "symbol": "JUP",
                    "decimals": 6,
                    "tokenProgram": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                    "organicScore": 97.98,
                    "organicScoreLabel": "high",
                    "isVerified": True,
                    "tags": ["community", "verified"],
                    "usdPrice": 0.1415,
                    "audit": {
                        "mintAuthorityDisabled": True,
                        "freezeAuthorityDisabled": True,
                        "topHoldersPercentage": 15.45,
                        "devMints": 1,
                    },
                }
            ]

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url, headers, params):
            assert url == JupiterTokenService.SEARCH_URL
            assert headers == {"x-api-key": "jup-key"}
            assert params == {"query": "JUP"}
            return FakeResponse()

    monkeypatch.setattr("steuerreport_v2.domain.jupiter.httpx.Client", FakeClient)

    result = JupiterTokenService(store).search("JUP")

    assert result.configured is True
    assert result.status == "ok"
    assert result.tokens_count == 1
    assert result.tokens[0].symbol == "JUP"
    assert result.tokens[0].usd_price is not None
    assert result.tokens[0].audit is not None
    assert result.tokens[0].audit.mint_authority_disabled is True


def test_jupiter_api_key_loads_from_v1_tax_engine_path(tmp_path, monkeypatch):
    v1_src = tmp_path / "v1src"
    package_dir = v1_src / "tax_engine"
    package_dir.mkdir(parents=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    (package_dir / "admin.py").write_text(
        "def resolve_secret_value(key):\n"
        "    return 'secret-from-v1' if key == 'secret.jupiter.api_key' else ''\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(JupiterTokenService, "V1_TAX_ENGINE_SRC", str(v1_src))
    monkeypatch.delitem(sys.modules, "tax_engine", raising=False)
    monkeypatch.delitem(sys.modules, "tax_engine.admin", raising=False)
    monkeypatch.setattr(sys, "path", [item for item in sys.path if item != str(v1_src)])

    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    assert JupiterTokenService(store)._api_key() == "secret-from-v1"


def test_jupiter_token_search_api_route(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(JupiterTokenService, "_api_key", lambda _self: "")

    response = _call_get_route(create_app(store), "/api/v1/sources/jupiter/tokens/search", query="JUP")

    assert response.status == "warning"
    assert response.data.status == "missing_api_key"


def test_jupiter_api_key_endpoint_writes_secret_without_echo(tmp_path, monkeypatch):
    from steuerreport_v2.contracts.admin import ApiKeyWrite

    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    written: list[tuple[str, str]] = []
    monkeypatch.setattr(AdminService, "_write_v1_secret_setting", lambda _self, key, value: written.append((key, value)))

    response = _call_post_route(
        create_app(store),
        "/api/v1/admin/jupiter/api-key",
        ApiKeyWrite(api_key="secret-jupiter-key"),
    )

    assert response.status == "ok"
    assert response.data.provider == "jupiter"
    assert response.data.written_keys == ["secret.jupiter.api_key"]
    assert written == [("secret.jupiter.api_key", "secret-jupiter-key")]
    assert "secret-jupiter-key" not in str(response.data)


def test_jupiter_metadata_cache_collects_mints_from_existing_data(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(JupiterTokenService, "V1_DB_PATH", tmp_path / "missing-v1.db")
    jup_mint = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
    iot_mint = "iotEVVZLEd5WcVdWNbG5tF2Kcc3KqkizjWAh6zK5mVf"
    with store.connect() as con:
        con.execute(
            """
            insert into portfolio_live_balance_snapshots
                (snapshot_id, connector_id, asset, quantity, source, fetched_at)
            values ('snap-1', 'solscan', ?, 1, 'test', ?)
            """,
            [jup_mint, datetime.now(timezone.utc)],
        )
        con.execute(
            """
            insert into raw_import_batches (batch_id, source, filename, file_hash, status, created_at)
            values ('batch-1', 'solscan', 'test.json', 'hash', 'committed', ?)
            """,
            [datetime.now(timezone.utc)],
        )
        con.execute(
            """
            insert into raw_objects (raw_object_id, batch_id, row_number, payload_json, created_at)
            values ('raw-1', 'batch-1', 1, ?, ?)
            """,
            [f'{{"tokenAddress":"{iot_mint}","owner":"not-a-mint"}}', datetime.now(timezone.utc)],
        )
    monkeypatch.setattr(JupiterTokenService, "_api_key", lambda _self: "jup-key")

    result = JupiterTokenService(store).metadata_cache()

    assert result.configured is True
    assert result.candidates_count == 2
    assert result.cached_count == 0
    assert result.uncached_count == 2


def test_jupiter_metadata_cache_collects_v1_solscan_token_addresses(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    v1_db = tmp_path / "steuerreport.db"
    hnt_mint = "hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux"
    with sqlite3.connect(v1_db) as con:
        con.execute(
            """
            create table solscan_account_transfers (
                token_address text,
                wallet_address text
            )
            """
        )
        con.execute(
            "insert into solscan_account_transfers (token_address, wallet_address) values (?, ?)",
            [hnt_mint, "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY"],
        )
    monkeypatch.setattr(JupiterTokenService, "V1_DB_PATH", v1_db)
    monkeypatch.setattr(JupiterTokenService, "_api_key", lambda _self: "jup-key")

    result = JupiterTokenService(store).metadata_cache()

    assert result.candidates_count == 1
    assert result.uncached_count == 1


def test_jupiter_metadata_refresh_writes_cache_without_touching_tax_data(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(JupiterTokenService, "V1_DB_PATH", tmp_path / "missing-v1.db")
    jup_mint = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
    with store.connect() as con:
        con.execute(
            """
            insert into portfolio_live_balance_snapshots
                (snapshot_id, connector_id, asset, quantity, source, fetched_at)
            values ('snap-1', 'solscan', ?, 1, 'test', ?)
            """,
            [jup_mint, datetime.now(timezone.utc)],
        )
    monkeypatch.setattr(JupiterTokenService, "_api_key", lambda _self: "jup-key")

    def fake_search(self, query):
        assert query == jup_mint
        return JupiterTokenSearchResult(
            generated_at=datetime.now(timezone.utc),
            query=query,
            configured=True,
            status="ok",
            tokens=[
                JupiterTokenSearchItem(
                    id=jup_mint,
                    symbol="JUP",
                    name="Jupiter",
                    decimals=6,
                    is_verified=True,
                    organic_score=Decimal("98.1"),
                    organic_score_label="high",
                    liquidity_usd=Decimal("12345.67"),
                    usd_price=Decimal("0.42"),
                )
            ],
            tokens_count=1,
            methodology="fake",
        )

    monkeypatch.setattr(JupiterTokenService, "search", fake_search)

    result = JupiterTokenService(store).refresh_metadata_cache(limit=10)
    cached = JupiterTokenService(store).metadata_cache()

    assert result.status == "ok"
    assert result.refreshed_count == 1
    assert result.cached_count == 1
    assert cached.items[0].mint == jup_mint
    assert cached.items[0].symbol == "JUP"
    assert cached.items[0].risk_status == "verified"
    with store.connect() as con:
        assert con.execute("select count(*) from tax_lots").fetchone()[0] == 0
        assert con.execute("select count(*) from tax_lines").fetchone()[0] == 0


def test_jupiter_metadata_refresh_reports_missing_key(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(JupiterTokenService, "V1_DB_PATH", tmp_path / "missing-v1.db")
    jup_mint = "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"
    with store.connect() as con:
        con.execute(
            """
            insert into portfolio_live_balance_snapshots
                (snapshot_id, connector_id, asset, quantity, source, fetched_at)
            values ('snap-1', 'solscan', ?, 1, 'test', ?)
            """,
            [jup_mint, datetime.now(timezone.utc)],
        )
    monkeypatch.setattr(JupiterTokenService, "_api_key", lambda _self: "")

    result = JupiterTokenService(store).refresh_metadata_cache(limit=10)

    assert result.configured is False
    assert result.status == "missing_api_key"
    assert result.refreshed_count == 0
    assert result.skipped_count == 1


def test_jupiter_metadata_cache_api_routes(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(JupiterTokenService, "V1_DB_PATH", tmp_path / "missing-v1.db")
    monkeypatch.setattr(JupiterTokenService, "_api_key", lambda _self: "")
    app = create_app(store)

    cache_response = _call_get_route(app, "/api/v1/sources/jupiter/tokens/metadata-cache", limit=20)
    refresh_route = next(
        route for route in app.routes if getattr(route, "path", None) == "/api/v1/sources/jupiter/tokens/metadata-cache/refresh"
    )
    refresh_response = refresh_route.endpoint(limit=20, force=False)

    assert cache_response.status == "ok"
    assert cache_response.data.status == "ok"
    assert refresh_response.status == "warning"
    assert refresh_response.data.status == "missing_api_key"


def test_jupiter_risk_review_filters_spam_review(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(JupiterTokenService, "V1_DB_PATH", tmp_path / "missing-v1.db")
    now = datetime.now(timezone.utc)
    with store.connect() as con:
        con.execute(
            """
            insert into jupiter_token_metadata_cache (
                mint, symbol, name, decimals, icon, token_program, is_verified,
                organic_score, organic_score_label, holder_count, liquidity_usd,
                usd_price, market_cap_usd, risk_status, source,
                discovered_sources_json, refreshed_at, jupiter_updated_at
            ) values
                ('fakeMint1111111111111111111111111111111111', 'FAKE', 'Fake JUP', 6, null, null, false,
                 1, 'low', 1, 0, 0, 0, 'spam_review', 'jupiter_tokens_v2', '["v1_solscan:wallet"]', ?, null),
                ('JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN', 'JUP', 'Jupiter', 6, null, null, true,
                 98, 'high', 100, 1000, 1, 1000, 'verified', 'jupiter_tokens_v2', '["v1_solscan:wallet"]', ?, null)
            """,
            [now, now],
        )

    result = JupiterTokenService(store).risk_review("spam_review")

    assert result.status == "ok"
    assert result.risk_status == "spam_review"
    assert result.items_count == 1
    assert result.spam_review_count == 1
    assert result.verified_count == 1
    assert result.items[0].symbol == "FAKE"
    assert result.items[0].risk_status == "spam_review"


def test_jupiter_risk_review_api_route_rejects_unknown_filter(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    response = _call_get_route(
        create_app(store),
        "/api/v1/sources/jupiter/tokens/risk-review",
        risk_status="danger",
        limit=20,
    )

    assert response.status == "error"
    assert response.errors[0].code == "jupiter_token_risk_review_failed"
