"""Zusaetzliche isolierte Reviewproben; Original-Identitaetsproben bleiben gleich."""

from __future__ import annotations

import csv
import io
import socket
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, getcontext, localcontext
from types import SimpleNamespace

import duckdb
import pytest

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_filing_audit import (
    TaxFilingAuditError,
    TaxFilingAuditService,
)


EVENT = "11111111-1111-4111-8111-111111111111"
LOT_A = "22222222-2222-4222-8222-222222222222"
LOT_B = "33333333-3333-4333-8333-333333333333"
ACQUISITION = "44444444-4444-4444-8444-444444444444"
OTHER_ACQUISITION = "55555555-5555-4555-8555-555555555555"
AT = datetime(2025, 6, 13, 12, tzinfo=timezone.utc)
AGGREGATE_FIELDS = (
    "taxable_private_disposals_eur",
    "tax_free_private_disposals_eur",
    "rewards_mining_staking_income_eur",
    "derivative_pnl_eur",
    "taxable_disposal_proceeds_eur",
    "acquisition_cost_eur",
)


@pytest.fixture(autouse=True)
def no_database_or_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Reviewprobe darf weder DB noch Netzwerk nutzen")

    monkeypatch.setattr(duckdb, "connect", forbidden)
    monkeypatch.setattr(DuckDbStore, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture
def service():
    return TaxFilingAuditService.__new__(TaxFilingAuditService)


def _position(**updates):
    return {
        "event_id": EVENT,
        "lot_id": LOT_A,
        "acquisition_event_id": ACQUISITION,
        "asset": "SYNTH",
        "quantity": Decimal("1"),
        "acquisition_cost": Decimal("10"),
        "proceeds": Decimal("15"),
        "gain": Decimal("5"),
        "disposed_at": AT,
        "acquired_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "holding_days": 163,
        "taxable": True,
        "source": "synthetic",
        "source_ref": "synthetic-disposal",
        **updates,
    }


@pytest.mark.parametrize(
    ("field", "other"),
    [("lot_id", LOT_B), ("acquisition_event_id", OTHER_ACQUISITION)],
)
def test_missing_event_id_never_overrides_conflicting_explicit_lot_identity(
    service, field, other
):
    old = _position(event_id=None)
    new = dict(old, **{field: other})

    pairs, removed, added = service._pair_positions([old], [new])

    assert pairs == [], "Fehlende Event-ID legitimiert keinen Lot-ID-Widerspruch"
    assert removed == [old]
    assert added == [new]


def test_multiple_lots_for_one_event_pair_only_their_own_identity(service):
    old_a = _position()
    old_b = _position(lot_id=LOT_B, acquisition_event_id=OTHER_ACQUISITION)
    new_a = dict(old_a, gain=Decimal("6"))
    new_b = dict(old_b, gain=Decimal("7"))

    pairs, removed, added = service._pair_positions([old_a, old_b], [new_b, new_a])

    assert len(pairs) == 2
    assert {left["lot_id"] for left, _ in pairs} == {LOT_A, LOT_B}
    assert all(left["lot_id"] == right["lot_id"] for left, right in pairs)
    assert removed == []
    assert added == []


def test_duplicate_identity_never_gets_arbitrary_occurrence_pair(service):
    old = [_position(), _position(gain=Decimal("6"))]
    new = [_position(gain=Decimal("7")), _position(gain=Decimal("8"))]

    pairs, removed, added = service._pair_positions(old, new)

    assert pairs == []
    assert removed == old
    assert added == new


def _tax_package(omitted, blank):
    row = {
        "Datum_Kauf": "2025-01-01T00:00:00+00:00",
        "Datum_Verkauf": AT.isoformat(),
        "Asset": "SYNTH",
        "Menge": "1",
        "Anschaffungskosten_EUR": "10",
        "Veraeusserungserloes_EUR": "15",
        "Gewinn_Verlust_EUR": "5",
        "Haltedauer_Tage": "163",
        "Steuerpflichtig": "ja",
        "Source_Event_ID": EVENT,
        "Lot_ID": LOT_A,
        "Anschaffungs_Event_ID": ACQUISITION,
    }
    if blank:
        row[omitted] = ""
    else:
        del row[omitted]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(row))
    writer.writeheader()
    writer.writerow(row)
    return {
        "members": {
            "02_Steuerliche_CSVs/tax-year-2025-tax-lines.csv": (
                buffer.getvalue().encode("utf-8")
            ),
        },
        "manifest": {"files": []},
    }


@pytest.mark.parametrize("blank", [False, True], ids=["missing-column", "empty-cell"])
@pytest.mark.parametrize(
    ("column", "parsed"),
    [
        ("Anschaffungskosten_EUR", "acquisition_cost"),
        ("Veraeusserungserloes_EUR", "proceeds"),
        ("Gewinn_Verlust_EUR", "gain"),
    ],
)
def test_missing_reference_amount_must_not_become_a_measured_zero(
    service, column, parsed, blank
):
    try:
        rows = service._reference_tax_lines(_tax_package(column, blank), 2025)
    except (TaxFilingAuditError, ValueError):
        return

    assert len(rows) == 1
    assert rows[0][parsed] is None, "Fehlender archivierter Betrag ist unbekannt, nicht 0"


def test_unknown_archived_taxability_does_not_prove_reclassification(service):
    old = _position(taxable=None)
    new = _position(taxable=True)

    cause, _ = service._classify_cause(old, new, "changed", "tax_line")

    assert cause == "unknown"


def test_decimal_delta_keeps_smallest_db_fraction_and_caller_context(service):
    old = _position(gain=Decimal("99999999999999999999.123456789012345678"))
    new = _position(gain=Decimal("99999999999999999999.123456789012345679"))

    with localcontext() as context:
        context.prec = 6
        delta = service._delta_from_position(old, new, "changed", "tax_line")
        assert delta.value_delta_eur == Decimal("0.000000000000000001")
        assert getcontext().prec == 6


def test_decimal_reconciliation_preserves_exact_fraction(service):
    baseline = SimpleNamespace(**dict.fromkeys(AGGREGATE_FIELDS, Decimal("0")))
    current = SimpleNamespace(**dict.fromkeys(AGGREGATE_FIELDS, Decimal("0")))
    baseline.taxable_private_disposals_eur = Decimal(
        "99999999999999999999.123456789012345678"
    )
    current.taxable_private_disposals_eur = Decimal(
        "99999999999999999999.123456789012345679"
    )
    delta = service._delta_from_position(
        _position(gain=baseline.taxable_private_disposals_eur),
        _position(gain=current.taxable_private_disposals_eur),
        "changed",
        "tax_line",
    )

    with localcontext() as context:
        context.prec = 6
        rows = service._reconciliation(
            baseline_values=baseline, current_values=current, deltas=[delta]
        )
        row = next(item for item in rows if item.key == "private_disposals")
        assert row.aggregate_delta_eur == Decimal("0.000000000000000001")
        assert row.individual_delta_eur == Decimal("0.000000000000000001")
        assert row.residual_eur == Decimal("0")
        assert row.status == "reconciled"
        assert getcontext().prec == 6


def test_build_uses_snapshot_child_and_materializes_only_after_exit(tmp_path, monkeypatch):
    events = []
    snapshot = SimpleNamespace(path=tmp_path / "never-opened.duckdb")
    result = object()

    @contextmanager
    def read_initialized_snapshot():
        events.append("enter")
        yield snapshot
        events.append("exit")

    store = SimpleNamespace(
        path=snapshot.path, read_initialized_snapshot=read_initialized_snapshot
    )
    outer = TaxFilingAuditService(store)

    def build_snapshot(child, year, queried_at):
        assert child.store is snapshot
        assert events == ["enter"]
        assert year == 2025
        assert queried_at == AT
        assert getcontext().prec >= 80
        events.append("read")
        return result

    def materialize(service, report):
        assert service is outer
        assert report is result
        assert events == ["enter", "read", "exit"]
        events.append("materialize")
        return report

    monkeypatch.setattr(TaxFilingAuditService, "_build_snapshot", build_snapshot)
    monkeypatch.setattr(TaxFilingAuditService, "_materialize", materialize)

    assert outer.build(2025, query_time=AT) is result
    assert events == ["enter", "read", "exit", "materialize"]
