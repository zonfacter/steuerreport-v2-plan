"""Zwei feste Herkunftsbeleg-Regressionen; nur synthetische Inputs."""
from datetime import datetime, timezone
from decimal import Decimal

from steuerreport_v2.contracts.bmf_event_evidence import (
    BmfCanonicalEventEvidence, BmfEventSourceEvidence,
)
from steuerreport_v2.contracts.bmf_fifo_staging import BmfCombinedFifoEventRow
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.tax import TaxLine, TaxLot
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.bmf_event_evidence import BmfFifoEventEvidenceService
from steuerreport_v2.domain.lot_origin import LotOriginIndex
from steuerreport_v2.domain.tax import TaxService


D = Decimal
WHEN = datetime(2024, 3, 1, tzinfo=timezone.utc)


def _evidence(key, kind, asset, *, blocked=False):
    return BmfCanonicalEventEvidence(
        event_id=key, event_time=WHEN, source="synthetic", event_type=kind, asset=asset,
        source_evidence=BmfEventSourceEvidence(
            identifier_kind="missing" if blocked else "raw_batch_row",
            status="blocked" if blocked else "ready"),
        status="blocked" if blocked else "ready",
        issue_codes=["missing_raw_evidence"] if blocked else [], evidence_digest="fixture-" + key,
    )


def test_blocked_intermediate_evidence_blocks_discrepancy_and_group():
    row = BmfCombinedFifoEventRow(
        year=2024, asset="JUP", disposal_event_id="sale", disposed_at=WHEN,
        acquisition_source_event_ids=["root"], direct_acquisition_event_ids=["target"],
        origin_classifications=["non_reward_origin"], combined_delta_eur=D("1"),
    )
    evidence = {"sale": _evidence("sale", "trade", "JUP"),
                "root": _evidence("root", "trade", "HNT"),
                "target": _evidence("target", "transfer", "JUP", blocked=True)}
    # These two pure consumers need no store; all evidence states are explicit controls.
    service = object.__new__(BmfFifoEventEvidenceService)
    discrepancy = service._discrepancy_row(row, evidence)
    group = service._group(service._scope_for(row), [row], evidence)
    assert evidence["target"].status == "blocked"
    assert (discrepancy.status, group.status) == ("blocked", "blocked"), (
        "Missing intermediate raw evidence must not become ready merely because root and sale are ready",
        discrepancy.status, discrepancy.issue_codes, group.status, group.issue_codes,
    )


def test_full_ledger_roles_include_prior_year_root_outside_disposal_asset_scope(tmp_path):
    store = DuckDbStore(tmp_path / "prior-year-root.duckdb")
    acquired = datetime(2023, 1, 1, tzinfo=timezone.utc)
    root, target, sale = store.add_canonical_events([
        CanonicalEventCreate(source="synthetic", event_time=acquired, event_type="mining",
                             asset="HNT", quantity=D("100")),
        CanonicalEventCreate(source="synthetic", event_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
                             event_type="transfer", asset="XYZ", quantity=D("1")),
        CanonicalEventCreate(source="synthetic", event_time=WHEN, event_type="trade", asset="XYZ",
                             quantity=D("-0.4"), quote_asset="EUR", quote_quantity=D("120")),
    ])
    lots = [TaxLot(lot_id="root-lot", asset="HNT", acquired_at=acquired, quantity_total=D("100"),
                   quantity_remaining=D("0"), cost_basis_eur_total=D("200"), source_event_id=root.event_id),
            TaxLot(lot_id="carried-lot", asset="XYZ", acquired_at=acquired, quantity_total=D("1"),
                   quantity_remaining=D("0.6"), cost_basis_eur_total=D("200"),
                   source_event_id=target.event_id, origin_lot_id="root-lot")]
    line = TaxLine(tax_line_id="sale-line", asset="XYZ", acquired_at=acquired, disposed_at=WHEN,
                   quantity=D("0.4"), acquisition_cost_eur=D("80"), disposal_proceeds_eur=D("120"),
                   gain_loss_eur=D("40"), holding_days=425, source_event_id=sale.event_id,
                   lot_id="carried-lot", acquisition_source_event_id=target.event_id, origin_lot_id="root-lot")
    TaxService(store)._replace_tax_tables(lots, [line], [])
    trace = LotOriginIndex(lots, [root, target, sale]).resolve(line)
    assert trace.status == "carried" and trace.origin_event_id == root.event_id
    roles = BmfFifoEventEvidenceService(store)._tax_graph_roles(
        years=[2024], as_of=datetime(2024, 12, 31, tzinfo=timezone.utc))
    assert {root.event_id, target.event_id, sale.event_id} <= set(roles), (
        "Full-ledger evidence must retain prior-year root and direct carry event even for XYZ disposals",
        roles, root.event_id,
    )
    assert "acquisition" in roles[root.event_id]
