from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


def _database(path: Path) -> None:
    con = duckdb.connect(str(path))
    con.execute("create table sample(id integer primary key, value varchar)")
    con.execute(
        "insert into sample select range, repeat('value', 20) from range(1000)"
    )
    con.execute("delete from sample where id % 2 = 0")
    con.close()


def test_compact_duckdb_verifies_catalog_and_rows(tmp_path: Path) -> None:
    source = tmp_path / "source.duckdb"
    target = tmp_path / "target.duckdb"
    report = tmp_path / "report.json"
    _database(source)

    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/compact_duckdb_v2.py"),
            "--source",
            str(source),
            "--target",
            str(target),
            "--report",
            str(report),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["status"] == "verified"
    assert payload["verification"]["catalog_equal"] is True
    assert payload["verification"]["bidirectional_except_all_empty"] is True
    assert payload["tables"][0]["rows"] == 500
    con = duckdb.connect(str(target), read_only=True)
    assert con.execute("select count(*) from sample").fetchone()[0] == 500
    con.close()


def test_consolidate_duckdb_replaces_only_after_verification(tmp_path: Path) -> None:
    source = tmp_path / "snapshot.duckdb"
    report_dir = tmp_path / "reports"
    run_report = tmp_path / "run.json"
    _database(source)
    original_mtime_ns = source.stat().st_mtime_ns

    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/consolidate_duckdb_snapshots_v2.py"),
            str(tmp_path),
            "--min-size-bytes",
            "0",
            "--execute",
            "--report-dir",
            str(report_dir),
            "--run-report",
            str(run_report),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(run_report.read_text(encoding="utf-8"))
    assert payload["status"] == "completed"
    assert payload["selected_count"] == 1
    assert payload["results"][0]["status"] == "verified_compact_replacement"
    assert source.stat().st_mtime_ns == original_mtime_ns
    assert not list(tmp_path.glob("*.original-tmp-*"))
    assert not list(tmp_path.glob("*.compact-tmp-*"))
    con = duckdb.connect(str(source), read_only=True)
    assert con.execute("select count(*) from sample").fetchone()[0] == 500
    con.close()


@pytest.mark.skipif(shutil.which("zstd") is None, reason="zstd is not installed")
def test_archive_duckdb_is_bit_exact_and_restorable(tmp_path: Path) -> None:
    source = tmp_path / "snapshot.duckdb"
    report = tmp_path / "archive-run.json"
    restored = tmp_path / "restored.duckdb"
    _database(source)
    original = source.read_bytes()

    subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/archive_duckdb_snapshots_v2.py"),
            str(tmp_path),
            "--min-size-bytes",
            "0",
            "--execute",
            "--report",
            str(report),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert not source.exists()
    archive = source.with_name(source.name + ".zst")
    manifest = json.loads(
        archive.with_name(archive.name + ".manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["source_sha256"] == manifest["decoded_sha256"]
    with restored.open("wb") as output:
        subprocess.run(
            ["zstd", "-q", "-d", "-c", str(archive)],
            check=True,
            stdout=output,
        )
    assert restored.read_bytes() == original
