from datetime import date, datetime, timezone
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

import httpx
import pytest

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore


ROOT = Path(__file__).resolve().parents[2]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


REPAIR = load_script("run_hnt_legacy_reward_price_repair_20260626")
APPLY = load_script("apply_ready_income_price_repairs_20260626")
PREVIEW = load_script("run_all_income_price_repair_preview_20260626")


@pytest.mark.parametrize("module", [REPAIR, APPLY], ids=["hnt", "income"])
@pytest.mark.parametrize("existing_target", [True, False], ids=["existing-db", "missing-db"])
@pytest.mark.parametrize("exclude", [True, False], ids=["with-exclusion", "without-exclusion"])
@pytest.mark.parametrize("preview_rows", [[], [{"status": "v1_asset_usd_review_required"}]], ids=["empty", "blocked"])
def test_execute_always_aborts_before_any_side_effect(tmp_path, monkeypatch, module, existing_target, exclude, preview_rows):
    db = tmp_path / "synthetic.duckdb"
    if existing_target:
        db.write_bytes(b"synthetic target bytes")
    legacy = tmp_path / "v1.sqlite"
    with sqlite3.connect(legacy) as con:
        con.execute("create table fx_cache (rate_date text, base_ccy text, quote_ccy text, rate text, updated_at_utc text)")
        con.execute("insert into fx_cache values ('2021-11-15', 'HNT', 'USD', '100', 'now')")
    output = tmp_path / "reports"
    cache = tmp_path / "prices"
    argv = [str(module.__file__), "--execute", "--db", str(db), "--v1-fx-db", str(legacy), "--output-dir", str(output)]
    if exclude:
        argv.append("--exclude-v1-asset-usd")
    if module is APPLY:
        preview = tmp_path / "synthetic-preview.json"
        preview.write_text(json.dumps({"rows": preview_rows}))
        argv += ["--preview", str(preview), "--price-cache-dir", str(cache)]
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(module, "DuckDbStore", lambda *args, **kwargs: pytest.fail("store created before guard"))
    monkeypatch.setattr(module.httpx, "Client", lambda *args, **kwargs: pytest.fail("network client created before guard"))
    with pytest.raises(SystemExit, match="--execute gesperrt.*Preis-.*FX-.*Identitaets-"):
        module.main()
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
    assert not output.exists() and not cache.exists() and not (tmp_path / "backups").exists()


def test_hnt_exclusion_uses_mock_provider_and_fx_without_asset_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(REPAIR, "fetch_cached_eur_price", lambda **kwargs: pytest.fail("V1 asset/USD selected"))
    monkeypatch.setattr(REPAIR, "usd_eur_rate", lambda *_: Decimal("0.9"))
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"coins": {"coingecko:helium": {"price": "3", "timestamp": 1636934400}}})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = REPAIR.fetch_defillama_eur_price(client=client, asset="HNT", coin_id="helium", price_date=date(2021, 11, 15),
                                                  v1_fx_db_path=tmp_path / "synthetic", allow_v1_asset_usd=False)
    assert len(calls) == 1 and result.price_eur == Decimal("2.7")
    assert ":asset_usd_v1_fx_cache" not in result.source


def test_income_exclusion_uses_cmc_and_fx_without_asset_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(APPLY.REPAIR, "fetch_cached_eur_price", lambda **kwargs: pytest.fail("V1 asset/USD selected"))
    monkeypatch.setattr(APPLY.REPAIR, "usd_eur_rate", lambda *_: Decimal("0.9"))
    day = date(2021, 11, 15)
    result = APPLY.resolve_external_price(asset="HNT", price_date=day, v1_fx_db_path=tmp_path / "synthetic",
        source_label="synthetic", client=None, coin_id="helium", cmc_id="99", cmc_history={day: Decimal("3")},
        price_cache_dir=tmp_path, refresh_price_cache=False, allow_v1_asset_usd=False)
    assert result.price_eur == Decimal("2.7") and "coinmarketcap" in result.source


def test_stablecoin_fx_only_still_works_when_asset_cache_excluded(monkeypatch, tmp_path):
    monkeypatch.setattr(REPAIR, "fetch_cached_eur_price", lambda **kwargs: pytest.fail("V1 asset/USD selected"))
    monkeypatch.setattr(REPAIR, "usd_eur_rate", lambda *_: Decimal("0.9"))
    with httpx.Client(transport=httpx.MockTransport(lambda _: pytest.fail("unexpected provider request"))) as client:
        result = REPAIR.fetch_defillama_eur_price(client=client, asset="USDT", coin_id="tether", price_date=date(2021, 11, 15),
                                                  v1_fx_db_path=tmp_path / "synthetic", allow_v1_asset_usd=False)
    assert result.price_eur == Decimal("0.9") and result.source.endswith(":stable_usd_fx")


@pytest.mark.parametrize("module", [REPAIR, APPLY], ids=["hnt", "income"])
def test_dry_run_labels_cached_v1_asset_as_unverified(tmp_path, monkeypatch, capsys, module):
    db = tmp_path / "synthetic.duckdb"
    store = DuckDbStore(db)
    store.add_canonical_event(CanonicalEventCreate(
        source="helium", source_ref="synthetic-reward", asset="HNT", quantity=Decimal("1"),
        event_time=datetime(2021, 11, 15, 12, tzinfo=timezone.utc), event_type="reward",
    ))
    legacy = tmp_path / "synthetic.sqlite"
    with sqlite3.connect(legacy) as con:
        con.execute("create table fx_cache (rate_date text, base_ccy text, quote_ccy text, rate text, updated_at_utc text)")
        con.execute("insert into fx_cache values ('2021-11-15', 'HNT', 'USD', '999', 'now')")
        con.execute("insert into fx_cache values ('2021-11-15', 'USD', 'EUR', '0.9', 'now')")
    before = legacy.read_bytes()
    original_client = httpx.Client
    monkeypatch.setattr(module.httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(lambda _: pytest.fail("unexpected provider request")), **kwargs))
    argv = [str(module.__file__), "--db", str(db), "--v1-fx-db", str(legacy), "--output-dir", str(tmp_path / "reports")]
    if module is APPLY:
        preview = tmp_path / "synthetic-preview.json"
        preview.write_text(json.dumps({"rows": [{"status": "ready_for_execute", "asset": "HNT", "source": "helium", "year": 2021, "coin_id": "helium"}]}))
        argv += ["--preview", str(preview), "--price-cache-dir", str(tmp_path / "cache")]
    monkeypatch.setattr(sys, "argv", argv)
    module.main()
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "dry-run" and output["v1_asset_usd_excluded"] is False
    assert output["execute_allowed"] is False
    report = output["groups"][0] if module is APPLY else output
    assert report["summary"]["unverified_v1_asset_usd_days"] == 1
    assert report["summary"]["importable_price_days"] == 0
    assert report["rows"][0]["v1_asset_usd_unverified"] is True and report["rows"][0]["will_import"] is False
    assert not store.list_price_points() and legacy.read_bytes() == before


def test_unverified_v1_candidate_is_visible_but_not_planned_or_ready():
    day = date(2021, 11, 15)
    reward = REPAIR.RewardDay(day, 1, Decimal("1"), Decimal("0"), ())
    price = REPAIR.ExternalPrice(day, Decimal("3"), Decimal("0.9"), Decimal("2.7"), None,
                                 "synthetic:asset_usd_v1_fx_cache")
    report = REPAIR.build_report(mode="dry-run", year=2021, asset="HNT", source="helium",
                                 reward_days=[reward], external_prices={day: price}, existing_primary_dates=set(), failures=[])
    assert report["rows"][0]["source"] == price.source
    assert report["rows"][0]["v1_asset_usd_unverified"] is True
    assert report["rows"][0]["will_import"] is False
    assert report["summary"]["unverified_v1_asset_usd_days"] == 1
    assert report["summary"]["importable_price_days"] == 0
    assert PREVIEW.group_status(report["summary"]) == "v1_asset_usd_review_required"
    assert not REPAIR.build_price_points(asset="HNT", reward_days=[reward], external_prices={day: price}, existing_primary_dates=set())


def test_mixed_group_with_unverified_v1_cannot_be_marked_ready():
    summary = {"failure_count": 0, "importable_price_days": 1, "unverified_v1_asset_usd_days": 1}
    assert PREVIEW.group_status(summary) == "v1_asset_usd_review_required"
