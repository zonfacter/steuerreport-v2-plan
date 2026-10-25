from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.connectors import (
    MobileConnectorPairingRequest,
    MobileConnectorSessionExchangeRequest,
    WalletOwnershipChallengeRequest,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.connectors import BASE58_ALPHABET, ConnectorService


def _encode_base58(value: bytes) -> str:
    number = int.from_bytes(value, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = BASE58_ALPHABET[remainder] + encoded
    leading_zeroes = len(value) - len(value.lstrip(b"\x00"))
    return "1" * leading_zeroes + (encoded or "")


def _wallet_keypair() -> tuple[Ed25519PrivateKey, str]:
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private_key, _encode_base58(public_key)


def _authorized_client(tmp_path, monkeypatch):
    token_file = tmp_path / "connector-setup.token"
    token_file.write_text("mobile-setup-token\n", encoding="utf-8")
    monkeypatch.setenv("STEUERREPORT_V2_CONNECTOR_SETUP_TOKEN_FILE", str(token_file))
    store = DuckDbStore(tmp_path / "db.duckdb")
    return store, TestClient(create_app(store)), {"Authorization": "Bearer mobile-setup-token"}


def test_connector_catalog_is_read_only_and_does_not_expose_setup_token(
    tmp_path, monkeypatch
):
    store, client, _headers = _authorized_client(tmp_path, monkeypatch)

    response = client.get("/api/v1/connectors/catalog")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"]["security"]["auth_mode"] == "setup_token"
    assert len(body["data"]["connectors"]) == 13
    assert "mobile-setup-token" not in response.text
    with store.connect() as con:
        assert con.execute("select count(*) from canonical_events").fetchone()[0] == 0
        assert con.execute("select count(*) from tax_lots").fetchone()[0] == 0


def test_wallet_challenge_requires_configured_bearer_token(tmp_path, monkeypatch):
    _private_key, wallet_address = _wallet_keypair()
    store = DuckDbStore(tmp_path / "db.duckdb")
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/connectors/wallet/challenges",
        json={"wallet_address": wallet_address, "wallet_provider": "phantom"},
    )
    assert response.status_code == 503

    token_file = tmp_path / "connector-setup.token"
    token_file.write_text("expected-token", encoding="utf-8")
    monkeypatch.setenv("STEUERREPORT_V2_CONNECTOR_SETUP_TOKEN_FILE", str(token_file))
    response = client.post(
        "/api/v1/connectors/wallet/challenges",
        headers={"Authorization": "Bearer wrong-token"},
        json={"wallet_address": wallet_address, "wallet_provider": "phantom"},
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_wallet_signature_creates_review_only_connection_without_tax_mutation(
    tmp_path, monkeypatch
):
    private_key, wallet_address = _wallet_keypair()
    store, client, headers = _authorized_client(tmp_path, monkeypatch)

    challenge_response = client.post(
        "/api/v1/connectors/wallet/challenges",
        headers=headers,
        json={
            "wallet_address": wallet_address,
            "wallet_provider": "phantom",
            "display_label": "Neue Phantom Wallet",
        },
    )
    challenge = challenge_response.json()["data"]
    signature = _encode_base58(private_key.sign(challenge["message"].encode("utf-8")))

    response = client.post(
        "/api/v1/connectors/wallet/verifications",
        headers=headers,
        json={"challenge_id": challenge["challenge_id"], "signature": signature},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"]["status"] == "ownership_verified_pending_registry"
    connection = body["data"]["connection"]
    assert connection["external_identifier"] == wallet_address
    assert connection["tax_activation"] == "review_required"
    assert connection["source_id"] is None
    assert body["data"]["registry_match"] is False
    connections = client.get("/api/v1/connectors/connections").json()["data"]
    assert len(connections) == 1
    assert connections[0]["external_identifier"] == wallet_address
    with store.connect() as con:
        assert con.execute("select count(*) from canonical_events").fetchone()[0] == 0
        assert con.execute("select count(*) from tax_lots").fetchone()[0] == 0

    replay = client.post(
        "/api/v1/connectors/wallet/verifications",
        headers=headers,
        json={"challenge_id": challenge["challenge_id"], "signature": signature},
    )
    assert replay.json()["status"] == "error"
    assert replay.json()["errors"][0]["code"] == "wallet_challenge_not_pending"


def test_registered_wallet_signature_retains_registry_activation(tmp_path, monkeypatch):
    private_key, wallet_address = _wallet_keypair()
    _store, client, headers = _authorized_client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        ConnectorService,
        "_registered_wallet_source_id",
        lambda _self, address: "registered-test-wallet" if address == wallet_address else None,
    )

    challenge = client.post(
        "/api/v1/connectors/wallet/challenges",
        headers=headers,
        json={"wallet_address": wallet_address, "wallet_provider": "jupiter"},
    ).json()["data"]
    signature = _encode_base58(private_key.sign(challenge["message"].encode("utf-8")))
    result = client.post(
        "/api/v1/connectors/wallet/verifications",
        headers=headers,
        json={"challenge_id": challenge["challenge_id"], "signature": signature},
    ).json()["data"]

    assert result["status"] == "registered"
    assert result["registry_match"] is True
    assert result["connection"]["source_id"] == "registered-test-wallet"
    assert result["connection"]["tax_activation"] == "registry_active"


def test_invalid_or_expired_wallet_signature_is_rejected(tmp_path, monkeypatch):
    private_key, wallet_address = _wallet_keypair()
    wrong_key, _wrong_address = _wallet_keypair()
    store, client, headers = _authorized_client(tmp_path, monkeypatch)
    challenge = client.post(
        "/api/v1/connectors/wallet/challenges",
        headers=headers,
        json={"wallet_address": wallet_address},
    ).json()["data"]
    invalid_signature = _encode_base58(
        wrong_key.sign(challenge["message"].encode("utf-8"))
    )

    invalid = client.post(
        "/api/v1/connectors/wallet/verifications",
        headers=headers,
        json={
            "challenge_id": challenge["challenge_id"],
            "signature": invalid_signature,
        },
    ).json()
    assert invalid["status"] == "error"
    assert invalid["errors"][0]["code"] == "wallet_signature_invalid"

    service = ConnectorService(store)
    issued_at = datetime(2026, 8, 27, 12, tzinfo=timezone.utc)
    expired = service.create_wallet_challenge(
        WalletOwnershipChallengeRequest(wallet_address=wallet_address),
        now=issued_at,
    )
    signature = _encode_base58(private_key.sign(expired.message.encode("utf-8")))
    try:
        service.verify_wallet_challenge(
            expired.challenge_id,
            signature,
            now=issued_at + timedelta(minutes=6),
        )
    except ValueError as exc:
        assert str(exc) == "wallet_challenge_expired"
    else:
        raise AssertionError("expired challenge was accepted")


def test_mobile_pairing_uses_hash_only_session_and_authorizes_wallet_setup(
    tmp_path, monkeypatch
):
    _private_key, wallet_address = _wallet_keypair()
    store, client, setup_headers = _authorized_client(tmp_path, monkeypatch)

    pairing_response = client.post(
        "/api/v1/connectors/mobile/pairings",
        headers=setup_headers,
        json={
            "device_name": "Mein iPhone",
            "platform": "ios",
            "scopes": ["connector:read", "wallet:verify"],
            "session_ttl_hours": 24,
        },
    )
    assert pairing_response.status_code == 200
    pairing = pairing_response.json()["data"]
    assert pairing["status"] == "pending"
    assert len(pairing["pairing_code"].replace("-", "")) == 20

    exchange_response = client.post(
        "/api/v1/connectors/mobile/sessions",
        json={
            "pairing_id": pairing["pairing_id"],
            "pairing_code": pairing["pairing_code"],
        },
    )
    assert exchange_response.status_code == 200
    exchange = exchange_response.json()["data"]
    access_token = exchange["access_token"]
    assert access_token.startswith("srv2m_")
    assert exchange["session"]["status"] == "active"
    mobile_headers = {"Authorization": f"Bearer {access_token}"}

    current = client.get(
        "/api/v1/connectors/mobile/session",
        headers=mobile_headers,
    ).json()["data"]
    assert current["device_name"] == "Mein iPhone"
    assert current["scopes"] == ["connector:read", "wallet:verify"]
    assert current["last_used_at"] is not None

    challenge_response = client.post(
        "/api/v1/connectors/wallet/challenges",
        headers=mobile_headers,
        json={"wallet_address": wallet_address, "wallet_provider": "phantom"},
    )
    assert challenge_response.status_code == 200
    assert challenge_response.json()["status"] == "ok"

    sessions = client.get(
        "/api/v1/connectors/mobile/sessions",
        headers=setup_headers,
    )
    assert access_token not in sessions.text
    sessions = sessions.json()["data"]
    assert len(sessions) == 1
    assert sessions[0]["session_id"] == exchange["session"]["session_id"]
    assert sessions[0]["last_used_at"] is not None
    catalog = client.get("/api/v1/connectors/catalog").json()["data"]
    assert catalog["security"]["mobile_pairing_enabled"] is True
    assert catalog["security"]["active_mobile_sessions"] == 1

    with store.connect() as con:
        pairing_row = con.execute(
            "select code_hash from mobile_connector_pairings"
        ).fetchone()
        session_row = con.execute(
            "select token_hash from mobile_connector_sessions"
        ).fetchone()
        assert pairing["pairing_code"] not in str(pairing_row[0])
        assert access_token not in str(session_row[0])
        assert con.execute("select count(*) from canonical_events").fetchone()[0] == 0
        assert con.execute("select count(*) from tax_lots").fetchone()[0] == 0

    replay = client.post(
        "/api/v1/connectors/mobile/sessions",
        json={
            "pairing_id": pairing["pairing_id"],
            "pairing_code": pairing["pairing_code"],
        },
    ).json()
    assert replay["status"] == "error"
    assert replay["errors"][0]["code"] == "mobile_pairing_invalid"

    revoked = client.delete(
        f"/api/v1/connectors/mobile/sessions/{exchange['session']['session_id']}",
        headers=setup_headers,
    ).json()["data"]
    assert revoked["status"] == "revoked"
    rejected = client.post(
        "/api/v1/connectors/wallet/challenges",
        headers=mobile_headers,
        json={"wallet_address": wallet_address},
    )
    assert rejected.status_code == 401
    assert rejected.json()["detail"] == "mobile_session_revoked"


def test_mobile_session_scope_is_enforced(tmp_path, monkeypatch):
    _private_key, wallet_address = _wallet_keypair()
    _store, client, setup_headers = _authorized_client(tmp_path, monkeypatch)
    pairing = client.post(
        "/api/v1/connectors/mobile/pairings",
        headers=setup_headers,
        json={
            "device_name": "Read-only Android",
            "platform": "android",
            "scopes": ["connector:read"],
        },
    ).json()["data"]
    token = client.post(
        "/api/v1/connectors/mobile/sessions",
        json={
            "pairing_id": pairing["pairing_id"],
            "pairing_code": pairing["pairing_code"],
        },
    ).json()["data"]["access_token"]

    response = client.post(
        "/api/v1/connectors/wallet/challenges",
        headers={"Authorization": f"Bearer {token}"},
        json={"wallet_address": wallet_address},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "mobile_session_scope_missing"


def test_mobile_pairing_expires_without_creating_session(tmp_path):
    store = DuckDbStore(tmp_path / "db.duckdb")
    service = ConnectorService(store)
    issued_at = datetime(2026, 8, 27, 12, tzinfo=timezone.utc)
    pairing = service.create_mobile_pairing(
        MobileConnectorPairingRequest(
            device_name="Expired Device",
            platform="android",
        ),
        now=issued_at,
    )

    with pytest.raises(ValueError, match="mobile_pairing_expired"):
        service.exchange_mobile_pairing(
            MobileConnectorSessionExchangeRequest(
                pairing_id=pairing.pairing_id,
                pairing_code=pairing.pairing_code,
            ),
            now=issued_at + timedelta(minutes=11),
        )

    with store.connect() as con:
        assert con.execute(
            "select status from mobile_connector_pairings"
        ).fetchone()[0] == "expired"
        assert con.execute(
            "select count(*) from mobile_connector_sessions"
        ).fetchone()[0] == 0


def test_mobile_pairing_locks_after_five_invalid_codes(tmp_path):
    store = DuckDbStore(tmp_path / "db.duckdb")
    service = ConnectorService(store)
    pairing = service.create_mobile_pairing(
        MobileConnectorPairingRequest(
            device_name="Untrusted Device",
            platform="other",
        )
    )
    invalid = MobileConnectorSessionExchangeRequest(
        pairing_id=pairing.pairing_id,
        pairing_code="22222-22222-22222-22222",
    )

    for _ in range(5):
        with pytest.raises(ValueError, match="mobile_pairing_invalid"):
            service.exchange_mobile_pairing(invalid)

    with pytest.raises(ValueError, match="mobile_pairing_invalid"):
        service.exchange_mobile_pairing(
            MobileConnectorSessionExchangeRequest(
                pairing_id=pairing.pairing_id,
                pairing_code=pairing.pairing_code,
            )
        )
    with store.connect() as con:
        row = con.execute(
            "select status, attempt_count from mobile_connector_pairings"
        ).fetchone()
        assert row == ("failed", 5)
        assert con.execute(
            "select count(*) from mobile_connector_sessions"
        ).fetchone()[0] == 0
