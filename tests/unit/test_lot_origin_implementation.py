"""Unabhaengige ID-/Summenproben, keine Provider und keine Sphaerenfreigabe."""
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.contracts.tax import TaxLine, TaxLot
from steuerreport_v2.contracts.tax_wallet_fifo import WalletFifoPreviewLine, WalletFifoPreviewLot
from steuerreport_v2.domain.lot_origin import POLICY_ID, LotOriginIndex
from steuerreport_v2.domain.business_inventory import BusinessRewardInventoryReviewService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.db.duckdb_store import DuckDbStore


D = Decimal
DAY = datetime(2024, 1, 1, tzinfo=timezone.utc)


def event(key="reward", asset="HNT", kind="mining", day=0, **changes):
    values = dict(event_id=key, source="helium", event_type=kind, asset=asset,
                  quantity=D("100"), event_time=DAY + timedelta(days=day), account="original")
    values.update(changes)
    return CanonicalEvent(**values)


def lot(key="root", asset="HNT", source="reward", parent=None, **changes):
    values = dict(lot_id=key, asset=asset, source_event_id=source, origin_lot_id=parent,
                  acquired_at=DAY, quantity_total=D("100"), quantity_remaining=D("0"),
                  cost_basis_eur_total=D("200"))
    values.update(changes)
    return TaxLot(**values)


def line(key="sale", current="root", asset="HNT", **changes):
    values = dict(tax_line_id=key, lot_id=current, asset=asset, acquired_at=DAY,
                  disposed_at=DAY + timedelta(days=2), quantity=D("0.4"),
                  acquisition_cost_eur=D("80"), disposal_proceeds_eur=D("120"),
                  gain_loss_eur=D("40"), holding_days=2, source_event_id="sell")
    values.update(changes)
    return TaxLine(**values)


def carried(asset="XYZ"):
    events = [event(), event("target", asset, "transfer", 1, quantity=D("1"))]
    lots = [lot(), lot("converted", asset, "target", "root", quantity_total=D("1"), quantity_remaining=D("0.5"))]
    sale = line(current="converted", asset=asset, acquisition_source_event_id="target", origin_lot_id="root")
    return lots, events, sale


@pytest.mark.parametrize("wallet", [False, True])
def test_pure_trace_preserves_root_with_no_mutation(wallet):
    lots, events, sale = carried()
    if wallet:
        lots = [WalletFifoPreviewLot(**{**item.model_dump(), "pool_id": "generated"}) for item in lots]
        sale = WalletFifoPreviewLine(**{**sale.model_dump(), "pool_id": "generated"})
    before = ([item.model_dump() for item in lots], sale.model_dump())
    trace = LotOriginIndex(iter(lots), iter(events)).resolve(sale)
    assert (trace.status, trace.lot_ids, trace.direct_event_id) == ("carried", ("converted", "root"), "target")
    assert (trace.origin_event_id, trace.origin_asset, trace.reason) == ("reward", "HNT", None)
    assert before == ([item.model_dump() for item in lots], sale.model_dump())
    with pytest.raises(FrozenInstanceError):
        trace.status = "direct"


def test_direct_eur_purchase_and_quote_side_purchase():
    buy = event("buy", "HNT", "trade", quantity=D("100"), quote_asset="EUR", quote_quantity=D("200"))
    direct = LotOriginIndex([lot(source="buy")], [buy]).resolve(line())
    assert direct.status == "direct" and direct.origin_event_id == "buy"
    quote_buy = event("buy", "BTC", "trade", quantity=D("-1"), quote_asset="HNT", quote_quantity=D("100"))
    assert LotOriginIndex([lot(source="buy")], [quote_buy]).resolve(line()).status == "direct"


@pytest.mark.parametrize("source", ["reward", "transfer"])
def test_own_transfer_may_retain_acquisition_event_or_link_target(source):
    transfer = event("transfer", "HNT", "transfer", 1)
    lots = [lot(), lot("moved", source=source, parent="root")]
    trace = LotOriginIndex(lots, [event(), transfer]).resolve(line(current="moved"))
    assert trace.status == "carried" and trace.origin_event_id == "reward"


def test_multihop_carry_and_equal_utc_acquisition_times():
    lots, events, sale = carried()
    lots.insert(1, lot("moved", parent="root"))
    lots[-1] = lots[-1].model_copy(update={"origin_lot_id": "moved"})
    local_time = datetime(2024, 1, 1, 1, tzinfo=timezone(timedelta(hours=1)))
    sale = sale.model_copy(update={"origin_lot_id": "moved", "acquired_at": local_time})
    trace = LotOriginIndex(lots, events).resolve(sale)
    assert trace.status == "carried" and trace.lot_ids == ("converted", "moved", "root")
    assert trace.origin_event_id == "reward"


@pytest.mark.parametrize("defect,expected", [
    ("missing_current", "missing_lot"),
    ("missing_parent", "missing_origin_lot"),
    ("duplicate_lot", "duplicate_lot_id"),
    ("duplicate_event", "duplicate_event_id"),
    ("missing_event", "missing_source_event"),
    ("self_link", "lot_cycle"),
    ("cycle", "lot_cycle"),
    ("line_source", "line_lot_source_conflict"),
    ("line_origin", "line_lot_origin_conflict"),
    ("line_asset", "line_lot_asset_conflict"),
    ("line_pool", "line_lot_pool_conflict"),
    ("line_date", "line_lot_acquisition_conflict"),
    ("parent_date", "carried_acquisition_conflict"),
    ("root_event_date", "root_acquisition_time_conflict"),
    ("source_asset", "source_event_asset_conflict"),
    ("source_future", "source_event_time_conflict"),
    ("disposal_before", "disposal_before_acquisition"),
])
def test_fail_closed(defect, expected):
    lots, events, sale = carried()
    if defect == "missing_current":
        lots.pop()
    elif defect == "missing_parent":
        lots.pop(0)
    elif defect == "duplicate_lot":
        lots.append(lots[-1])
    elif defect == "duplicate_event":
        events.append(events[-1])
    elif defect == "missing_event":
        events.pop()
    elif defect == "self_link":
        lots[-1] = lots[-1].model_copy(update={"origin_lot_id": "converted"})
        sale = sale.model_copy(update={"origin_lot_id": "converted"})
    elif defect == "cycle":
        lots[0] = lots[0].model_copy(update={"origin_lot_id": "converted"})
    elif defect.startswith("line_"):
        field, value = {"line_source": ("acquisition_source_event_id", "wrong"),
                        "line_origin": ("origin_lot_id", "wrong"),
                        "line_asset": ("asset", "OTHER"),
                        "line_pool": ("pool_id", "wrong"),
                        "line_date": ("acquired_at", DAY + timedelta(seconds=1))}[defect]
        sale = sale.model_copy(update={field: value})
    elif defect == "parent_date":
        lots[0] = lots[0].model_copy(update={"acquired_at": DAY + timedelta(seconds=1)})
    elif defect == "root_event_date":
        events[0] = events[0].model_copy(update={"event_time": DAY + timedelta(seconds=1)})
    elif defect == "source_asset":
        events[-1] = events[-1].model_copy(update={"asset": "OTHER"})
    elif defect == "source_future":
        events[-1] = events[-1].model_copy(update={"event_time": DAY + timedelta(days=3)})
    elif defect == "disposal_before":
        sale = sale.model_copy(update={"disposed_at": DAY - timedelta(seconds=1)})
    trace = LotOriginIndex(lots, events).resolve(sale)
    assert (trace.status, trace.reason) == ("unresolved", expected)
    assert trace.origin_event_id is None and trace.origin_asset is None
    assert len(trace.lot_ids) <= 64


@pytest.mark.parametrize("length,status", [(64, "carried"), (65, "unresolved")])
def test_depth_limit(length, status):
    lots = [lot(str(i), parent=str(i - 1) if i else None) for i in range(length)]
    trace = LotOriginIndex(lots, [event()]).resolve(line(current=str(length - 1)))
    assert trace.status == status and len(trace.lot_ids) == 64
    assert trace.reason == ("lot_depth_exceeded" if length == 65 else None)


def test_large_id_index_does_not_merge_lots_by_symbol_or_amount():
    lots = [lot(str(i), parent="root") for i in range(10000)] + [lot()]
    index = LotOriginIndex(lots, [event()])
    for i in range(10000):
        trace = index.resolve(line(current=str(i)))
        assert trace.lot_ids == (str(i), "root") and trace.origin_event_id == "reward"


def persist(tmp_path, lots, events, lines):
    store = DuckDbStore(tmp_path / "origin.duckdb")
    for item in events:
        created = store.add_canonical_event(item)
        # Stored fixtures retain explicit IDs for independent lineage assertions.
        with store.connect() as con:
            con.execute("update canonical_events set event_id=? where event_id=?", [item.event_id, created.event_id])
    TaxService(store)._replace_tax_tables(lots, lines, [])
    return store


def snapshot(store):
    with store.connect() as con:
        return tuple(con.execute(f"select * from {table} order by 1").fetchall()
                     for table in ("canonical_events", "tax_lots", "tax_lines", "tax_run_summaries", "admin_settings"))


def test_stored_partial_conversion_root_filter_exact_totals_and_read_only(tmp_path):
    lots, events, sale = carried()
    second = sale.model_copy(update={"tax_line_id": "sale2", "quantity": D("0.1"),
        "acquisition_cost_eur": D("20"), "disposal_proceeds_eur": D("30"), "gain_loss_eur": D("10")})
    store = persist(tmp_path, lots, events, [sale, second])
    before = snapshot(store)
    service = BusinessRewardInventoryReviewService(store)
    for assets in [("HNT",), ("XYZ",), ("HNT", "XYZ")]:
        report = service.review(assets=assets)
        assert report.total_tax_lines_count == 2 and len(report.rows) == 1
        row = report.rows[0]
        assert row.classification == "potential_business_inventory" and row.blocks_private_fifo_classification
        assert (row.quantity_disposed, row.acquisition_cost_eur, row.disposal_proceeds_eur, row.gain_loss_eur) == (D("0.5"), D("100"), D("150"), D("50"))
        assert row.sample_origin_event_id == "reward" and row.origin_event_type == "mining"
        assert row.lineage_status == "carried" and row.sample_lot_path == ["converted", "root"]
        assert row.sample_direct_event_id == "target" and row.lineage_reason is None
        assert not report.strict_ready
    assert service.review(assets=("BTC",)).total_tax_lines_count == 0
    assert service.review(assets=()).total_tax_lines_count == 0
    assert snapshot(store) == before


@pytest.mark.parametrize("defect", ["missing_parent", "self_link", "line_conflict", "missing_current"])
def test_stored_unresolved_never_uses_intermediate_as_root(tmp_path, defect):
    lots, events, sale = carried("IOT")
    store = persist(tmp_path, lots, events, [sale])
    with store.connect() as con:
        if defect == "missing_parent":
            con.execute("delete from tax_lots where lot_id='root'")
        elif defect == "self_link":
            con.execute("update tax_lots set origin_lot_id='converted' where lot_id='converted'")
            con.execute("update tax_lines set origin_lot_id='converted'")
        elif defect == "line_conflict":
            con.execute("update tax_lines set acquisition_source_event_id='reward'")
        else:
            con.execute("delete from tax_lots where lot_id='converted'")
    before = snapshot(store)
    report = BusinessRewardInventoryReviewService(store).review()
    assert report.total_tax_lines_count == 1 and report.unresolved_tax_lines_count == 1
    row = report.rows[0]
    assert row.lineage_status == "unresolved" and row.lineage_reason
    assert row.origin_source is None and row.sample_origin_event_id is None
    assert row.classification == "missing_origin" and row.blocks_private_fifo_classification
    assert not report.strict_ready and snapshot(store) == before


@pytest.mark.parametrize("kind", ["unknown", "fee", "derivative"])
def test_unknown_root_type_never_default_non_reward(kind):
    assert BusinessRewardInventoryReviewService.classify_origin("helium", kind)[0] == "origin_classification_review"


def test_stored_unknown_root_type_and_zero_basis_remain_review(tmp_path):
    store = persist(tmp_path, [lot(cost_basis_eur_total=D("0"))], [event(kind="unknown")],
                    [line(acquisition_cost_eur=D("0"))])
    before = snapshot(store)
    report = BusinessRewardInventoryReviewService(store).review()
    row = report.rows[0]
    assert row.lineage_status == "direct" and row.classification == "origin_classification_review"
    assert row.blocks_private_fifo_classification and not report.strict_ready
    assert row.acquisition_cost_eur == 0 and snapshot(store) == before


def test_stored_direct_purchase_and_berlin_year(tmp_path):
    buy = event("buy", kind="trade", quote_asset="EUR", quote_quantity=D("200"))
    sale = line(disposed_at=datetime(2024, 12, 31, 23, 30, tzinfo=timezone.utc))
    store = persist(tmp_path, [lot(source="buy")], [buy], [sale])
    report = BusinessRewardInventoryReviewService(store).review()
    row = report.rows[0]
    assert row.lineage_status == "direct" and row.disposal_year == 2025
    assert row.classification == "non_reward_origin" and row.sample_origin_event_id == "buy"


def test_large_stored_decimals_are_not_rounded_by_aggregation(tmp_path):
    huge = D("9999999999999999999.123456789012345678")
    twice = D("19999999999999999998.246913578024691356")
    sale = line(quantity=huge, acquisition_cost_eur=huge, disposal_proceeds_eur=huge, gain_loss_eur=D("0"))
    store = persist(tmp_path, [lot(quantity_total=twice, cost_basis_eur_total=twice)],
                    [event(quantity=twice)], [sale, sale.model_copy(update={"tax_line_id": "sale2"})])
    report = BusinessRewardInventoryReviewService(store).review()
    row = report.rows[0]
    assert row.quantity_disposed == twice and row.acquisition_cost_eur == twice
    assert report.potential_business_acquisition_cost_eur == twice


def test_policy_constant_is_stable():
    assert POLICY_ID == "linked_lot_origin_v1"


def test_service_supplies_policy_explicitly_for_both_report_paths(tmp_path):
    from steuerreport_v2.contracts.business_inventory import BusinessRewardInventoryReviewReport
    store = persist(tmp_path, [lot()], [event()], [line()])
    service = BusinessRewardInventoryReviewService(store)
    report = service.review()
    assert report.origin_trace_policy == "linked_lot_origin_v1"
    assert service.review(assets=()).origin_trace_policy == "linked_lot_origin_v1"
    legacy = report.model_dump(exclude={"origin_trace_policy"})
    assert BusinessRewardInventoryReviewReport.model_validate(legacy).origin_trace_policy == "legacy_direct_origin_v1"
