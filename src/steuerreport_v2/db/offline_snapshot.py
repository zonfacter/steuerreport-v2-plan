"""Explizite Offline-Kopie einer sauberen DuckDB, niemals ein Live-Restore."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

import duckdb


class OfflineDatabaseCloneError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class OfflineDatabaseCloneResult:
    source_sha256: str
    target_sha256: str
    size_bytes: int
    table_count: int


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sidecars(path: Path) -> bool:
    return any(os.path.lexists(str(path) + suffix) for suffix in (".wal", ".tmp"))


def _no_symlinks(path: Path) -> None:
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise OfflineDatabaseCloneError("symlink_not_allowed")


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _validate_tables(connection: duckdb.DuckDBPyConnection) -> int:
    tables = connection.execute(
        "select schema_name, table_name from duckdb_tables() where not internal"
    ).fetchall()
    for schema, table in tables:
        # Fetch every persisted value without materializing a whole table in Python.
        rows = connection.execute(f"select * from {_identifier(schema)}.{_identifier(table)}")
        while rows.fetchmany(1024):
            pass
    return len(tables)


def _clone_offline_database(
    source: Path, destination: Path, *, expected_sha256: str | None = None,
) -> OfflineDatabaseCloneResult:
    """Copy under DuckDB's read-only lock; publish only to an unused local path.

    Source and destination must be on a trusted local filesystem. Existing WALs
    are refused, not replayed/checkpointed. This copies no profiles, raw files,
    artifacts or vault keys and is not an application backup or schema migration.
    """
    source = Path(source).expanduser().absolute()
    destination = Path(destination).expanduser().absolute()
    if any(part.endswith((".wal", ".tmp")) for path in (source, destination) for part in path.parts):
        raise OfflineDatabaseCloneError("reserved_sidecar_path")
    if expected_sha256 is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise OfflineDatabaseCloneError("invalid_expected_sha256")
    _no_symlinks(source)
    _no_symlinks(destination)
    try:
        original_stat = source.stat()
    except OSError:
        raise OfflineDatabaseCloneError("source_unavailable") from None
    if not stat.S_ISREG(original_stat.st_mode) or original_stat.st_nlink != 1:
        raise OfflineDatabaseCloneError("source_not_unique_regular_file")
    if _sidecars(source):
        raise OfflineDatabaseCloneError("source_pending_state")
    if os.path.lexists(destination):
        raise OfflineDatabaseCloneError("destination_exists")
    if _sidecars(destination):
        raise OfflineDatabaseCloneError("destination_pending_state")
    if not destination.parent.is_dir():
        raise OfflineDatabaseCloneError("destination_parent_unavailable")

    temporary: Path | None = None
    published = False
    try:
        # No DuckDbStore: opening must not create/migrate the source schema.
        with duckdb.connect(str(source), read_only=True, config={"enable_external_access": False}) as con, source.open("rb") as input_stream:
            if _sidecars(source):
                raise OfflineDatabaseCloneError("source_pending_state")
            current_stat = source.stat()
            if _identity(current_stat) != _identity(original_stat) or _identity(os.fstat(input_stream.fileno())) != _identity(current_stat):
                raise OfflineDatabaseCloneError("source_changed")
            table_count = _validate_tables(con)
            descriptor, name = tempfile.mkstemp(prefix=".steuerreport-offline-", suffix=".duckdb", dir=destination.parent)
            temporary = Path(name)
            digest = hashlib.sha256()
            # POSIX record locks can be released when ANY source fd is closed.
            # Keep this one stream open through validation and publication.
            with os.fdopen(descriptor, "wb") as output:
                while chunk := input_stream.read(1024 * 1024):
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            source_hash = digest.hexdigest()
            if expected_sha256 is not None and source_hash != expected_sha256.lower():
                raise OfflineDatabaseCloneError("source_hash_mismatch")
            input_stream.seek(0)
            second_source_hash = hashlib.file_digest(input_stream, "sha256").hexdigest()
            if _identity(source.stat()) != _identity(current_stat) or _sidecars(source) or second_source_hash != source_hash:
                raise OfflineDatabaseCloneError("source_changed")
            target_hash = _digest(temporary)
            if target_hash != source_hash:
                raise OfflineDatabaseCloneError("copy_hash_mismatch")
            with duckdb.connect(str(temporary), read_only=True, config={"enable_external_access": False}) as copied:
                if _validate_tables(copied) != table_count:
                    raise OfflineDatabaseCloneError("copy_validation_failed")
                if os.path.lexists(destination) or _sidecars(destination):
                    raise OfflineDatabaseCloneError("destination_changed")
                # Keep the copy locked through publication: its hard link is
                # the same inode, so a target writer must still be refused.
                os.link(temporary, destination)
                published = True
                if _sidecars(destination):
                    raise OfflineDatabaseCloneError("publication_state_unknown")
                directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            return OfflineDatabaseCloneResult(source_hash, target_hash, current_stat.st_size, table_count)
    except OfflineDatabaseCloneError:
        raise
    except (OSError, duckdb.Error):
        code = "publication_state_unknown" if published else "offline_clone_failed"
        raise OfflineDatabaseCloneError(code) from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                code = "publication_state_unknown" if published else "temporary_cleanup_failed"
                raise OfflineDatabaseCloneError(code) from None


def clone_offline_database(
    source: Path, destination: Path, *, expected_sha256: str | None = None,
) -> OfflineDatabaseCloneResult:
    """Run the copy in its own process, preserving other callers' POSIX locks."""
    request = {"source": str(Path(source).expanduser().absolute()),
               "destination": str(Path(destination).expanduser().absolute()), "expected_sha256": expected_sha256}
    try:
        response = subprocess.run(
            [sys.executable, "-I", str(Path(__file__).resolve()), "--_worker"],
            input=json.dumps(request), capture_output=True, text=True,
        )
        result = json.loads(response.stdout)
    except (OSError, ValueError):
        raise OfflineDatabaseCloneError("worker_state_unknown") from None
    if not isinstance(result, dict):
        raise OfflineDatabaseCloneError("worker_state_unknown")
    if response.returncode == 2 and result.get("status") == "blocked":
        code = result.get("reason")
        if isinstance(code, str) and re.fullmatch(r"[a-z0-9_]{1,80}", code):
            raise OfflineDatabaseCloneError(code)
    if response.returncode != 0 or result.get("status") != "verified":
        raise OfflineDatabaseCloneError("worker_state_unknown")
    try:
        values = OfflineDatabaseCloneResult(**result["result"])
    except (KeyError, TypeError):
        raise OfflineDatabaseCloneError("worker_state_unknown") from None
    if (not isinstance(values.source_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", values.source_sha256)
            or values.source_sha256 != values.target_sha256
            or type(values.size_bytes) is not int or values.size_bytes < 0
            or type(values.table_count) is not int or values.table_count < 0):
        raise OfflineDatabaseCloneError("worker_state_unknown")
    return values


def _worker_main() -> int:
    try:
        request = json.load(sys.stdin)
        result = _clone_offline_database(Path(request["source"]), Path(request["destination"]),
                                         expected_sha256=request.get("expected_sha256"))
    except OfflineDatabaseCloneError as exc:
        print(json.dumps({"status": "blocked", "reason": exc.code}))
        return 2
    except Exception:
        print(json.dumps({"status": "blocked", "reason": "worker_state_unknown"}))
        return 2
    print(json.dumps({"status": "verified", "result": asdict(result)}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--expected-sha256", help="Erwarteter Sicherungshash fuer Wiederherstellung in ein neues Ziel")
    args = parser.parse_args()
    try:
        result = clone_offline_database(args.source, args.destination, expected_sha256=args.expected_sha256)
    except OfflineDatabaseCloneError as exc:
        print(json.dumps({"status": "blocked", "reason": exc.code,
                          "existing_files_overwritten": False, "scope": "database_only"}))
        return 2
    print(json.dumps({"status": "verified", "scope": "database_only", "existing_files_overwritten": False,
                      **asdict(result)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_worker_main() if sys.argv[1:] == ["--_worker"] else main())
