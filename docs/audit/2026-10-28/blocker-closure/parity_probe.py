"""Nur lesende Datenparitaet, keine Appimporte/Schema-/Preis-/Steuerberechnung.

Private HMAC-Multimengen erkennen Inhaltsaenderungen trotz gleicher Counts.
Ereignis-/Raw-/Entscheidungsidentitaeten bleiben erhalten. Nur bekannte neu
erzeugte Preis-/Lot-/Tax-Line-IDs werden in V2-Semantik ersetzt, nicht blind
weggeworfen. Strikte Fingerprints behalten ausnahmslos alle Spalten.
"""
from collections import Counter
from contextlib import contextmanager
from datetime import date, datetime, time, timezone
from decimal import Decimal
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3


def typed(value):
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("nonfinite_decimal")
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return {"decimal": "0" if value == 0 else text}
    if isinstance(value, datetime):
        value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        return {"utc": value.isoformat()}
    if isinstance(value, (date, time)):
        return {type(value).__name__: value.isoformat()}
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if isinstance(value, dict):
        return {str(k): typed(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [typed(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError("unsupported_value_type")


def packed(value):
    return json.dumps(typed(value), sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False).encode("ascii")


def tag(key, value):
    return hmac.new(key, packed(value), hashlib.sha256).hexdigest()


def bag_add(bag, key, value):
    bag[tag(key, value)] += 1


def bag_summary(bag, key):
    return {"count": sum(bag.values()), "distinct": len(bag),
            "hmac_sha256": tag(key, sorted(bag.items())), "bag": dict(bag)}


def compare_bags(left, right):
    a, b = Counter(left["bag"]), Counter(right["bag"])
    return {"equal": a == b, "left_count": sum(a.values()), "right_count": sum(b.values()),
            "common_rows": sum((a & b).values()), "left_only_rows": sum((a-b).values()),
            "right_only_rows": sum((b-a).values()),
            "left_hmac": left["hmac_sha256"], "right_hmac": right["hmac_sha256"]}


def parsed(value):
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value, parse_float=Decimal)
    except (ValueError, TypeError):
        return {"unparsed_json": value}


def semantic_json_columns(row):
    return {k: parsed(v) if k.endswith("_json") else v for k, v in row.items()}


def quote(name):
    return '"' + name.replace('"', '""') + '"'


@contextmanager
def read_connection(path, backend):
    path = Path(path).resolve(strict=True)
    if backend == "sqlite-v1":
        # mode=ro liest ggf. vorhandenes WAL; immutable=1 wuerde WAL ignorieren.
        con = sqlite3.connect(path.as_uri()+"?mode=ro", uri=True, timeout=5)
        con.execute("pragma query_only=on")
    elif backend == "duckdb-v2":
        import duckdb
        con = duckdb.connect(str(path), read_only=True)
    else:
        raise ValueError("unknown_backend")
    try:
        con.execute("begin transaction")
        yield con
    finally:
        con.rollback()
        con.close()


def rows(con, table):
    cursor = con.execute("select * from " + quote(table))
    names = [x[0] for x in cursor.description]
    while batch := cursor.fetchmany(512):
        for row in batch:
            yield dict(zip(names, row))


def file_identity(path):
    p = Path(path)
    s = p.stat()
    return {"device": s.st_dev, "inode": s.st_ino, "size": s.st_size,
            "mtime_ns": s.st_mtime_ns}


def sidecars(path):
    return {suffix: file_identity(str(path)+suffix) if Path(str(path)+suffix).exists() else None
            for suffix in ("-wal", "-shm", "-journal", ".wal")}


def v2_semantic(table, row, lot_anchors):
    row = semantic_json_columns(row)
    if table == "price_ledger":
        return {k:v for k,v in row.items() if k not in {"price_id", "created_at"}}
    if table in {"tax_lots", "tax_lines"}:
        excluded = {"created_at", "lot_id" if table == "tax_lots" else "tax_line_id"}
        output = {k:v for k,v in row.items() if k not in excluded}
        for column in ("lot_id",):
            if column in output and output[column] is not None:
                ref = str(output[column])
                output[column] = {"lot_content": lot_anchors[ref]} if ref in lot_anchors else {"unresolved_lot_id": ref}
        return output
    return row


GROUPS = {
    "sqlite-v1": {
        "raw": ["source_files", "raw_events"], "events": ["raw_events", "product_position_events"],
        "reviews": ["settings", "transfer_matches"], "prices": ["fx_cache"], "lots": [],
        "tax_lines": ["tax_lines", "derivative_lines"],
        "methods": ["ruleset_catalog", "processing_queue", "report_integrity", "settings"],
        "archives": ["report_snapshots", "report_integrity"]},
    "duckdb-v2": {
        "raw": ["raw_import_batches", "raw_objects"], "events": ["canonical_events"],
        "reviews": ["review_decisions", "review_issues", "admin_settings"], "prices": ["price_ledger"],
        "lots": ["tax_lots", "tax_unmatched_disposals"], "tax_lines": ["tax_lines", "derivative_lines"],
        "methods": ["admin_settings", "tax_run_summaries"],
        "archives": ["tax_filing_snapshots", "tax_filing_snapshot_files", "tax_filing_snapshot_events", "export_packages"]}}


def numeric(value):
    return None if value is None or value == "" else Decimal(str(value))


def utc(value):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return typed(value)
    try:
        return typed(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (ValueError, TypeError):
        return {"unparsed_time": value}


def tax_projection(row, backend, lot_anchors):
    if backend == "sqlite-v1":
        columns = ("asset", "qty", "buy_timestamp_utc", "sell_timestamp_utc", "cost_basis_eur",
                   "proceeds_eur", "gain_loss_eur", "source_event_id", "lot_source_event_id")
    else:
        row = dict(row)
        if not row.get("acquisition_source_event_id") and row.get("lot_id") in lot_anchors:
            row["acquisition_source_event_id"] = lot_anchors[row["lot_id"]]["source_event_id"]
        columns = ("asset", "quantity", "acquired_at", "disposed_at", "acquisition_cost_eur",
                   "disposal_proceeds_eur", "gain_loss_eur", "source_event_id", "acquisition_source_event_id")
    values = [row.get(k) for k in columns]
    return {"asset":values[0], "quantity":numeric(values[1]), "acquired_at":utc(values[2]),
            "disposed_at":utc(values[3]), "cost_eur":numeric(values[4]), "proceeds_eur":numeric(values[5]),
            "gain_eur":numeric(values[6]), "disposal_event_ref":values[7], "acquisition_event_ref":values[8]}


def snapshot(path, backend, key):
    path = Path(path).resolve(strict=True)
    before = file_identity(path)
    before_sidecars = sidecars(path)
    result = {"backend":backend, "database_identity":before, "sidecars_before":before_sidecars,
              "tables":{}, "dimensions":{}, "projections":{}, "notes":[]}
    originals, tax_core, raw_nested = Counter(), Counter(), Counter()
    v1_shapes = Counter()
    with read_connection(path, backend) as con:
        if backend == "sqlite-v1":
            names = [x[0] for x in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name").fetchall()]
        else:
            names = [x[0] for x in con.execute("select table_name from information_schema.tables where table_schema='main' and table_type='BASE TABLE' order by 1").fetchall()]
        lot_anchors = {}
        if backend == "duckdb-v2" and "tax_lots" in names:
            for row in rows(con, "tax_lots"):
                lot_anchors[str(row["lot_id"])] = {k:row.get(k) for k in (
                    "asset", "acquired_at", "quantity_total", "cost_basis_eur_total", "source_event_id", "pool_id", "fifo_method", "origin_lot_id")}
        for table in names:
            strict, semantic = Counter(), Counter()
            columns = [(x[1],str(x[2])) for x in con.execute("pragma table_info("+quote(table)+")").fetchall()]
            for row in rows(con, table):
                bag_add(strict, key, row)
                transformed = v2_semantic(table,row,lot_anchors) if backend == "duckdb-v2" else semantic_json_columns(row)
                bag_add(semantic,key,transformed)
                if (backend,table) in {("sqlite-v1","raw_events"),("duckdb-v2","raw_objects")}:
                    payload = parsed(row["payload_json"])
                    bag_add(raw_nested,key,payload)
                    if backend == "duckdb-v2":
                        bag_add(originals,key,payload)
                    elif isinstance(payload,dict) and isinstance(payload.get("raw_row"),dict):
                        bag_add(originals,key,payload["raw_row"])
                if table == "tax_lines":
                    bag_add(tax_core,key,tax_projection(row,backend,lot_anchors))
                if backend == "sqlite-v1" and table in {"processing_queue", "report_snapshots"}:
                    payload = parsed(row.get("result_json") if table == "processing_queue" else row.get("payload_json"))
                    if isinstance(payload,dict):
                        inventory = payload.get("inventory_end")
                        v1_shapes["inventory_end_scalar_map"] += int(isinstance(inventory,dict) and all(not isinstance(v,(dict,list)) for v in inventory.values()))
                        v1_shapes["top_level_lots_or_lot_rows"] += int(any(isinstance(payload.get(k),list) for k in ("lots", "lot_rows", "tax_lots")))
            result["tables"][table] = {"columns":columns,"strict":bag_summary(strict,key),
                                        "semantic":bag_summary(semantic,key)}
        result["projections"] = {"raw_original_payloads":bag_summary(originals,key),
                                  "raw_stored_json":bag_summary(raw_nested,key),
                                  "tax_amount_time_event_refs":bag_summary(tax_core,key)}
    for group, tables in GROUPS[backend].items():
        present = {table: {"count": result["tables"][table]["strict"]["count"],
                            "strict_hmac":result["tables"][table]["strict"]["hmac_sha256"],
                            "semantic_hmac":result["tables"][table]["semantic"]["hmac_sha256"]}
                   for table in tables if table in result["tables"]}
        result["dimensions"][group] = {"available":bool(present), "tables":present,
                                          "representation":backend+":"+group}
    if backend == "sqlite-v1":
        result["v1_payload_shape_counts"] = dict(v1_shapes)
        result["notes"] = ["source_hash is normalized import payload fingerprint, not original file bytes",
            "raw_events contains normalized payload; raw_row is a partial original-row projection",
            "no persisted individual lot table; inventory_end aggregates cannot prove original lot bases/dates",
            "review/settings, rule/job catalog and JSON archives are not isomorphic to V2",
            "fx_cache currency pairs and reference days are not implicitly EUR PricePoints"]
    result["database_identity_after"] = file_identity(path)
    result["sidecars_after"] = sidecars(path)
    result["file_metadata_unchanged_during_read"] = before == result["database_identity_after"] and before_sidecars == result["sidecars_after"]
    archives = Counter()
    roots = [path.parent / "tax_filing_archive", path.parent / ".steuerreport_v2_cache/tax_year_evidence_package"] if backend == "duckdb-v2" else []
    result["archive_roots"] = {str(root):root.is_dir() and not root.is_symlink() for root in roots}
    for root in roots:
        if not root.is_dir() or root.is_symlink():
            continue
        for item in sorted(root.rglob("*.zip")):
            if item.is_symlink() or not item.is_file():
                continue
            start = file_identity(item)
            digest = hmac.new(key,digestmod=hashlib.sha256)
            with item.open("rb") as handle:
                for chunk in iter(lambda:handle.read(1024*1024),b""):
                    digest.update(chunk)
            if file_identity(item) != start:
                raise RuntimeError("archive_changed_during_read")
            bag_add(archives,key,{"root_kind":root.name,"path":str(item.relative_to(root)),"content_hmac":digest.hexdigest()})
    result["archive_file_bag"] = bag_summary(archives,key)
    return result


def compare(left, right):
    output = {"dimensions":{}, "projections":{}, "common_tables":{}, "engine_parity_proven":False,
              "engine_limit":"No replay with bound identical inputs and methods; stored data is not engine equivalence."}
    for group in GROUPS[left["backend"]]:
        a,b=left["dimensions"][group],right["dimensions"][group]
        status = "same_representation" if a["representation"] == b["representation"] else "different_models"
        if not a["available"] or not b["available"]:
            status="unavailable_not_equal_to_empty"
        output["dimensions"][group] = {"status":status,"left":a,"right":b}
    for name in left["projections"].keys() & right["projections"].keys():
        output["projections"][name]=compare_bags(left["projections"][name],right["projections"][name])
    for table in left["tables"].keys() & right["tables"].keys():
        a,b=left["tables"][table],right["tables"][table]
        output["common_tables"][table] = {"same_schema":a["columns"]==b["columns"],
                                           "strict":compare_bags(a["strict"],b["strict"]),
                                           "semantic":compare_bags(a["semantic"],b["semantic"])}
    output["inputs_equal_proven"] = (left["backend"] == right["backend"] and
        all(output["projections"][x]["equal"] for x in ("raw_original_payloads","raw_stored_json")) and
        all(left["tables"].get(t)==right["tables"].get(t) for t in GROUPS[left["backend"]]["raw"]))
    return output
