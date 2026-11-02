import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from steuerreport_v2.domain.external_price_backfill import (
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
            return SimpleNamespace(pipeline_status="failed", stored_price_ids=["synthetic-price-id"])
    return FakeBackfill


@pytest.mark.parametrize("kind", ["storage", "pipeline"])
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
    expected = HistoricalBackfillStorageUnknown if kind == "storage" else HistoricalBackfillPipelineFailed
    with pytest.raises(expected):
        jup._apply(tmp_path / "unused", wallet="synthetic", rows=[], fx_db=tmp_path / "unused-fx")
    assert calls == ["pipeline"]


@pytest.mark.parametrize("kind", ["storage", "pipeline"])
def test_migration_stops_before_followup_steps(scripts, tmp_path, monkeypatch, kind):
    _, migration = scripts
    monkeypatch.setattr(migration, "_load_v1_rows", lambda *args, **kwargs: [])
    monkeypatch.setattr(migration, "_apply_solana_rpc", lambda *args, **kwargs: {})
    monkeypatch.setattr(migration, "_import_wallet_month", lambda *args: {})
    monkeypatch.setattr(migration, "_apply_opening_balance", lambda *args: {})
    monkeypatch.setattr(migration, "DuckDbStore", lambda path: object())
    monkeypatch.setattr(migration, "ExternalPriceBackfillService", make_backfill(kind))
    monkeypatch.setattr(migration, "PipelineService", lambda store: pytest.fail("pipeline followup must not run"))
    expected = HistoricalBackfillStorageUnknown if kind == "storage" else HistoricalBackfillPipelineFailed
    with pytest.raises(expected):
        migration._run_full_import(tmp_path / "unused", v1_db=tmp_path / "v1", wallet_month_csv=tmp_path / "wallet", price_config=tmp_path / "config", max_year=2024)


@pytest.mark.parametrize("which", ["jup", "migration"])
@pytest.mark.parametrize("kind", ["storage", "pipeline"])
@pytest.mark.parametrize("phase", ["stage", "live"])
def test_cli_failure_stops_without_restore(scripts, tmp_path, monkeypatch, capsys, which, kind, phase):
    jup, migration = scripts
    module = jup if which == "jup" else migration
    stage = tmp_path / "stage"
    live = tmp_path / "live"
    monkeypatch.setattr(module, "_snapshot_database", lambda *args: stage)
    monkeypatch.setattr(module, "_backup_database", lambda *args: tmp_path / "backup")
    monkeypatch.setattr(module.shutil, "copy2", lambda *args: pytest.fail("automatic restore must not run"))
    error = HistoricalBackfillStorageUnknown if kind == "storage" else HistoricalBackfillPipelineFailed
    def run(path, **kwargs):
        if path == (stage if phase == "stage" else live):
            raise error(["synthetic-price-id"]) if kind == "pipeline" else error()
        return {"review": {"allow_export": True}, "reconciliation_rows": []}
    if which == "jup":
        monkeypatch.setattr(jup, "_fetch_balance_changes", lambda *args, **kwargs: ([{}], {}))
        monkeypatch.setattr(jup, "_rows_from_balance_changes", lambda *args: [{}])
        monkeypatch.setattr(jup, "_jup_reconciliation_export_ready", lambda rows: True)
        monkeypatch.setattr(jup, "_apply", run)
    else:
        monkeypatch.setattr(migration, "_run_full_import", run)
    monkeypatch.setattr(sys, "argv", ["script", "--execute", "--db", str(live)])
    assert module.main() == 2
    result = json.loads(capsys.readouterr().out)
    assert result["blocked_reason"] == ("stage_price_backfill_incomplete" if phase == "stage" else "live_price_backfill_incomplete_state_unknown_or_partial")
    assert result["target_changed"] is (False if phase == "stage" else None)
    assert "restored" not in result["blocked_reason"]
    if kind == "pipeline":
        assert result[f"{phase}_confirmed_backfill_price_ids"] == ["synthetic-price-id"]
    else:
        assert f"{phase}_confirmed_backfill_price_ids" not in result
