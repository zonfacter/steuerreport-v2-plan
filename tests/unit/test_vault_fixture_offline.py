from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from steuerreport_v2.domain.secret_vault import encrypt_secret_setting


SPEC = importlib.util.spec_from_file_location(
    "check_vault_fixture_offline_v2", Path(__file__).resolve().parents[2] / "scripts/check_vault_fixture_offline_v2.py"
)
assert SPEC is not None and SPEC.loader is not None
proof = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proof)


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.selected = None
        self.closed = False

    def execute(self, query, params):
        self.selected = params[0]
        return self

    def fetchall(self):
        return self.rows.get(self.selected, [])

    def close(self):
        self.closed = True


@pytest.fixture
def fixture(monkeypatch):
    key = bytes(range(1, 33))
    pairs = {
        "secret.cex.binance.api_key": "synthetic-key",
        "secret.cex.binance.api_secret": "synthetic-secret",
    }
    rows = {name: [(encrypt_secret_setting(name, value, key),)] for name, value in pairs.items()}
    connection = FakeConnection(rows)
    monkeypatch.setenv("STEUERREPORT_SYNTHETIC_VAULT_PROOF", "1")
    monkeypatch.setattr(proof.Path, "read_bytes", lambda self: key)
    monkeypatch.setattr(proof.duckdb, "connect", lambda path, read_only: connection)
    monkeypatch.setattr(proof, "decode_secret_setting", lambda name, raw: pairs[name])
    return key, pairs, connection


def test_synthetic_ciphertexts_and_wrong_key_are_checked(fixture, capsys):
    key, _, connection = fixture
    proof.main()
    assert len(capsys.readouterr().out.strip()) == 64
    assert connection.closed and len(key) == 32


def test_plaintext_is_rejected(fixture):
    _, pairs, connection = fixture
    name = next(iter(pairs))
    connection.rows[name] = [(json.dumps(pairs[name]),)]
    with pytest.raises(ValueError, match="not_encrypted"):
        proof.main()
    assert connection.closed


def test_missing_confirmation_stops_before_open(fixture, monkeypatch):
    _, _, connection = fixture
    monkeypatch.delenv("STEUERREPORT_SYNTHETIC_VAULT_PROOF")
    with pytest.raises(RuntimeError, match="synthetic_fixture_confirmation_required"):
        proof.main()
    assert not connection.closed


def test_plaintext_is_rejected_with_python_optimization():
    code = r'''
import importlib.util, json, os, sys
from pathlib import Path
spec = importlib.util.spec_from_file_location("proof", sys.argv[1])
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)
class Fake:
    def execute(self, query, params): return self
    def fetchall(self): return [(json.dumps("synthetic-key"),)]
    def close(self): pass
proof.Path.read_bytes = lambda self: bytes(range(1,33))
proof.duckdb.connect = lambda *args, **kwargs: Fake()
os.environ["STEUERREPORT_SYNTHETIC_VAULT_PROOF"] = "1"
try:
    proof.main()
except ValueError as exc:
    if str(exc) == "not_encrypted": raise SystemExit(0)
raise SystemExit(1)
'''
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    script = Path(__file__).resolve().parents[2] / "scripts/check_vault_fixture_offline_v2.py"
    result = subprocess.run([sys.executable, "-O", "-c", code, str(script)], env=env, check=False, capture_output=True)
    assert result.returncode == 0
