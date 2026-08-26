#!/usr/bin/env python3
"""Create and verify a compact, logically identical DuckDB database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _catalog(con: duckdb.DuckDBPyConnection, database: str) -> list[tuple[Any, ...]]:
    return con.execute(
        """
        select schema_name, table_name, sql, has_primary_key, column_count,
               check_constraint_count
          from duckdb_tables()
         where database_name = ?
         order by schema_name, table_name
        """,
        [database],
    ).fetchall()


def _object_counts(con: duckdb.DuckDBPyConnection, database: str) -> dict[str, int]:
    queries = {
        "tables": "select count(*) from duckdb_tables() where database_name = ?",
        "views": (
            "select count(*) from duckdb_views() "
            "where database_name = ? and not internal"
        ),
        "indexes": "select count(*) from duckdb_indexes() where database_name = ?",
        "sequences": "select count(*) from duckdb_sequences() where database_name = ?",
        "types": (
            "select count(*) from duckdb_types() "
            "where database_name = ? and not internal"
        ),
    }
    return {
        name: int(con.execute(query, [database]).fetchone()[0])
        for name, query in queries.items()
    }


def _verify_tables(
    con: duckdb.DuckDBPyConnection,
    source_database: str,
    target_database: str,
    catalog: list[tuple[Any, ...]],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for schema_name, table_name, *_ in catalog:
        source = (
            f"{_identifier(source_database)}.{_identifier(schema_name)}."
            f"{_identifier(table_name)}"
        )
        target = (
            f"{_identifier(target_database)}.{_identifier(schema_name)}."
            f"{_identifier(table_name)}"
        )
        source_count = int(con.execute(f"select count(*) from {source}").fetchone()[0])
        target_count = int(con.execute(f"select count(*) from {target}").fetchone()[0])
        source_only = int(
            con.execute(
                f"select count(*) from ((select * from {source}) "
                f"except all (select * from {target}))"
            ).fetchone()[0]
        )
        target_only = int(
            con.execute(
                f"select count(*) from ((select * from {target}) "
                f"except all (select * from {source}))"
            ).fetchone()[0]
        )
        if source_count != target_count or source_only or target_only:
            raise RuntimeError(
                f"Table mismatch for {schema_name}.{table_name}: "
                f"source={source_count}, target={target_count}, "
                f"source_only={source_only}, target_only={target_only}"
            )
        results.append(
            {
                "schema": schema_name,
                "table": table_name,
                "rows": source_count,
                "source_only_rows": source_only,
                "target_only_rows": target_only,
            }
        )
    return results


def compact(source: Path, target: Path, report_path: Path) -> dict[str, Any]:
    source = source.resolve()
    target = target.resolve()
    report_path = report_path.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if target.exists():
        raise FileExistsError(target)
    if source == target:
        raise ValueError("Source and target must differ")

    target.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    source_stat_before = source.stat()
    source_sha256 = _sha256(source)

    con = duckdb.connect(":memory:")
    try:
        con.execute(
            f"attach {_literal(str(source))} as source_db (read_only)"
        )
        con.execute(f"attach {_literal(str(target))} as compact_db")
        source_catalog = _catalog(con, "source_db")
        source_objects = _object_counts(con, "source_db")
        con.execute("copy from database source_db to compact_db")
        con.execute("checkpoint compact_db")

        target_catalog = _catalog(con, "compact_db")
        target_objects = _object_counts(con, "compact_db")
        if source_catalog != target_catalog:
            raise RuntimeError("Catalog mismatch between source and compact database")
        if source_objects != target_objects:
            raise RuntimeError(
                f"Database object mismatch: {source_objects} != {target_objects}"
            )
        tables = _verify_tables(con, "source_db", "compact_db", source_catalog)
        con.execute("detach compact_db")
        con.execute("detach source_db")
    except Exception:
        con.close()
        target.unlink(missing_ok=True)
        raise
    con.close()

    source_stat_after = source.stat()
    if (
        source_stat_before.st_size != source_stat_after.st_size
        or source_stat_before.st_mtime_ns != source_stat_after.st_mtime_ns
    ):
        target.unlink(missing_ok=True)
        raise RuntimeError("Source database changed during compaction")

    with target.open("rb") as handle:
        os.fsync(handle.fileno())
    report = {
        "status": "verified",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source": str(source),
        "source_size_bytes": source_stat_before.st_size,
        "source_sha256": source_sha256,
        "target": str(target),
        "target_size_bytes": target.stat().st_size,
        "target_sha256": _sha256(target),
        "bytes_saved_after_swap": source_stat_before.st_size - target.stat().st_size,
        "database_objects": source_objects,
        "tables": tables,
        "verification": {
            "catalog_equal": True,
            "database_objects_equal": True,
            "row_counts_equal": True,
            "bidirectional_except_all_empty": True,
            "source_unchanged_during_copy": True,
        },
    }
    temporary_report = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary_report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary_report, report_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = compact(args.source, args.target, args.report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
