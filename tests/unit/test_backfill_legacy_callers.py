import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from steuerreport_v2.domain.external_price_backfill import (
    HistoricalBackfillJobsFailed,
    HistoricalBackfillPipelineFailed,
    HistoricalBackfillStorageUnknown,
)


@pytest.fixture
def scripts(monkeypatch):
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", "")
    monkeypatch.setenv("STEUERREPORT_PRIMARY_SOLANA_WALLET", "synthetic")
    root = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(root))
    modules = []
    for name in ("import_jup_solscan_balance_change_v2", "run_v1_solana_rpc_migration_v2"):
        spec = importlib.util.spec_from_file_location(name, root / f"{name}.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


def make_backfill(kind):
    class FakeBackfill:
        def __init__(self, store):
            pass

        def run(self, **kwargs):
            if kind == "storage":
                raise HistoricalBackfillStorageUnknown()
            return SimpleNamespace(pipeline_status="failed" if kind == "pipeline" else "completed",
                                   failed=1, stored_price_ids=["synthetic-price-id"])
    return FakeBackfill


@pytest.mark.parametrize("kind", ["storage", "pipeline", "jobs"])
def test_jup_apply_stops_before_followup_steps(scripts, tmp_path, monkeypatch, kind):
    jup, _ = scripts
    calls = []
    monkeypatch.setattr(jup, "DuckDbStore", lambda path: object())
    monkeypatch.setattr(jup, "_delete_existing_jup_batches", lambda *args: [])
    monkeypatch.setattr(jup, "CsvRawImporter", lambda store: SimpleNamespace(import_rows=lambda *args: object()))
    monkeypatch.setattr(jup, "_store_solscan_event_prices", lambda *args: 0)
    monkeypatch.setattr(jup, "PipelineService", lambda store: SimpleNamespace(rebuild_all=lambda: calls.append("pipeline")))
    monkeypatch.setattr(jup, "ExternalPriceBackfillService", make_backfill(kind))
    monkeypatch.setattr(jup, "PortfolioService", lambda store: pytest.fail("portfolio followup must not run"))
    monkeypatch.setattr(jup, "_store_jlwsol_live_price", lambda store: pytest.fail("price followup must not run"))
    expected = {"storage": HistoricalBackfillStorageUnknown, "pipeline": HistoricalBackfillPipelineFailed,
                "jobs": HistoricalBackfillJobsFailed}[kind]
    with pytest.raises(expected):
        jup._apply(tmp_path / "unused", wallet="synthetic", rows=[], fx_db=tmp_path / "unused-fx")
    assert calls == ["pipeline"]


@pytest.mark.parametrize("kind", ["storage", "pipeline", "jobs"])
def test_migration_stops_before_followup_steps(scripts, tmp_path, monkeypatch, kind):
    _, migration = scripts
    monkeypatch.setattr(migration, "_load_v1_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr(migration, "_apply_solana_rpc", lambda *args, **kwargs: {})
    monkeypatch.setattr(migration, "_import_wallet_month", lambda *args: {})
    monkeypatch.setattr(migration, "_apply_opening_balance", lambda *args: {})
    monkeypatch.setattr(migration, "DuckDbStore", lambda path: object())
    monkeypatch.setattr(migration, "ExternalPriceBackfillService", make_backfill(kind))
    monkeypatch.setattr(migration, "PipelineService", lambda store: pytest.fail("pipeline followup must not run"))
    expected = {"storage": HistoricalBackfillStorageUnknown, "pipeline": HistoricalBackfillPipelineFailed,
                "jobs": HistoricalBackfillJobsFailed}[kind]
    with pytest.raises(expected):
        migration._run_full_import(tmp_path / "unused", v1_db=tmp_path / "v1", wallet_month_csv=tmp_path / "wallet", price_config=tmp_path / "config", max_year=2024)


@pytest.mark.parametrize("which", ["jup", "migration"])
@pytest.mark.parametrize("kind", ["storage", "pipeline", "jobs"])
@pytest.mark.parametrize("execute", [False, True])
def test_cli_cannot_reach_unsafe_stage_or_live_even_on_backfill_failure(scripts, tmp_path, monkeypatch, capsys, which, kind, execute):
    jup, migration = scripts
    module = jup if which == "jup" else migration
    live = tmp_path / "live"
    monkeypatch.setattr("shutil.copy2", lambda *args: pytest.fail("automatic restore must not run"))
    error = {"storage": HistoricalBackfillStorageUnknown, "pipeline": HistoricalBackfillPipelineFailed,
             "jobs": HistoricalBackfillJobsFailed}[kind]
    calls = []
    def run(path, **kwargs):
        calls.append(path)
        raise error() if kind == "storage" else error(["synthetic-price-id"])
    if which == "jup":
        monkeypatch.setattr(jup, "_fetch_balance_changes", lambda *args, **kwargs: pytest.fail("blocked CLI must not fetch"))
        monkeypatch.setattr(jup, "_apply", run)
    else:
        monkeypatch.setattr(migration, "_run_full_import", run)
    monkeypatch.setattr(sys, "argv", ["script", "--db", str(live)] + (["--execute"] if execute else []))
    assert module.main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["blocked_reason"] == "unsafe_database_snapshot_and_restore_unavailable"
    assert result["target_changed"] is False
    assert result["stage_attempted"] is False and result["restore_attempted"] is False
    assert calls == [] and not live.exists()
    assert "restored" not in result["blocked_reason"]
