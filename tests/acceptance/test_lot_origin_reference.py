"""Unabhaengige, rein synthetische Herkunftsreferenz ohne Rechenoracle.

100 HNT, Basis 90 -> Eigenuebertrag -> 1 NEW -> Verkauf 0.4 fuer 60:
Basis 36, Gewinn 24, Rest 0.6 / Basis 54. Herkunft ist keine Freigabe.
"""

from datetime import datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import shutil
import socket

import duckdb
import pytest

from steuerreport_v2.contracts.bmf_event_evidence import BmfFifoEventEvidenceRunRequest
from steuerreport_v2.contracts.bmf_fifo_staging import (
    BmfCombinedFifoEventRow,
    BmfFifoStagingRunRequest,
)
from steuerreport_v2.contracts.events import CanonicalEvent, CanonicalEventCreate
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.tax import TaxLine, TaxLot
from steuerreport_v2.contracts.tax_wallet_fifo import (
    WalletFifoPreviewLine,
    WalletFifoPreviewLot,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.bmf_event_evidence import BmfFifoEventEvidenceService
from steuerreport_v2.domain.bmf_fifo_staging import BmfCombinedFifoStagingService
from steuerreport_v2.domain.business_inventory import (
    BusinessRewardInventoryReviewService,
)
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService
from steuerreport_v2.domain.tax_years import TaxYearService


ROOT = Path("/tmp/sr-origin-20261028-independent")
ACQUIRED = datetime(2024, 1, 10, 12, tzinfo=timezone.utc)
DISPOSED = datetime(2024, 7, 1, 12, tzinfo=timezone.utc)
AS_OF = datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


@pytest.fixture(scope="session", autouse=True)
def frozen_consumer_sources(request):
    repo = Path(__file__).resolve().parents[2]
    names = (
        "domain/lot_origin.py",
        "domain/business_inventory.py",
        "domain/bmf_fifo_staging.py",
        "domain/bmf_event_evidence.py",
        "domain/review.py",
        "domain/tax.py",
        "domain/tax_wallet_fifo.py",
        "domain/token_conversion.py",
        "contracts/business_inventory.py",
        "contracts/bmf_fifo_staging.py",
        "contracts/bmf_event_evidence.py",
    )

    def hashes():
        return {
            name: hashlib.sha256(path.read_bytes()).hexdigest()
            if path.is_file()
            else None
            for name in names
            for path in [repo / "src/steuerreport_v2" / name]
        }

    before = hashes()
    yield
    after = hashes()
    xml = request.config.getoption("xmlpath")
    name = Path(xml).stem if xml else "reference"
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / f"{name}-source-freeze.json").write_text(
        json.dumps(
            {
                "before": before,
                "after": after,
                "unchanged": before == after,
                "retained_bytes": _budget(),
            },
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    assert before == after, "Consumerquellen waehrend Referenzlauf veraendert"


def _budget():
    size = sum(p.stat().st_size for p in ROOT.rglob("*") if p.is_file())
    assert size < 500 * 1024 * 1024, f"Eigenes Tmpbudget ueberschritten: {size}"
    return size


@pytest.fixture
def case(tmp_path, monkeypatch, request):
    assert tmp_path.resolve().is_relative_to(ROOT)
    config = tmp_path / "private-configs"
    config.mkdir()
    profile = tmp_path / "profile.json"
    profile.write_text("{}\n")
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", str(profile))
    monkeypatch.setenv("STEUERREPORT_PRIVATE_CONFIG_DIR", str(config))
    monkeypatch.setenv("STEUERREPORT_V2_DB", str(tmp_path / "synthetic.duckdb"))
    original_connect = duckdb.connect

    def guarded_connect(database=":memory:", *args, **kwargs):
        if str(database) != ":memory:":
            assert Path(database).resolve().is_relative_to(tmp_path.resolve())
        return original_connect(database, *args, **kwargs)

    def blocked(*args, **kwargs):
        raise OSError("Lot-Referenz: Netzwerk gesperrt")

    monkeypatch.setattr(duckdb, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    _budget()
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    store.health()
    yield tmp_path, config, store
    if getattr(request.node, "_steuerreport_call_passed", False):
        for path in sorted(
            tmp_path.rglob("*"), key=lambda p: len(p.parts), reverse=True
        ):
            if path.is_file() and (
                path.suffix in {".duckdb", ".wal"} or path.name.endswith(".prepared")
            ):
                path.unlink()
            elif path.is_dir() and path.name.endswith(".prepared"):
                shutil.rmtree(path)
    _budget()


def _event(event_id, *, asset="HNT", kind="mining", account="A", at=ACQUIRED):
    return CanonicalEvent(
        event_id=event_id,
        source="helium",
        event_time=at,
        event_type=kind,
        asset=asset,
        quantity=Decimal("100"),
        account=account,
    )


def _objects():
    root = TaxLot(
        lot_id="reward-lot",
        asset="HNT",
        acquired_at=ACQUIRED,
        quantity_total=Decimal("100"),
        quantity_remaining=Decimal("0"),
        cost_basis_eur_total=Decimal("90"),
        source_event_id="reward",
    )
    moved = TaxLot(
        lot_id="transfer-lot",
        asset="HNT",
        acquired_at=ACQUIRED,
        quantity_total=Decimal("100"),
        quantity_remaining=Decimal("0"),
        cost_basis_eur_total=Decimal("90"),
        source_event_id="transfer",
        origin_lot_id=root.lot_id,
    )
    current = TaxLot(
        lot_id="conversion-lot",
        asset="NEW",
        acquired_at=ACQUIRED,
        quantity_total=Decimal("1"),
        quantity_remaining=Decimal("0.6"),
        cost_basis_eur_total=Decimal("90"),
        source_event_id="conversion",
        origin_lot_id=moved.lot_id,
    )
    line = TaxLine(
        tax_line_id="sale-line",
        asset="NEW",
        acquired_at=ACQUIRED,
        disposed_at=DISPOSED,
        quantity=Decimal("0.4"),
        acquisition_cost_eur=Decimal("36"),
        disposal_proceeds_eur=Decimal("60"),
        gain_loss_eur=Decimal("24"),
        holding_days=173,
        source_event_id="sale",
        lot_id=current.lot_id,
        acquisition_source_event_id="conversion",
        origin_lot_id=moved.lot_id,
    )
    events = [
        _event("reward"),
        _event("transfer", kind="transfer", account="B"),
        _event("conversion", kind="transfer", asset="NEW", account="B"),
        _event("sale", kind="trade", asset="NEW", account="B", at=DISPOSED),
    ]
    return [root, moved, current], events, line


def _persist(store, lots, events, lines):
    with store.connect() as con:
        for event in events:
            con.execute(
                "insert into canonical_events "
                "(event_id,source,event_time,event_type,asset,quantity,account,confidence) "
                "values (?,?,?,?,?,?,?,?)",
                [
                    event.event_id,
                    event.source,
                    event.event_time,
                    event.event_type,
                    event.asset,
                    event.quantity,
                    event.account,
                    Decimal("1"),
                ],
            )
        for lot in lots:
            con.execute(
                "insert into tax_lots (lot_id,asset,acquired_at,quantity_total,"
                "quantity_remaining,cost_basis_eur_total,source_event_id,origin_lot_id,created_at) "
                "values (?,?,?,?,?,?,?,?,?)",
                [
                    lot.lot_id,
                    lot.asset,
                    lot.acquired_at,
                    lot.quantity_total,
                    lot.quantity_remaining,
                    lot.cost_basis_eur_total,
                    lot.source_event_id,
                    lot.origin_lot_id,
                    AS_OF,
                ],
            )
        for line in lines:
            con.execute(
                "insert into tax_lines (tax_line_id,asset,acquired_at,disposed_at,quantity,"
                "acquisition_cost_eur,disposal_proceeds_eur,gain_loss_eur,holding_days,"
                "source_event_id,lot_id,acquisition_source_event_id,origin_lot_id,created_at) "
                "values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    line.tax_line_id,
                    line.asset,
                    line.acquired_at,
                    line.disposed_at,
                    line.quantity,
                    line.acquisition_cost_eur,
                    line.disposal_proceeds_eur,
                    line.gain_loss_eur,
                    line.holding_days,
                    line.source_event_id,
                    line.lot_id,
                    line.acquisition_source_event_id,
                    line.origin_lot_id,
                    AS_OF,
                ],
            )


def _snapshot(store):
    with store.connect() as con:
        return {
            table: con.execute(f"select * from {table} order by 1").fetchall()
            for table in (
                "tax_lots",
                "tax_lines",
                "canonical_events",
                "tax_run_summaries",
                "raw_objects",
                "raw_import_batches",
                "price_ledger",
            )
        }


@pytest.mark.parametrize("assets", [("HNT",), ("NEW",), None])
def test_stored_reward_root_survives_transfer_conversion_and_asset_filter(case, assets):
    _, _, store = case
    lots, events, line = _objects()
    _persist(store, lots, events, [line])
    before = _snapshot(store)
    report = BusinessRewardInventoryReviewService(store).review(
        **({"assets": assets} if assets else {})
    )
    assert _snapshot(store) == before
    assert report.total_tax_lines_count == 1
    assert report.potential_business_tax_lines_count == 1
    assert report.strict_ready is False
    assert report.potential_business_acquisition_cost_eur == Decimal("36")
    assert report.potential_business_proceeds_eur == Decimal("60")
    assert report.potential_business_gain_loss_eur == Decimal("24")
    assert len(report.rows) == 1
    row = report.rows[0]
    assert row.asset == "NEW"
    assert row.quantity_disposed == Decimal("0.4")
    assert row.sample_origin_event_id == "reward"
    assert row.sample_direct_event_id == "conversion"
    assert row.lineage_status == "carried"
    assert row.sample_lot_path == ["conversion-lot", "transfer-lot", "reward-lot"]
    assert row.blocks_private_fifo_classification is True


def _event_digest(event):
    # Nur Bindungsprotokoll, kein fachliches Erwartungsoracle.
    body = event.model_dump(mode="python")
    body["event_time"] = event.event_time.replace(tzinfo=timezone.utc).isoformat()
    with localcontext() as context:
        context.prec = 80
        for key, value in body.items():
            if isinstance(value, Decimal):
                body[key] = str(value.normalize())
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _replay_inputs(case, *, convert=True, root_kind="mining"):
    path, config, store = case
    batch = store.create_import_batch(
        ImportBatchCreate(source="helium", filename="synthetic-origin.json")
    )
    specs = [
        ("reward", ACQUIRED, root_kind, "HNT", "100", "A", None, "90"),
        (
            "out",
            datetime(2024, 3, 1, 12, tzinfo=timezone.utc),
            "transfer",
            "HNT",
            "-100",
            "A",
            "own-transfer",
            None,
        ),
        (
            "in",
            datetime(2024, 3, 1, 12, tzinfo=timezone.utc),
            "transfer",
            "HNT",
            "100",
            "B",
            "own-transfer",
            None,
        ),
    ]
    if convert:
        specs += [
            (
                "convert-out",
                datetime(2024, 6, 1, 12, tzinfo=timezone.utc),
                "transfer",
                "HNT",
                "-100",
                "B",
                "conversion",
                None,
            ),
            (
                "convert-in",
                datetime(2024, 6, 1, 12, tzinfo=timezone.utc),
                "transfer",
                "NEW",
                "1",
                "B",
                "conversion",
                None,
            ),
        ]
    specs.append(
        (
            "sale",
            DISPOSED,
            "trade",
            "NEW" if convert else "HNT",
            "-0.4" if convert else "-40",
            "B",
            "sale-tx",
            "60",
        )
    )
    by_role = {}
    raw_by_role = {}
    for n, (role, at, kind, asset, quantity, account, tx_id, eur) in enumerate(
        specs, 1
    ):
        raw_body = {"role": role, "synthetic": True}
        if role.startswith("convert-"):
            raw_body["conversion_kind"] = "redenomination"
        payload = json.dumps(raw_body, sort_keys=True)
        raw = store.add_raw_object(
            batch.batch_id, RawObjectCreate(row_number=n, payload_json=payload)
        )
        event = store.add_canonical_events(
            [
                CanonicalEventCreate(
                    source="helium",
                    source_ref=f"independent:{role}",
                    event_time=at,
                    event_type=kind,
                    asset=asset,
                    quantity=Decimal(quantity),
                    account=account,
                    tx_id=tx_id,
                    raw_object_id=raw.raw_object_id,
                    quote_asset="EUR" if eur else None,
                    quote_quantity=Decimal(eur) if eur else None,
                )
            ]
        )[0]
        by_role[role] = event
        raw_by_role[role] = payload
    if convert:
        evidence = config / "synthetic-conversion.txt"
        evidence.write_text(
            "Synthetischer Beleg: 100 HNT entsprechen 1 NEW. Keine steuerliche Freigabe.\n"
        )
        mapping = {
            "mapping_id": "independent-100-to-1",
            "enabled": True,
            "kind": "redenomination",
            "source_event_id": by_role["convert-out"].event_id,
            "target_event_id": by_role["convert-in"].event_id,
            "source_event_sha256": _event_digest(by_role["convert-out"]),
            "target_event_sha256": _event_digest(by_role["convert-in"]),
            "source_raw_sha256": hashlib.sha256(
                raw_by_role["convert-out"].encode()
            ).hexdigest(),
            "target_raw_sha256": hashlib.sha256(
                raw_by_role["convert-in"].encode()
            ).hexdigest(),
            "ratio_numerator": "1",
            "ratio_denominator": "100",
            "tax_treatment": "carry_original_basis_and_date",
            "actor": "independent-synthetic",
            "rationale": "Reine Referenzpruefung ohne produktive Methodenfreigabe.",
            "evidence_ref": evidence.name,
            "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            "acknowledge_same_economic_asset": True,
            "acknowledge_no_automatic_tax_approval": True,
        }
        (config / "token_conversion_mappings.json").write_text(
            json.dumps({"schema_version": 1, "mappings": [mapping]})
        )
    TaxService(store).rebuild_fifo()
    staging = BmfCombinedFifoStagingService(store, artifact_root=path / "staging")
    return store, staging, by_role


def test_real_bmf_preview_keeps_helium_root_and_literal_partial_sale(case):
    store, staging, events = _replay_inputs(case)
    before = _snapshot(store)
    income_before = TaxYearService(store).income_report(2024).model_dump(mode="json")
    assert Decimal(income_before["total_income_eur"]) == Decimal("90")
    assert income_before["events_count"] == 1
    state = WalletFifoPreviewService(store).replay(as_of=AS_OF)
    lines = [line for line in state.tax_lines if line.asset == "NEW"]
    assert len(lines) == 1
    assert (
        lines[0].quantity,
        lines[0].acquisition_cost_eur,
        lines[0].disposal_proceeds_eur,
        lines[0].gain_loss_eur,
    ) == (
        Decimal("0.4"),
        Decimal("36"),
        Decimal("60"),
        Decimal("24"),
    )
    remaining = [lot for lot in state.all_lots if lot.asset == "NEW"]
    assert len(remaining) == 1
    assert remaining[0].quantity_remaining == Decimal("0.6")
    assert remaining[0].cost_basis_eur_total == Decimal("90")
    assert (
        remaining[0].cost_basis_eur_total
        * remaining[0].quantity_remaining
        / remaining[0].quantity_total
    ) == Decimal("54")
    report = staging.run(BmfFifoStagingRunRequest(years=[2024], as_of=AS_OF))
    assert _snapshot(store) == before
    income_after = TaxYearService(store).income_report(2024).model_dump(mode="json")
    income_before.pop("generated_at", None)
    income_after.pop("generated_at", None)
    assert income_before == income_after
    for totals in (
        report.active_global,
        report.received_first_global,
        report.active_wallet,
        report.received_first_wallet,
    ):
        assert totals.tax_lines_count == 1
        assert totals.acquisition_cost_eur == Decimal("36")
        assert totals.disposal_proceeds_eur == Decimal("60")
        assert totals.gain_loss_eur == Decimal("24")
    assert report.strict_ready is False
    assert report.status == "blocked"
    assert report.potential_business_inventory_tax_lines_count == 1
    assert report.origin_trace_policy == "linked_lot_origin_v1"
    sale = next(
        row
        for row in report.top_events
        if row.disposal_event_id == events["sale"].event_id
    )
    assert sale.acquisition_source_event_ids == [events["reward"].event_id]
    assert sale.origin_classifications == ["potential_business_inventory"]
    assert sale.direct_acquisition_event_ids == [events["convert-in"].event_id]
    assert sale.lineage_issue_codes == []


def test_zero_eur_delta_origin_review_is_not_dropped_from_event_evidence(case):
    path, _, _ = case
    store, staging, events = _replay_inputs(case, convert=False)
    preview = staging.run(BmfFifoStagingRunRequest(years=[2024], as_of=AS_OF))
    assert preview.combined_delta_eur == Decimal("0")
    assert len(preview.top_events) == 1
    before = _snapshot(store)
    evidence = BmfFifoEventEvidenceService(
        store,
        artifact_root=path / "evidence",
        staging_service=staging,
    ).run(BmfFifoEventEvidenceRunRequest())
    assert _snapshot(store) == before
    assert evidence.strict_ready is False
    assert evidence.selected_discrepancy_rows_count == 1
    assert len(evidence.discrepancy_rows) == 1
    row = evidence.discrepancy_rows[0]
    assert row.disposal_event_id == events["sale"].event_id
    assert row.combined_delta_eur == Decimal("0")
    assert row.status in {"review", "blocked"}


def test_legacy_staging_without_origin_policy_is_not_silently_current(case):
    path, _, _ = case
    store, staging, _ = _replay_inputs(case, convert=False)
    staging.run(BmfFifoStagingRunRequest(years=[2024], as_of=AS_OF))
    latest = path / "staging/latest.json"
    legacy = json.loads(latest.read_text())
    legacy.pop("origin_trace_policy", None)
    legacy_text = json.dumps(legacy, sort_keys=True, indent=2) + "\n"
    latest.write_text(legacy_text)
    (path / "legacy-staging-original.json").write_text(legacy_text)
    before = _snapshot(store)
    assert staging.latest().origin_trace_policy == "legacy_direct_origin_v1"
    report = BmfFifoEventEvidenceService(
        store,
        artifact_root=path / "legacy-evidence",
        staging_service=staging,
    ).run(BmfFifoEventEvidenceRunRequest())
    assert report.staging_matches_current_input is False
    assert report.staging_matches_current_tax_component is True
    assert report.strict_ready is False
    assert report.status in {"review", "blocked"}
    assert any("Herkunftszuordnung" in finding for finding in report.findings)
    assert latest.read_text() == legacy_text
    assert _snapshot(store) == before


def test_event_evidence_lineage_only_zero_delta_blocks_even_with_ready_raw_events(case):
    path, _, _ = case
    store, staging, events = _replay_inputs(case, convert=False, root_kind="trade")
    for at, value in ((ACQUIRED, "0.9"), (DISPOSED, "1.5")):
        store.add_price_point(
            PricePointCreate(
                asset="HNT",
                priced_at=at,
                price_eur=Decimal(value),
                source="independent-synthetic-reference",
            )
        )
    staging.run(BmfFifoStagingRunRequest(years=[2024], as_of=AS_OF))
    latest = path / "staging/latest.json"
    artifact = json.loads(latest.read_text())
    # Isolierte Artefakt-Konsumergrenze, kein vorgetaeuschter Resolverfehler.
    row = BmfCombinedFifoEventRow(
        year=2024,
        asset="HNT",
        disposal_event_id=events["sale"].event_id,
        disposed_at=DISPOSED,
        acquisition_source_event_ids=[events["reward"].event_id],
        direct_acquisition_event_ids=[events["reward"].event_id],
        origin_classifications=["non_reward_origin"],
        lineage_issue_codes=["missing_origin_lot"],
    )
    artifact["top_events"] = [row.model_dump(mode="json")]
    text = json.dumps(artifact, sort_keys=True, indent=2) + "\n"
    latest.write_text(text)
    (path / "lineage-only-staging-original.json").write_text(text)
    before = _snapshot(store)
    report = BmfFifoEventEvidenceService(
        store,
        artifact_root=path / "lineage-evidence",
        staging_service=staging,
    ).run(BmfFifoEventEvidenceRunRequest())
    assert _snapshot(store) == before
    assert latest.read_text() == text
    assert report.selected_discrepancy_rows_count == 1
    assert report.blocked_events_count == 0
    assert report.strict_ready is False
    assert report.status == "blocked"
    assert report.discrepancy_rows[0].lineage_issue_codes == ["missing_origin_lot"]
    assert "lot_origin_unresolved" in report.discrepancy_rows[0].issue_codes
    assert report.discrepancy_rows[0].status == "blocked"
    group = next(
        group for group in report.groups if group.scope_key == "hnt_solana_2024"
    )
    assert group.status == "blocked"
    assert "lot_origin_unresolved" in group.issue_codes


def _broken_objects(mode):
    lots, events, line = _objects()
    if mode == "missing_current":
        lots.pop()
    elif mode == "orphan":
        lots[1].origin_lot_id = "absent-parent"
    elif mode == "cycle":
        lots[0].origin_lot_id = lots[2].lot_id
    elif mode == "line_event_conflict":
        line.acquisition_source_event_id = "reward"
    elif mode == "line_lot_conflict":
        line.origin_lot_id = "reward-lot"
    elif mode == "acquired_at_conflict":
        line.acquired_at = datetime(2024, 1, 11, 12, tzinfo=timezone.utc)
    elif mode == "parent_acquired_at_conflict":
        lots[0].acquired_at = datetime(2024, 1, 9, 12, tzinfo=timezone.utc)
    elif mode == "missing_root_event":
        events.pop(0)
    elif mode == "duplicate_lot":
        lots.append(lots[0].model_copy())
    elif mode == "duplicate_event":
        events.append(events[0].model_copy())
    else:
        raise AssertionError(mode)
    return lots, events, line


BROKEN_STORED = (
    "missing_current",
    "orphan",
    "cycle",
    "line_event_conflict",
    "line_lot_conflict",
    "acquired_at_conflict",
    "parent_acquired_at_conflict",
    "missing_root_event",
)


@pytest.mark.parametrize("mode", BROKEN_STORED)
def test_stored_broken_lineage_never_becomes_private_or_loses_amounts(case, mode):
    _, _, store = case
    lots, events, line = _broken_objects(mode)
    _persist(store, lots, events, [line])
    before = _snapshot(store)
    report = BusinessRewardInventoryReviewService(store).review(assets=("NEW",))
    assert _snapshot(store) == before
    assert report.total_tax_lines_count == 1
    assert report.strict_ready is False
    assert report.unresolved_tax_lines_count == 1
    assert len(report.rows) == 1
    row = report.rows[0]
    assert row.lineage_status == "unresolved"
    assert row.lineage_reason
    assert row.sample_origin_event_id is None
    assert row.blocks_private_fifo_classification is True
    assert (
        row.quantity_disposed,
        row.acquisition_cost_eur,
        row.disposal_proceeds_eur,
        row.gain_loss_eur,
    ) == (
        Decimal("0.4"),
        Decimal("36"),
        Decimal("60"),
        Decimal("24"),
    )


@pytest.mark.parametrize("carried", [True, False])
def test_stored_unknown_root_type_is_review_not_non_reward_clearance(case, carried):
    _, _, store = case
    lots, events, line = _objects()
    events[0].event_type = "unknown"
    if not carried:
        lots = [lots[0]]
        line = line.model_copy(
            update={
                "asset": "HNT",
                "lot_id": "reward-lot",
                "origin_lot_id": None,
                "acquisition_source_event_id": "reward",
            }
        )
    _persist(store, lots, events, [line])
    report = BusinessRewardInventoryReviewService(store).review(assets=("NEW", "HNT"))
    assert report.total_tax_lines_count == 1
    assert report.strict_ready is False
    assert report.unresolved_tax_lines_count == 1
    assert report.rows[0].classification != "non_reward_origin"
    assert report.rows[0].blocks_private_fifo_classification is True


@pytest.mark.parametrize("mode", ["missing_current", "orphan", "cycle"])
def test_review_gate_reads_all_stored_lines_and_blocks_unresolved_origin(case, mode):
    _, _, store = case
    lots, events, line = _broken_objects(mode)
    _persist(store, lots, events, [line])
    before = _snapshot(store)
    gate = ReviewService(store).gate()
    assert _snapshot(store) == before
    issues = [issue for issue in gate.issues if issue.code == "lot_origin_unresolved"]
    assert len(issues) == 1
    assert issues[0].blocks_export is True
    assert gate.allow_export is False


def test_stored_direct_eur_buy_is_not_fabricated_as_business_reward(case):
    _, _, store = case
    lots, _, line = _objects()
    lot = lots[2].model_copy(
        update={"source_event_id": "eur-buy", "origin_lot_id": None}
    )
    line = line.model_copy(
        update={"acquisition_source_event_id": "eur-buy", "origin_lot_id": None}
    )
    event = _event("eur-buy", kind="trade", asset="NEW").model_copy(
        update={
            "source": "synthetic-exchange",
            "quote_asset": "EUR",
            "quote_quantity": Decimal("90"),
            "quantity": Decimal("1"),
        }
    )
    _persist(store, [lot], [event], [line])
    before = _snapshot(store)
    report = BusinessRewardInventoryReviewService(store).review(assets=("NEW",))
    assert _snapshot(store) == before
    assert report.total_tax_lines_count == 1
    assert report.potential_business_tax_lines_count == 0
    assert report.unresolved_tax_lines_count == 0
    assert report.rows[0].classification == "non_reward_origin"
    assert report.rows[0].lineage_status == "direct"
    assert report.rows[0].sample_origin_event_id == "eur-buy"


def test_stored_two_lines_one_root_do_not_duplicate_origin_or_totals(case):
    _, _, store = case
    lots, events, line = _objects()
    first = line.model_copy(
        update={
            "quantity": Decimal("0.1"),
            "acquisition_cost_eur": Decimal("9"),
            "disposal_proceeds_eur": Decimal("15"),
            "gain_loss_eur": Decimal("6"),
        }
    )
    second = line.model_copy(
        update={
            "tax_line_id": "sale-line-2",
            "quantity": Decimal("0.3"),
            "acquisition_cost_eur": Decimal("27"),
            "disposal_proceeds_eur": Decimal("45"),
            "gain_loss_eur": Decimal("18"),
        }
    )
    _persist(store, lots, events, [first, second])
    before = _snapshot(store)
    for _ in range(2):
        report = BusinessRewardInventoryReviewService(store).review(
            assets=("NEW", "HNT")
        )
        assert report.total_tax_lines_count == 2
        assert report.potential_business_tax_lines_count == 2
        assert report.potential_business_acquisition_cost_eur == Decimal("36")
        assert report.potential_business_proceeds_eur == Decimal("60")
        assert report.potential_business_gain_loss_eur == Decimal("24")
        assert len(report.rows) == 1
        assert report.rows[0].origin_events_count == 1
        assert report.rows[0].quantity_disposed == Decimal("0.4")
    assert _snapshot(store) == before


def _typed_objects(lots, line, engine):
    if engine == "global":
        return lots, line
    return (
        [
            WalletFifoPreviewLot.model_validate(
                {**lot.model_dump(), "pool_id": "helium:B"}
            )
            for lot in lots
        ],
        WalletFifoPreviewLine.model_validate(
            {**line.model_dump(), "pool_id": "helium:B"}
        ),
    )


@pytest.mark.parametrize("engine", ["global", "wallet"])
def test_resolver_follows_explicit_root_without_mutating_financial_inputs(engine):
    from steuerreport_v2.domain.lot_origin import LotOriginIndex

    lots, events, line = _objects()
    lots, line = _typed_objects(lots, line, engine)
    before = [item.model_dump(mode="json") for item in [*lots, *events, line]]
    index = LotOriginIndex(iter(lots), iter(events))
    trace = index.resolve(line)
    assert trace.status == "carried"
    assert trace.lot_ids == ("conversion-lot", "transfer-lot", "reward-lot")
    assert trace.direct_event_id == "conversion"
    assert trace.origin_event_id == "reward"
    assert trace.origin_asset == "HNT"
    assert trace.reason is None
    assert index.resolve(line) == trace
    with pytest.raises((AttributeError, TypeError)):
        trace.status = "direct"
    assert [item.model_dump(mode="json") for item in [*lots, *events, line]] == before


@pytest.mark.parametrize("engine", ["global", "wallet"])
@pytest.mark.parametrize("mode", [*BROKEN_STORED, "duplicate_lot", "duplicate_event"])
def test_resolver_rejects_ambiguous_or_broken_links(engine, mode):
    from steuerreport_v2.domain.lot_origin import LotOriginIndex

    lots, events, line = _broken_objects(mode)
    lots, line = _typed_objects(lots, line, engine)
    trace = LotOriginIndex(lots, events).resolve(line)
    assert trace.status == "unresolved"
    assert trace.origin_event_id is None
    assert trace.origin_asset is None
    assert trace.reason
    assert len(trace.lot_ids) <= 64


@pytest.mark.parametrize("engine", ["global", "wallet"])
def test_resolver_direct_eur_purchase_is_direct_not_invented_reward(engine):
    from steuerreport_v2.domain.lot_origin import LotOriginIndex

    lots, _, line = _objects()
    current = lots[2].model_copy(
        update={"origin_lot_id": None, "source_event_id": "eur-buy"}
    )
    line = line.model_copy(
        update={"origin_lot_id": None, "acquisition_source_event_id": "eur-buy"}
    )
    events = [_event("eur-buy", asset="NEW", kind="trade")]
    lots, line = _typed_objects([current], line, engine)
    trace = LotOriginIndex(lots, events).resolve(line)
    assert trace.status == "direct"
    assert trace.lot_ids == ("conversion-lot",)
    assert trace.origin_event_id == "eur-buy"
    assert trace.origin_asset == "NEW"
    assert trace.reason is None


def test_resolver_depth_is_bounded_and_large_quantity_is_not_a_heuristic():
    from steuerreport_v2.domain.lot_origin import LotOriginIndex

    lots, events, line = _objects()
    template = lots[0]
    chain = [
        template.model_copy(
            update={
                "lot_id": f"chain-{n}",
                "source_event_id": "reward",
                "origin_lot_id": f"chain-{n + 1}" if n < 64 else None,
                "quantity_total": Decimal("1000000000000000000"),
            }
        )
        for n in range(65)
    ]
    line = line.model_copy(
        update={
            "lot_id": "chain-0",
            "origin_lot_id": "chain-1",
            "acquisition_source_event_id": "reward",
            "asset": "HNT",
            "quantity": Decimal("400000000000000000"),
        }
    )
    trace = LotOriginIndex(chain, events).resolve(line)
    assert trace.status == "unresolved"
    assert trace.origin_event_id is None
    assert trace.reason
    assert len(trace.lot_ids) <= 64
    direct = line.model_copy(update={"lot_id": "chain-64", "origin_lot_id": None})
    trace = LotOriginIndex(chain, events).resolve(direct)
    assert trace.status == "direct"
    assert trace.origin_event_id == "reward"
    assert trace.origin_asset == "HNT"
