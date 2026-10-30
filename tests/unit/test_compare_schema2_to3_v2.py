from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path

import duckdb
import pytest

SPEC = importlib.util.spec_from_file_location(
    "compare_schema2_to3_v2", Path(__file__).resolve().parents[2] / "scripts/compare_schema2_to3_v2.py"
)
assert SPEC is not None and SPEC.loader is not None
comparator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(comparator)
SchemaComparisonError = comparator.SchemaComparisonError
compare_schema2_to3 = comparator.compare_schema2_to3
main = comparator.main


BITGET_CONTEXT = {
    "context_version": "1",
    "export_timezone": "UTC+08:00",
    "timezone_basis": "legacy_default_unverified",
    "product_scope": "unspecified_legacy",
}
SECRET_SENTINEL = "synthetic-private-payload-must-not-be-printed"
TABLE_NAMES = (
    "canonical_events",
    "constraint_parent",
    "constraint_probe",
    "duplicate_probe",
    "raw_import_batches",
    "raw_objects",
    "schema_meta",
)


@pytest.fixture(autouse=True)
def isolated_comparator_temp_root(tmp_path, monkeypatch):
    monkeypatch.setattr(comparator.tempfile, "gettempdir", lambda: str(tmp_path))


def _create_schema(connection, *, with_context=False):
    connection.execute(
        "create table schema_meta(key varchar primary key, value varchar not null)"
    )
    connection.execute(
        """create table constraint_parent(
            parent_id varchar primary key,
            label varchar unique,
            constraint parent_id_check check(length(parent_id) > 0)
        )"""
    )
    context_column = (
        ", import_context_json varchar not null default '{}'" if with_context else ""
    )
    connection.execute(
        f"""create table raw_import_batches(
            batch_id varchar primary key,
            source varchar not null,
            filename varchar,
            file_hash varchar,
            status varchar not null check(status in ('imported')),
            created_at timestamp not null,
            connection_id varchar not null,
            constraint batch_file_connection_unique unique(file_hash, connection_id),
            constraint batch_connection_fk foreign key(connection_id)
                references constraint_parent(parent_id),
            constraint batch_id_check check(length(batch_id) > 0)
            {context_column}
        )"""
    )
    connection.execute(
        """create table raw_objects(
            raw_id varchar primary key,
            batch_id varchar not null references raw_import_batches(batch_id),
            payload_json varchar check(length(payload_json) >= 0)
        )"""
    )
    connection.execute(
        "create table canonical_events(event_id varchar primary key, quantity decimal(38,18), payload struct(kind varchar, fee decimal(18,8)))"
    )
    connection.execute(
        """create table constraint_probe(
            probe_id varchar primary key,
            unique_value varchar unique,
            checked_value integer check(checked_value >= 0),
            parent_id varchar references constraint_parent(parent_id)
        )"""
    )
    connection.execute(
        "create table duplicate_probe(label varchar, amount decimal(18,4))"
    )


def _insert_schema2_rows(connection):
    connection.executemany(
        "insert into schema_meta values (?, ?)",
        [("schema_version", "2"), ("method", "synthetic-method-v1")],
    )
    connection.execute(
        "insert into constraint_parent values ('connection-a', 'test-a'), ('connection-b', 'test-b')"
    )
    connection.executemany(
        "insert into raw_import_batches values (?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "batch-1",
                "bitget",
                "synthetic.csv",
                "a" * 64,
                "imported",
                "2025-01-01 00:00:00",
                "connection-a",
            ),
            (
                "batch-2",
                "binance",
                "synthetic.csv",
                "b" * 64,
                "imported",
                "2025-01-02 00:00:00",
                "connection-b",
            ),
        ],
    )
    connection.executemany(
        "insert into raw_objects values (?, ?, ?)",
        [
            ("raw-1", "batch-1", SECRET_SENTINEL),
            ("raw-2", "batch-2", '{"synthetic":true}'),
        ],
    )
    connection.execute(
        "insert into canonical_events values (?, ?, {'kind': ?, 'fee': ?})",
        ["event-1", "0.123456789012345678", "trade", "0.00001000"],
    )
    connection.execute(
        "insert into constraint_probe values ('probe-1', 'unique-1', 1, 'connection-a')"
    )
    connection.executemany(
        "insert into duplicate_probe values (?, ?)",
        [("same", "1.0000"), ("same", "1.0000")],
    )
    connection.execute(
        "create index duplicate_probe_label_idx on duplicate_probe(label)"
    )


def _schema2(path):
    connection = duckdb.connect(str(path))
    _create_schema(connection)
    _insert_schema2_rows(connection)
    connection.close()


def _schema3_from_schema2(before, after):
    source = duckdb.connect(str(before), read_only=True)
    target = duckdb.connect(str(after))
    _create_schema(target, with_context=True)
    for table, columns in (
        ("schema_meta", ("key", "value")),
        ("constraint_parent", ("parent_id", "label")),
        (
            "raw_import_batches",
            (
                "batch_id",
                "source",
                "filename",
                "file_hash",
                "status",
                "created_at",
                "connection_id",
            ),
        ),
        ("raw_objects", ("raw_id", "batch_id", "payload_json")),
        ("canonical_events", ("event_id", "quantity", "payload")),
        (
            "constraint_probe",
            ("probe_id", "unique_value", "checked_value", "parent_id"),
        ),
        ("duplicate_probe", ("label", "amount")),
    ):
        quoted_columns = ", ".join(f'"{column}"' for column in columns)
        rows = source.execute(f'select {quoted_columns} from "{table}"').fetchall()
        if table == "schema_meta":
            rows = [
                (key, "3" if key == "schema_version" else value) for key, value in rows
            ]
        placeholders = ", ".join("?" for _ in columns)
        target.executemany(
            f'insert into "{table}" ({quoted_columns}) values ({placeholders})', rows
        )
    target.execute(
        "update raw_import_batches set import_context_json=? where lower(source)='bitget'",
        [json.dumps(BITGET_CONTEXT, sort_keys=True)],
    )
    target.execute("create index duplicate_probe_label_idx on duplicate_probe(label)")
    source.close()
    target.close()


def _pair(tmp_path):
    before = tmp_path / "before-schema-2.duckdb"
    after = tmp_path / "after-schema-3.duckdb"
    _schema2(before)
    _schema3_from_schema2(before, after)
    return before, after


def _change(path, sql, parameters=None):
    connection = duckdb.connect(str(path))
    connection.execute(sql, parameters or [])
    connection.close()


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _table_id(table_name):
    return f"table_{sorted(TABLE_NAMES).index(table_name) + 1:04d}"


def _replace_probe_without_constraint(path, definition):
    connection = duckdb.connect(str(path))
    rows = connection.execute("select * from constraint_probe").fetchall()
    connection.execute("drop table constraint_probe")
    connection.execute(definition)
    connection.executemany("insert into constraint_probe values (?, ?, ?, ?)", rows)
    connection.close()


def test_valid_transition_preserves_data_constraints_indexes_and_hashes(tmp_path):
    before, after = _pair(tmp_path)
    before_hash, after_hash = _sha256(before), _sha256(after)

    result = compare_schema2_to3(before, after)

    assert result["status"] == "passed"
    assert result["before_schema_version"] == 2
    assert result["after_schema_version"] == 3
    assert result["input_sha256"] == {
        "before": {"pre": before_hash, "post": before_hash},
        "after": {"pre": after_hash, "post": after_hash},
    }
    assert {item["id"] for item in result["tables"]} == {
        _table_id(name) for name in TABLE_NAMES
    }
    assert next(
        item for item in result["tables"] if item["id"] == _table_id("duplicate_probe")
    ) == {"id": _table_id("duplicate_probe"), "before_rows": 2, "after_rows": 2}


def test_changed_existing_row_is_rejected(tmp_path):
    before, after = _pair(tmp_path)
    _change(after, "update canonical_events set quantity=?", ["0.123456789012345679"])

    with pytest.raises(SchemaComparisonError) as error:
        compare_schema2_to3(before, after)

    assert error.value.code == "row_multiset_changed"
    assert error.value.table_id == _table_id("canonical_events")


def test_missing_existing_row_is_rejected(tmp_path):
    before, after = _pair(tmp_path)
    _change(after, "delete from raw_objects where raw_id=?", ["raw-1"])

    with pytest.raises(SchemaComparisonError) as error:
        compare_schema2_to3(before, after)

    assert error.value.code == "row_multiset_changed"
    assert error.value.table_id == _table_id("raw_objects")


def test_additional_table_uses_anonymous_identifier_only(tmp_path, capsys):
    before, after = _pair(tmp_path)
    table_name = "unexpected table PRIVATE_IDENTIFIER"
    _change(after, f'create table "{table_name}"(value varchar)')

    assert main(["--before", str(before), "--after", str(after)]) == 1
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["code"] == "table_set_changed"
    assert table_name not in output
    assert SECRET_SENTINEL not in output
    assert all(re.fullmatch(r"table_[0-9]{4,}", row["id"]) for row in report["tables"])


def test_lost_primary_key_with_same_rows_is_rejected(tmp_path):
    before, after = _pair(tmp_path)
    _replace_probe_without_constraint(
        after,
        """create table constraint_probe(
            probe_id varchar not null,
            unique_value varchar unique,
            checked_value integer check(checked_value >= 0),
            parent_id varchar references constraint_parent(parent_id)
        )""",
    )

    with pytest.raises(SchemaComparisonError) as error:
        compare_schema2_to3(before, after)

    assert error.value.code == "constraint_changed"
    assert error.value.table_id == _table_id("constraint_probe")


@pytest.mark.parametrize(
    "definition",
    [
        """create table constraint_probe(
            probe_id varchar primary key,
            unique_value varchar,
            checked_value integer check(checked_value >= 0),
            parent_id varchar references constraint_parent(parent_id)
        )""",
        """create table constraint_probe(
            probe_id varchar primary key,
            unique_value varchar unique,
            checked_value integer,
            parent_id varchar references constraint_parent(parent_id)
        )""",
        """create table constraint_probe(
            probe_id varchar primary key,
            unique_value varchar unique,
            checked_value integer check(checked_value >= 0),
            parent_id varchar
        )""",
    ],
    ids=["unique", "check", "foreign-key"],
)
def test_lost_unique_check_or_foreign_key_is_rejected(tmp_path, definition):
    before, after = _pair(tmp_path)
    _replace_probe_without_constraint(after, definition)

    with pytest.raises(SchemaComparisonError) as error:
        compare_schema2_to3(before, after)

    assert error.value.code == "constraint_changed"
    assert error.value.table_id == _table_id("constraint_probe")


def test_lost_explicit_index_with_same_rows_is_rejected(tmp_path):
    before, after = _pair(tmp_path)
    _change(after, "drop index duplicate_probe_label_idx")

    with pytest.raises(SchemaComparisonError) as error:
        compare_schema2_to3(before, after)

    assert error.value.code == "index_changed"
    assert error.value.table_id == _table_id("duplicate_probe")


def test_unexpected_context_constraint_is_rejected(tmp_path):
    before, after = _pair(tmp_path)
    connection = duckdb.connect(str(after))
    rows = connection.execute("select * from duplicate_probe").fetchall()
    connection.execute("drop index duplicate_probe_label_idx")
    connection.execute("drop table duplicate_probe")
    connection.execute(
        "create table duplicate_probe(label varchar, amount decimal(18,4), check(amount >= 0))"
    )
    connection.executemany("insert into duplicate_probe values (?, ?)", rows)
    connection.execute(
        "create index duplicate_probe_label_idx on duplicate_probe(label)"
    )
    connection.close()

    with pytest.raises(SchemaComparisonError) as error:
        compare_schema2_to3(before, after)

    assert error.value.code == "constraint_changed"
    assert error.value.table_id == _table_id("duplicate_probe")


def test_incorrect_legacy_context_is_rejected(tmp_path):
    before, after = _pair(tmp_path)
    _change(
        after,
        "update raw_import_batches set import_context_json=? where batch_id=?",
        [json.dumps({**BITGET_CONTEXT, "export_timezone": "UTC"}), "batch-1"],
    )

    with pytest.raises(SchemaComparisonError) as error:
        compare_schema2_to3(before, after)

    assert error.value.code == "legacy_context_invalid"
    assert error.value.table_id == _table_id("raw_import_batches")


@pytest.mark.parametrize("side,version", [("before", "1"), ("after", "2")])
def test_wrong_schema_version_is_rejected(tmp_path, side, version):
    before, after = _pair(tmp_path)
    target = before if side == "before" else after
    _change(
        target, "update schema_meta set value=? where key='schema_version'", [version]
    )

    with pytest.raises(SchemaComparisonError) as error:
        compare_schema2_to3(before, after)

    assert error.value.code == "schema_version_invalid"
    assert error.value.table_id == _table_id("schema_meta")


def test_input_files_remain_byte_identical(tmp_path):
    before, after = _pair(tmp_path)
    before_hash, after_hash = _sha256(before), _sha256(after)

    compare_schema2_to3(before, after)

    assert _sha256(before) == before_hash
    assert _sha256(after) == after_hash


def test_content_replacement_during_comparison_is_rejected(tmp_path, monkeypatch):
    before, after = _pair(tmp_path)
    replacement = tmp_path / "replacement.duckdb"
    _schema2(replacement)
    _change(
        replacement,
        "update schema_meta set value=? where key='method'",
        ["synthetic-replacement-method"],
    )
    original_row_multiset = comparator._row_multiset
    replaced = False

    def replace_before_after_first_read(*args, **kwargs):
        nonlocal replaced
        result = original_row_multiset(*args, **kwargs)
        if not replaced:
            os.replace(replacement, before)
            replaced = True
        return result

    monkeypatch.setattr(comparator, "_row_multiset", replace_before_after_first_read)

    with pytest.raises(SchemaComparisonError) as error:
        compare_schema2_to3(before, after)

    assert replaced
    assert error.value.code == "input_changed_during_comparison"
    assert (
        error.value.input_sha256["before"]["pre"]
        != error.value.input_sha256["before"]["post"]
    )
    assert (
        error.value.input_sha256["after"]["pre"]
        == error.value.input_sha256["after"]["post"]
    )


@pytest.mark.parametrize(("side", "suffix"), [("before", ".wal"), ("after", ".lock")])
def test_active_sidecar_fails_closed(tmp_path, side, suffix):
    before, after = _pair(tmp_path)
    target = before if side == "before" else after
    sidecar = target.with_name(target.name + suffix)
    sidecar.write_text("synthetic active writer marker", encoding="ascii")

    with pytest.raises(SchemaComparisonError) as error:
        compare_schema2_to3(before, after)

    assert error.value.code == "active_database_state_detected"
    assert str(sidecar) not in str(error.value)


def test_cli_reports_hashes_counts_and_no_identifiers_or_row_values(tmp_path, capsys):
    before, after = _pair(tmp_path)
    before_hash, after_hash = _sha256(before), _sha256(after)

    assert main(["--before", str(before), "--after", str(after)]) == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["status"] == "passed"
    assert report["input_sha256"] == {
        "before": {"pre": before_hash, "post": before_hash},
        "after": {"pre": after_hash, "post": after_hash},
    }
    assert SECRET_SENTINEL not in output
    assert str(before) not in output and str(after) not in output
    assert "schema_meta" not in output and "raw_import_batches" not in output
    assert all(
        set(item) == {"id", "before_rows", "after_rows"}
        and re.fullmatch(r"table_[0-9]{4,}", item["id"])
        for item in report["tables"]
    )


@pytest.mark.parametrize(("sql", "code"), [
    ("create view synthetic_view as select * from duplicate_probe", "unsupported_persistent_views"),
    ("create schema synthetic_schema", "unsupported_persistent_objects"),
    ("create sequence synthetic_sequence", "unsupported_persistent_objects"),
    ("create macro synthetic_macro(a) as a + 1", "unsupported_persistent_objects"),
    ("create type synthetic_type as enum ('a', 'b')", "unsupported_persistent_objects"),
])
@pytest.mark.parametrize("side", ["before", "after"])
def test_unsupported_persistent_objects_fail_closed(tmp_path, sql, code, side):
    before, after = _pair(tmp_path)
    _change(before if side == "before" else after, sql)

    with pytest.raises(SchemaComparisonError) as error:
        compare_schema2_to3(before, after)

    assert error.value.code == code
    assert "synthetic_" not in str(error.value)


def test_different_column_collation_fails_closed(tmp_path):
    before, after = _pair(tmp_path)
    _change(before, "create table synthetic_collation(value varchar collate nocase)")
    _change(after, "create table synthetic_collation(value varchar)")

    with pytest.raises(SchemaComparisonError) as error:
        compare_schema2_to3(before, after)

    assert error.value.code == "unsupported_table_collation"


def test_input_outside_temporary_root_is_rejected(tmp_path, monkeypatch):
    before, after = _pair(tmp_path)
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setattr(comparator.tempfile, "gettempdir", lambda: str(allowed))

    with pytest.raises(SchemaComparisonError) as error:
        compare_schema2_to3(before, after)

    assert error.value.code == "input_must_be_regular_temp_copy"
