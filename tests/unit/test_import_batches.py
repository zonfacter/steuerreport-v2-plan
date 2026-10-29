import pytest
import duckdb

from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from datetime import datetime, timezone
from decimal import Decimal


def test_create_and_list_import_batch(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="binance.csv",
            file_hash="sha256:test",
        )
    )

    assert batch.source == "binance"
    assert batch.filename == "binance.csv"
    assert batch.file_hash == "sha256:test"
    assert batch.status == "created"
    assert batch.raw_object_count == 0
    assert store.get_import_batch(batch.batch_id) == batch
    assert store.get_import_batch_by_file_hash("binance", "sha256:test") == batch
    assert store.list_import_batches() == [batch]


def test_schema_v1_migration_preserves_old_imports_as_unbound(tmp_path):
    path = tmp_path / "legacy-v1.duckdb"
    con = duckdb.connect(str(path))
    con.execute("create table schema_meta (key varchar primary key, value varchar not null)")
    con.execute("insert into schema_meta values ('schema_version', '1')")
    con.execute("""create table raw_import_batches (
        batch_id varchar primary key, source varchar not null, filename varchar,
        file_hash varchar, status varchar not null, created_at timestamp not null
    )""")
    con.execute("""create table raw_objects (
        raw_object_id varchar primary key, batch_id varchar not null, row_number integer,
        payload_json varchar not null, created_at timestamp not null
    )""")
    created = datetime(2025, 1, 1, tzinfo=timezone.utc)
    original_payload = '{"coin":"BTC","change":"1"}'
    con.execute("insert into raw_import_batches values (?, ?, ?, ?, ?, ?)", [
        "legacy-batch", "binance", "old.csv", "sha256:legacy", "loaded", created,
    ])
    con.execute("insert into raw_objects values (?, ?, ?, ?, ?)", [
        "legacy-raw", "legacy-batch", 1, original_payload, created,
    ])
    con.close()

    store = DuckDbStore(path)
    migrated = store.get_import_batch("legacy-batch")
    assert migrated is not None
    assert migrated.connection_id is None
    assert migrated.file_hash == "sha256:legacy"
    assert store.list_raw_objects("legacy-batch", limit=None)[0].payload_json == original_payload
    assert store.health()["schema_version"] == 2
    with store.connect() as upgraded:
        assert upgraded.execute(
            "select connection_id from raw_import_batches where batch_id='legacy-batch'"
        ).fetchone() == (None,)


def test_add_raw_object_updates_batch_count_and_status(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(ImportBatchCreate(source="pionex"))

    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(row_number=1, payload_json='{"asset":"USDT"}'),
    )
    updated = store.get_import_batch(batch.batch_id)

    assert raw.batch_id == batch.batch_id
    assert raw.row_number == 1
    assert updated is not None
    assert updated.status == "loaded"
    assert updated.raw_object_count == 1


def test_add_raw_objects_bulk_updates_batch_count_and_status(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(ImportBatchCreate(source="pionex"))

    raw_objects = store.add_raw_objects(
        batch.batch_id,
        [
            RawObjectCreate(row_number=1, payload_json='{"asset":"USDT"}'),
            RawObjectCreate(row_number=2, payload_json='{"asset":"HNT"}'),
        ],
    )
    updated = store.get_import_batch(batch.batch_id)

    assert len(raw_objects) == 2
    assert raw_objects[0].batch_id == batch.batch_id
    assert updated is not None
    assert updated.status == "loaded"
    assert updated.raw_object_count == 2


def test_list_raw_objects_can_return_all_rows_without_limit(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(ImportBatchCreate(source="pionex"))
    store.add_raw_objects(
        batch.batch_id,
        [
            RawObjectCreate(row_number=index, payload_json=f'{{"row":{index}}}')
            for index in range(1, 602)
        ],
    )

    assert len(store.list_raw_objects(batch.batch_id)) == 500
    assert len(store.list_raw_objects(batch.batch_id, limit=None)) == 601


def test_delete_import_batch_removes_raw_objects(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(ImportBatchCreate(source="pionex"))
    store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(row_number=1, payload_json='{"asset":"USDT"}'),
    )

    deleted = store.delete_import_batch(batch.batch_id)

    assert deleted is True
    assert store.get_import_batch(batch.batch_id) is None
    assert store.list_raw_objects(batch.batch_id) == []


def test_delete_import_batch_reports_missing_batch(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    assert store.delete_import_batch("missing") is False


def test_add_raw_object_rejects_unknown_batch(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    with pytest.raises(ValueError, match="unknown import batch"):
        store.add_raw_object(
            "missing",
            RawObjectCreate(payload_json="{}"),
        )


def test_add_canonical_events_bulk_persists_events(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    events = store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="pionex",
                source_ref="1",
                event_time=datetime(2021, 1, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("1"),
                raw_object_id="raw-1",
            ),
            CanonicalEventCreate(
                source="pionex",
                source_ref="2",
                event_time=datetime(2021, 1, 2, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("2"),
                raw_object_id="raw-2",
            ),
        ]
    )

    assert len(events) == 2
    assert events[0].event_id != events[1].event_id
    assert [event.asset for event in store.list_canonical_events()] == ["USDT", "HNT"]


def test_raw_backed_canonical_event_ids_are_stable_across_rebuilds(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(ImportBatchCreate(source="pionex"))
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(row_number=1, payload_json='{"asset":"HNT"}'),
    )
    payload = CanonicalEventCreate(
        source="pionex",
        source_ref="stable-row",
        event_time=datetime(2022, 1, 1, tzinfo=timezone.utc),
        event_type="trade",
        asset="HNT",
        quantity=Decimal("1.25"),
        quote_asset="USDT",
        quote_quantity=Decimal("10"),
        raw_object_id=raw.raw_object_id,
    )

    first = store.add_canonical_event(payload)
    store.delete_canonical_events_for_batch(batch.batch_id)
    second = store.add_canonical_event(payload)

    assert second.event_id == first.event_id


def test_identical_raw_backed_event_legs_remain_distinct_and_stable(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(ImportBatchCreate(source="binance"))
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(row_number=1, payload_json='{"asset":"SOL"}'),
    )
    payload = CanonicalEventCreate(
        source="binance",
        event_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        event_type="transfer",
        asset="SOL",
        quantity=Decimal("1"),
        raw_object_id=raw.raw_object_id,
    )

    first = store.add_canonical_events([payload, payload])
    store.delete_canonical_events_for_batch(batch.batch_id)
    second = store.add_canonical_events([payload, payload])

    assert first[0].event_id != first[1].event_id
    assert [event.event_id for event in second] == [
        event.event_id for event in first
    ]
