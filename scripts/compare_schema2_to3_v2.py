#!/usr/bin/env python3
"""Vergleicht zwei offline DuckDB-Kopien vor/nach Schema 2->3, strikt read-only.

Die Eingaben muessen getrennte regulaere Dateien unter dem System-Temp-Verzeichnis
sein. Der Aufrufer erstellt und isoliert diese Kopien. Das Werkzeug oeffnet beide
Datenbanken ausschliesslich mit ``read_only=True``; es erstellt selbst keine Kopien.

Es prueft Tabellen, Spalten, Constraints, explizite Indizes und Zeilen als
Multisets. Erlaubt sind nur schema_meta.schema_version 2->3, die neue Spalte
raw_import_batches.import_context_json samt NOT-NULL-Constraint und die
dokumentierten Legacy-Kontexte. Ergebnis und Pruefung werden an die SHA-256-
Inhalte beider Dateien vor und nach dem Vergleich gebunden. Tabellen erscheinen
nur als table_####.
Vorhandene WAL-/Lock-/Temp-Sidecars fuehren zum Abbruch.
Nichtsystemische Views, zusaetzliche Schemas, Sequenzen, Makros/Funktionen,
benutzerdefinierte Typen, persistente Secrets und Tabellen mit expliziter
Collation werden fail-closed abgewiesen.

Der Aufrufer muss konsistente, offline und temporaer gespeicherte Kopien
bereitstellen. Dieses Werkzeug erstellt keine Sicherungen und prueft keine
Dateien ausserhalb der beiden DuckDBs, insbesondere keinen Vollhash von /state.
Ein aktiver Writer ohne sichtbaren Sidecar wird nur durch DuckDBs read-only-
Sperrverhalten erkannt; deshalb sind abgeschlossene Offlinekopien Voraussetzung.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import tempfile
from typing import Any
import uuid

import duckdb


LEGACY_BITGET_CONTEXT = {
    "context_version": "1",
    "export_timezone": "UTC+08:00",
    "timezone_basis": "legacy_default_unverified",
    "product_scope": "unspecified_legacy",
}


class SchemaComparisonError(ValueError):
    """Sicherer, datenfreier Fehlercode fuer API und CLI."""

    def __init__(
        self,
        code: str,
        table_id: str | None = None,
        input_sha256: dict[str, dict[str, str | None]] | None = None,
    ):
        super().__init__(code)
        self.code = code
        self.table_id = (
            table_id
            if table_id and re.fullmatch(r"table_[0-9]{4,}", table_id)
            else None
        )
        self.input_sha256 = input_sha256 or {
            "before": {"pre": None, "post": None},
            "after": {"pre": None, "post": None},
        }
        self.tables: list[dict[str, Any]] = []


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _table_sql(schema: str, table: str) -> str:
    return f"{_quote_identifier(schema)}.{_quote_identifier(table)}"


def _path_stat(path: Path) -> os.stat_result:
    if path.is_symlink():
        raise SchemaComparisonError("input_must_be_regular_temp_copy")
    try:
        resolved = path.resolve(strict=True)
        temp_root = Path(tempfile.gettempdir()).resolve(strict=True)
        resolved.relative_to(temp_root)
        info = resolved.stat(follow_symlinks=False)
    except SchemaComparisonError:
        raise
    except (OSError, ValueError):
        raise SchemaComparisonError("input_must_be_regular_temp_copy") from None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise SchemaComparisonError("input_must_be_regular_temp_copy")
    return info


def _stat_signature(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_mode,
    )


def _sha256_file(path: Path, expected_stat: os.stat_result) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as source:
            initial = os.fstat(source.fileno())
            if not stat.S_ISREG(initial.st_mode) or _stat_signature(
                initial
            ) != _stat_signature(expected_stat):
                raise SchemaComparisonError("input_changed_during_comparison")
            digest = hashlib.sha256()
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
            final = os.fstat(source.fileno())
            if _stat_signature(initial) != _stat_signature(final):
                raise SchemaComparisonError("input_changed_during_comparison")
            return digest.hexdigest()
    except SchemaComparisonError:
        raise
    except OSError:
        raise SchemaComparisonError("input_unreadable") from None


def _reject_active_sidecars(path: Path) -> None:
    exact = {".wal", ".tmp", ".lock", "-wal", "-shm"}
    prefixes = (".wal.", ".tmp.", "-wal.", "-shm.")
    try:
        with os.scandir(path.parent) as entries:
            for entry in entries:
                suffix = (
                    entry.name[len(path.name) :]
                    if entry.name.startswith(path.name)
                    else ""
                )
                if suffix in exact or suffix.startswith(prefixes):
                    raise SchemaComparisonError("active_database_state_detected")
    except SchemaComparisonError:
        raise
    except OSError:
        raise SchemaComparisonError("database_state_unverifiable") from None


def _table_names(connection: duckdb.DuckDBPyConnection) -> tuple[tuple[str, str], ...]:
    rows = connection.execute(
        """select table_schema, table_name from information_schema.tables
           where table_type='BASE TABLE'
             and table_schema not in ('information_schema', 'pg_catalog')
           order by table_schema, table_name"""
    ).fetchall()
    return tuple((str(schema), str(name)) for schema, name in rows)


def _reject_unsupported_persistent_objects(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    queries = {
        "views": """select count(*) from duckdb_views()
                     where not internal and not temporary
                       and schema_name not in ('information_schema', 'pg_catalog')""",
        "schemas": """select count(*) from duckdb_schemas()
                       where not internal and schema_name <> 'main'""",
        "sequences": """select count(*) from duckdb_sequences()
                          where not temporary
                            and schema_name not in ('information_schema', 'pg_catalog')""",
        "functions": """select count(*) from duckdb_functions()
                          where not internal
                            and schema_name not in ('information_schema', 'pg_catalog')""",
        "types": """select count(*) from duckdb_types()
                      where not internal
                        and schema_name not in ('information_schema', 'pg_catalog')""",
        "secrets": "select count(*) from duckdb_secrets() where persistent",
        "databases": "select count(*) from duckdb_databases() where not internal",
    }
    try:
        counts = {
            kind: int(connection.execute(query).fetchone()[0])
            for kind, query in queries.items()
        }
        table_sql = connection.execute(
            "select sql from duckdb_tables() where not internal and not temporary"
        ).fetchall()
    except Exception:
        raise SchemaComparisonError("persistent_object_catalog_unavailable") from None
    if any(not isinstance(row[0], str) or re.search(r"\bCOLLATE\b", row[0], re.IGNORECASE) for row in table_sql):
        raise SchemaComparisonError("unsupported_table_collation")
    if counts["views"]:
        raise SchemaComparisonError("unsupported_persistent_views")
    if counts["databases"] != 1 or any(
        counts[kind]
        for kind in ("schemas", "sequences", "functions", "types", "secrets")
    ):
        raise SchemaComparisonError("unsupported_persistent_objects")


def _columns(
    connection: duckdb.DuckDBPyConnection, schema: str, table: str
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """select column_name, data_type, is_nullable, column_default, ordinal_position
           from information_schema.columns
           where table_schema=? and table_name=?
           order by ordinal_position""",
        [schema, table],
    ).fetchall()
    return [
        {
            "name": str(name),
            "type": str(data_type),
            "nullable": str(nullable),
            "default": default,
            "position": int(position),
        }
        for name, data_type, nullable, default, position in rows
    ]


def _constraint_rows(
    connection: duckdb.DuckDBPyConnection,
) -> dict[tuple[str, str], list[tuple[Any, ...]]]:
    try:
        referential_rows = connection.execute(
            """select constraint_schema, constraint_name,
                      unique_constraint_schema, unique_constraint_name,
                      match_option, update_rule, delete_rule
               from information_schema.referential_constraints
               where constraint_schema not in ('information_schema', 'pg_catalog')"""
        ).fetchall()
        rows = connection.execute(
            """select schema_name, table_name, constraint_type, constraint_text,
                      expression, constraint_column_names, constraint_name,
                      referenced_table, referenced_column_names
               from duckdb_constraints()
               where schema_name not in ('information_schema', 'pg_catalog')"""
        ).fetchall()
    except Exception:
        raise SchemaComparisonError("constraint_catalog_unavailable") from None
    referential: dict[tuple[str, str], tuple[Any, ...]] = {}
    for (
        schema,
        name,
        target_schema,
        target_name,
        match,
        update,
        delete,
    ) in referential_rows:
        key = (str(schema), str(name))
        if key in referential:
            raise SchemaComparisonError("constraint_catalog_ambiguous")
        referential[key] = (
            target_schema,
            target_name,
            match,
            update,
            delete,
        )
    result: dict[tuple[str, str], list[tuple[Any, ...]]] = {}
    for (
        schema,
        table,
        constraint_type,
        constraint_text,
        expression,
        column_names,
        constraint_name,
        referenced_table,
        referenced_column_names,
    ) in rows:
        key = (str(schema), str(table))
        foreign_key_rules = None
        if constraint_type == "FOREIGN KEY":
            foreign_key_rules = referential.get((str(schema), str(constraint_name)))
            if foreign_key_rules is None:
                raise SchemaComparisonError("constraint_catalog_incomplete")
        signature = (
            str(constraint_type),
            constraint_text,
            expression,
            tuple(column_names or ()),
            constraint_name,
            referenced_table,
            tuple(referenced_column_names or ()),
            foreign_key_rules,
        )
        result.setdefault(key, []).append(signature)
    return result


def _index_rows(
    connection: duckdb.DuckDBPyConnection,
) -> dict[tuple[str, str], list[tuple[Any, ...]]]:
    try:
        rows = connection.execute(
            """select schema_name, table_name, index_name, comment, tags,
                      is_unique, is_primary, expressions, sql
               from duckdb_indexes()
               where schema_name not in ('information_schema', 'pg_catalog')"""
        ).fetchall()
    except Exception:
        raise SchemaComparisonError("index_catalog_unavailable") from None
    result: dict[tuple[str, str], list[tuple[Any, ...]]] = {}
    for schema, table, *details in rows:
        result.setdefault((str(schema), str(table)), []).append(tuple(details))
    return result


def _compare_catalog_rows(
    before_rows: dict[tuple[str, str], list[tuple[Any, ...]]],
    after_rows: dict[tuple[str, str], list[tuple[Any, ...]]],
    table_ids: dict[tuple[str, str], str],
    *,
    catalog: str,
) -> None:
    for key in sorted(set(before_rows) | set(after_rows)):
        if key not in table_ids:
            raise SchemaComparisonError(f"{catalog}_catalog_invalid")
        old = Counter(_row_digest(row) for row in before_rows.get(key, []))
        new = Counter(_row_digest(row) for row in after_rows.get(key, []))
        if old != new:
            raise SchemaComparisonError(f"{catalog}_changed", table_ids[key])


def _compare_constraints(
    before: duckdb.DuckDBPyConnection,
    after: duckdb.DuckDBPyConnection,
    table_ids: dict[tuple[str, str], str],
) -> None:
    old = _constraint_rows(before)
    new = _constraint_rows(after)
    target = ("main", "raw_import_batches")
    allowed = [
        row
        for row in new.get(target, [])
        if row[0:4] == ("NOT NULL", "NOT NULL", None, ("import_context_json",))
        and row[5:] == (None, (), None)
    ]
    if len(allowed) != 1:
        raise SchemaComparisonError("constraint_changed", table_ids.get(target))
    new[target].remove(allowed[0])
    _compare_catalog_rows(old, new, table_ids, catalog="constraint")


def _compare_indexes(
    before: duckdb.DuckDBPyConnection,
    after: duckdb.DuckDBPyConnection,
    table_ids: dict[tuple[str, str], str],
) -> None:
    _compare_catalog_rows(
        _index_rows(before), _index_rows(after), table_ids, catalog="index"
    )


def _typed(value: Any) -> Any:
    """Type-preserving canonical form; never rendered in reports or logs."""
    if value is None:
        return ["none"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, float):
        return ["float64", struct.pack("!d", value).hex()]
    if isinstance(value, Decimal):
        item = value.as_tuple()
        return ["decimal", item.sign, list(item.digits), str(item.exponent)]
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    if isinstance(value, bytearray | memoryview):
        return ["bytes", bytes(value).hex()]
    if isinstance(value, datetime):
        return ["datetime", value.isoformat(), value.fold]
    if isinstance(value, date):
        return ["date", value.isoformat()]
    if isinstance(value, time):
        return ["time", value.isoformat(), value.fold]
    if isinstance(value, timedelta):
        return ["timedelta", value.days, value.seconds, value.microseconds]
    if isinstance(value, uuid.UUID):
        return ["uuid", value.hex]
    if isinstance(value, list):
        return ["list", [_typed(item) for item in value]]
    if isinstance(value, tuple):
        return ["tuple", [_typed(item) for item in value]]
    if isinstance(value, dict):
        entries = [(_typed(key), _typed(item)) for key, item in value.items()]
        entries.sort(
            key=lambda item: json.dumps(
                item[0], separators=(",", ":"), ensure_ascii=True
            )
        )
        return ["dict", entries]
    raise SchemaComparisonError("unsupported_database_value_type")


def _row_digest(row: tuple[Any, ...]) -> str:
    encoded = json.dumps(_typed(row), separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
    return hashlib.sha256(encoded).hexdigest()


def _row_multiset(
    connection: duckdb.DuckDBPyConnection,
    schema: str,
    table: str,
    columns: list[str],
    *,
    normalize_schema_version: bool = False,
) -> Counter[str]:
    selection = ", ".join(_quote_identifier(column) for column in columns)
    query = f"select {selection} from {_table_sql(schema, table)}"
    cursor = connection.execute(query)
    result: Counter[str] = Counter()
    key_index = columns.index("key") if normalize_schema_version else -1
    value_index = columns.index("value") if normalize_schema_version else -1
    while batch := cursor.fetchmany(2048):
        for source_row in batch:
            row = tuple(source_row)
            if normalize_schema_version and row[key_index] == "schema_version":
                row = row[:value_index] + ("2",) + row[value_index + 1 :]
            result[_row_digest(row)] += 1
    return result


def _schema_version(connection: duckdb.DuckDBPyConnection, table_id: str | None) -> str:
    table = ("main", "schema_meta")
    if table not in _table_names(connection):
        raise SchemaComparisonError("schema_version_invalid", table_id)
    columns = [column["name"] for column in _columns(connection, *table)]
    if columns != ["key", "value"]:
        raise SchemaComparisonError("schema_version_invalid", table_id)
    try:
        rows = connection.execute(
            'select "value" from "main"."schema_meta" where "key"=?', ["schema_version"]
        ).fetchall()
    except Exception:
        raise SchemaComparisonError("schema_version_invalid", table_id) from None
    if len(rows) != 1 or not isinstance(rows[0][0], str):
        raise SchemaComparisonError("schema_version_invalid", table_id)
    return rows[0][0]


def _validate_legacy_contexts(
    connection: duckdb.DuckDBPyConnection, table_id: str | None
) -> None:
    try:
        rows = connection.execute(
            'select "source", "import_context_json" from "main"."raw_import_batches"'
        ).fetchall()
    except Exception:
        raise SchemaComparisonError("legacy_context_invalid", table_id) from None
    for source, raw_context in rows:
        try:
            context = json.loads(raw_context)
        except (TypeError, ValueError):
            raise SchemaComparisonError("legacy_context_invalid", table_id) from None
        expected = (
            LEGACY_BITGET_CONTEXT
            if isinstance(source, str) and source.casefold() == "bitget"
            else {}
        )
        if context != expected:
            raise SchemaComparisonError("legacy_context_invalid", table_id)


def _summaries(
    before: duckdb.DuckDBPyConnection,
    after: duckdb.DuckDBPyConnection,
    before_tables: tuple[tuple[str, str], ...],
    after_tables: tuple[tuple[str, str], ...],
    table_ids: dict[tuple[str, str], str],
) -> list[dict[str, Any]]:
    before_set, after_set = set(before_tables), set(after_tables)
    result = []
    for schema, table in sorted(before_set | after_set):
        sql = _table_sql(schema, table)
        before_count = (
            before.execute(f"select count(*) from {sql}").fetchone()[0]
            if (schema, table) in before_set
            else None
        )
        after_count = (
            after.execute(f"select count(*) from {sql}").fetchone()[0]
            if (schema, table) in after_set
            else None
        )
        result.append(
            {
                "id": table_ids[(schema, table)],
                "before_rows": int(before_count) if before_count is not None else None,
                "after_rows": int(after_count) if after_count is not None else None,
            }
        )
    return result


def compare_schema2_to3(
    before_path: str | os.PathLike[str], after_path: str | os.PathLike[str]
) -> dict[str, Any]:
    """Compare offline schema-2 and schema-3 copies without modifying either file."""
    before_file, after_file = Path(before_path), Path(after_path)
    input_sha256: dict[str, dict[str, str | None]] = {
        "before": {"pre": None, "post": None},
        "after": {"pre": None, "post": None},
    }
    before_stat: os.stat_result | None = None
    after_stat: os.stat_result | None = None
    before_resolved: Path | None = None
    after_resolved: Path | None = None
    connections: list[duckdb.DuckDBPyConnection] = []
    failure: SchemaComparisonError | None = None
    result: dict[str, Any] | None = None
    summaries: list[dict[str, Any]] = []
    table_ids: dict[tuple[str, str], str] = {}
    try:
        before_stat, after_stat = _path_stat(before_file), _path_stat(after_file)
        before_resolved = before_file.resolve(strict=True)
        after_resolved = after_file.resolve(strict=True)
        if before_resolved == after_resolved or (
            before_stat.st_dev,
            before_stat.st_ino,
        ) == (after_stat.st_dev, after_stat.st_ino):
            raise SchemaComparisonError("input_copies_must_be_distinct")

        _reject_active_sidecars(before_resolved)
        _reject_active_sidecars(after_resolved)
        input_sha256["before"]["pre"] = _sha256_file(before_resolved, before_stat)
        input_sha256["after"]["pre"] = _sha256_file(after_resolved, after_stat)
        _reject_active_sidecars(before_resolved)
        _reject_active_sidecars(after_resolved)

        try:
            before = duckdb.connect(str(before_resolved), read_only=True)
            connections.append(before)
            after = duckdb.connect(str(after_resolved), read_only=True)
            connections.append(after)
            before.execute("begin transaction")
            after.execute("begin transaction")
        except Exception:
            raise SchemaComparisonError("database_open_failed") from None

        _reject_unsupported_persistent_objects(before)
        _reject_unsupported_persistent_objects(after)
        before_tables = _table_names(before)
        after_tables = _table_names(after)
        table_keys = sorted(set(before_tables) | set(after_tables))
        table_ids = {
            key: f"table_{position:04d}"
            for position, key in enumerate(table_keys, start=1)
        }
        summaries = _summaries(before, after, before_tables, after_tables, table_ids)
        before_set, after_set = set(before_tables), set(after_tables)
        if before_set != after_set:
            raise SchemaComparisonError("table_set_changed")
        schema_meta_id = table_ids.get(("main", "schema_meta"))
        if (
            _schema_version(before, schema_meta_id) != "2"
            or _schema_version(after, schema_meta_id) != "3"
        ):
            raise SchemaComparisonError("schema_version_invalid", schema_meta_id)

        target = ("main", "raw_import_batches")
        if target not in before_set:
            raise SchemaComparisonError("table_missing")
        target_id = table_ids[target]

        before_columns = {table: _columns(before, *table) for table in before_tables}
        after_columns = {table: _columns(after, *table) for table in after_tables}
        for table in before_tables:
            old = before_columns[table]
            new = after_columns[table]
            old_shape = [
                (
                    column["name"],
                    column["type"],
                    column["nullable"],
                    column["default"],
                    column["position"],
                )
                for column in old
            ]
            new_shape = [
                (
                    column["name"],
                    column["type"],
                    column["nullable"],
                    column["default"],
                    column["position"],
                )
                for column in new
            ]
            if table == target:
                if any(column[0] == "import_context_json" for column in old_shape):
                    raise SchemaComparisonError("schema2_shape_invalid", target_id)
                expected_context = (
                    "import_context_json",
                    "VARCHAR",
                    "NO",
                    "'{}'",
                    len(old_shape) + 1,
                )
                if new_shape != old_shape + [expected_context]:
                    raise SchemaComparisonError("column_schema_changed", target_id)
            elif old_shape != new_shape:
                raise SchemaComparisonError("column_schema_changed", table_ids[table])

        _compare_constraints(before, after, table_ids)
        _compare_indexes(before, after, table_ids)
        _validate_legacy_contexts(after, target_id)

        for schema, table in before_tables:
            key = (schema, table)
            old_names = [column["name"] for column in before_columns[key]]
            compare_names = old_names
            normalize_version = key == ("main", "schema_meta")
            if normalize_version and not {"key", "value"}.issubset(compare_names):
                raise SchemaComparisonError("schema_version_invalid", schema_meta_id)
            old_rows = _row_multiset(before, schema, table, compare_names)
            new_rows = _row_multiset(
                after,
                schema,
                table,
                compare_names,
                normalize_schema_version=normalize_version,
            )
            if old_rows != new_rows:
                raise SchemaComparisonError("row_multiset_changed", table_ids[key])

        result = {
            "status": "passed",
            "before_schema_version": 2,
            "after_schema_version": 3,
            "tables": summaries,
        }
    except SchemaComparisonError as exc:
        failure = exc
    except Exception:
        # Database diagnostics can contain SQL, paths, or values; never echo them.
        failure = SchemaComparisonError("database_read_failed")
    finally:
        for connection in reversed(connections):
            try:
                connection.close()
            except Exception:
                failure = failure or SchemaComparisonError("database_close_failed")

    if before_resolved is not None and before_stat is not None:
        try:
            _reject_active_sidecars(before_resolved)
            current_stat = _path_stat(before_resolved)
            if input_sha256["before"]["pre"] is not None:
                current_hash = _sha256_file(before_resolved, current_stat)
                input_sha256["before"]["post"] = current_hash
                if (
                    _stat_signature(current_stat) != _stat_signature(before_stat)
                    or current_hash != input_sha256["before"]["pre"]
                ):
                    raise SchemaComparisonError("input_changed_during_comparison")
        except SchemaComparisonError as exc:
            if exc.code in {
                "active_database_state_detected",
                "database_state_unverifiable",
            }:
                failure = exc
            else:
                failure = SchemaComparisonError("input_changed_during_comparison")
    if after_resolved is not None and after_stat is not None:
        try:
            _reject_active_sidecars(after_resolved)
            current_stat = _path_stat(after_resolved)
            if input_sha256["after"]["pre"] is not None:
                current_hash = _sha256_file(after_resolved, current_stat)
                input_sha256["after"]["post"] = current_hash
                if (
                    _stat_signature(current_stat) != _stat_signature(after_stat)
                    or current_hash != input_sha256["after"]["pre"]
                ):
                    raise SchemaComparisonError("input_changed_during_comparison")
        except SchemaComparisonError as exc:
            if exc.code in {
                "active_database_state_detected",
                "database_state_unverifiable",
            }:
                failure = exc
            else:
                failure = SchemaComparisonError("input_changed_during_comparison")

    if failure is not None:
        failure.input_sha256 = input_sha256.copy()
        if failure.table_id:
            failure.tables = [
                item for item in summaries if item["id"] == failure.table_id
            ]
        else:
            failure.tables = summaries
        raise failure
    assert result is not None
    result["input_sha256"] = input_sha256
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--before",
        required=True,
        help="Offline-DuckDB-Kopie mit Schema 2 unter dem Temp-Verzeichnis",
    )
    parser.add_argument(
        "--after",
        required=True,
        help="Offline-DuckDB-Kopie mit Schema 3 unter dem Temp-Verzeichnis",
    )
    args = parser.parse_args(argv)
    try:
        result = compare_schema2_to3(args.before, args.after)
    except SchemaComparisonError as exc:
        result = {
            "status": "failed",
            "code": exc.code,
            "tables": getattr(exc, "tables", []),
            "input_sha256": exc.input_sha256,
        }
    except Exception:
        result = {
            "status": "failed",
            "code": "comparison_internal_error",
            "tables": [],
            "input_sha256": {
                "before": {"pre": None, "post": None},
                "after": {"pre": None, "post": None},
            },
        }
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
