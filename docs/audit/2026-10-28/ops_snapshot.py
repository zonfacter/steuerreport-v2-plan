"""Privater Vollvergleich, ohne Datensaetze oder Geheimnisse auszugeben."""
import base64
import datetime
import decimal
import hashlib
import json
import os
from pathlib import Path
import uuid

import duckdb


def encode(value):
    if isinstance(value, bytes):
        return {"bytes": base64.b64encode(value).decode("ascii")}
    if isinstance(value, (datetime.date, datetime.time, decimal.Decimal, uuid.UUID)):
        return {type(value).__name__: str(value)}
    if isinstance(value, datetime.timedelta):
        return {"timedelta": str(value)}
    raise TypeError(type(value).__name__)


def packed(value):
    return json.dumps(value, default=encode, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":")).encode("ascii")


def snapshot():
    root = Path(os.environ.get("STEUERREPORT_STATE_DIR", "/state"))
    path = Path(os.environ.get("STEUERREPORT_V2_DB", str(root / "data/steuerreport_v2.duckdb")))
    result = {"tables": {}, "files": {}, "database_present": path.exists()}
    if path.exists():
        con = duckdb.connect(str(path), read_only=True)
        try:
            con.execute("begin transaction")
            tables = con.execute("select table_schema, table_name from information_schema.tables "
                                 "where table_type='BASE TABLE' and table_schema not in "
                                 "('information_schema','pg_catalog') order by 1,2").fetchall()
            for schema, name in tables:
                quoted = '.'.join('"' + p.replace('"', '""') + '"' for p in (schema, name))
                cursor = con.execute("select * from " + quoted)
                description = [(column[0], str(column[1])) for column in cursor.description]
                rows = []
                while batch := cursor.fetchmany(4096):
                    rows.extend(hashlib.sha256(packed(row)).digest() for row in batch)
                digest = hashlib.sha256(packed(description))
                for row in sorted(rows):
                    digest.update(row)
                result["tables"][schema + "." + name] = {
                    "rows": len(rows), "sha256": digest.hexdigest(), "columns": description}
            con.execute("commit")
        finally:
            con.close()
    # DB/WAL niemals als vermeintlich konsistente Dateikopie verwenden.
    for item in sorted(root.rglob("*")):
        if item.is_symlink() or not item.is_file():
            continue
        if item == path or item.suffix in {".wal", ".lock"}:
            continue
        digest = hashlib.sha256()
        with item.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        result["files"][str(item.relative_to(root))] = digest.hexdigest()
    return result


if __name__ == "__main__":
    print(json.dumps(snapshot(), sort_keys=True))
