from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

from steuerreport_v2.contracts.connectors import (
    ConnectorVaultStatus,
    SecretVaultMigrationResult,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore


SECRET_PREFIX = "secret."
ENVELOPE_TYPE = "steuerreport-secret"
ENVELOPE_VERSION = 1
KEY_FILE_ENV = "STEUERREPORT_V2_SECRET_VAULT_KEY_FILE"
REQUIRE_ENCRYPTED_ENV = "STEUERREPORT_V2_REQUIRE_ENCRYPTED_SECRETS"


def encrypted_secrets_required() -> bool:
    return os.environ.get(REQUIRE_ENCRYPTED_ENV, "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def load_vault_key() -> bytes | None:
    configured_path = os.environ.get(KEY_FILE_ENV, "").strip()
    if not configured_path:
        return None
    try:
        content = Path(configured_path).expanduser().read_bytes()
    except OSError:
        return None
    if len(content) == 32:
        return content
    try:
        encoded = content.decode("ascii").strip()
    except UnicodeDecodeError:
        return None
    if len(encoded) == 64:
        try:
            decoded = bytes.fromhex(encoded)
        except ValueError:
            decoded = b""
        if len(decoded) == 32:
            return decoded
    try:
        decoded = base64.b64decode(encoded, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error):
        return None
    return decoded if len(decoded) == 32 else None


def vault_key_id(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:16]


def is_encrypted_envelope(value_json: str) -> bool:
    try:
        value = json.loads(value_json)
    except json.JSONDecodeError:
        return False
    return (
        isinstance(value, dict)
        and value.get("type") == ENVELOPE_TYPE
        and value.get("version") == ENVELOPE_VERSION
    )


def encrypt_secret_setting(key_name: str, secret_value: str, vault_key: bytes) -> str:
    if len(vault_key) != 32:
        raise ValueError("secret_vault_key_must_be_32_bytes")
    nonce = os.urandom(12)
    ciphertext = AESGCM(vault_key).encrypt(
        nonce,
        secret_value.encode("utf-8"),
        key_name.encode("utf-8"),
    )
    return json.dumps(
        {
            "type": ENVELOPE_TYPE,
            "version": ENVELOPE_VERSION,
            "algorithm": "AES-256-GCM",
            "key_id": vault_key_id(vault_key),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def decode_secret_setting(key_name: str, value_json: str) -> str:
    try:
        value = json.loads(value_json)
    except json.JSONDecodeError:
        return ""
    if not isinstance(value, dict) or value.get("type") != ENVELOPE_TYPE:
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        raise ValueError("secret_setting_must_be_json_string")
    if value.get("version") != ENVELOPE_VERSION:
        raise ValueError("unsupported_secret_envelope_version")
    vault_key = load_vault_key()
    if vault_key is None:
        raise RuntimeError("secret_vault_key_unavailable")
    try:
        nonce = base64.b64decode(str(value["nonce"]), validate=True)
        ciphertext = base64.b64decode(str(value["ciphertext"]), validate=True)
        plaintext = AESGCM(vault_key).decrypt(
            nonce,
            ciphertext,
            key_name.encode("utf-8"),
        )
    except (KeyError, ValueError, binascii.Error, InvalidTag) as exc:
        raise ValueError("secret_envelope_unreadable") from exc
    return plaintext.decode("utf-8").strip()


def prepare_secret_setting(key_name: str, secret_value: str) -> str:
    vault_key = load_vault_key()
    if vault_key is not None:
        return encrypt_secret_setting(key_name, secret_value, vault_key)
    if encrypted_secrets_required():
        raise RuntimeError("secret_vault_key_required")
    return json.dumps(secret_value)


def secret_vault_status(store: DuckDbStore) -> ConnectorVaultStatus:
    vault_key = load_vault_key()
    encrypted = 0
    plaintext = 0
    unreadable = 0
    for setting in store.list_admin_settings():
        if not setting.key.casefold().startswith(SECRET_PREFIX):
            continue
        if is_encrypted_envelope(setting.value_json):
            encrypted += 1
            try:
                decode_secret_setting(setting.key, setting.value_json)
            except (RuntimeError, ValueError, UnicodeDecodeError):
                unreadable += 1
            continue
        try:
            if decode_secret_setting(setting.key, setting.value_json):
                plaintext += 1
        except (RuntimeError, ValueError, UnicodeDecodeError):
            unreadable += 1
    if unreadable:
        status = "error"
    elif vault_key is None:
        status = "not_configured"
    elif plaintext:
        status = "migration_required"
    else:
        status = "encrypted"
    return ConnectorVaultStatus(
        configured=vault_key is not None,
        require_encrypted_secrets=encrypted_secrets_required(),
        key_id=vault_key_id(vault_key) if vault_key is not None else None,
        encrypted_secrets=encrypted,
        plaintext_secrets=plaintext,
        unreadable_secrets=unreadable,
        status=status,
    )


def migrate_secret_vault(store: DuckDbStore, *, apply: bool) -> SecretVaultMigrationResult:
    generated_at = datetime.now(timezone.utc)
    vault_key = load_vault_key()
    if vault_key is None:
        return SecretVaultMigrationResult(
            generated_at=generated_at,
            status="blocked",
            message="Secret-Vault-Key fehlt oder ist unlesbar.",
        )
    with store.connect() as con:
        rows = con.execute(
            """
            select key, value_json
            from admin_settings
            where lower(key) like 'secret.%'
            order by key
            """
        ).fetchall()
    already_encrypted = 0
    unreadable = 0
    plaintext_rows: list[tuple[str, str]] = []
    for row in rows:
        key_name = str(row[0])
        value_json = str(row[1])
        if is_encrypted_envelope(value_json):
            already_encrypted += 1
            try:
                decode_secret_setting(key_name, value_json)
            except (RuntimeError, ValueError, UnicodeDecodeError):
                unreadable += 1
            continue
        try:
            if decode_secret_setting(key_name, value_json):
                plaintext_rows.append((key_name, value_json))
        except (RuntimeError, ValueError, UnicodeDecodeError):
            unreadable += 1
    if unreadable:
        return SecretVaultMigrationResult(
            generated_at=generated_at,
            status="blocked",
            already_encrypted=already_encrypted,
            plaintext_remaining=len(plaintext_rows),
            unreadable_secrets=unreadable,
            key_id=vault_key_id(vault_key),
            message="Mindestens ein Secret-Setting ist unlesbar; Migration abgebrochen.",
        )
    if not apply:
        return SecretVaultMigrationResult(
            generated_at=generated_at,
            status="no_changes" if not plaintext_rows else "blocked",
            already_encrypted=already_encrypted,
            plaintext_remaining=len(plaintext_rows),
            key_id=vault_key_id(vault_key),
            message=(
                "Keine Klartext-Secrets vorhanden."
                if not plaintext_rows
                else "Vorschau: Klartext-Secrets koennen mit --apply migriert werden."
            ),
        )
    encrypted_rows = [
        (
            key_name,
            encrypt_secret_setting(
                key_name,
                decode_secret_setting(key_name, value_json),
                vault_key,
            ),
        )
        for key_name, value_json in plaintext_rows
    ]
    for key_name, encrypted_value in encrypted_rows:
        if not decode_secret_setting(key_name, encrypted_value):
            raise RuntimeError("secret_vault_verification_failed")
    with store.connect() as con:
        con.execute("begin transaction")
        try:
            updated_at = datetime.now(timezone.utc)
            for key_name, encrypted_value in encrypted_rows:
                con.execute(
                    """
                    update admin_settings
                    set value_json = ?, updated_at = ?
                    where key = ?
                    """,
                    [encrypted_value, updated_at, key_name],
                )
            remaining = con.execute(
                """
                select key, value_json
                from admin_settings
                where lower(key) like 'secret.%'
                """
            ).fetchall()
            if any(not is_encrypted_envelope(str(row[1])) for row in remaining):
                raise RuntimeError("plaintext_secret_remaining")
            for key_name, encrypted_value in remaining:
                decode_secret_setting(str(key_name), str(encrypted_value))
            con.execute("commit")
        except Exception:
            con.execute("rollback")
            raise
    status = secret_vault_status(store)
    return SecretVaultMigrationResult(
        generated_at=generated_at,
        status="encrypted" if encrypted_rows else "no_changes",
        encrypted_now=len(encrypted_rows),
        already_encrypted=already_encrypted,
        plaintext_remaining=status.plaintext_secrets,
        unreadable_secrets=status.unreadable_secrets,
        key_id=status.key_id,
        message=(
            "Alle V2-Secrets sind AES-256-GCM-verschluesselt."
            if encrypted_rows
            else "Alle V2-Secrets waren bereits verschluesselt."
        ),
    )
