"""Echte DuckDB-Lockproben fuer Helperprozesse, ohne Docker-Daemon."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import duckdb
import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def ops():
    spec = importlib.util.spec_from_file_location("state_guard_subject", ROOT / "scripts/docker_state_v2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def source(tmp_path):
    database = tmp_path / "source.duckdb"
    with duckdb.connect(str(database)) as con:
        con.execute("create table evidence (n integer)")
        con.execute("insert into evidence values (42)")
    return database


def payload(source):
    return {"mounts": [{"target": "/state", "helper_root": str(source.parent)}],
            "runtime_paths": {"STEUERREPORT_V2_DB": "/state/" + source.name}}


def writer(source):
    return subprocess.run([sys.executable, "-I", "-c", """
import sys, duckdb
try:
    con=duckdb.connect(sys.argv[1])
except duckdb.IOException as error:
    if 'lock' not in str(error).lower():
        raise
    sys.exit(23)
con.execute('insert into evidence values (99)')
con.close()
""", str(source)], capture_output=True, text=True, timeout=20)


@pytest.mark.parametrize("mode", ["archive", "inventory", "snapshot"])
def test_real_helper_keeps_independent_read_lock_despite_parent_fd_closes(ops, source, monkeypatch, mode):
    original = source.read_bytes()
    def observe(*args, **kwargs):
        # Closing this descriptor must not release the separate guard's lock.
        assert source.read_bytes() == original
        blocked = writer(source)
        assert blocked.returncode == 23, blocked.stderr
        return {}
    monkeypatch.setattr(ops, "_helper_archive", observe)
    monkeypatch.setattr(ops, "_helper_inventory", observe)
    ops._helper_main(mode, json.dumps(payload(source)))
    assert source.read_bytes() == original
    assert writer(source).returncode == 0


def test_lost_archive_guard_cannot_report_success(ops, source, monkeypatch):
    processes = []
    original_popen = subprocess.Popen
    def record(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(ops.subprocess, "Popen", record)
    def lose_guard(*args, **kwargs):
        assert processes
        processes[0].kill()
        processes[0].wait(timeout=10)
    monkeypatch.setattr(ops, "_helper_archive", lose_guard)
    with pytest.raises(SystemExit) as error:
        ops._helper_main("archive", json.dumps(payload(source)))
    assert error.value.code == 2
    assert all(process.poll() is not None for process in processes)
