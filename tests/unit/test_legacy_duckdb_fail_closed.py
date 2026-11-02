import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from steuerreport_v2.domain.request_limits import RequestCancelled, RequestDeadlineExceeded


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ("run_v1_solana_rpc_migration_v2", "import_jup_solscan_balance_change_v2")


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", SCRIPTS)
@pytest.mark.parametrize("execute", [False, True])
def test_no_stage_live_fetch_or_restore_even_on_injected_failure(name, execute, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", "")
    monkeypatch.setenv("STEUERREPORT_STATE_DIR", str(tmp_path / "state"))
    module = load_script(name)
    def forbidden(*args, **kwargs):
        raise AssertionError("blocked workflow must not reach stage, live, fetch or restore")

    monkeypatch.setattr(module, "_run_full_import" if name == SCRIPTS[0] else "_apply", forbidden)
    if name == SCRIPTS[1]:
        monkeypatch.setattr(module, "_fetch_balance_changes", forbidden)
    monkeypatch.setattr("shutil.copy2", forbidden)
    db = tmp_path / "missing.duckdb"
    monkeypatch.setattr(sys, "argv", [name, "--db", str(db)] + (["--execute"] if execute else []))
    assert module.main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["blocked_reason"] == "unsafe_database_snapshot_and_restore_unavailable"
    assert result["target_changed"] is False
    assert result["stage_attempted"] is False
    assert result["restore_attempted"] is False
    assert not db.exists()
    assert not (tmp_path / "backups").exists()


def run_cli(name, db, execute):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), STEUERREPORT_PRIVATE_PROFILE="",
               STEUERREPORT_STATE_DIR=str(db.parent / "state"))
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / (name + ".py")), "--db", str(db)]
        + (["--execute"] if execute else []),
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=30,
    )


@pytest.mark.parametrize("name", SCRIPTS)
@pytest.mark.parametrize("execute", [False, True])
@pytest.mark.parametrize("crashed", [False, True])
def test_active_or_abandoned_wal_is_untouched(name, execute, crashed, tmp_path):
    db = tmp_path / "synthetic.duckdb"
    writer = subprocess.Popen(
        [sys.executable, "-u", "-c", (
            "import duckdb,sys,time; c=duckdb.connect(sys.argv[1]); "
            "c.execute('create table evidence(i integer)'); "
            "c.execute('insert into evidence values (42)'); print('ready',flush=True); time.sleep(60)"
        ), str(db)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert writer.stdout.readline().strip() == "ready"
        wal = Path(str(db) + ".wal")
        assert wal.exists() and wal.stat().st_size > 0
        if crashed:
            writer.kill()
            writer.wait(timeout=10)
        before = {p.name: p.read_bytes() for p in (db, wal)}
        outcome = run_cli(name, db, execute)
        assert outcome.returncode == 2, outcome.stderr
        result = json.loads(outcome.stdout)
        assert result["blocked_reason"] == "unsafe_database_snapshot_and_restore_unavailable"
        assert result["target_changed"] is False
        assert result["restore_attempted"] is False
        assert {p.name: p.read_bytes() for p in (db, wal)} == before
        assert sorted(p.name for p in tmp_path.iterdir()) == sorted(before)
    finally:
        if writer.poll() is None:
            writer.kill()
            writer.wait(timeout=10)
        writer.stdout.close()
        writer.stderr.close()
    with duckdb.connect(str(db)) as con:
        assert con.execute("select * from evidence").fetchall() == [(42,)]


@pytest.mark.parametrize("name", SCRIPTS)
def test_corrupt_backup_and_synthetic_vault_are_not_used_or_overwritten(name, tmp_path):
    db = tmp_path / "synthetic.duckdb"
    db.write_bytes(b"not a database")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup = backup_dir / "broken.duckdb"
    backup.write_bytes(b"incomplete backup")
    vault = tmp_path / "vault.key"
    vault.write_bytes(b"synthetic key")
    before = {p: p.read_bytes() for p in (db, backup, vault)}
    outcome = run_cli(name, db, True)
    assert outcome.returncode == 2, outcome.stderr
    result = json.loads(outcome.stdout)
    assert result["restore_attempted"] is False
    assert result["target_changed"] is False
    assert {p: p.read_bytes() for p in before} == before
    assert list(backup_dir.iterdir()) == [backup]


@pytest.mark.parametrize("name", SCRIPTS)
@pytest.mark.parametrize("signal", [RequestCancelled, RequestDeadlineExceeded])
def test_cancellation_cannot_enter_blocked_cli_or_leak_exception(name, signal, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", "")
    monkeypatch.setenv("STEUERREPORT_STATE_DIR", str(tmp_path / "state"))
    module = load_script(name)
    calls = []
    def abort(*args, **kwargs):
        calls.append("called")
        raise signal("synthetic-sensitive-detail")
    monkeypatch.setattr(module, "_run_full_import" if name == SCRIPTS[0] else "_apply", abort)
    if name == SCRIPTS[1]:
        monkeypatch.setattr(module, "_fetch_balance_changes", abort)
    monkeypatch.setattr("shutil.copy2", abort)
    monkeypatch.setattr(sys, "argv", [name, "--db", str(tmp_path / "unused"), "--execute"])
    assert module.main() == 2
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert calls == []
    assert result["restore_attempted"] is False
    assert result["target_changed"] is False
    assert "synthetic-sensitive-detail" not in captured.out + captured.err
    assert "restored" not in captured.out


@pytest.mark.parametrize("name", SCRIPTS)
@pytest.mark.parametrize("signal", [RequestCancelled, RequestDeadlineExceeded])
def test_direct_helper_propagates_cancellation_after_prior_steps(name, signal, tmp_path, monkeypatch):
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", "")
    monkeypatch.setenv("STEUERREPORT_STATE_DIR", str(tmp_path / "state"))
    module = load_script(name)
    effects = []
    def abort(*args, **kwargs):
        raise signal("synthetic-sensitive-detail")
    def no_restore(*args, **kwargs):
        pytest.fail("automatic restore must not run")
    monkeypatch.setattr("shutil.copy2", no_restore)
    if name == SCRIPTS[0]:
        monkeypatch.setattr(module, "_load_v1_rows", lambda *a, **kw: [])
        monkeypatch.setattr(module, "_apply_solana_rpc", lambda *a, **kw: effects.append("prior_write"))
        monkeypatch.setattr(module, "_import_wallet_month", lambda *a: {})
        monkeypatch.setattr(module, "_apply_opening_balance", lambda *a: {})
        monkeypatch.setattr(module, "_backfill_prices", abort)
        call = lambda: module._run_full_import(tmp_path / "unused", v1_db=tmp_path / "v1",
                                               wallet_month_csv=tmp_path / "wallet",
                                               price_config=tmp_path / "config", max_year=2024)
    else:
        monkeypatch.setattr(module, "DuckDbStore", lambda path: object())
        monkeypatch.setattr(module, "_delete_existing_jup_batches", lambda *a: effects.append("prior_write"))
        monkeypatch.setattr(module, "CsvRawImporter", lambda store: SimpleNamespace(import_rows=lambda *a: object()))
        monkeypatch.setattr(module, "_store_solscan_event_prices", lambda *a: 0)
        monkeypatch.setattr(module, "PipelineService", lambda store: SimpleNamespace(rebuild_all=lambda: object()))
        monkeypatch.setattr(module, "ExternalPriceBackfillService", lambda store: SimpleNamespace(run=abort))
        monkeypatch.setattr(module, "PortfolioService", no_restore)
        call = lambda: module._apply(tmp_path / "unused", wallet="synthetic", rows=[], fx_db=tmp_path / "fx")
    with pytest.raises(signal):
        call()
    assert effects == ["prior_write"]


def test_fetch_only_uses_synthetic_cache_without_provider_or_database(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", "")
    monkeypatch.setenv("STEUERREPORT_STATE_DIR", str(tmp_path / "state"))
    module = load_script(SCRIPTS[1])
    cache = tmp_path / "cache.json"
    cache.write_text(json.dumps({"data": [{"trans_id": "synthetic"}]}))
    def forbidden(*args, **kwargs):
        raise AssertionError("provider or database accessed")
    monkeypatch.setattr(module, "managed_urlopen", forbidden)
    monkeypatch.setattr(module, "_solscan_api_key", forbidden)
    monkeypatch.setattr(module, "_apply", forbidden)
    monkeypatch.setattr(sys, "argv", [SCRIPTS[1], "--fetch-only", "--wallet", "synthetic",
                                     "--db", str(tmp_path / "missing.duckdb"), "--cache-path", str(cache)])
    assert module.main() == 0
    assert json.loads(capsys.readouterr().out)["fetch"]["status"] == "cache"
    assert not (tmp_path / "missing.duckdb").exists()
