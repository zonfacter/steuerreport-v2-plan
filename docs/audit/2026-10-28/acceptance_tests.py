"""Unabhaengige Abnahme; ausschliesslich synthetische Daten, keine Freigabe.

Explizit ausfuehren, nicht Teil der globalen Unit-Suite:
pytest docs/audit/2026-10-28/acceptance_tests.py --basetemp /tmp/sr-acceptance-G-20261028
Feste Sollwerte wurden vor Adapterimplementierung aus G_MATRIX abgeleitet,
nicht durch Aufruf der zu pruefenden Produktfunktionen erzeugt.
"""
from decimal import Decimal
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import zipfile

import pytest


REPO = Path(__file__).resolve().parents[3]
TESTROOT = Path("/tmp/steuerreport-migration-20261028-acceptance-tests")
TESTROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
BOOT = Path(tempfile.mkdtemp(prefix="bootstrap-", dir=TESTROOT))
shutil.copytree(REPO / "configs", BOOT / "software/configs")
(BOOT / "profile.json").write_text("{}\n")
os.environ.update({
    "STEUERREPORT_V2_ROOT": str(BOOT / "software"),
    "STEUERREPORT_V2_DB": str(BOOT / "bootstrap.duckdb"),
    "STEUERREPORT_STATE_DIR": str(BOOT / "state"),
    "STEUERREPORT_PRIVATE_PROFILE": str(BOOT / "profile.json"),
    "STEUERREPORT_PRIVATE_CONFIG_DIR": str(BOOT / "private-configs"),
    "STEUERREPORT_USERTRANSFER_ROOT": str(BOOT / "imports"),
    "STEUERREPORT_V2_SECRET_VAULT_KEY_FILE": str(BOOT / "keys/vault.key"),
})

# Vor Produktimporten keine Operator-Konfiguration oder Netzwerkzugriffe erlauben.
_socket_connect = socket.socket.connect


def no_network(sock, address):
    if sock.family in {socket.AF_INET, socket.AF_INET6}:
        raise OSError("Acceptance: Netzwerk vollstaendig gesperrt")
    return _socket_connect(sock, address)


socket.socket.connect = no_network
socket.socket.connect_ex = lambda sock, address: (_ for _ in ()).throw(OSError("Acceptance: Netzwerk gesperrt"))

import duckdb

_duckdb_connect = duckdb.connect


def isolated_connect(database=":memory:", *args, **kwargs):
    if str(database) != ":memory:" and not Path(database).resolve().is_relative_to(TESTROOT.resolve()):
        raise RuntimeError("Acceptance: DB ausserhalb eigenem Testroot gesperrt")
    return _duckdb_connect(database, *args, **kwargs)


duckdb.connect = isolated_connect

from fastapi.testclient import TestClient
from pypdf import PdfReader
from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.contracts.exports import PdfExportRequest
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.review import ReviewDecisionCreate
from steuerreport_v2.contracts.tax_filing_snapshots import TaxFilingSnapshotCaptureRequest
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.derived_prices import DerivedPriceService
from steuerreport_v2.domain.exports import ExportService
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_filing_snapshots import TaxFilingSnapshotService
from steuerreport_v2.domain.tax_time import reporting_tax_year, reporting_time, reporting_year_sql
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService
from steuerreport_v2.domain.tax_years import TaxYearService
from steuerreport_v2.domain.valuation import PriceCoverageService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


SOLL = {
    "G01": {"kauf_stueck": "10", "kauf_eur": "100", "verkauf_stueck": "4",
            "erloes_eur": "60", "verbrauchte_basis_eur": "40", "gewinn_eur": "20",
            "rest_stueck": "6", "restbasis_eur": "60"},
    "G02": {"annahme": "EUR-Erwerbskosten kapitalisiert, direkte EUR-Verkaufskosten mindern Erloes",
            "kauf_eur": "100", "kaufgebuehr_eur": "2", "verkaufgebuehr_eur": "1",
            "verbrauchte_basis_eur": "40.8", "gewinn_eur": "18.2", "restbasis_eur": "61.2"},
    "G03": {"annahme": "10 Brutto-Token, davon 0.1 Erwerbsgebuehr; kein spaeterer zweiter Abzug",
            "rest_stueck": "9.9", "grenze": "Kosten-/Sphaerenbehandlung separat pruefen"},
    "G04": {"annahme": "Drittassetgebuehr darf weder verschwinden noch zweimal abgezogen werden",
            "grenze": "EUR-Wert, eigener Lotverbrauch und Zuordnung muessen alle nachweisbar sein"},
    "G05": {"verkauf_a": "2", "erwerb_b": "5", "erloes_eur": "60", "basis_a_eur": "40",
            "gewinn_eur": "20", "basis_b_eur": "60", "eur_einzahlung": "0",
            "annahme": "Beide Beine ein belegter Tausch, kein Fiatzufluss"},
    "G06": {"token": "100", "usd_pro_token": "0.8", "eur_pro_usd": "0.9", "wert_eur": "72"},
    "G07": {"token": "100", "eur_pro_token": "0.6", "wert_eur": "60"},
    "G08": {"usd": "100", "eur_pro_usd": "0.9", "eur": "90",
            "gegenrichtung_usd_pro_eur": "1.111111111111111111", "toleranz_eur": "0.00000000000000001"},
    "G09": {"annahme": "Dokumentierter Freitag-FX fuer Sonntag nur unter ausdruecklicher FX-Policy",
            "fehlender_fx": "keine Bewertung statt implizitem Faktor 1"},
    "G10": {"ereignis": "2025-01-15T12:00:00Z", "altkurs": "2021-01-15T12:00:00Z",
            "zukunftskurs": "2025-01-15T13:00:00Z", "zugelassen": False,
            "finale_freigabe": False, "grenze": "Lookup/Coverage/Tax/Review/Export pruefen, nicht Lookup allein"},
    "G11": {"basis_a_eur": "10", "basis_b_eur": "20", "verkauf_b_eur": "30",
            "gewinn_wallet_eur": "10", "gewinn_global_eur": "20", "aktivierung": False},
    "G12": {"transfer_stueck": "4", "original_basis_eur": "40", "original_datum": "2023-01-10",
            "annahme": "Eigenuebertrag mit Originalbasis/-datum; Gebuehr getrennt"},
    "G13": {"reward_eur": "100", "verkauf_eur": "150", "anschaffung_eur": "100",
            "veraeusserungsgewinn_eur": "50", "annahme": "Rewardart und Wirtschaftssphaere ausdruecklich belegt"},
    "G14": {"annahme": "Unbelegter Reward ist weder automatisch privat noch betrieblich freigegeben",
            "finale_freigabe": False},
    "G15": {"kauf": "2023-03-01", "jahrestag": "2024-03-01", "jahrestag_innerhalb": True,
            "folgetag": "2024-03-02", "folgetag_innerhalb": False,
            "schalttag_kauf": "2024-02-29", "schalttag_jahrestag": "2025-02-28",
            "schalttag_folgetag": "2025-03-01"},
    "G16": {"berlin_jahreswechsel_utc": "2024-12-31T23:30:00Z", "berlin_jahr": 2025,
            "berlin_jahrestag_ende_utc": "2024-03-01T23:00:00Z",
            "berlin_sommer_folgetag_utc": "2024-06-30T22:00:00Z",
            "dst_fruehjahr_utc": "2024-03-31T01:30:00Z", "dst_berlin_stunde": 3},
    "G17": {"luecken": ["fehlende_basis", "fehlende_historie", "fehlender_preis"],
            "erfundener_kauf": False, "unmarkierte_finale_nullbasis": False, "finale_freigabe": False},
    "G18": {"annahme": "Gleiches Symbol bei zwei Contracts/Chains darf Identitaetskonflikt nicht aufloesen",
            "finale_freigabe_bei_konflikt": False},
    "G19": {"annahme": "Nur belegte Migration 100:1, keine pauschale Symbolparitaet",
            "alt_token": "100", "neu_token": "1"},
    "G20": {"annahme": "Identische CSV zweimal: idempotenter Import",
            "raw_zeilen": 2, "canonical_events": 2, "rest_stueck": "6", "gewinn_eur": "20"},
    "G21": {"mutationen": ["daten", "preise", "regeln"], "altes_archiv_unveraendert": True,
            "alte_uebernahme_gesperrt": True, "binding_erforderlich": True},
    "G22": {"offline": True, "fachlich_semantisch_gleich": True,
            "zufalls_uuid_oder_pdfzeit_ist_keine_fachdifferenz": True},
    "G23": {"technischer_download": True, "inhalt_als_vorschau_markiert": True,
            "leere_reviewliste_ist_jahresfreigabe": False},
    "G24": {"2023_599.99": True, "2023_600": False, "2024_999.99": True, "2024_1000": False,
            "annahme": "Nur modellierte private Gewinne; sonstige persoenliche Einkuenfte unbekannt"},
    "G25": {"raw_erhalten": True, "secret_erhalten": True, "review_erhalten": True,
            "altes_paket_unveraendert": True, "neuer_revisionsstand_nachvollziehbar": True},
}


@pytest.fixture
def case(monkeypatch):
    root = Path(tempfile.mkdtemp(prefix="case-", dir=TESTROOT))
    shutil.copytree(REPO / "configs", root / "software/configs")
    (root / "profile.json").write_text("{}\n")
    for key, value in {
        "STEUERREPORT_V2_ROOT": root / "software",
        "STEUERREPORT_V2_DB": root / "data.duckdb",
        "STEUERREPORT_STATE_DIR": root / "runtime",
        "STEUERREPORT_PRIVATE_PROFILE": root / "profile.json",
        "STEUERREPORT_PRIVATE_CONFIG_DIR": root / "private-configs",
        "STEUERREPORT_USERTRANSFER_ROOT": root / "imports",
        "STEUERREPORT_V2_SECRET_VAULT_KEY_FILE": root / "keys/vault.key",
    }.items():
        monkeypatch.setenv(key, str(value))
    # Bereits beim Import gebundene Pfade bleiben ebenfalls im eigenen Testroot.
    for module in list(sys.modules.values()):
        if not getattr(module, "__name__", "").startswith("steuerreport_v2"):
            continue
        for key, value in list(vars(module).items()):
            if isinstance(value, Path) and value.is_relative_to(BOOT):
                monkeypatch.setattr(module, key, root / value.relative_to(BOOT))
            if isinstance(value, type) and value.__module__ == module.__name__:
                for attr, item in list(vars(value).items()):
                    if isinstance(item, Path) and item.is_relative_to(BOOT):
                        monkeypatch.setattr(value, attr, root / item.relative_to(BOOT))
    store = DuckDbStore(root / "data.duckdb")
    store.health()
    return root, store


HEADER = "time,asset,amount,type,quote_asset,quote_quantity,fee_asset,fee_quantity,account,tx_id\n"
BASIC_ROWS = [
    ["2024-01-10T12:00:00Z", "BTC", "10", "buy", "EUR", "100", "", "", "Depot-A", "synthetic-buy"],
    ["2024-02-10T12:00:00Z", "BTC", "-4", "sell", "EUR", "60", "", "", "Depot-A", "synthetic-sale"],
]


def import_rows(store, rows, filename="synthetic.csv"):
    text = io.StringIO()
    text.write(HEADER)
    writer = csv.writer(text)
    writer.writerows(rows)
    content = text.getvalue()
    batch = CsvRawImporter(store).import_text(source="binance", filename=filename, content=content)
    RawNormalizer(store).normalize_batch(batch.batch_id)
    return batch, content


def point(store, asset, price, at="2024-01-10T00:00:00Z"):
    return store.add_price_point(PricePointCreate(asset=asset, price_eur=Decimal(price),
                priced_at=datetime.fromisoformat(at.replace("Z", "+00:00")), source="synthetic:documented"))


def rebuild(store):
    BalanceLedgerBuilder(store).rebuild()
    return TaxService(store).rebuild_fifo()


def numbers(result):
    return {
        "cost": sum((line.acquisition_cost_eur for line in result.tax_lines), Decimal("0")),
        "gain": sum((line.gain_loss_eur for line in result.tax_lines), Decimal("0")),
        "proceeds": sum((line.disposal_proceeds_eur for line in result.tax_lines), Decimal("0")),
        "remaining": sum((lot.quantity_remaining for lot in result.lots if lot.asset == "BTC"), Decimal("0")),
    }


def year_package(store, year=2024):
    with TestClient(create_app(store)) as client:
        response = client.get(f"/api/v1/export/tax-years/{year}/evidence-package.zip")
    assert response.status_code == 200, response.text[:500]
    return response.content


def members(content):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def manifest(content):
    return json.loads(members(content)["00_Manifest/year-evidence-manifest.json"])


def semantic_tax(result):
    return {
        "lots": sorted((lot.asset, lot.acquired_at.isoformat(), str(lot.quantity_total),
                        str(lot.quantity_remaining), str(lot.cost_basis_eur_total)) for lot in result.lots),
        "lines": sorted((line.asset, line.acquired_at.isoformat(), line.disposed_at.isoformat(),
                         str(line.quantity), str(line.acquisition_cost_eur),
                         str(line.disposal_proceeds_eur), str(line.gain_loss_eur)) for line in result.tax_lines),
        "unmatched": result.unmatched_disposals,
    }


def test_G01_csv_fifo_restbasis_und_jahreswerte(case):
    _, store = case
    batch, _ = import_rows(store, BASIC_ROWS)
    result = rebuild(store)
    assert batch.raw_object_count == 2
    assert numbers(result) == {"cost": Decimal("40"), "gain": Decimal("20"),
                               "proceeds": Decimal("60"), "remaining": Decimal("6")}
    lot = result.lots[0]
    assert lot.cost_basis_eur_total * lot.quantity_remaining / lot.quantity_total == Decimal("60")
    year = next(row for row in TaxYearService(store).summary().years if row.year == 2024)
    assert year.acquisition_cost_eur == Decimal("40")
    assert year.realized_gain_loss_eur == Decimal("20")
    with TestClient(create_app(store)) as client:
        rows = list(csv.DictReader(io.StringIO(client.get("/api/v1/export/tax-lines.csv").text)))
    assert len(rows) == 1
    assert Decimal(rows[0]["Gewinn_Verlust_EUR"]) == Decimal("20")


def test_G02_eur_erwerbskosten_und_verkaufskosten(case):
    _, store = case
    rows = [list(row) for row in BASIC_ROWS]
    rows[0][6:8] = ["EUR", "2"]
    rows[1][6:8] = ["EUR", "1"]
    import_rows(store, rows)
    result = rebuild(store)
    assert numbers(result)["cost"] == Decimal("40.8"), "EUR-Erwerbskosten nicht kapitalisiert"
    assert numbers(result)["gain"] == Decimal("18.2")
    lot = result.lots[0]
    assert lot.cost_basis_eur_total * lot.quantity_remaining / lot.quantity_total == Decimal("61.2")


def test_G03_erwerbsassetgebuehr_netto_menge(case):
    _, store = case
    row = list(BASIC_ROWS[0])
    row[6:8] = ["BTC", "0.1"]
    import_rows(store, [row])
    result = rebuild(store)
    assert result.lots[0].quantity_total == Decimal("9.9")
    assert result.lots[0].cost_basis_eur_total == Decimal("100")


def test_G04_drittassetgebuehr_lotverbrauch_teilprobe(case):
    _, store = case
    import_rows(store, [
        ["2024-01-09T12:00:00Z", "BNB", "1", "buy", "EUR", "20", "", "", "Depot-A", "synthetic-fee-funding"],
        ["2024-01-10T12:00:00Z", "BTC", "10", "buy", "EUR", "100", "BNB", "0.1", "Depot-A", "synthetic-third-fee"],
    ])
    point(store, "BNB", "20")
    result = rebuild(store)
    remaining = sum((lot.quantity_remaining for lot in result.lots if lot.asset == "BNB"), Decimal("0"))
    assert remaining == Decimal("0.9"), "Ausgegebene Drittassetgebuehr muss auch den BNB-Lotbestand mindern"
    # Keine Annahme ueber noch nicht modellierte steuerliche Gebuehrenzuordnung.


def test_G05_swap_beide_beine_gewinne_ohne_fiatdeposit(case):
    _, store = case
    import_rows(store, [
        ["2024-01-10T12:00:00Z", "BTC", "2", "buy", "EUR", "40", "", "", "Depot-A", "synthetic-swap-buy"],
        ["2024-02-10T12:00:00Z", "ETH", "5", "buy", "BTC", "2", "", "", "Depot-A", "synthetic-swap"],
    ])
    point(store, "BTC", "30", "2024-02-10T00:00:00Z")
    point(store, "ETH", "12", "2024-02-10T00:00:00Z")
    result = rebuild(store)
    assert len(result.tax_lines) == 1
    assert result.tax_lines[0].acquisition_cost_eur == Decimal("40")
    assert result.tax_lines[0].gain_loss_eur == Decimal("20")
    eth = next(lot for lot in result.lots if lot.asset == "ETH")
    assert (eth.quantity_remaining, eth.cost_basis_eur_total) == (Decimal("5"), Decimal("60"))
    assert not any(e.asset == "EUR" and e.quantity > 0 for e in store.list_canonical_events())


@pytest.mark.parametrize("stable_price,expected", [("0.72", "72"), ("0.6", "60")], ids=["G06-FX", "G07-Depeg"])
def test_G06_G07_stablecoin_tatsaechlicher_eur_kurs(case, stable_price, expected):
    _, store = case
    import_rows(store, [["2024-01-10T12:00:00Z", "BTC", "1", "buy", "USDT", "100", "", "", "Depot-A", "synthetic-stable"]])
    point(store, "USDT", stable_price)
    result = rebuild(store)
    assert result.lots[0].cost_basis_eur_total == Decimal(expected)
    # FX-Anbieter-/Originalantwortprobe bleibt separat offen; hier konsumierter EUR-PricePoint.


@pytest.mark.parametrize("price_time", ["2021-01-15T12:00:00Z", "2025-01-15T13:00:00Z"], ids=["alt", "zukunft"])
def test_G10_lookup_alte_und_zukuenftige_preise_abgelehnt(case, price_time):
    _, store = case
    point(store, "BTC", "10", price_time)
    assert HistoricalPriceLookup(store).at_or_before("BTC", datetime(2025, 1, 15, 12, tzinfo=timezone.utc)) is None


def stale_income(store):
    import_rows(store, [["2025-01-15T12:00:00Z", "BTC", "1", "reward", "", "", "", "", "Depot-A", "synthetic-stale"]])
    point(store, "BTC", "10", "2021-01-15T12:00:00Z")


def test_G10_coverage_sql_meldet_altkurs_als_luecke(case):
    _, store = case
    stale_income(store)
    coverage = PriceCoverageService(store).report()
    assert coverage.missing_count >= 1
    assert "BTC" in coverage.missing_assets


def test_G10_tax_kein_unmarkierter_altkurs(case):
    _, store = case
    stale_income(store)
    result = rebuild(store)
    assert result.lots[0].cost_basis_eur_total != Decimal("10"), "2021-Kurs im 2025-Lot verbraucht"


def test_G10_review_altkurs_darf_final_nicht_freigeben(case):
    _, store = case
    stale_income(store)
    rebuild(store)
    assert not ReviewService(store).gate().allow_export


def test_G10_derived_preis_darf_altkurs_nicht_zeitlich_waschen(case):
    _, store = case
    import_rows(store, [["2025-01-15T12:00:00Z", "ETH", "5", "buy", "BTC", "2", "", "", "Depot-A", "synthetic-laundering"]])
    point(store, "BTC", "30", "2021-01-15T12:00:00Z")
    DerivedPriceService(store).rebuild_from_event_quotes()
    assert not [p for p in store.list_price_points() if p.asset == "ETH"], "Altpreis wurde zum neuen ETH-Preis abgeleitet"


def test_G10_altkurs_jahresarchiv_nicht_final(case):
    _, store = case
    stale_income(store)
    rebuild(store)
    meta = manifest(year_package(store, year=2025))
    assert meta["export_ready"] is False, "Altpreisfall als final exportbereit etikettiert"
    assert meta.get("filing_status") == "preview"


def test_G11_wallet_global_vorschau_ohne_aktivierung(case):
    _, store = case
    import_rows(store, [
        ["2024-01-01T12:00:00Z", "BTC", "1", "buy", "EUR", "10", "", "", "Depot-A", "synthetic-A"],
        ["2024-01-02T12:00:00Z", "BTC", "1", "buy", "EUR", "20", "", "", "Depot-B", "synthetic-B"],
        ["2024-02-01T12:00:00Z", "BTC", "-1", "sell", "EUR", "30", "", "", "Depot-B", "synthetic-B-sale"],
    ])
    global_result = TaxService(store).preview_global_fifo()
    wallet = WalletFifoPreviewService(store).replay()
    assert numbers(global_result)["gain"] == Decimal("20")
    assert sum((line.gain_loss_eur for line in wallet.tax_lines), Decimal("0")) == Decimal("10")
    with store.connect() as con:
        assert con.execute("select count(*) from tax_run_summaries").fetchone()[0] == 0


def test_G12_eigenuebertrag_originaldatum_basis_teilprobe(case):
    _, store = case
    import_rows(store, [
        ["2023-01-10T12:00:00Z", "BTC", "10", "buy", "EUR", "100", "", "", "Depot-A", "synthetic-transfer-buy"],
        ["2024-01-10T12:00:00Z", "BTC", "-4", "transfer", "", "", "", "", "Depot-A", "synthetic-own-transfer"],
        ["2024-01-10T12:00:01Z", "BTC", "4", "transfer", "", "", "", "", "Depot-B", "synthetic-own-transfer"],
    ])
    state = WalletFifoPreviewService(store).replay()
    target = [lot for lot in state.open_lots if "depot-b" in lot.pool_id.lower()]
    assert len(target) == 1
    assert target[0].quantity_remaining == Decimal("4")
    assert target[0].cost_basis_eur_total == Decimal("40")
    assert target[0].acquired_at.date().isoformat() == "2023-01-10"
    assert state.transfer_traces


def test_G13_reward_einnahme_basis_und_veraeusserung_getrennt(case):
    _, store = case
    import_rows(store, [
        ["2024-01-10T12:00:00Z", "BTC", "1", "reward", "", "", "", "", "Depot-A", "synthetic-reward"],
        ["2024-02-10T12:00:00Z", "BTC", "-1", "sell", "EUR", "150", "", "", "Depot-A", "synthetic-reward-sale"],
    ])
    point(store, "BTC", "100")
    result = rebuild(store)
    assert result.lots[0].cost_basis_eur_total == Decimal("100")
    assert numbers(result)["gain"] == Decimal("50")
    income = TaxYearService(store).income_report(2024)
    assert income.total_income_eur == Decimal("100")
    assert income.declaration_income_eur + income.review_only_income_eur == Decimal("100")
    # Eine echte Belegung der Wirtschaftssphaere ist hier NICHT simuliert.


def test_G14_unklares_income_als_review_teilprobe(case):
    _, store = case
    import_rows(store, [["2024-01-10T12:00:00Z", "BTC", "1", "income", "", "", "", "", "Depot-A", "synthetic-unclear-income"]])
    point(store, "BTC", "100")
    rebuild(store)
    report = TaxYearService(store).income_report(2024)
    assert report.review_only_income_eur == Decimal("100")
    assert report.declaration_income_eur == Decimal("0")
    # Keine vollstaendige privat/betrieblich-Sphaerenmodellierung behaupten.


@pytest.mark.parametrize("buy,sale,expected_taxable,expected_free", [
    ("2023-03-01T12:00:00Z", "2024-03-01T12:00:00Z", "20", "0"),
    ("2023-03-01T12:00:00Z", "2024-03-02T12:00:00Z", "0", "20"),
    ("2024-02-29T12:00:00Z", "2025-02-28T12:00:00Z", "20", "0"),
    ("2024-02-29T12:00:00Z", "2025-03-01T12:00:00Z", "0", "20"),
    ("2023-03-01T12:00:00Z", "2024-03-01T23:00:00Z", "0", "20"),
    ("2023-06-30T12:00:00Z", "2024-06-30T22:00:00Z", "0", "20"),
    ("2024-03-01T12:00:00Z", "2025-03-01T23:00:00Z", "0", "20"),
    ("2024-06-30T12:00:00Z", "2025-06-30T22:00:00Z", "0", "20"),
], ids=["G15-366-Jahrestag", "G15-Folgetag", "G15-29Feb-Jahrestag", "G15-29Feb-Folgetag", "G16-Berlin-Winter", "G16-Berlin-Sommer", "G16-Winter-365", "G16-Sommer-365"])
def test_G15_G16_jahresconsumer_kalenderfrist(case, buy, sale, expected_taxable, expected_free):
    _, store = case
    rows = [list(row) for row in BASIC_ROWS]
    rows[0][0], rows[1][0] = buy, sale
    import_rows(store, rows)
    rebuild(store)
    year = next(row for row in TaxYearService(store).summary().years if row.year == datetime.fromisoformat(sale.replace("Z", "+00:00")).year)
    assert year.realized_gain_loss_eur == Decimal(expected_taxable)
    assert year.tax_free_gain_loss_eur == Decimal(expected_free)


def test_G16_berlin_jahr_dst_und_sql(case):
    _, store = case
    boundary = datetime(2024, 12, 31, 23, 30, tzinfo=timezone.utc)
    assert reporting_tax_year(boundary) == 2025
    assert reporting_time(datetime(2024, 3, 31, 1, 30, tzinfo=timezone.utc)).hour == 3
    with store.connect() as con:
        sql_year = con.execute("select " + reporting_year_sql("cast(? as timestamp)"), [boundary.replace(tzinfo=None)]).fetchone()[0]
    assert sql_year == 2025


def test_G15_jahrestag_csv_klassifikation(case):
    _, store = case
    rows = [list(row) for row in BASIC_ROWS]
    rows[0][0], rows[1][0] = "2023-03-01T12:00:00Z", "2024-03-01T12:00:00Z"
    import_rows(store, rows)
    rebuild(store)
    with TestClient(create_app(store)) as client:
        response = client.get("/api/v1/export/tax-lines.csv")
    assert response.status_code == 200
    exported = list(csv.DictReader(io.StringIO(response.text)))
    assert exported[0]["Steuerpflichtig"] == "ja", "Jahrestag trotz366Tagen noch innerhalb"


def test_G15_berlin_planungszeitpunkt(case):
    _, store = case
    row = list(BASIC_ROWS[0])
    row[0] = "2023-03-01T12:00:00Z"
    import_rows(store, [row])
    point(store, "BTC", "20", "2024-03-01T00:00:00Z")
    rebuild(store)
    report = TaxService(store).holding_period_report(as_of=datetime(2024, 3, 1, 22, 59, 59, tzinfo=timezone.utc))
    assert len(report.lots) == 1
    assert report.lots[0].tax_free_at == datetime(2024, 3, 1, 23, tzinfo=timezone.utc)


@pytest.mark.parametrize("gap", ["basis", "historie", "preis"])
def test_G17_fehlende_basis_oder_preis_kein_finaler_stand(case, gap):
    _, store = case
    if gap == "basis":
        import_rows(store, [BASIC_ROWS[1]])
    elif gap == "historie":
        import_rows(store, [
            ["2024-01-10T12:00:00Z", "BTC", "4", "deposit", "", "", "", "", "Depot-A", "synthetic-missing-history"],
            BASIC_ROWS[1],
        ])
    else:
        import_rows(store, [["2024-01-10T12:00:00Z", "BTC", "1", "reward", "", "", "", "", "Depot-A", "synthetic-no-price"]])
    original = [(e.event_id, e.raw_object_id, e.event_type) for e in store.list_canonical_events()]
    result = rebuild(store)
    assert [(e.event_id, e.raw_object_id, e.event_type) for e in store.list_canonical_events()] == original
    if gap in {"basis", "historie"}:
        assert result.unmatched_disposals == 1
        assert not result.lots
    assert not ReviewService(store).gate().allow_export


def test_G20_doppelimport_keine_ereignis_oder_lotverschiebung(case):
    _, store = case
    batch, text = import_rows(store, BASIC_ROWS)
    first = rebuild(store)
    raw_ids = {row.raw_object_id for row in store.list_raw_objects(batch.batch_id, limit=None)}
    duplicate = CsvRawImporter(store).import_text(source="binance", filename="synthetic-again.csv", content=text)
    assert duplicate.batch_id == batch.batch_id
    assert {row.raw_object_id for row in store.list_raw_objects(batch.batch_id, limit=None)} == raw_ids
    second = rebuild(store)
    assert len(store.list_canonical_events()) == 2
    assert semantic_tax(first) == semantic_tax(second)
    assert numbers(second)["gain"] == Decimal("20")


def test_G22_offline_neulauf_semantisch_inkl_export(case):
    _, store = case
    import_rows(store, BASIC_ROWS)
    first = rebuild(store)
    with TestClient(create_app(store)) as client:
        csv_first = list(csv.DictReader(io.StringIO(client.get("/api/v1/export/tax-lines.csv").text)))
    second = rebuild(store)
    with TestClient(create_app(store)) as client:
        csv_second = list(csv.DictReader(io.StringIO(client.get("/api/v1/export/tax-lines.csv").text)))
    assert semantic_tax(first) == semantic_tax(second)
    fields = ("Asset", "Menge", "Anschaffungskosten_EUR", "Veraeusserungserloes_EUR", "Gewinn_Verlust_EUR")
    assert [[row[key] for key in fields] for row in csv_first] == [[row[key] for key in fields] for row in csv_second]


def technical_store(store):
    import_rows(store, [["2024-01-10T12:00:00Z", "USDT", "10", "deposit", "", "", "", "", "Depot-A", "synthetic-deposit"]])
    point(store, "USDT", "0.9")
    rebuild(store)


def test_G23_technisch_exportierbar_ist_keine_jahresfreigabe(case):
    _, store = case
    technical_store(store)
    readiness = ExportService(store).readiness().model_dump()
    assert readiness["allow_export"] is True
    assert readiness.get("technical_export_allowed") is True, "F04-Dimension fehlt"
    assert readiness.get("final_filing_allowed") is False, "Leere Reviewliste ist keine Jahresfreigabe"


def test_G23_echtes_jahresarchiv_inhalt_als_vorschau(case):
    _, store = case
    import_rows(store, BASIC_ROWS)
    rebuild(store)
    content = year_package(store)
    payload = members(content)
    meta = manifest(content)
    assert meta.get("filing_status") == "preview", "ZIP-Inhalt ohne expliziten Vorschau-Status"
    assert meta["export_ready"] is False
    assert b"VORSCHAU" in payload["README.txt"]
    assert meta.get("input_binding_sha256")
    assert meta.get("calculation_run_id")
    for entry in meta["files"]:
        assert hashlib.sha256(payload[entry["path"]]).hexdigest() == entry["sha256"]


@pytest.mark.parametrize("mutation", ["daten", "preise", "regeln"])
def test_G21_pdf_binding_veraltet_bei_inputaenderung(case, mutation):
    _, store = case
    technical_store(store)
    exports = ExportService(store)
    result = exports.create_pdf_packages(PdfExportRequest(label="synthetic-preview", estimated_pages=1))
    assert not result.blocked
    package = result.packages[0]
    rendered = exports.render_pdf_package(package.package_id)
    assert rendered is not None
    if mutation == "daten":
        import_rows(store, [["2024-01-11T12:00:00Z", "EUR", "1", "deposit", "", "", "", "", "Depot-A", "synthetic-change"]], "change.csv")
    elif mutation == "preise":
        point(store, "USDT", "0.91", "2024-01-11T00:00:00Z")
    else:
        store.upsert_admin_setting(AdminSettingWrite(key="synthetic.method.rule", value_json='{"version":2}'))
    assert exports.render_pdf_package(package.package_id) is None, "Alter PDF-Download trotz Inputaenderung verfuegbar"


@pytest.mark.parametrize("year,gain,state", [(2023,"599.99","below_threshold"),(2023,"600","threshold_reached"),
                                             (2024,"999.99","below_threshold"),(2024,"1000","threshold_reached")])
def test_G24_echte_route_freigrenze_strikt_kleiner(case, year, gain, state):
    _, store = case
    rows = [list(row) for row in BASIC_ROWS]
    rows[0][0], rows[0][2], rows[0][5] = f"{year}-01-10T12:00:00Z", "1", "100"
    rows[1][0], rows[1][2], rows[1][5] = f"{year}-02-10T12:00:00Z", "-1", str(Decimal("100") + Decimal(gain))
    import_rows(store, rows)
    rebuild(store)
    with TestClient(create_app(store)) as client:
        response = client.post(f"/api/v1/tax-years/{year}/private-disposal-threshold-assessment", json={
            "other_private_gain_loss_eur":"0", "confirm_other_private_disposals_complete":True})
    assert response.status_code == 200, "G24: oeffentlicher Freigrenzenconsumer fehlt"
    data = response.json()["data"]
    assert data["status"] == state
    assert Decimal(data["calculated_crypto_gain_loss_eur"]) == Decimal(gain)
    assert Decimal(data["total_private_gain_loss_eur"]) == Decimal(gain)
    assert Decimal(data["threshold_eur"]) == Decimal("600" if year == 2023 else "1000")
    assert data["threshold_reached"] is (state == "threshold_reached")
    assert data["final_filing_allowed"] is False


@pytest.mark.parametrize("body", [
    {"other_private_gain_loss_eur":None},
    {"other_private_gain_loss_eur":None, "confirm_other_private_disposals_complete":True},
    {"other_private_gain_loss_eur":"0"},
    {"other_private_gain_loss_eur":"0", "confirm_other_private_disposals_complete":False},
])
def test_G24_unbekannte_andere_private_einkuenfte_kein_nullfallback(case, body):
    _, store = case
    import_rows(store, BASIC_ROWS)
    rebuild(store)
    with TestClient(create_app(store)) as client:
        response = client.post("/api/v1/tax-years/2024/private-disposal-threshold-assessment", json=body)
    assert response.status_code == 200, "G24: Consumer fehlt"
    data = response.json()["data"]
    assert data["status"] == "context_required"
    assert data.get("total_private_gain_loss_eur") is None
    assert data.get("threshold_reached") is None
    assert data["final_filing_allowed"] is False


@pytest.mark.parametrize("year", [2008, 2027])
def test_G24_unterstuetzte_jahre_nicht_still_ausdehnen(case, year):
    _, store = case
    with TestClient(create_app(store)) as client:
        response = client.post(f"/api/v1/tax-years/{year}/private-disposal-threshold-assessment", json={
            "other_private_gain_loss_eur":"0", "confirm_other_private_disposals_complete":True})
    assert response.status_code == 200, "G24: Consumer fehlt"
    data = response.json()["data"]
    assert data["status"] == "unsupported_year"
    assert data["threshold_reached"] is None
    assert data["final_filing_allowed"] is False


def test_G24_bestaetigung_strikter_bool_keine_stringfreigabe(case):
    _, store = case
    with TestClient(create_app(store)) as client:
        response = client.post("/api/v1/tax-years/2024/private-disposal-threshold-assessment", json={
            "other_private_gain_loss_eur":"0", "confirm_other_private_disposals_complete":"true"})
    assert response.status_code == 422, "Strikte Bestaetigung darf Text nicht als true akzeptieren"


def test_G23_pdf_ist_inhaltlich_vorschau(case):
    _, store = case
    technical_store(store)
    exports = ExportService(store)
    result = exports.create_pdf_packages(PdfExportRequest(label="synthetic-preview", estimated_pages=1))
    assert not result.blocked
    package, data = exports.render_pdf_package(result.packages[0].package_id)
    assert package.model_dump().get("filing_status") == "preview"
    assert "VORSCHAU" in "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)


def test_G25_originalarchiv_revision_raw_review_synthetischer_restore(case):
    root, store = case
    import_rows(store, BASIC_ROWS)
    rebuild(store)
    store.upsert_admin_setting(AdminSettingWrite(key="synthetic.secret.reference", value_json='"SYNTHETIC_NOT_A_REAL_SECRET"'))
    decision = store.add_review_decision(ReviewDecisionCreate(decision_type="synthetic_evidence", scope="synthetic:2024", title="Nur Fixture", rationale="Keine fachliche Freigabe", evidence_ref="synthetic.csv"))
    content = year_package(store)
    archives = TaxFilingSnapshotService(store)
    captured = archives.capture_package(year=2024, package_bytes=content,
        request=TaxFilingSnapshotCaptureRequest(state="reference"), source_kind="acceptance-synthetic").snapshot
    old_bytes = archives.read_package(captured.snapshot_id)
    with store.connect() as con:
        raw_before = con.execute("select * from raw_objects order by raw_object_id").fetchall()
    # Alle Verbindungen des Stores sind geschlossen: keine Kopie einer aktiven DB.
    backup = root / "consistent-synthetic-backup"
    backup.mkdir()
    shutil.copy2(store.path, backup / "data.duckdb")
    shutil.copytree(archives.archive_root, backup / "tax_filing_archive")
    restored = DuckDbStore(backup / "data.duckdb")
    with restored.connect() as con:
        assert con.execute("select * from raw_objects order by raw_object_id").fetchall() == raw_before
        assert con.execute("select value_json from admin_settings where key='synthetic.secret.reference'").fetchone()[0] == '"SYNTHETIC_NOT_A_REAL_SECRET"'
    assert decision.decision_id in {d.decision_id for d in restored.list_review_decisions()}
    assert TaxFilingSnapshotService(restored).read_package(captured.snapshot_id) == old_bytes
    point(store, "BTC", "99", "2024-03-01T00:00:00Z")
    new_content = year_package(store)
    new_snapshot = archives.capture_package(year=2024, package_bytes=new_content,
        request=TaxFilingSnapshotCaptureRequest(state="reference", note="Synthetische Revision nach Preisinput"),
        source_kind="acceptance-synthetic").snapshot
    assert archives.read_package(captured.snapshot_id) == old_bytes
    assert new_snapshot.revision == captured.revision + 1
    assert new_snapshot.package_sha256 != captured.package_sha256
