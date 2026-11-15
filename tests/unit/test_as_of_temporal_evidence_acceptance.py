"""Issue46: unabhaengige Zeitbeleg-Gegenproben, nur synthetische DuckDB.

Kein Import der neuen Klassifikationsfunktion: bestehendes Gate und API muessen
die Gegenfaelle selbst abweisen. Fehlende additive Felder sind Vertragsluecken,
keine alleinigen Beweise fuer falsche finanzielle Altdaten.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
from urllib.parse import quote

from fastapi.testclient import TestClient
import pytest

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.divorce import DivorceValuationGate
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.portfolio import PortfolioPosition
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.valuation_runs import DivorceValuationRunReport
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.as_of_price_gate import AsOfPriceGateService
from steuerreport_v2.domain.divorce import DivorceEqualizationService
from steuerreport_v2.domain.stichtag_token_valuation import StichtagTokenValuationService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.valuation_runs import DivorceValuationRunService
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


AT = datetime(2025, 6, 13, 1, tzinfo=timezone.utc)
MIDNIGHT = datetime(2025, 6, 13, tzinfo=timezone.utc)
POLICY = "stichtag-temporal-evidence"
MINT = "11111111111111111111111111111111"
FX_LABEL = "defillama_token_history:usd_eur:v1_fx_cache:as_of_gate:2025-06-13:fxref:" + quote(
    json.dumps({"policy_id": "fx_reference_on_or_before_max_7_calendar_days_v1",
                "reference_date": "2025-06-12", "base": "USD", "quote": "EUR",
                "rate": "0.9", "source": "synthetic-reference"}, sort_keys=True, separators=(",", ":")),
    safe="",
)
FINANCIAL_TABLES = ("price_ledger", "canonical_events", "balance_ledger", "flow_ledger",
                    "tax_lines", "tax_lots", "tax_run_summaries")


def financial_snapshot(store):
    with store.connect() as con:
        return {name: con.execute(f"select * from {name} order by all").fetchall()
                for name in FINANCIAL_TABLES}


def field(value, name):
    assert name in value, f"VERTRAGSLUECKE: additives Feld {name} fehlt"
    return value[name]


def gate_policy(gate):
    assert field(gate, "price_time_policy_id") == POLICY
    assert field(gate, "price_time_policy_version") == 1
    assert type(gate["price_time_policy_version"]) is int


def unverified_assessment(value, *, kind="unknown", stored_at=MIDNIGHT):
    assert value["policy_id"] == POLICY and value["policy_version"] == 1
    assert value["asset"] == "BTC"
    assert value["status"] == "unverified_time" and value["strict_eligible"] is False
    assert value["reference_kind"] == kind
    assert datetime.fromisoformat(value["stored_reference_at"].replace("Z", "+00:00")) == stored_at
    for key in ("observed_at", "period_start", "period_end", "price_published_at", "fx_published_at",
                "valuation_method_id", "valuation_method_version", "price_evidence_ref", "fx_evidence_ref"):
        assert key in value and value[key] is None, f"Kein erfundener Beleg fuer {key}"
    assert value["reason_codes"] and value["explanation"].strip()


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Zeitbeleg-Lesen darf keinen Provider oder Pipeline-Rebuild starten")
    monkeypatch.setattr("steuerreport_v2.domain.as_of_price_gate.managed_client", forbidden)
    monkeypatch.setattr("steuerreport_v2.domain.external_price_backfill.managed_client", forbidden)
    monkeypatch.setattr("steuerreport_v2.domain.pipeline.PipelineService.rebuild_all", forbidden)
    monkeypatch.setattr(AsOfPriceGateService, "_provider_sources", staticmethod(
        lambda path: {asset: ("synthetic-" + asset.lower(), None)
                      for asset in ("BTC", "USDC", "USDT", "SYNTHRISK")}))
    # Optional Belegconnectoren duerfen nur eigene leere Testverzeichnisse sehen.
    for key in ("STEUERREPORT_SPARKASSE_CAMT_DIR", "STEUERREPORT_SPARKASSE_STATEMENT_DIR",
                "STEUERREPORT_TRADE_REPUBLIC_DOCUMENT_ROOT", "STEUERREPORT_INHERITANCE_DOCUMENT_ROOT"):
        monkeypatch.setenv(key, str(tmp_path / "empty-documents"))
    def seed(*, asset="BTC", value="100", source="synthetic:unknown", at=MIDNIGHT,
             confidence="0.95", accounts=1, with_price=True):
        store = DuckDbStore(tmp_path / "synthetic-temporal.duckdb")
        for index in range(accounts):
            store.add_canonical_event(CanonicalEventCreate(
                source="synthetic-temporal", source_ref=f"position-{index}",
                account=f"synthetic-wallet-{index}", event_time=AT - timedelta(days=1),
                event_type="transfer", asset=asset, quantity=Decimal("1"),
            ))
        if with_price:
            store.add_price_point(PricePointCreate(asset=asset, price_eur=Decimal(value),
                                  priced_at=at, source=source, confidence=Decimal(confidence)))
        BalanceLedgerBuilder(store).rebuild()
        return store
    return seed


def read_report(store, surface="api", threshold="1"):
    if surface == "service":
        return AsOfPriceGateService(store).report(as_of=AT, materiality_threshold_eur=Decimal(threshold)).model_dump(mode="json")
    response = TestClient(create_app(store)).get("/api/v1/prices/as-of-gate", params={
        "as_of": AT.isoformat(), "materiality_threshold_eur": threshold,
    })
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.parametrize("surface", ["service", "api"])
@pytest.mark.parametrize("source,at", [
    (FX_LABEL, MIDNIGHT),
    ("synthetic:unknown", MIDNIGHT),
    ("synthetic:unknown-intraday", AT - timedelta(minutes=1)),
    ("fiat:EUR", MIDNIGHT),
], ids=["daily-anchor-earlier-fx", "unknown-midnight", "unknown-exact-clock", "forged-eur-label"])
def test_unproven_reference_at_0100_must_not_open_strict_gate(sandbox, surface, source, at):
    store = sandbox(source=source, at=at)
    before = financial_snapshot(store)
    report = read_report(store, surface)
    assert financial_snapshot(store) == before
    assert report["strict_ready"] is False, (
        f"GEGENBELEG: {surface} 01:00 UTC, Quelle={source}, gespeicherte Zeit={at.isoformat()} "
        f"wird ohne Zeitbeleg strict_ready; Gate={report['gate']}"
    )
    assert report["gate"]["strict_ready"] is False
    assert field(report["gate"], "unverified_price_time_count") == 1
    assert field(report, "time_review_count") == 1
    assert report["candidates"][0]["status"] == "time_review"


@pytest.mark.parametrize("confidence", ["0.1", "0.95", "1"])
def test_confidence_cannot_replace_original_time_evidence(sandbox, confidence):
    store = sandbox(confidence=confidence, source="synthetic:operator-reviewed")
    before = financial_snapshot(store)
    report = read_report(store)
    assert financial_snapshot(store) == before
    assert not report["strict_ready"], f"GEGENBELEG: Confidence {confidence} ersetzt fehlenden Zeitbeleg"


@pytest.mark.parametrize("asset", ["USDC", "USDT"])
@pytest.mark.parametrize("source", ["fiat:EUR", "synthetic:stablecoin-parity"])
def test_usd_stablecoin_and_forged_fiat_label_are_not_eur_identity(sandbox, asset, source):
    store = sandbox(asset=asset, value="1", source=source, confidence="1")
    before = financial_snapshot(store)
    report = read_report(store)
    assert financial_snapshot(store) == before
    assert not report["strict_ready"], f"GEGENBELEG: {asset}/{source} wird als zeitlich belegt freigegeben"
    candidate, = report["candidates"]
    assessment = field(candidate, "price_time")
    assert assessment["status"] == "unverified_time" and not assessment["strict_eligible"]


@pytest.mark.parametrize("value", ["0.00000001", "0.5"])
def test_unverified_small_value_cannot_prove_immateriality_or_hide_candidate(sandbox, value):
    store = sandbox(value=value, accounts=2)
    before = financial_snapshot(store)
    report = read_report(store, threshold="1")
    assert financial_snapshot(store) == before
    assert not report["strict_ready"], (
        f"GEGENBELEG: ungepruefter Kurs {value} beweist selbst Unwesentlichkeit; "
        f"Gate={report['gate']}, Kandidaten={report['candidates']}"
    )
    assert report["gate"]["material_positions_count"] == 2
    assert field(report["gate"], "unverified_price_time_count") == 2
    assert field(report, "time_review_count") == 1
    candidate, = report["candidates"]
    assert candidate["asset"] == "BTC" and candidate["status"] == "time_review"
    assert Decimal(candidate["value_eur"]) == Decimal(value) * 2


def test_position_counter_and_asset_counter_are_separate(sandbox):
    store = sandbox(accounts=2)
    report = read_report(store)
    assert report["gate"]["positions_count"] == 2
    gate_policy(report["gate"])
    assert field(report["gate"], "unverified_price_time_count") == 2
    assert field(report, "time_review_count") == 1
    assert len(report["candidates"]) == 1


@pytest.mark.parametrize("naive", [False, True])
@pytest.mark.parametrize("daily", [False, True])
def test_additive_assessment_exposes_reference_but_invents_no_observation(sandbox, naive, daily):
    store = sandbox(at=MIDNIGHT.replace(tzinfo=None) if naive else MIDNIGHT,
                    source=FX_LABEL if daily else "synthetic:unknown")
    before = financial_snapshot(store)
    report = read_report(store)
    assert financial_snapshot(store) == before
    gate_policy(report["gate"])
    candidate, = report["candidates"]
    unverified_assessment(field(candidate, "price_time"),
                          kind="daily_reference_candidate" if daily else "unknown")
    assert candidate["current_priced_at"] in {"2025-06-13T00:00:00Z", "2025-06-13T00:00:00+00:00"}


def test_actual_eur_identity_remains_positive_without_a_market_quote(sandbox):
    store = sandbox(asset="EUR", with_price=False)
    before = financial_snapshot(store)
    report = read_report(store)
    assert report["strict_ready"] is True and report["gate"]["strict_ready"] is True
    candidate, = report["candidates"]
    assert candidate["asset"] == "EUR" and Decimal(candidate["current_price_eur"]) == 1
    assert candidate["current_price_source"] == "fiat:EUR"
    assert not store.list_price_points() and financial_snapshot(store) == before


def test_eur_assessment_has_no_fabricated_epoch_observation(sandbox):
    store = sandbox(asset="EUR", with_price=False)
    report = read_report(store)
    gate_policy(report["gate"])
    assert field(report["gate"], "unverified_price_time_count") == 0
    assert field(report, "time_review_count") == 0
    assessment = field(report["candidates"][0], "price_time")
    assert assessment["status"] == "fixed_eur_identity" and assessment["strict_eligible"] is True
    assert assessment["reference_kind"] == "fixed_identity"
    for name in ("observed_at", "period_start", "period_end", "price_published_at", "fx_published_at",
                 "valuation_method_id", "valuation_method_version", "price_evidence_ref", "fx_evidence_ref"):
        assert assessment[name] is None


@pytest.mark.parametrize("asset,value,source", [
    ("EUR", "1", "synthetic:eur-market"), ("EUR", "2", "fiat:EUR"),
    ("BTC", "1", "fiat:EUR"), ("USDC", "1", "fiat:EUR"),
])
def test_gate_boundary_checks_asset_value_and_exact_eur_source(sandbox, asset, value, source):
    store = sandbox(asset=asset, with_price=False)
    position = PortfolioPosition(account="synthetic-wallet", asset=asset, quantity=Decimal("10"),
                                 price_eur=Decimal(value), value_eur=Decimal(value) * 10,
                                 priced_at=MIDNIGHT, price_source=source)
    before = financial_snapshot(store)
    gate = DivorceEqualizationService(store)._valuation_gate([position], AT, Decimal("1"))
    assert financial_snapshot(store) == before
    assert not gate.strict_ready, f"GEGENBELEG: Gate akzeptiert falsche EUR-Identitaet {asset}/{value}/{source}"


def test_eur_identity_is_timeless_even_with_epoch_reference(sandbox):
    store = sandbox(asset="EUR", with_price=False)
    position = PortfolioPosition(account="synthetic-wallet", asset="EUR", quantity=Decimal("10"),
                                 price_eur=Decimal("1"), value_eur=Decimal("10"), price_source="fiat:EUR",
                                 priced_at=datetime(1970, 1, 1, tzinfo=timezone.utc))
    gate = DivorceEqualizationService(store)._valuation_gate([position], AT, Decimal("1"))
    assert gate.strict_ready, "VERTRAGSABWEICHUNG: echte EUR-Identitaet darf nicht als alter Marktkurs verworfen werden"


@pytest.mark.parametrize("kind", ["missing", "future", "zero", "negative", "derived"])
def test_existing_conservative_price_guards_remain_closed(sandbox, kind):
    store = sandbox(with_price=kind != "missing", value={"zero": "0", "negative": "-1"}.get(kind, "100"),
                    source="derived:event_quote" if kind == "derived" else "synthetic:unknown",
                    at=AT + timedelta(seconds=1) if kind == "future" else MIDNIGHT)
    before = financial_snapshot(store)
    report = read_report(store)
    assert not report["strict_ready"] and not report["gate"]["strict_ready"]
    assert financial_snapshot(store) == before


def test_future_position_cannot_open_gate_at_boundary(sandbox):
    store = sandbox(with_price=False)
    position = PortfolioPosition(account="synthetic-wallet", asset="BTC", quantity=Decimal("1"),
                                 price_eur=Decimal("100"), value_eur=Decimal("100"), price_source="synthetic:unknown",
                                 priced_at=AT + timedelta(seconds=1))
    gate = DivorceEqualizationService(store)._valuation_gate([position], AT, Decimal("1"))
    assert not gate.strict_ready, "GEGENBELEG: Gate-Grenze akzeptiert zukuenftigen Referenzzeitpunkt"


def test_existing_token_acceptance_never_supplies_missing_price_time(sandbox):
    store = sandbox(asset="SYNTHRISK", source=FX_LABEL)
    with store.connect() as con:
        con.execute("""insert into jupiter_token_metadata_cache
            (mint, symbol, name, decimals, token_program, is_verified, organic_score,
             organic_score_label, holder_count, liquidity_usd, usd_price, market_cap_usd,
             risk_status, source, discovered_sources_json, refreshed_at)
            values (?, 'SYNTHRISK', 'Synthetic Risk', 2, null, false, 1,
                    'low', 1, 1, 1, 1, 'spam_review', 'synthetic', '[]', ?)""", [MINT, AT])
    before = financial_snapshot(store)
    decision, _ = StichtagTokenValuationService(store).accept_same_day_valuation(
        asset="SYNTHRISK", as_of_date=date(2025, 6, 13), price_eur=Decimal("100"),
        price_source=FX_LABEL, evidence_ref="synthetic:token-identity-only",
        actor="synthetic-test", rationale="Tokenannahme allein ist kein Preiszeitbeleg.")
    assert financial_snapshot(store) == before
    reviews = [row.model_dump(mode="json") for row in store.list_review_decisions()]
    report = read_report(store)
    assert financial_snapshot(store) == before
    assert [row.model_dump(mode="json") for row in store.list_review_decisions()] == reviews
    candidate, = report["candidates"]
    assert candidate["token_review_status"] == "accepted" and candidate["token_review_decision_id"] == decision.decision_id
    assert not report["strict_ready"], "GEGENBELEG: bestehende Tokenannahme ueberwindet fehlenden Zeitbeleg"
    assert report["gate"]["accepted_review_asset_count"] == 1
    assert field(report["gate"], "unverified_price_time_count") == 1
    assert field(report, "time_review_count") == 1
    assert candidate["status"] == "time_review"


def test_gate_reading_preserves_nonempty_price_and_tax_rows(sandbox):
    store = sandbox(asset="EUR", with_price=False)
    store.add_canonical_events([
        CanonicalEventCreate(source="synthetic-temporal", source_ref="buy", account="synthetic-trading",
                             event_time=AT - timedelta(days=1), event_type="trade", asset="BTC",
                             quantity=Decimal("1"), quote_asset="EUR", quote_quantity=Decimal("20")),
        CanonicalEventCreate(source="synthetic-temporal", source_ref="sell", account="synthetic-trading",
                             event_time=AT - timedelta(minutes=30), event_type="trade", asset="BTC",
                             quantity=Decimal("-0.5"), quote_asset="EUR", quote_quantity=Decimal("30")),
    ])
    store.add_price_point(PricePointCreate(asset="BTC", price_eur=Decimal("100"), priced_at=MIDNIGHT,
                                         source="synthetic:unknown"))
    TaxService(store).rebuild_fifo()
    BalanceLedgerBuilder(store).rebuild()
    before = financial_snapshot(store)
    assert before["tax_lines"] and before["price_ledger"], "Probe braucht echte synthetische Steuer- und Preiszeilen"
    for surface in ("service", "api"):
        read_report(store, surface)
        assert financial_snapshot(store) == before


def test_legacy_gate_model_does_not_default_to_the_new_policy():
    legacy = DivorceValuationGate(valuation_at=AT, strict_ready=True, status="strict_ready").model_dump(mode="json")
    assert field(legacy, "price_time_policy_id") is None
    assert field(legacy, "price_time_policy_version") is None
    assert field(legacy, "unverified_price_time_count") == 0


def write_synthetic_run(store, root, policies):
    """Gueltiges altes Reportformat; kein echter FIFO-/Run-Auftrag wird gestartet."""
    cutoff = AT - timedelta(days=1)
    summary = DivorceEqualizationService(store).summary(cutoff_at=cutoff, valuation_at=AT)
    run_id = "valuation-synthetic-temporal-acceptance"
    run_dir = root / run_id
    artifact = run_dir / "valuation_run.json"
    latest = root / "latest_valuation_gate.json"
    report = DivorceValuationRunReport(
        run_id=run_id, generated_at=AT, status="strict_ready", strict_ready=True,
        cutoff_at=cutoff, valuation_at=AT, materiality_threshold_eur=Decimal("1"),
        material_delta_threshold_eur=Decimal("0.01"),
        cutoff_price_gate=summary.cutoff_price_gate, valuation_price_gate=summary.valuation_price_gate,
        semantic_sha256="a" * 64, artifact_path=str(artifact), latest_artifact_path=str(latest),
        methodology="Synthetisches Archiv einer frueheren Read-Policy, keine fachliche Freigabe.", summary=summary,
    ).model_dump(mode="json")
    for label in ("cutoff", "valuation"):
        for container in (report, report["summary"]):
            gate = container[label + "_price_gate"]
            gate.update(strict_ready=True, status="strict_ready")
            for key in ("price_time_policy_id", "price_time_policy_version", "unverified_price_time_count"):
                gate.pop(key, None)
            if policies[label] is not None:
                gate.update(price_time_policy_id=policies[label][0], price_time_policy_version=policies[label][1],
                            unverified_price_time_count=0)
    run_dir.mkdir(parents=True)
    raw = json.dumps(report, sort_keys=True, indent=2).encode("utf-8")
    artifact.write_bytes(raw)
    latest.write_bytes(raw)
    return run_id, raw, artifact, latest


@pytest.mark.parametrize("policies", [
    {"cutoff": None, "valuation": None},
    {"cutoff": ("legacy-same-day", 1), "valuation": (POLICY, 1)},
    {"cutoff": (POLICY, 1), "valuation": (POLICY, 99)},
    {"cutoff": (POLICY, 1), "valuation": None},
], ids=["legacy-without-policy", "wrong-cutoff-id", "wrong-valuation-version", "half-current"])
def test_legacy_latest_is_not_current_but_get_preserves_the_archive(sandbox, tmp_path, policies):
    store = sandbox(asset="EUR", with_price=False)
    root = tmp_path / "synthetic-valuation-runs"
    before = financial_snapshot(store)
    run_id, raw, artifact, latest_path = write_synthetic_run(store, root, policies)
    service = DivorceValuationRunService(store, artifact_root=root,
                                       wallet_fifo_artifact_root=tmp_path / "unused-fifo")
    archive = service.get(run_id)
    assert archive is not None and archive.run_id == run_id and archive.strict_ready
    current = service.latest()
    assert artifact.read_bytes() == latest_path.read_bytes() == raw
    assert financial_snapshot(store) == before
    assert current is None, "GEGENBELEG: alter/falsch versionierter streng-positiver Lauf gilt als aktueller Lauf"
    for label in ("cutoff", "valuation"):
        if policies[label] is None:
            gate = getattr(archive, label + "_price_gate")
            assert getattr(gate, "price_time_policy_id", None) is None
            assert getattr(gate, "price_time_policy_version", None) is None


def test_matching_policy_run_remains_readable_without_archive_rewrite(sandbox, tmp_path):
    store = sandbox(asset="EUR", with_price=False)
    root = tmp_path / "synthetic-valuation-runs"
    run_id, raw, artifact, latest_path = write_synthetic_run(
        store, root, {"cutoff": (POLICY, 1), "valuation": (POLICY, 1)})
    service = DivorceValuationRunService(store, artifact_root=root,
                                       wallet_fifo_artifact_root=tmp_path / "unused-fifo")
    current, archive = service.latest(), service.get(run_id)
    assert current is not None and archive is not None and current.run_id == archive.run_id == run_id
    assert current.model_dump(mode="json") == archive.model_dump(mode="json")
    assert artifact.read_bytes() == latest_path.read_bytes() == raw
