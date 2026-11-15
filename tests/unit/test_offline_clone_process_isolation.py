"""Echte POSIX-/DuckDB-Proben fuer die drei unabhaengigen Reviewbefunde."""

from dataclasses import asdict
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import selectors
import stat
import subprocess
import sys
import textwrap

import duckdb
import pytest


ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = 20
pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX-Dateisperren")


@pytest.fixture
def subject(monkeypatch):
    path = ROOT / "src/steuerreport_v2/db/offline_snapshot.py"
    assert path.is_file(), f"Offline-Helper fehlt: {path}"
    spec = importlib.util.spec_from_file_location("offline_clone_process_isolation_subject", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "s.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("create table evidence(i integer)")
        con.execute("insert into evidence values (42)")
    return path


def writer_status(path):
    script = textwrap.dedent("""\
        import json
        import sys
        import duckdb

        try:
            con = duckdb.connect(sys.argv[1])
        except duckdb.IOException as exc:
            if "Could not set lock" not in str(exc):
                raise
            print(json.dumps({"status": "locked"}))
        else:
            try:
                con.execute("insert into evidence values (99)")
            finally:
                con.close()
            print(json.dumps({"status": "written"}))
    """)
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(path)],
        capture_output=True, text=True, timeout=TIMEOUT,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["status"]


def assert_clean_copy(source, destination, proof, original):
    digest = hashlib.sha256(original).hexdigest()
    assert proof.source_sha256 == proof.target_sha256 == digest
    assert proof.table_count == 1 and proof.size_bytes == len(original)
    assert source.read_bytes() == destination.read_bytes() == original
    assert not Path(str(source) + ".wal").exists()
    assert not Path(str(destination) + ".wal").exists()
    assert destination.stat().st_nlink == 1
    with duckdb.connect(str(destination), read_only=True) as con:
        assert con.execute("select * from evidence").fetchall() == [(42,)]


def test_public_clone_preserves_an_existing_parent_read_only_lock(subject, source, tmp_path):
    original = source.read_bytes()
    destination = tmp_path / "backup.duckdb"
    with duckdb.connect(
        str(source), read_only=True, config={"enable_external_access": False},
    ) as reader:
        assert writer_status(source) == "locked"
        proof = subject.clone_offline_database(source, destination)
        # Kein read_bytes/hash der Quelle hier: dessen close loest selbst POSIX-Locks.
        assert writer_status(source) == "locked"
        assert reader.execute("select * from evidence").fetchall() == [(42,)]
    assert_clean_copy(source, destination, proof, original)
    assert writer_status(source) == "written"


def test_finishing_public_clone_does_not_unlock_a_paused_other_worker(subject, source, tmp_path):
    original = source.read_bytes()
    slow_destination = tmp_path / "slow.duckdb"
    fast_destination = tmp_path / "fast.duckdb"
    script = textwrap.dedent("""\
        from dataclasses import asdict
        import importlib.util
        import json
        import os
        from pathlib import Path
        import sys

        helper = Path(sys.argv[1])
        sys.path.insert(0, str(helper.parents[2]))
        spec = importlib.util.spec_from_file_location("gated_offline_clone_subject", helper)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        real_digest = module._digest

        def gated_digest(path):
            if path.name.startswith(".steuerreport-offline-"):
                print(json.dumps({"phase": "paused", "pid": os.getpid()}), flush=True)
                if sys.stdin.readline().strip() != "continue":
                    raise RuntimeError("missing test gate release")
            return real_digest(path)

        module._digest = gated_digest
        proof = module._clone_offline_database(Path(sys.argv[2]), Path(sys.argv[3]))
        print(json.dumps({"phase": "finished", "result": asdict(proof)}), flush=True)
    """)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONPATH": str(Path(subject.__file__).resolve().parents[2])}
    worker = subprocess.Popen(
        [sys.executable, "-B", "-u", "-c", script, subject.__file__,
         str(source), str(slow_destination)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=env,
    )
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(worker.stdout, selectors.EVENT_READ)
            assert selector.select(TIMEOUT), "Clone A erreicht das Pipe-Gate nicht"
            line = worker.stdout.readline()
        assert line, f"Clone A endete vor dem Gate: {worker.poll()}"
        ready = json.loads(line)
        assert ready["phase"] == "paused" and ready["pid"] != os.getpid()
        assert writer_status(source) == "locked"
        fast_proof = subject.clone_offline_database(source, fast_destination)
        assert worker.poll() is None
        assert writer_status(source) == "locked"
        stdout, stderr = worker.communicate(input="continue\n", timeout=TIMEOUT)
        assert worker.returncode == 0, stderr
        finished = json.loads(stdout)
        assert finished["phase"] == "finished"
        slow_proof = subject.OfflineDatabaseCloneResult(**finished["result"])
        assert asdict(slow_proof) == asdict(fast_proof)
        assert_clean_copy(source, slow_destination, slow_proof, original)
        assert_clean_copy(source, fast_destination, fast_proof, original)
        assert not list(tmp_path.glob(".steuerreport-offline-*"))
        assert writer_status(source) == "written"
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.communicate(timeout=TIMEOUT)


def test_destination_writer_is_blocked_during_directory_fsync(subject, source, tmp_path, monkeypatch):
    original = source.read_bytes()
    destination = tmp_path / "backup.duckdb"
    real_fsync = os.fsync
    attempts = []

    def fsync_spy(descriptor):
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            attempts.append(writer_status(destination))
        return real_fsync(descriptor)

    monkeypatch.setattr(subject.os, "fsync", fsync_spy)
    proof = subject._clone_offline_database(source, destination)
    assert attempts == ["locked"]
    assert_clean_copy(source, destination, proof, original)
    assert not list(tmp_path.glob(".steuerreport-offline-*"))
    assert writer_status(destination) == "written"


@pytest.mark.parametrize("public", [False, True], ids=["private-worker", "public-worker"])
@pytest.mark.parametrize("suffix", [".wal", ".tmp"])
@pytest.mark.parametrize("placement", ["leaf", "missing-parent", "existing-parent"])
def test_reserved_destination_is_rejected_before_access_or_new_files(
    subject, source, tmp_path, monkeypatch, public, suffix, placement,
):
    reserved = Path(str(source) + suffix)
    if placement == "leaf":
        destination = reserved
    else:
        if placement == "existing-parent":
            reserved.mkdir()
        destination = reserved / "nested" / "backup.duckdb"
    original = source.read_bytes()
    before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))

    def forbidden(*args, **kwargs):
        pytest.fail("Reservierter Pfad muss vor Dateizugriff abgewiesen werden")

    with monkeypatch.context() as guard:
        if not public:
            guard.setattr(subject, "_no_symlinks", forbidden)
            guard.setattr(subject.duckdb, "connect", forbidden)
            guard.setattr(subject.tempfile, "mkstemp", forbidden)
        clone = subject.clone_offline_database if public else subject._clone_offline_database
        with pytest.raises(subject.OfflineDatabaseCloneError) as error:
            clone(source, destination)
    assert error.value.code == "reserved_sidecar_path"
    assert source.read_bytes() == original
    assert sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")) == before
    assert not destination.exists()
