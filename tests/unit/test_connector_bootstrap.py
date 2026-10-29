import json
import os
import stat
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest
from nacl.signing import SigningKey

from steuerreport_v2.api.app import create_app
from steuerreport_v2.container_entrypoint import initialize_state
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.connector_bootstrap import TOKEN_FILE_ENV, initialize_token, read_token, token_path


def _base58(content):
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number, encoded = int.from_bytes(content, "big"), ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = alphabet[remainder] + encoded
    return "1" * (len(content) - len(content.lstrip(b"\0"))) + encoded


@pytest.fixture
def bootstrap(tmp_path, monkeypatch):
    monkeypatch.delenv(TOKEN_FILE_ENV, raising=False)
    monkeypatch.delenv("STEUERREPORT_V2_ALLOW_INITIAL_VAULT_KEY_PROVISIONING", raising=False)
    # Track missing variables too: initialize_state sets defaults directly.
    for key in ("STEUERREPORT_V2_REQUIRE_ENCRYPTED_SECRETS", "STEUERREPORT_USERTRANSFER_ROOT"):
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)
    monkeypatch.setenv("STEUERREPORT_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", str(tmp_path / "private_profile.json"))
    monkeypatch.setenv("STEUERREPORT_V2_DB", str(tmp_path / "data/test.duckdb"))
    monkeypatch.setenv("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", str(tmp_path / "keys/vault.key"))
    return tmp_path


def test_init_is_explicit_private_and_idempotent(bootstrap):
    assert read_token() == ""
    first = initialize_token()
    path = token_path()
    value = path.read_bytes()
    assert first["created"] and first["secret_returned"] is False
    assert len(read_token()) == 64
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert read_token() not in json.dumps(first)
    assert initialize_token()["created"] is False
    assert path.read_bytes() == value


def test_existing_explicit_configuration_is_not_replaced_or_bypassed(bootstrap, monkeypatch):
    initialize_token()
    original = token_path().read_bytes()
    monkeypatch.setenv(TOKEN_FILE_ENV, "")
    assert read_token() == ""
    with pytest.raises(RuntimeError, match="disabled"):
        initialize_token()
    monkeypatch.setenv(TOKEN_FILE_ENV, str(bootstrap / "missing.token"))
    assert read_token() == ""
    monkeypatch.delenv(TOKEN_FILE_ENV)
    assert token_path().read_bytes() == original


@pytest.mark.parametrize("damage", ["permissions", "empty", "symlink", "hardlink"])
def test_unsafe_existing_managed_files_fail_closed_without_replacement(bootstrap, damage):
    initialize_token()
    path = token_path()
    value = path.read_bytes()
    if damage == "permissions":
        path.chmod(0o644)
    elif damage == "empty":
        path.write_bytes(b"")
    elif damage == "symlink":
        original = path.with_suffix(".original")
        path.rename(original)
        path.symlink_to(original)
    else:
        os.link(path, path.with_suffix(".alias"))
    assert read_token() == ""
    with pytest.raises(RuntimeError):
        initialize_token()
    assert path.read_bytes() == (b"" if damage == "empty" else value)


def test_bootstrap_does_not_allow_software_or_shared_write_locations(bootstrap, monkeypatch):
    from steuerreport_v2.paths import PROJECT_ROOT
    monkeypatch.setenv(TOKEN_FILE_ENV, str(PROJECT_ROOT / "forbidden.token"))
    with pytest.raises(RuntimeError, match="inside_software"):
        initialize_token()
    parent = bootstrap / "shared"
    parent.mkdir(mode=0o777)
    parent.chmod(0o777)
    monkeypatch.setenv(TOKEN_FILE_ENV, str(parent / "forbidden.token"))
    with pytest.raises(RuntimeError, match="directory_not_private"):
        initialize_token()
    assert not (parent / "forbidden.token").exists()
    monkeypatch.setenv(TOKEN_FILE_ENV, str(parent / "private-subdirectory/forbidden.token"))
    with pytest.raises(RuntimeError, match="directory_not_private"):
        initialize_token()


@pytest.mark.parametrize("existing", [None, "profile", "database", "vault"])
def test_bootstrap_only_prepares_auth_for_a_fresh_installation(bootstrap, existing):
    if existing == "profile":
        (bootstrap / "private_profile.json").write_text("{}")
    elif existing == "database":
        (bootstrap / "data").mkdir()
        (bootstrap / "data/test.duckdb").write_bytes(b"existing-fixture")
    elif existing == "vault":
        (bootstrap / "keys").mkdir()
        (bootstrap / "keys/vault.key").write_bytes(bytes(range(32)))
    mask = os.umask(0o077)
    try:
        if existing in {"profile", "database"}:
            with pytest.raises(RuntimeError, match="secret_vault_key_missing"):
                initialize_state()
            assert not (bootstrap / "keys/vault.key").exists()
            assert read_token() == ""
            return
        initialize_state()
        assert bool(read_token()) is (existing is None)
        vault = (bootstrap / "keys/vault.key").read_bytes()
        token = read_token()
        initialize_state()
        assert read_token() == token
        assert (bootstrap / "keys/vault.key").read_bytes() == vault
    finally:
        os.umask(mask)


def test_wallet_still_requires_bearer_and_signature_after_bootstrap(bootstrap):
    (bootstrap / "private_profile.json").write_text("{}")
    store = DuckDbStore(bootstrap / "data/test.duckdb")
    client = TestClient(create_app(store))
    payload = {"wallet_address": _base58(SigningKey.generate().verify_key.encode()), "wallet_provider": "other"}
    endpoint = "/api/v1/connectors/wallet/challenges"
    assert client.post(endpoint, json=payload).status_code == 503
    initialize_token()
    assert client.post(endpoint, json=payload).status_code == 401
    assert client.post(endpoint, json=payload, headers={"Authorization": "Bearer wrong"}).status_code == 401
    response = client.post(endpoint, json=payload, headers={"Authorization": "Bearer " + read_token()})
    assert response.status_code == 200
    challenge = response.json()["data"]
    result = client.post("/api/v1/connectors/wallet/verifications", json={"challenge_id": challenge["challenge_id"], "signature": "1" * 64}, headers={"Authorization": "Bearer " + read_token()})
    assert result.json()["status"] == "error"
    catalog = client.get("/api/v1/connectors/catalog")
    assert catalog.json()["data"]["security"]["auth_mode"] == "setup_token"
    assert read_token() not in catalog.text
    with store.connect() as connection:
        assert connection.execute("select count(*) from canonical_events").fetchone()[0] == 0
        assert connection.execute("select count(*) from tax_lots").fetchone()[0] == 0


def test_cli_never_returns_secret_without_explicit_interactive_display(bootstrap, monkeypatch, capsys):
    from steuerreport_v2.connector_setup import main
    monkeypatch.setattr(sys, "argv", ["connector_setup", "init"])
    main()
    assert read_token() not in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["connector_setup", "show-token"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    output = capsys.readouterr()
    assert read_token() not in output.out + output.err
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    main()
    assert capsys.readouterr().out.strip() == read_token()


def test_fresh_process_sees_same_protected_setup_without_disclosing_value(bootstrap):
    initialize_token()
    original = token_path().read_bytes()
    result = subprocess.run([sys.executable, "-m", "steuerreport_v2.connector_setup", "status"], capture_output=True, text=True, check=True)
    assert json.loads(result.stdout)["configured"] is True
    assert read_token() not in result.stdout + result.stderr
    assert token_path().read_bytes() == original


@pytest.mark.parametrize("public_key", [bytes(32), b"\x01" + bytes(31), b"\xff" * 32])
def test_invalid_or_low_order_public_keys_cannot_prove_wallet_ownership(bootstrap, public_key):
    from steuerreport_v2.contracts.connectors import WalletOwnershipChallengeRequest
    from steuerreport_v2.domain.connectors import ConnectorService
    service = ConnectorService(DuckDbStore(bootstrap / "data/test.duckdb"))
    with pytest.raises(ValueError, match="invalid_solana_wallet_address"):
        service.create_wallet_challenge(WalletOwnershipChallengeRequest(wallet_address=_base58(public_key), wallet_provider="other"))


def test_legacy_low_order_challenge_is_rejected_on_verification(bootstrap, monkeypatch):
    from steuerreport_v2.contracts.connectors import WalletOwnershipChallengeRequest
    from steuerreport_v2.domain.connectors import ConnectorService
    service = ConnectorService(DuckDbStore(bootstrap / "data/test.duckdb"))
    with monkeypatch.context() as patch:
        patch.setattr(service, "_validate_solana_address", lambda *_args: None)
        challenge = service.create_wallet_challenge(WalletOwnershipChallengeRequest(wallet_address=_base58(bytes(32)), wallet_provider="other"))
    with pytest.raises(ValueError, match="wallet_signature_invalid"):
        service.verify_wallet_challenge(challenge.challenge_id, _base58(bytes(64)))
