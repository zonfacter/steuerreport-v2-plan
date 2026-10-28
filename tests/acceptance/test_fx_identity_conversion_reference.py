"""Unabhaengiges Gate G08/G09/G18/G19 plus zwei P1-Regressionsfaelle.

Feste Sollwerte, keine Unit-Helfer oder Produktformeln als Erwartungsoracle.
FX:100USD ->90EUR; Umstellung100:1:100OLD/Basis90 ->1NEW/Basis90,
Teilverkauf0.4 fuer60:Basis36/Gewinn24/Restbasis54. Reward bleibt einmal90.
"""

from datetime import date, datetime, timezone
from decimal import Decimal, localcontext
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import tempfile

import pytest


REPO = Path(__file__).resolve().parents[2]
TESTROOT = Path("/tmp/steuerreport-blockers-20261028-reference-tests")
TESTROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
BOOT = Path(tempfile.mkdtemp(prefix="bootstrap-", dir=TESTROOT))
shutil.copytree(REPO / "configs", BOOT / "software/configs")
(BOOT / "profile.json").write_text("{}\n")
os.environ.update(
    {
        "STEUERREPORT_V2_ROOT": str(BOOT / "software"),
        "STEUERREPORT_V2_DB": str(BOOT / "bootstrap.duckdb"),
        "STEUERREPORT_STATE_DIR": str(BOOT / "runtime"),
        "STEUERREPORT_PRIVATE_PROFILE": str(BOOT / "profile.json"),
        "STEUERREPORT_PRIVATE_CONFIG_DIR": str(BOOT / "private-configs"),
        "STEUERREPORT_USERTRANSFER_ROOT": str(BOOT / "imports"),
    }
)

# Isolation muss vor Produktimporten gelten: keine Operatorprofile/Default-DBs.
import duckdb  # noqa: E402
from steuerreport_v2.contracts.events import CanonicalEventCreate  # noqa: E402
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate  # noqa: E402
from steuerreport_v2.contracts.prices import PricePointCreate  # noqa: E402
from steuerreport_v2.db.duckdb_store import DuckDbStore  # noqa: E402
from steuerreport_v2.domain.asset_identity import AssetIdentityIndex  # noqa: E402
from steuerreport_v2.domain.review import ReviewService  # noqa: E402
from steuerreport_v2.domain.tax import TaxService  # noqa: E402
from steuerreport_v2.domain.tax_years import TaxYearService  # noqa: E402
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService  # noqa: E402
from steuerreport_v2.domain.token_conversion import (  # noqa: E402
    TokenConversionService,
    config_binding,
)
from steuerreport_v2.domain.v1_fx_cache_importer import V1FxCacheImporter  # noqa: E402
from steuerreport_v2.domain.wallet_fifo_runs import WalletFifoParallelRunService  # noqa: E402
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter  # noqa: E402
from steuerreport_v2.importers.raw_normalizer import RawNormalizer  # noqa: E402


def frozen_inputs():
    tracked = (
        subprocess.check_output(
            [
                "git",
                "-c",
                "safe.directory=" + str(REPO),
                "-C",
                str(REPO),
                "ls-files",
                "-z",
                "src",
                "configs",
                "frontend",
                "scripts",
                "requirements*",
                "pyproject.toml",
            ]
        )
        .decode()
        .split("\0")
    )
    return {
        name: hashlib.sha256((REPO / name).read_bytes()).hexdigest()
        for name in tracked
        if name and (REPO / name).is_file()
    }


@pytest.fixture(scope="session", autouse=True)
def source_freeze():
    before = frozen_inputs()
    yield
    after = frozen_inputs()
    proof = {"unchanged": before == after, "before": before, "after": after}
    (BOOT / "source-freeze.json").write_text(
        json.dumps(proof, sort_keys=True, indent=2) + "\n"
    )
    assert before == after, (
        "Runtime-/Konfigurations-/Versionsquellen waehrend Gate veraendert"
    )


@pytest.fixture
def case(tmp_path, monkeypatch):
    # tmp_path muss bei explizitem Gate-Aufruf ausserhalb des Repos liegen.
    assert not tmp_path.resolve().is_relative_to(REPO.resolve())
    configs = tmp_path / "private-configs"
    configs.mkdir()
    profile = tmp_path / "profile.json"
    profile.write_text("{}\n")
    monkeypatch.setenv("STEUERREPORT_PRIVATE_CONFIG_DIR", str(configs))
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", str(profile))
    monkeypatch.setenv("STEUERREPORT_STATE_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("STEUERREPORT_V2_DB", str(tmp_path / "own.duckdb"))
    original_connect = duckdb.connect

    def db_connect(database=":memory:", *args, **kwargs):
        if str(database) != ":memory:" and not (
            Path(database).resolve().is_relative_to(tmp_path.resolve())
            or Path(database).resolve().is_relative_to(BOOT.resolve())
        ):
            raise RuntimeError("Referenzgate: fremde DB gesperrt")
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(duckdb, "connect", db_connect)

    def blocked(*args, **kwargs):
        raise OSError("Referenzgate: kein Netzwerk")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    store = DuckDbStore(tmp_path / "own.duckdb")
    store.health()
    return tmp_path, configs, store


def csv_events(store, rows):
    out = io.StringIO()
    writer = csv.DictWriter(
        out,
        fieldnames=[
            "time",
            "asset",
            "amount",
            "type",
            "quote_asset",
            "quote_quantity",
            "fee_asset",
            "fee_quantity",
            "account",
            "tx_id",
            "conversion_kind",
        ],
    )
    writer.writeheader()
    writer.writerows(rows)
    batch = CsvRawImporter(store).import_text(
        source="binance", filename="synthetic-reference.csv", content=out.getvalue()
    )
    return RawNormalizer(store).normalize_batch(batch.batch_id)


def row(at, asset, quantity, kind, **kwargs):
    return dict(
        time=at,
        asset=asset,
        amount=quantity,
        type=kind,
        account="Synthetic-Depot",
        **kwargs,
    )


def price(store, asset, value, at):
    store.add_price_point(
        PricePointCreate(
            asset=asset,
            price_eur=Decimal(value),
            priced_at=datetime.fromisoformat(at.replace("Z", "+00:00")),
            source="synthetic:explicit-evidence",
        )
    )


def fx_fixture(case, fx_rows):
    root, _, store = case
    csv_events(store, [row("2025-01-12T12:00:00Z", "FXTEST", "1", "reward")])
    path = root / "synthetic-fx.db"
    with sqlite3.connect(path) as con:
        con.execute(
            "create table fx_cache(rate_date text,base_ccy text,quote_ccy text,rate text,source text,source_rate_date text)"
        )
        con.execute(
            "insert into fx_cache values (?,?,?,?,?,?)",
            ("2025-01-12", "FXTEST", "USD", "100", "synthetic-asset", "2025-01-12"),
        )
        con.executemany("insert into fx_cache values (?,?,?,?,?,?)", fx_rows)
    return store, path


@pytest.mark.parametrize(
    "base,quote,rate",
    [("USD", "EUR", "0.9"), ("EUR", "USD", "1.111111111111111111111111111111111111")],
)
def test_G08_real_fx_consumer_100usd_90eur(case, base, quote, rate):
    store, path = fx_fixture(
        case, [("2025-01-10", base, quote, rate, "synthetic-Friday", "2025-01-10")]
    )
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    preview, points = V1FxCacheImporter(store).to_price_points(str(path), Decimal("1"))
    assert preview.importable_count == 1 and len(points) == 1
    assert points[0].price_eur == Decimal("90")
    assert preview.importable[0].source_rate_date == "2025-01-10"
    assert "2025-01-10" in points[0].source
    assert base in points[0].source and quote in points[0].source
    store.add_price_points(points)
    lots = TaxService(store).preview_global_fifo().lots
    assert len(lots) == 1 and lots[0].cost_basis_eur_total == Decimal("90")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_G09_documented_seven_day_reference_boundary(case):
    store, path = fx_fixture(
        case,
        [("2025-01-05", "USD", "EUR", "0.9", "synthetic-observation", "2025-01-05")],
    )
    preview, points = V1FxCacheImporter(store).to_price_points(str(path), Decimal("1"))
    assert preview.importable_count == 1
    assert points[0].price_eur == Decimal("90")
    assert preview.importable[0].source_rate_date == "2025-01-05"


@pytest.mark.parametrize(
    "rows",
    [
        [],
        [("2025-01-04", "USD", "EUR", "0.9", "synthetic-old", "2025-01-04")],
        [("2025-01-13", "USD", "EUR", "0.9", "synthetic-future", "2025-01-13")],
        [("2025-01-12", "USD", "EUR", "0.9", "synthetic-backdated", "2025-01-13")],
        [("2025-01-12", "USD", "EUR", "0.9", "synthetic-laundered", "2024-12-01")],
        [("2025-01-10", "USD", "EUR", "0", "synthetic-zero", "2025-01-10")],
        [("2025-01-10", "USD", "EUR", "-0.9", "synthetic-negative", "2025-01-10")],
        [("2025-01-10", "USD", "EUR", "NaN", "synthetic-nan", "2025-01-10")],
        [("2025-01-10", "GBP", "EUR", "0.9", "synthetic-wrong-unit", "2025-01-10")],
        [("2025-01-10", "USD", "EUR", "0.9", "synthetic-unbound", None)],
        [("2025-01-10", "USD", "EUR", "0.9", "", "2025-01-10")],
    ],
)
def test_G09_missing_invalid_future_old_fx_never_factor_one(case, rows):
    store, path = fx_fixture(case, rows)
    preview, points = V1FxCacheImporter(store).to_price_points(str(path), Decimal("1"))
    assert not points and preview.importable_count == 0
    assert preview.missing_usd_eur_count == 1


def identity_event(store, symbol, payload, quantity="1"):
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="synthetic-identity",
            filename="synthetic-identity.json",
            file_hash=hashlib.sha256(
                json.dumps(payload, sort_keys=True).encode()
            ).hexdigest(),
        )
    )
    raw = store.add_raw_objects(
        batch.batch_id,
        [
            RawObjectCreate(
                row_number=1, payload_json=json.dumps(payload, sort_keys=True)
            )
        ],
    )[0]
    return store.add_canonical_event(
        CanonicalEventCreate(
            source="synthetic-identity",
            source_ref="synthetic-reference",
            event_time=datetime(2025, 1, 12, 12, tzinfo=timezone.utc),
            event_type="reward",
            asset=symbol,
            quantity=Decimal(quantity),
            account="Synthetic-Depot",
            raw_object_id=raw.raw_object_id,
        )
    )


@pytest.mark.parametrize(
    "second",
    [
        {"network": "arbitrum", "contract_address": "0x" + "1" * 40, "decimals": 6},
        {"network": "ethereum", "contract_address": "0x" + "2" * 40, "decimals": 6},
        {"network": "ethereum", "contract_address": "0x" + "1" * 40, "decimals": 18},
    ],
)
def test_G18_same_symbol_does_not_resolve_chain_contract_or_decimals(case, second):
    _, _, store = case
    identity_event(
        store,
        "IDENTITYTEST",
        {"network": "ethereum", "contract_address": "0x" + "1" * 40, "decimals": 6},
    )
    identity_event(store, "IDENTITYTEST", second)
    before = [x.model_dump(mode="json") for x in store.list_canonical_events()]
    index = AssetIdentityIndex(store)
    assert "IDENTITYTEST" in index.problems
    plan = [{"asset": "IDENTITYTEST", "status": "planned", "reason": None}]
    index.apply_to_plan(plan, {}, provider="defillama")
    assert plan[0]["status"] == "blocked" and plan[0]["price_eur"] is None
    assert any(
        ("identity" in x.code or "decimal" in x.code) and x.blocks_export
        for x in ReviewService(store).gate().issues
    )
    assert [x.model_dump(mode="json") for x in store.list_canonical_events()] == before


def test_G18_original_decimals_raw_quantity_mismatch_blocks(case):
    _, _, store = case
    identity_event(
        store,
        "DECIMALTEST",
        {
            "network": "ethereum",
            "contract_address": "0x" + "3" * 40,
            "decimals": 6,
            "amount_raw": "1000000",
        },
        quantity="2",
    )
    index = AssetIdentityIndex(store)
    assert "DECIMALTEST" in index.problems


def test_G18_coingecko_symbol_only_is_not_identity_evidence(case):
    _, _, store = case
    identity_event(
        store,
        "IDENTITYTEST",
        {"network": "ethereum", "contract_address": "0x" + "4" * 40, "decimals": 6},
    )
    plan = [
        {
            "asset": "IDENTITYTEST",
            "status": "planned",
            "reason": None,
            "provider_id": "coingecko:synthetic",
        }
    ]
    AssetIdentityIndex(store).apply_to_plan(
        plan, {"IDENTITYTEST": {"coingecko_id": "synthetic"}}, provider="coingecko"
    )
    assert plan[0]["status"] == "blocked"
    assert plan[0]["reason"] == "price_mapping_identity_unbound"


def test_G18_coingecko_explicit_chain_contract_bound_control(case):
    _, _, store = case
    identity_event(
        store,
        "IDENTITYTEST",
        {"network": "ethereum", "contract_address": "0x" + "4" * 40, "decimals": 6},
    )
    plan = [
        {
            "asset": "IDENTITYTEST",
            "status": "planned",
            "reason": None,
            "provider_id": "coingecko:synthetic",
        }
    ]
    mapping = {
        "coingecko_id": "synthetic",
        "network": "ethereum",
        "contract_address": "0x" + "4" * 40,
        "decimals": 6,
    }
    AssetIdentityIndex(store).apply_to_plan(
        plan, {"IDENTITYTEST": mapping}, provider="coingecko"
    )
    assert plan[0]["status"] == "planned"
    assert plan[0]["provider_id"] == "coingecko:synthetic"


def test_G18_bound_wsol_existing_coingecko_provider_is_preserved(case):
    _, _, store = case
    # Oeffentliche Protokoll-Tokenkonstante, keine private Kontoadresse.
    mint = "So11111111111111111111111111111111111111112"
    identity_event(store, "WSOL", {"network": "solana", "mint": mint, "decimals": 9})
    plan = [
        {
            "asset": "WSOL",
            "status": "planned",
            "reason": None,
            "provider_id": "coingecko:solana",
        }
    ]
    mapping = {
        "defillama_id": "coingecko:solana",
        "coingecko_id": "solana",
        "network": "solana",
        "solana_mint": mint,
        "decimals": 9,
    }
    AssetIdentityIndex(store).apply_to_plan(
        plan, {"WSOL": mapping}, provider="defillama"
    )
    assert plan[0]["status"] == "planned"
    assert plan[0]["provider_id"] == "coingecko:solana"


def event_signature(event):
    # Technischer Signaturvertrag, niemals Zahlen-/Steueroracle.
    body = event.model_dump(mode="python")
    body["event_time"] = (
        event.event_time.replace(tzinfo=timezone.utc).isoformat()
        if event.event_time.tzinfo is None
        else event.event_time.astimezone(timezone.utc).isoformat()
    )
    with localcontext() as context:
        context.prec = 80
        for key, value in body.items():
            if isinstance(value, Decimal):
                body[key] = str(value.normalize())
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def conversion_case(case, *, reward=False):
    _, configs, store = case
    events = csv_events(
        store,
        [
            row(
                "2024-01-10T12:00:00Z",
                "OLDTEST",
                "100",
                "reward" if reward else "buy",
                **({} if reward else {"quote_asset": "EUR", "quote_quantity": "90"}),
            ),
            row(
                "2024-06-01T12:00:00Z",
                "OLDTEST",
                "-100",
                "transfer",
                tx_id="synthetic-conversion",
                conversion_kind="redenomination",
            ),
            row(
                "2024-06-01T12:00:00Z",
                "NEWTEST",
                "1",
                "transfer",
                tx_id="synthetic-conversion",
                conversion_kind="redenomination",
            ),
        ],
    )
    if reward:
        price(store, "OLDTEST", "0.9", "2024-01-10T00:00:00Z")
    source = next(x for x in events if x.quantity == Decimal("-100"))
    target = next(x for x in events if x.asset == "NEWTEST")
    evidence = configs / "conversion-evidence.txt"
    evidence.write_text(
        "Synthetischer Primarbeleg:100OLDTEST entsprechen1NEWTEST; keine automatische steuerliche Freigabe.\n"
    )
    with store.connect() as con:
        raw = dict(
            con.execute("select raw_object_id,payload_json from raw_objects").fetchall()
        )
    mapping = {
        "mapping_id": "synthetic-100-to-1",
        "enabled": True,
        "kind": "redenomination",
        "source_event_id": source.event_id,
        "target_event_id": target.event_id,
        "source_event_sha256": event_signature(source),
        "target_event_sha256": event_signature(target),
        "source_raw_sha256": hashlib.sha256(
            raw[source.raw_object_id].encode()
        ).hexdigest(),
        "target_raw_sha256": hashlib.sha256(
            raw[target.raw_object_id].encode()
        ).hexdigest(),
        "ratio_numerator": "1",
        "ratio_denominator": "100",
        "tax_treatment": "carry_original_basis_and_date",
        "actor": "synthetic-reviewer",
        "rationale": "Nur unabhaengiger synthetischer Referenzfall, keine produktive Freigabe.",
        "evidence_ref": "conversion-evidence.txt",
        "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
        "acknowledge_same_economic_asset": True,
        "acknowledge_no_automatic_tax_approval": True,
    }
    path = configs / "token_conversion_mappings.json"
    path.write_text(json.dumps({"schema_version": 1, "mappings": [mapping]}))
    return store, path, evidence, mapping, source, target


@pytest.mark.parametrize("engine", ["global", "wallet"])
def test_G19_100_to_1_carries_basis_date_global_and_wallet(case, engine):
    store, _, _, _, source, target = conversion_case(case)
    report = TokenConversionService(store).report()
    assert len(report["ready"]) == 1 and not report["issues"]
    state = (
        TaxService(store).preview_global_fifo()
        if engine == "global"
        else WalletFifoPreviewService(store).replay()
    )
    lots = state.lots if engine == "global" else state.all_lots
    new = [x for x in lots if x.asset == "NEWTEST"]
    old = [x for x in lots if x.asset == "OLDTEST"]
    assert len(new) == 1
    assert new[0].quantity_remaining == Decimal("1")
    assert new[0].cost_basis_eur_total == Decimal("90")
    assert new[0].acquired_at.date() == date(2024, 1, 10)
    assert new[0].origin_lot_id == old[0].lot_id
    assert new[0].source_event_id == target.event_id, (
        "Carried Lot muss Zieltransfer referenzieren, nicht Reward/Originalerwerb"
    )


@pytest.mark.parametrize("engine", ["global", "wallet"])
def test_G19_partial_sale_fixed_basis_36_gain_24(case, engine):
    store, _, _, _, _, _ = conversion_case(case)
    csv_events(
        store,
        [
            row(
                "2024-07-01T12:00:00Z",
                "NEWTEST",
                "-0.4",
                "sell",
                quote_asset="EUR",
                quote_quantity="60",
            )
        ],
    )
    state = (
        TaxService(store).preview_global_fifo()
        if engine == "global"
        else WalletFifoPreviewService(store).replay()
    )
    lines = [x for x in state.tax_lines if x.asset == "NEWTEST"]
    assert len(lines) == 1
    assert lines[0].acquisition_cost_eur == Decimal("36")
    assert lines[0].disposal_proceeds_eur == Decimal("60")
    assert lines[0].gain_loss_eur == Decimal("24")
    lots = state.lots if engine == "global" else state.all_lots
    new = next(x for x in lots if x.asset == "NEWTEST")
    assert new.quantity_remaining == Decimal("0.6")
    assert (
        new.cost_basis_eur_total * new.quantity_remaining / new.quantity_total
        == Decimal("54")
    )


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "changed",
        "absolute",
        "parent",
        "symlink",
        "wrong-ratio",
        "false-ack",
        "string-ack",
    ],
)
def test_G19_no_conversion_without_bound_primary_evidence(case, damage):
    store, path, evidence, mapping, _, _ = conversion_case(case)
    if damage == "missing":
        evidence.unlink()
    elif damage == "changed":
        evidence.write_text("geaenderte synthetische Belegbytes")
    elif damage == "absolute":
        mapping["evidence_ref"] = str(evidence)
    elif damage == "parent":
        mapping["evidence_ref"] = "../private-configs/conversion-evidence.txt"
    elif damage == "symlink":
        linked = evidence.with_name("linked-evidence.txt")
        linked.symlink_to(evidence)
        mapping["evidence_ref"] = linked.name
    elif damage == "wrong-ratio":
        mapping["ratio_denominator"] = "99"
    elif damage == "false-ack":
        mapping["acknowledge_same_economic_asset"] = False
    else:
        mapping["acknowledge_no_automatic_tax_approval"] = "true"
    path.write_text(json.dumps({"schema_version": 1, "mappings": [mapping]}))
    report = TokenConversionService(store).report()
    assert not report["ready"] and report["issues"]


def test_G19_evidence_bytes_invalidate_config_and_wallet_run_fingerprint(case):
    store, _, evidence, _, _, _ = conversion_case(case)
    before = config_binding()
    service = WalletFifoParallelRunService(store)
    fingerprint = service.input_fingerprint(
        datetime(2024, 12, 31, tzinfo=timezone.utc)
    ).digest
    evidence.write_text("Aenderung des lokalen Primaerbelegs ohne Configaenderung")
    assert config_binding() != before
    assert (
        service.input_fingerprint(datetime(2024, 12, 31, tzinfo=timezone.utc)).digest
        != fingerprint
    )
    assert not TokenConversionService(store).report()["ready"]


def test_G19_evidence_bytes_invalidate_preview_input_fingerprint(case):
    from steuerreport_v2.domain.ai_changes import _fingerprint

    store, _, evidence, _, _, _ = conversion_case(case)
    with store.connect() as con:
        before = _fingerprint(con)
    evidence.write_text(
        "NurBelegbytesgeaendert; alleJSONundDatenbankinputsbleibengleich"
    )
    with store.connect() as con:
        after = _fingerprint(con)
    assert after != before, (
        "TXT-Primarbeleg muss die gemeinsame Preview-Eingabebindung aendern"
    )


def test_G19_reward_conversion_never_doubles_income(case):
    store, _, _, _, _, target = conversion_case(case, reward=True)
    result = TaxService(store).rebuild_fifo()
    new = next(x for x in result.lots if x.asset == "NEWTEST")
    with store.connect() as con:
        bound_reward_basis = con.execute(
            "select sum(l.cost_basis_eur_total) from tax_lots l join canonical_events e on e.event_id=l.source_event_id where e.event_type='reward'"
        ).fetchone()[0]
    assert bound_reward_basis == Decimal("90"), (
        "Persistierte Reward-Erwerbslots duerfen den einmaligen Zufluss nicht auf180 verdoppeln"
    )
    income = TaxYearService(store).income_report(2024)
    assert income.total_income_eur == Decimal("90"), (
        "Ein Reward90, keine zusaetzliche Einnahme90 durch Carry-Lot"
    )
    assert new.source_event_id == target.event_id


def test_G04_known_price_without_stored_fee_consumption_remains_blocked(case):
    _, _, store = case
    events = csv_events(
        store,
        [
            row(
                "2024-01-10T12:00:00Z",
                "BNB",
                "1",
                "buy",
                quote_asset="EUR",
                quote_quantity="20",
            ),
            row(
                "2024-02-10T12:00:00Z",
                "BTC",
                "10",
                "buy",
                quote_asset="EUR",
                quote_quantity="100",
                fee_asset="BNB",
                fee_quantity="0.1",
            ),
        ],
    )
    bnb = next(x for x in events if x.asset == "BNB")
    btc = next(x for x in events if x.asset == "BTC")
    price(store, "BNB", "20", "2024-02-10T00:00:00Z")
    price(store, "BTC", "10", "2024-02-10T00:00:00Z")
    # Eigene alte DB mit belegtem Preis, aber ohne gespeicherten Gebuehrenverbrauch.
    with store.connect() as con:
        for event, cost in [(bnb, "20"), (btc, "100")]:
            con.execute(
                "insert into tax_lots (lot_id,asset,acquired_at,quantity_total,quantity_remaining,cost_basis_eur_total,source_event_id,created_at) values (?,?,?,?,?,?,?,?)",
                [
                    "synthetic-legacy-" + event.asset,
                    event.asset,
                    event.event_time,
                    event.quantity,
                    event.quantity,
                    cost,
                    event.event_id,
                    datetime(2024, 2, 11),
                ],
            )
        con.execute(
            "insert into tax_run_summaries (run_id,tax_lines_count,unmatched_disposals,created_at) values (?,?,?,?)",
            ["synthetic-legacy-run", 0, 0, datetime(2024, 2, 11)],
        )
    gate = ReviewService(store).gate()
    assert any("fee" in issue.code and issue.blocks_export for issue in gate.issues), (
        "Preis allein ist kein Nachweis des physischen Gebuehrenverbrauchs"
    )


def test_G04_fee_proof_becomes_stale_after_price_input_change(case):
    _, _, store = case
    events = csv_events(
        store,
        [
            row(
                "2024-01-10T12:00:00Z",
                "BNB",
                "1",
                "buy",
                quote_asset="EUR",
                quote_quantity="20",
            ),
            row(
                "2024-02-10T12:00:00Z",
                "BTC",
                "10",
                "buy",
                quote_asset="EUR",
                quote_quantity="100",
                fee_asset="BNB",
                fee_quantity="0.1",
            ),
        ],
    )
    btc = next(x for x in events if x.asset == "BTC")
    price(store, "BNB", "20", "2024-02-10T00:00:00Z")
    price(store, "BTC", "10", "2024-02-10T00:00:00Z")
    result = TaxService(store).rebuild_fifo()
    assert sum(
        (
            x.quantity
            for x in result.tax_lines
            if x.asset == "BNB" and x.source_event_id == btc.event_id
        ),
        Decimal("0"),
    ) == Decimal("0.1")
    assert not any(
        "fee" in issue.code and issue.blocks_export
        for issue in ReviewService(store).gate().issues
    )
    price(store, "BNB", "21", "2024-02-10T11:00:00Z")
    assert any(
        "fee" in issue.code and issue.blocks_export
        for issue in ReviewService(store).gate().issues
    ), "GespeicherteZeilealleingenuegtnichtnachPreisinputaenderung"
