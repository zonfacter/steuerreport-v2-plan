from fastapi.testclient import TestClient
from nacl.signing import SigningKey
import pytest
from datetime import datetime, timezone
from decimal import Decimal

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.connectors import WalletOwnershipChallengeRequest
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.connectors import ConnectorService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.source_registry import SourceRegistryService
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


def base58(value):
    alphabet, number, encoded = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz", int.from_bytes(value, "big"), ""
    while number:
        number, rest = divmod(number, 58)
        encoded = alphabet[rest] + encoded
    return "1" * (len(value) - len(value.lstrip(b"\0"))) + encoded


@pytest.fixture
def setup(tmp_path, monkeypatch):
    profile = tmp_path / "profile.json"
    profile.write_text("{}")
    registry = tmp_path / "registry.json"
    registry.write_text('{"registry_version":"test","entries":[],"ledger_adjustments":[],"transfer_evidence":[]}')
    monkeypatch.setenv("STEUERREPORT_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", str(profile))
    monkeypatch.setenv("STEUERREPORT_V2_CONNECTOR_SETUP_TOKEN_FILE", "")
    monkeypatch.setattr(SourceRegistryService, "DEFAULT_CONFIG_PATH", registry)
    monkeypatch.setattr(PortfolioService, "SOURCE_REGISTRY_CONFIG_PATH", registry)
    monkeypatch.setattr(PortfolioService, "PRIMARY_SOLANA_WALLET", "")
    monkeypatch.setattr(PortfolioService, "KNOWN_JUP_WALLET", "")
    def no_external(*args, **kwargs):
        raise AssertionError("No external call allowed")
    monkeypatch.setattr(PortfolioService, "_live_solana_wallet_balances", no_external)
    store = DuckDbStore(tmp_path / "test.duckdb")
    app = create_app(store)
    return TestClient(app), store, profile, registry


def test_public_wallet_without_password_or_signature_is_persistent_and_review_only(setup):
    client, store, profile, registry = setup
    original_profile, original_registry = profile.read_bytes(), registry.read_bytes()
    address = base58(SigningKey.generate().verify_key.encode())
    result = client.post("/api/v1/workspace/wallets", json={"wallet_address": address, "display_label": "Test wallet"})
    assert result.status_code == 200
    data = result.json()["data"]
    assert data["created"]
    assert data["connection"]["status"] == "address_saved"
    assert data["connection"]["verified_at"] is None
    assert data["connection"]["source_id"] is None
    assert data["connection"]["tax_activation"] == "review_required"
    fresh = TestClient(create_app(DuckDbStore(store.path)))
    rows = fresh.get("/api/v1/workspace/sources").json()["data"]["sources"]
    assert len(rows) == 1 and rows[0]["wallet_address"] == address
    assert rows[0]["value_eur"] is None and rows[0]["ownership_status"] == "not_assessed"
    ref = rows[0]["ref"]
    assert address not in ref
    detail = fresh.get(f"/api/v1/workspace/sources/{ref}").json()["data"]
    assert detail["evidence"]["wallet_address"] == address
    assert fresh.post(f"/api/v1/workspace/sources/{ref}/sync").status_code == 409
    assert profile.read_bytes() == original_profile and registry.read_bytes() == original_registry
    with store.connect() as con:
        for table in ("canonical_events", "balance_ledger", "tax_lines", "tax_lots", "wallet_ownership_challenges", "portfolio_live_connector_runs"):
            assert con.execute(f"select count(*) from {table}").fetchone()[0] == 0


def test_duplicates_do_not_create_new_sources_or_change_existing_verified_status(setup):
    client, store, _profile, _registry = setup
    key = SigningKey.generate()
    address = base58(key.verify_key.encode())
    first = client.post("/api/v1/workspace/wallets", json={"wallet_address": address}).json()["data"]
    second = client.post("/api/v1/workspace/wallets", json={"wallet_address": address, "display_label": "Other name"}).json()["data"]
    assert second["created"] is False and second["connection"] == first["connection"]
    service = ConnectorService(store)
    challenge = service.create_wallet_challenge(WalletOwnershipChallengeRequest(wallet_address=address))
    verified = service.verify_wallet_challenge(challenge.challenge_id, base58(key.sign(challenge.message.encode()).signature))
    assert verified.connection.connection_id == first["connection"]["connection_id"]
    again = client.post("/api/v1/workspace/wallets", json={"wallet_address": address}).json()["data"]
    assert again["connection"]["status"] == "ownership_verified_pending_registry"
    assert again["connection"]["verified_at"] is not None
    assert len(service.connections()) == 1


@pytest.mark.parametrize("address", ["x", "0" * 44, "x" * 44, "1" * 33, "A" * 45])
def test_invalid_addresses_are_rejected_without_writes(setup, address):
    client, store, *_rest = setup
    response = client.post("/api/v1/workspace/wallets", json={"wallet_address": address})
    assert response.status_code in {400, 422}
    assert not ConnectorService(store).connections()


def test_two_wallets_are_distinct_and_profile_wallet_is_not_duplicated(setup, monkeypatch):
    client, store, *_rest = setup
    addresses = [base58(SigningKey.generate().verify_key.encode()) for _ in range(2)]
    monkeypatch.setattr(PortfolioService, "PRIMARY_SOLANA_WALLET", addresses[0])
    for address in addresses:
        assert client.post("/api/v1/workspace/wallets", json={"wallet_address": address}).status_code == 200
    rows = client.get("/api/v1/workspace/sources").json()["data"]["sources"]
    assert len(rows) == 2 and {row["wallet_address"] for row in rows} == set(addresses)
    assert len({row["ref"] for row in rows}) == 2
    assert len(ConnectorService(store).connections()) == 2


def test_private_profile_address_is_visible_without_writing_a_connection_or_proof(setup, monkeypatch):
    client, store, *_rest = setup
    address = base58(SigningKey.generate().verify_key.encode())
    monkeypatch.setattr(PortfolioService, "PRIMARY_SOLANA_WALLET", address)
    rows = client.get("/api/v1/workspace/sources").json()["data"]["sources"]
    assert len(rows) == 1 and rows[0]["wallet_address"] == address
    assert rows[0]["connection_status"] == "address_saved"
    assert rows[0]["ownership_status"] == "not_assessed"
    assert not ConnectorService(store).connections()


def test_address_source_keeps_its_ref_after_import_without_double_listing(setup):
    client, store, *_rest = setup
    address = base58(SigningKey.generate().verify_key.encode())
    client.post("/api/v1/workspace/wallets", json={"wallet_address": address})
    before = client.get("/api/v1/workspace/sources").json()["data"]["sources"][0]["ref"]
    store.add_canonical_event(CanonicalEventCreate(source="manual-csv", event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        event_type="transfer", asset="SOL", quantity=Decimal("1"), account=address, wallet=address))
    BalanceLedgerBuilder(store).rebuild()
    rows = client.get("/api/v1/workspace/sources").json()["data"]["sources"]
    assert len(rows) == 1 and rows[0]["ref"] == before and rows[0]["events_count"] == 1
    assert client.get(f"/api/v1/workspace/sources/{before}").status_code == 200


def test_existing_import_detail_links_keep_working_when_address_is_added(setup):
    client, store, *_rest = setup
    address = base58(SigningKey.generate().verify_key.encode())
    store.add_canonical_event(CanonicalEventCreate(source="manual-csv", event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
        event_type="transfer", asset="SOL", quantity=Decimal("1"), account=address, wallet=address))
    BalanceLedgerBuilder(store).rebuild()
    legacy = client.get("/api/v1/workspace/sources").json()["data"]["sources"][0]["ref"]
    client.post("/api/v1/workspace/wallets", json={"wallet_address": address})
    detail = client.get(f"/api/v1/workspace/sources/{legacy}").json()["data"]
    assert detail["source"]["ref"] == legacy
    page = client.post("/api/v1/activity/query", json={"source_ref": legacy}).json()["data"]
    assert page["total"] == 1


def test_public_address_does_not_grant_proof_authorization_and_rejects_spoofed_fields(setup):
    client, _store, *_rest = setup
    address = base58(SigningKey.generate().verify_key.encode())
    assert client.post("/api/v1/workspace/wallets", json={"wallet_address": address}).status_code == 200
    assert client.post("/api/v1/connectors/wallet/challenges", json={"wallet_address": address}).status_code == 503
    assert client.post("/api/v1/workspace/wallets", json={"wallet_address": address, "status": "registered"}).status_code == 422


def test_revoked_connection_is_not_reactivated_by_public_save(setup):
    client, store, *_rest = setup
    address = base58(SigningKey.generate().verify_key.encode())
    client.post("/api/v1/workspace/wallets", json={"wallet_address": address})
    with store.connect() as con:
        con.execute("update connector_connections set status='revoked', revoked_at=current_timestamp")
    assert client.post("/api/v1/workspace/wallets", json={"wallet_address": address}).status_code == 400
    assert ConnectorService(store).connections()[0].status == "revoked"


def test_origin_guard_and_readonly_demo_prevent_address_writes(setup):
    client, store, *_rest = setup
    data = {"wallet_address": base58(SigningKey.generate().verify_key.encode())}
    assert client.post("/api/v1/workspace/wallets", json=data, headers={"Origin": "https://untrusted.invalid"}).status_code == 403
    assert client.post("/api/v1/workspace/wallets", json=data, headers={"Host": "untrusted.invalid"}).status_code == 400
    client.app.state.ux_sandbox = True
    assert client.post("/api/v1/workspace/wallets", json=data).status_code == 403
    assert not ConnectorService(store).connections()
