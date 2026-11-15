"""Unabhaengige Identitaetsproben; nur synthetische Helper-Eingaben, keine DB."""

from __future__ import annotations

import csv
import hashlib
import io
import socket
from datetime import datetime, timezone
from decimal import Decimal

import duckdb
import pytest

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_filing_audit import TaxFilingAuditService


EVENT_ID = "11111111-1111-4111-8111-111111111111"
OTHER_EVENT_ID = "22222222-2222-4222-8222-222222222222"
LOT_ID = "33333333-3333-4333-8333-333333333333"
ACQUISITION_ID = "44444444-4444-4444-8444-444444444444"
DISPOSED = "2025-06-13T12:00:00+00:00"
IDENTITIES = {
    "Source_Event_ID": EVENT_ID,
    "Lot_ID": LOT_ID,
    "Anschaffungs_Event_ID": ACQUISITION_ID,
}


@pytest.fixture(autouse=True)
def no_database_or_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Identitaetsprobe darf weder DB noch Netzwerk nutzen")

    monkeypatch.setattr(duckdb, "connect", forbidden)
    monkeypatch.setattr(DuckDbStore, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture
def service():
    # These helpers need no store; deliberately do not construct any service state.
    return TaxFilingAuditService.__new__(TaxFilingAuditService)


def _csv_bytes(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def _package(*, identities, canonical_at=None):
    row = {
        "Datum_Kauf": "2025-01-02T10:00:00+00:00",
        "Datum_Verkauf": DISPOSED,
        "Asset": "BTC",
        "Menge": "1.125",
        "Anschaffungskosten_EUR": "100",
        "Veraeusserungserloes_EUR": "125",
        "Gewinn_Verlust_EUR": "25",
        "Haltedauer_Tage": "162",
        "Steuerpflichtig": "ja",
        "Frist_Methodenversion": "synthetic-policy-v1",
        **identities,
    }
    members = {
        "02_Steuerliche_CSVs/tax-year-2025-tax-lines.csv": _csv_bytes([row]),
    }
    if canonical_at is not None:
        members["01_Transaktionen/tax-year-2025-canonical-events.csv"] = (
            _csv_bytes(
                [{
                    "Event_ID": OTHER_EVENT_ID,
                    "Zeitpunkt_UTC": canonical_at,
                    "Asset": "BTC",
                    "Quelle": "synthetic",
                    "Source_Ref": "synthetic-unrelated-event",
                    "Event_Typ": "sell",
                }]
            )
        )
    return {
        "members": members,
        "manifest": {
            "year": 2025,
            "files": [
                {
                    "path": path,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                }
                for path, content in members.items()
            ],
        },
    }


@pytest.mark.parametrize("canonical_at", [None, DISPOSED], ids=["absent", "conflict"])
@pytest.mark.parametrize(
    ("csv_field", "parsed_field"),
    [
        ("Source_Event_ID", "event_id"),
        ("Lot_ID", "lot_id"),
        ("Anschaffungs_Event_ID", "acquisition_event_id"),
    ],
)
def test_reference_parser_preserves_explicit_csv_identity(
    service, canonical_at, csv_field, parsed_field
):
    rows = service._reference_tax_lines(
        _package(identities=IDENTITIES, canonical_at=canonical_at), 2025
    )

    assert len(rows) == 1
    assert rows[0][parsed_field] == IDENTITIES[csv_field]


@pytest.mark.parametrize("canonical_at", [DISPOSED, "2025-06-13T09:00:00+00:00"])
@pytest.mark.parametrize("missing", ["columns", "values"])
def test_missing_ids_never_inherit_canonical_identity_by_time(
    service, canonical_at, missing
):
    identities = {} if missing == "columns" else dict.fromkeys(IDENTITIES, "")
    rows = service._reference_tax_lines(
        _package(identities=identities, canonical_at=canonical_at), 2025
    )

    assert len(rows) == 1
    assert rows[0]["event_id"] in (None, "")
    assert rows[0]["lot_id"] in (None, "")
    assert rows[0]["acquisition_event_id"] in (None, "")


def _position(event_id, at):
    return {
        "event_id": event_id,
        "asset": "BTC",
        "disposed_at": datetime.fromisoformat(at),
        "acquired_at": datetime(2025, 1, 2, 10, tzinfo=timezone.utc),
        "quantity": Decimal("1.125"),
        "gain": Decimal("25"),
        "proceeds": Decimal("125"),
        "acquisition_cost": Decimal("100"),
        "holding_days": 162,
        "lot_id": LOT_ID,
        "acquisition_event_id": ACQUISITION_ID,
        "taxable": True,
    }


@pytest.mark.parametrize("new_at", [DISPOSED, "2025-06-13T15:00:00+00:00"])
def test_different_explicit_event_ids_are_removed_added_never_changed(service, new_at):
    old = _position(EVENT_ID, DISPOSED)
    new = _position(OTHER_EVENT_ID, new_at)
    new["gain"] = Decimal("30")

    pairs, removed, added = service._pair_positions([old], [new])

    assert pairs == [], "Unterschiedliche belegte Event-IDs sind keine gleiche Position"
    assert removed == [old]
    assert added == [new]
    deltas, _ = service._compare_positions([old], [new], position_kind="tax_line")
    assert sorted(item.change_kind for item in deltas) == ["added", "removed"]


def test_matching_explicit_event_id_remains_pairable(service):
    old = _position(EVENT_ID, DISPOSED)
    new = dict(old, gain=Decimal("30"))

    pairs, removed, added = service._pair_positions([old], [new])

    assert pairs == [(old, new)]
    assert removed == []
    assert added == []


def test_missing_ids_without_canonical_rows_remain_unknown(service):
    rows = service._reference_tax_lines(_package(identities={}), 2025)

    assert len(rows) == 1
    assert rows[0]["event_id"] in (None, "")
    assert rows[0]["lot_id"] in (None, "")
    assert rows[0]["acquisition_event_id"] in (None, "")
