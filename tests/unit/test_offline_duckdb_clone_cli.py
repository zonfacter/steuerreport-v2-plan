import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import duckdb
import pytest

from steuerreport_v2.db import offline_snapshot


ROOT = Path(__file__).resolve().parents[2]


def invoke(*args, module=True):
    command = [sys.executable]
    command += ["-m", "steuerreport_v2.db.offline_snapshot"] if module else [str(ROOT / "scripts/clone_offline_duckdb_v2.py")]
    return subprocess.run(command + list(map(str, args)), capture_output=True, text=True, timeout=30,
                          env={**os.environ, "PYTHONPATH": str(ROOT / "src")})


@pytest.mark.parametrize("module", [True, False])
def test_offline_cli_and_packaged_module_clone_and_restore_to_new_path(tmp_path, module):
    source, backup, restored = (tmp_path / name for name in ("source.duckdb", "backup.duckdb", "restored.duckdb"))
    with duckdb.connect(str(source)) as con:
        con.execute("create table evidence(value decimal(38,18), note varchar)")
        con.execute("insert into evidence values (0.123456789012345678, 'synthetic')")
    original = source.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    result = invoke("--source", source, "--destination", backup, module=module)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "verified" and data["scope"] == "database_only"
    assert data["source_sha256"] == data["target_sha256"] == digest
    assert data["table_count"] == 1 and data["size_bytes"] == len(original)
    assert backup.stat().st_mode & 0o777 == 0o600
    result = invoke("--source", backup, "--destination", restored, "--expected-sha256", digest, module=module)
    assert result.returncode == 0, result.stderr
    assert source.read_bytes() == backup.read_bytes() == restored.read_bytes() == original
    with duckdb.connect(str(restored), read_only=True) as con:
        assert con.execute("select cast(value as varchar),note from evidence").fetchall() == [
            ("0.123456789012345678", "synthetic")]
    assert not list(tmp_path.glob(".steuerreport-offline-*"))


def test_cli_error_does_not_echo_source_path_or_file_content(tmp_path):
    source = tmp_path / "synthetic-private-name.duckdb"
    source.write_bytes(b"synthetic-private-content-not-duckdb")
    result = invoke("--source", source, "--destination", tmp_path / "copy.duckdb")
    assert result.returncode == 2 and result.stderr == ""
    assert json.loads(result.stdout)["status"] == "blocked"
    assert "synthetic-private" not in result.stdout
    assert source.read_bytes() == b"synthetic-private-content-not-duckdb"
    assert sorted(p.name for p in tmp_path.iterdir()) == [source.name]


def test_no_replace_publication_preserves_racing_destination(tmp_path, monkeypatch):
    source, destination = tmp_path / "source.duckdb", tmp_path / "target.duckdb"
    with duckdb.connect(str(source)) as con:
        con.execute("create table evidence(i integer)")
    original = source.read_bytes()
    real_link = os.link
    def concurrent_destination(first, second):
        destination.write_bytes(b"synthetic-concurrent-owner")
        return real_link(first, second)
    monkeypatch.setattr(offline_snapshot.os, "link", concurrent_destination)
    with pytest.raises(offline_snapshot.OfflineDatabaseCloneError):
        offline_snapshot._clone_offline_database(source, destination)
    assert destination.read_bytes() == b"synthetic-concurrent-owner"
    assert source.read_bytes() == original
    assert not list(tmp_path.glob(".steuerreport-offline-*"))


def test_failure_after_publication_is_unknown_and_keeps_verified_new_copy(tmp_path, monkeypatch):
    source, destination = tmp_path / "source.duckdb", tmp_path / "target.duckdb"
    with duckdb.connect(str(source)) as con:
        con.execute("create table evidence(i integer)")
    original = source.read_bytes()
    real_fsync = os.fsync
    calls = []
    def fail_directory_sync(descriptor):
        calls.append(descriptor)
        if len(calls) == 2:
            raise OSError("synthetic directory sync failure")
        return real_fsync(descriptor)
    monkeypatch.setattr(offline_snapshot.os, "fsync", fail_directory_sync)
    with pytest.raises(offline_snapshot.OfflineDatabaseCloneError, match="publication_state_unknown"):
        offline_snapshot._clone_offline_database(source, destination)
    assert source.read_bytes() == destination.read_bytes() == original
    assert not list(tmp_path.glob(".steuerreport-offline-*"))


def test_cleanup_error_after_publication_is_sanitized_and_not_reported_as_success(tmp_path, monkeypatch):
    source, destination = tmp_path / "source.duckdb", tmp_path / "target.duckdb"
    with duckdb.connect(str(source)) as con:
        con.execute("create table evidence(i integer)")
    original = source.read_bytes()
    real_unlink = Path.unlink
    def fail_own_cleanup(path, *args, **kwargs):
        if path.name.startswith(".steuerreport-offline-"):
            raise OSError("synthetic private cleanup detail")
        return real_unlink(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail_own_cleanup)
        with pytest.raises(offline_snapshot.OfflineDatabaseCloneError, match="publication_state_unknown"):
            offline_snapshot._clone_offline_database(source, destination)
    assert source.read_bytes() == destination.read_bytes() == original
    for pending in tmp_path.glob(".steuerreport-offline-*"):
        pending.unlink()


@pytest.mark.parametrize("returncode,body", [
    (-9, ""), (0, "not json"), (0, "[]"), (0, '{"status":"verified","result":{}}'),
    (2, '{"status":"blocked","reason":"/synthetic-private-path"}'),
    (0, json.dumps({"status": "verified", "result": {
        "source_sha256": "a" * 64, "target_sha256": "b" * 64, "size_bytes": 100, "table_count": 1}})),
])
def test_worker_crash_or_malformed_protocol_is_unknown_without_echo(tmp_path, monkeypatch, returncode, body):
    monkeypatch.setattr(offline_snapshot.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=returncode, stdout=body, stderr="synthetic-private-content"))
    with pytest.raises(offline_snapshot.OfflineDatabaseCloneError, match="worker_state_unknown"):
        offline_snapshot.clone_offline_database(tmp_path / "source.duckdb", tmp_path / "clone.duckdb")
    assert list(tmp_path.iterdir()) == []
