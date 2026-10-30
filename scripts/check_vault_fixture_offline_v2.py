"""Inspect only the explicitly enabled synthetic Docker vault fixture offline."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import duckdb
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from steuerreport_v2.domain.secret_vault import decode_secret_setting


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def main() -> None:
    if os.environ.get("STEUERREPORT_SYNTHETIC_VAULT_PROOF") != "1":
        raise RuntimeError("synthetic_fixture_confirmation_required")
    key = Path("/state/keys/vault.key").read_bytes()
    require(len(key) == 32 and key != bytes(32), "synthetic_key_invalid")
    connection = duckdb.connect("/state/data/steuerreport_v2.duckdb", read_only=True)
    try:
        for name, expected in (
            ("secret.cex.binance.api_key", "synthetic-key"),
            ("secret.cex.binance.api_secret", "synthetic-secret"),
        ):
            rows = connection.execute("select value_json from admin_settings where key = ?", [name]).fetchall()
            require(len(rows) == 1, "synthetic_setting_count_invalid")
            raw = rows[0][0]
            envelope = json.loads(raw)
            require(isinstance(envelope, dict) and envelope.get("type") == "steuerreport-secret", "not_encrypted")
            require(envelope.get("algorithm") == "AES-256-GCM", "unexpected_algorithm")
            require(envelope.get("key_id") == hashlib.sha256(key).hexdigest()[:16], "incorrect_key_id")
            require(expected not in raw and decode_secret_setting(name, raw) == expected, "fixture_not_decryptable")
            try:
                AESGCM(bytes(32)).decrypt(
                    base64.b64decode(envelope["nonce"], validate=True),
                    base64.b64decode(envelope["ciphertext"], validate=True),
                    name.encode(),
                )
            except InvalidTag:
                pass
            else:
                raise AssertionError("incorrect_key_was_accepted")
    finally:
        connection.close()
    # The randomly generated key belongs only to the isolated synthetic volume.
    print(hashlib.sha256(key).hexdigest())


if __name__ == "__main__":
    main()
