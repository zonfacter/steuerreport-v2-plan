"""Synthetische Vertragstests ohne Store, Migrationen oder produktive Daten."""

from contextlib import contextmanager
from dataclasses import is_dataclass
from datetime import date, datetime
from decimal import Decimal
import hashlib
import io
import os
from pathlib import Path
import selectors
import subprocess
import sys

import duckdb
import pytest

from steuerreport_v2.db.offline_snapshot import (
    _clone_offline_database as clone_worker_database,
    OfflineDatabaseCloneError,
    OfflineDatabaseCloneResult,
    clone_offline_database,
)


_WRITER = """
import sys
import duckdb

con = duckdb.connect(sys.argv[1], config={"threads": 1})
if sys.argv[2] == "dirty":
    con.execute("SET checkpoint_threshold = '1TB'")
    con.execute("INSERT INTO marker VALUES (2, 'nur im WAL')")
print("READY", flush=True)
sys.stdin.readline()
con.close()
"""

_TRY_WRITER = """
import sys
import duckdb

try:
    con = duckdb.connect(sys.argv[1], config={"threads": 1})
except duckdb.IOException as error:
    print(str(error), flush=True)
    sys.exit(23)
con.close()
"""


def _child_env():
    return {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}


@contextmanager
def _writer(source, *, dirty=False):
    process = subprocess.Popen(
        [sys.executable, "-u", "-c", _WRITER, str(source), "dirty" if dirty else "clean"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_child_env(),
    )
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=20), "DuckDB-Schreiber meldet sich nicht bereit"
        assert process.stdout.readline().strip() == "READY", "DuckDB-Schreiber abgebrochen"
        assert process.poll() is None
        yield process
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=20)


def _try_writer(source):
    return subprocess.run(
        [sys.executable, "-u", "-c", _TRY_WRITER, str(source)],
        capture_output=True,
        text=True,
        timeout=20,
        env=_child_env(),
    )


def _tree_state(root):
    """Vergleiche auch Sidecars, Symlinkziele und liegengebliebene Staging-Dateien."""
    state = {}
    for path in sorted(root.rglob("*")):
        stat = path.lstat()
        metadata = (stat.st_ino, stat.st_mode, stat.st_nlink)
        if path.is_symlink():
            value = (metadata, os.readlink(path))
        elif path.is_file():
            value = (metadata, stat.st_size, stat.st_mtime_ns, path.read_bytes())
        else:
            value = (metadata, "directory")
        state[path.relative_to(root)] = value
    return state


def _reject_unchanged(root, source, target, code, **kwargs):
    before = _tree_state(root)
    with pytest.raises(OfflineDatabaseCloneError) as caught:
        clone_offline_database(source, target, **kwargs)
    assert caught.value.code == code
    assert str(caught.value)
    assert _tree_state(root) == before


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.duckdb"
    with duckdb.connect(str(path), config={"threads": 1}) as con:
        con.execute("CREATE SCHEMA audit")
        con.execute("CREATE TABLE marker (id INTEGER PRIMARY KEY, note VARCHAR NOT NULL)")
        con.execute("INSERT INTO marker VALUES (1, 'synthetisch')")
        con.execute('''
            CREATE TABLE audit."quoted \"\" table" (
                id INTEGER PRIMARY KEY,
                amount DECIMAL(38, 18) NOT NULL,
                units HUGEINT,
                observed_at TIMESTAMP,
                day DATE,
                payload BLOB,
                note VARCHAR
            )
        ''')
        con.executemany(
            'INSERT INTO audit."quoted \"\" table" VALUES (?, ?, ?, ?, ?, ?, ?)',
            [
                (1, Decimal("12345678901234567890.123456789012345678"),
                 2**100 + 1, datetime(2025, 1, 2, 3, 4, 5, 123456),
                 date(2025, 1, 2), b"\x00\xff\x10", 'synthetisch " zitiert'),
                (2, Decimal("-0.000000000000000001"), -(2**100), None, None, b"", None),
            ],
        )
        con.execute("CREATE TABLE audit.marker (empty_value DECIMAL(38, 18))")
        con.execute("CREATE VIEW audit.visible AS SELECT * FROM main.marker")
        con.execute("CREATE INDEX marker_note ON marker(note)")
    assert not Path(str(path) + ".wal").exists()
    assert not Path(str(path) + ".tmp").exists()
    return path


@pytest.mark.parametrize("hash_mode", ["none", "exact", "uppercase"])
def test_closed_clean_clone_preserves_exact_bytes_values_and_schema(tmp_path, source, hash_mode):
    original = source.read_bytes()
    stat = source.stat()
    digest = hashlib.sha256(original).hexdigest()
    expected = {"none": None, "exact": digest, "uppercase": digest.upper()}[hash_mode]
    target = tmp_path / "clone.duckdb"

    result = clone_offline_database(source, target, expected_sha256=expected)

    assert isinstance(result, OfflineDatabaseCloneResult)
    assert is_dataclass(result) and not isinstance(result, type)
    assert result.source_sha256 == result.target_sha256 == digest
    assert result.size_bytes == len(original) > 0
    assert result.table_count == 3
    assert target.read_bytes() == original == source.read_bytes()
    assert target.stat().st_ino != source.stat().st_ino
    assert target.stat().st_nlink == source.stat().st_nlink == 1
    assert (source.stat().st_ino, source.stat().st_mtime_ns) == (stat.st_ino, stat.st_mtime_ns)
    assert set(tmp_path.iterdir()) == {source, target}

    with duckdb.connect(str(target), read_only=True) as con:
        assert con.execute('SELECT * FROM audit."quoted \"\" table" ORDER BY id').fetchall() == [
            (1, Decimal("12345678901234567890.123456789012345678"),
             2**100 + 1, datetime(2025, 1, 2, 3, 4, 5, 123456),
             date(2025, 1, 2), b"\x00\xff\x10", 'synthetisch " zitiert'),
            (2, Decimal("-0.000000000000000001"), -(2**100), None, None, b"", None),
        ]
        assert con.execute("SELECT * FROM audit.visible").fetchall() == [(1, "synthetisch")]
        assert con.execute("SELECT count(*) FROM audit.marker").fetchone() == (0,)
        assert con.execute("SELECT index_name FROM duckdb_indexes()").fetchall() == [("marker_note",)]
        with duckdb.connect(str(source), read_only=True) as original_con:
            for query in (
                "SELECT schema_name, table_name, sql FROM duckdb_tables() WHERE NOT internal ORDER BY 1, 2",
                "SELECT table_schema, table_name, column_name, data_type, is_nullable "
                "FROM information_schema.columns ORDER BY 1, 2, ordinal_position",
                "SELECT schema_name, table_name, constraint_type, constraint_text "
                "FROM duckdb_constraints() ORDER BY 1, 2, 3, 4",
            ):
                assert con.execute(query).fetchall() == original_con.execute(query).fetchall()
    assert source.read_bytes() == original


def test_closed_database_without_tables_is_a_valid_clone(tmp_path):
    source = tmp_path / "empty.duckdb"
    with duckdb.connect(str(source)):
        pass
    target = tmp_path / "clone.duckdb"
    result = clone_offline_database(source, target)
    assert result.table_count == 0
    assert result.size_bytes == len(source.read_bytes())
    assert source.read_bytes() == target.read_bytes()


def test_active_writer_without_wal_is_refused_by_real_duckdb_lock(tmp_path, source):
    with _writer(source):
        assert not Path(str(source) + ".wal").exists()
        _reject_unchanged(tmp_path, source, tmp_path / "clone.duckdb", "offline_clone_failed")
    # Der abgelehnte Versuch darf keine Sperre hinterlassen.
    assert clone_offline_database(source, tmp_path / "after-close.duckdb").table_count == 3


def test_committed_orphan_wal_after_sigkill_is_not_replayed_or_checkpointed(tmp_path, source):
    original = source.read_bytes()
    wal = Path(str(source) + ".wal")
    with _writer(source, dirty=True) as process:
        assert wal.is_file() and wal.stat().st_size > 0
        process.kill()
        assert process.wait(timeout=20) < 0
    assert source.read_bytes() == original
    _reject_unchanged(tmp_path, source, tmp_path / "clone.duckdb", "source_pending_state")
    assert wal.is_file() and source.read_bytes() == original


def test_missing_source_is_not_created(tmp_path):
    _reject_unchanged(tmp_path, tmp_path / "missing.duckdb", tmp_path / "clone.duckdb", "source_unavailable")


@pytest.mark.parametrize("content", [b"", b"not a DuckDB database\x00\xff"])
def test_corrupt_source_is_not_repaired_or_published(tmp_path, content):
    source = tmp_path / "corrupt.duckdb"
    source.write_bytes(content)
    _reject_unchanged(tmp_path, source, tmp_path / "clone.duckdb", "offline_clone_failed")


def test_truncated_real_database_is_refused(tmp_path, source):
    original = source.read_bytes()
    source.write_bytes(original[:len(original) // 2])
    _reject_unchanged(tmp_path, source, tmp_path / "clone.duckdb", "offline_clone_failed")


def test_expected_hash_must_match_actual_source_bytes(tmp_path, source):
    wrong_hash = hashlib.sha256(b"andere synthetische Bytes").hexdigest()
    assert wrong_hash != hashlib.sha256(source.read_bytes()).hexdigest()
    _reject_unchanged(
        tmp_path, source, tmp_path / "clone.duckdb", "source_hash_mismatch",
        expected_sha256=wrong_hash,
    )


@pytest.mark.parametrize("expected", ["", "a" * 63, "a" * 65, "g" * 64, " " + "a" * 64])
def test_malformed_expected_hash_is_rejected_without_changes(tmp_path, source, expected):
    _reject_unchanged(
        tmp_path, source, tmp_path / "clone.duckdb", "invalid_expected_sha256",
        expected_sha256=expected,
    )


@pytest.mark.parametrize("with_wal", [False, True])
def test_existing_database_is_never_automatically_restored(tmp_path, source, with_wal):
    target = tmp_path / "existing.duckdb"
    with duckdb.connect(str(target)) as con:
        con.execute("CREATE TABLE keep_me AS SELECT 42 AS value")
    if with_wal:
        Path(str(target) + ".wal").write_bytes(b"bestehendes Ziel-WAL")
    _reject_unchanged(tmp_path, source, target, "destination_exists")


@pytest.mark.parametrize("location", ["source", "destination"])
@pytest.mark.parametrize("suffix", [".wal", ".tmp"])
@pytest.mark.parametrize("kind", ["file", "directory", "dangling_symlink"])
def test_any_pending_sidecar_blocks_clone_unchanged(tmp_path, source, location, suffix, kind):
    target = tmp_path / "clone.duckdb"
    sidecar = Path(str(source if location == "source" else target) + suffix)
    if kind == "file":
        sidecar.write_bytes(b"synthetischer, nicht wiederherzustellender Zustand")
    elif kind == "directory":
        sidecar.mkdir()
    else:
        sidecar.symlink_to(tmp_path / "missing-sidecar")
    _reject_unchanged(tmp_path, source, target, f"{location}_pending_state")


@pytest.mark.parametrize("location", ["source", "destination"])
@pytest.mark.parametrize("dangling", [False, True])
def test_file_symlinks_are_never_followed(tmp_path, source, location, dangling):
    link = tmp_path / "alias.duckdb"
    link.symlink_to(tmp_path / "missing.duckdb" if dangling else source)
    _reject_unchanged(
        tmp_path, link if location == "source" else source,
        tmp_path / "clone.duckdb" if location == "source" else link,
        "symlink_not_allowed",
    )


@pytest.mark.parametrize("location", ["source", "destination"])
def test_symlink_in_parent_path_is_rejected(tmp_path, source, location):
    directory = tmp_path / "real"
    directory.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(directory, target_is_directory=True)
    if location == "source":
        real_source = directory / source.name
        source.rename(real_source)
        source = alias / source.name
    _reject_unchanged(
        tmp_path, source, (alias if location == "destination" else directory) / "clone.duckdb",
        "symlink_not_allowed",
    )


def test_source_with_any_hardlink_alias_is_refused(tmp_path, source):
    os.link(source, tmp_path / "source-alias.duckdb")
    _reject_unchanged(tmp_path, source, tmp_path / "clone.duckdb", "source_not_unique_regular_file")


def test_destination_hardlink_to_source_cannot_be_overwritten(tmp_path, source):
    target = tmp_path / "alias.duckdb"
    os.link(source, target)
    _reject_unchanged(tmp_path, source, target, "source_not_unique_regular_file")


def test_same_source_and_destination_are_not_a_restore(tmp_path, source):
    _reject_unchanged(tmp_path, source, source, "destination_exists")


def test_source_directory_and_missing_target_parent_are_refused(tmp_path, source):
    directory = tmp_path / "directory.duckdb"
    directory.mkdir()
    _reject_unchanged(tmp_path, directory, tmp_path / "clone.duckdb", "source_not_unique_regular_file")
    _reject_unchanged(tmp_path, source, tmp_path / "missing" / "clone.duckdb", "destination_parent_unavailable")


def test_read_only_lock_blocks_real_writer_during_every_source_read(tmp_path, source, monkeypatch):
    real_open = io.open
    attempts = []

    def observed_open(file, mode="r", *args, **kwargs):
        stream = real_open(file, mode, *args, **kwargs)
        if not isinstance(file, int) and Path(file) == source and mode == "rb":
            try:
                attempt = _try_writer(source)
                attempts.append(attempt)
                assert attempt.returncode == 23, attempt.stdout + attempt.stderr
                assert "lock" in attempt.stdout.lower()
            except BaseException:
                stream.close()
                raise
        return stream

    with monkeypatch.context() as patch:
        patch.setattr(io, "open", observed_open)
        clone_worker_database(source, tmp_path / "clone.duckdb")
    assert attempts, "Keine Quelldateilesung unter echter DuckDB-Sperre beobachtet"
    after = _try_writer(source)
    assert after.returncode == 0, after.stdout + after.stderr


def test_source_and_staging_reopened_read_only_without_external_access(tmp_path, source, monkeypatch):
    real_connect = duckdb.connect
    calls = []
    probes = {}
    statements = []

    class ObservedConnection:
        def __init__(self, connection, path):
            self.connection = connection
            self.path = path

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

        def execute(self, query, *args, **kwargs):
            statements.append((self.path, query))
            result = self.connection.execute(query, *args, **kwargs)
            assert result is self.connection
            return self

        def _record(self):
            columns = tuple(column[0] for column in self.connection.description)
            probes.setdefault(self.path, set()).add(columns)

        def fetchmany(self, *args, **kwargs):
            self._record()
            return self.connection.fetchmany(*args, **kwargs)

        def fetchall(self):
            self._record()
            return self.connection.fetchall()

        def fetchone(self):
            self._record()
            return self.connection.fetchone()

        def __getattr__(self, name):
            return getattr(self.connection, name)

    def observed_connect(database, *args, **kwargs):
        connection = real_connect(database, *args, **kwargs)
        calls.append((Path(database), kwargs.copy()))
        return ObservedConnection(connection, Path(database))

    monkeypatch.setattr(duckdb, "connect", observed_connect)
    clone_worker_database(source, tmp_path / "clone.duckdb")
    assert len(calls) >= 2
    assert calls[0][0] == source
    assert any(path != source for path, _ in calls), "Kopie wurde nicht erneut geoeffnet"
    for _, options in calls:
        assert options["read_only"] is True
        assert options["config"]["enable_external_access"] in (False, "false", "False")
    expected_columns = {
        ("id", "note"),
        ("id", "amount", "units", "observed_at", "day", "payload", "note"),
        ("empty_value",),
    }
    for path, _ in calls:
        assert expected_columns <= probes.get(path, set()), "Tabellen wurden nicht vollstaendig probegelesen"
    assert not any("checkpoint" in query.lower() for _, query in statements)


def test_publication_is_atomic_and_late_destination_is_not_replaced(tmp_path, source, monkeypatch):
    target = tmp_path / "clone.duckdb"
    original = source.read_bytes()
    real_link = os.link
    published = []
    sentinel = b"konkurrierendes Ziel, niemals ueberschreiben"
    wal_bytes = b"konkurrierendes WAL, niemals ueberschreiben"
    wal = Path(str(target) + ".wal")

    def competing_link(staging, destination, *args, **kwargs):
        if Path(destination) == target:
            published.append(Path(staging))
            assert not target.exists()
            assert Path(staging).parent == target.parent
            # Do not open/close a second fd on the worker's locked target.
            assert Path(staging).stat().st_size == len(original)
            target.write_bytes(sentinel)
            wal.write_bytes(wal_bytes)
        return real_link(staging, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", competing_link)
    with pytest.raises(OfflineDatabaseCloneError) as caught:
        clone_worker_database(source, target)
    assert caught.value.code == "offline_clone_failed"
    assert len(published) == 1
    assert target.read_bytes() == sentinel
    assert wal.read_bytes() == wal_bytes
    assert source.read_bytes() == original
    assert set(tmp_path.iterdir()) == {source, target, wal}


@pytest.mark.parametrize("suffix", [".wal", ".tmp"])
def test_pending_target_sidecar_at_publication_reports_unknown_without_deleting_clone(tmp_path, source, monkeypatch, suffix):
    target = tmp_path / "clone.duckdb"
    sidecar = Path(str(target) + suffix)
    original = source.read_bytes()
    real_link = os.link
    attempted = []

    def late_sidecar(staging, destination, *args, **kwargs):
        if Path(destination) == target:
            attempted.append(destination)
            sidecar.write_bytes(b"Sidecar erscheint unmittelbar vor Veroeffentlichung")
        return real_link(staging, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", late_sidecar)
    with pytest.raises(OfflineDatabaseCloneError) as caught:
        clone_worker_database(source, target)
    assert caught.value.code == "publication_state_unknown"
    assert attempted
    assert target.is_file()
    assert target.read_bytes() == original
    assert target.stat().st_ino != source.stat().st_ino
    assert target.stat().st_nlink == 1
    assert sidecar.read_bytes() == b"Sidecar erscheint unmittelbar vor Veroeffentlichung"
    assert source.read_bytes() == original
    assert set(tmp_path.iterdir()) == {source, sidecar, target}


def test_source_read_lock_is_still_effective_at_publication(tmp_path, source, monkeypatch):
    real_link = os.link
    target = tmp_path / "clone.duckdb"
    attempts = []

    def observed_link(staging, destination, *args, **kwargs):
        if Path(destination) == target:
            attempt = _try_writer(source)
            attempts.append(attempt)
            assert attempt.returncode == 23, "Quelle vor Veroeffentlichung bereits schreibbar"
            assert "lock" in attempt.stdout.lower()
        return real_link(staging, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", observed_link)
    clone_worker_database(source, target)
    assert attempts
