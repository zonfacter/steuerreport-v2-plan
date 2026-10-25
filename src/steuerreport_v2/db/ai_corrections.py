"""Fixed, parameterized correction operations; never accept SQL from a model."""
from __future__ import annotations

import hashlib
import json


TABLES = {"event": ("canonical_events", "event_id"), "price": ("price_ledger", "price_id")}
FIELDS = {
    "event": {"event_time", "event_type", "asset", "quantity", "quote_asset", "quote_quantity", "fee_asset", "fee_quantity", "wallet", "account"},
    "price": {"price_eur", "confidence"},
}


class CorrectionConflict(ValueError):
    pass


def encoded(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return None if value is None else str(value)


def json_text(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(value):
    return hashlib.sha256(json_text(value).encode()).hexdigest()


def record(con, kind, target_id):
    table, key = TABLES[kind]
    cursor = con.execute(f"select * from {table} where {key} = ?", [target_id])
    names = [item[0] for item in cursor.description]
    row = cursor.fetchone()
    return dict(zip(names, map(encoded, row))) if row else None


def update(con, kind, target_id, patch):
    if not patch or not set(patch) <= FIELDS[kind]:
        raise ValueError("ai_change_field_not_allowed")
    table, key = TABLES[kind]
    names = sorted(patch)
    con.execute(f"update {table} set {', '.join(name + ' = ?' for name in names)} where {key} = ?",
                [*[patch[name] for name in names], target_id])


def replay(con, *, event_ids=None):
    corrected_records = {}
    where = "where original_json <> corrected_json"
    if event_ids is not None:
        where += " and kind = 'event' and target_id in (select unnest(?))"
    rows = con.execute(f"select kind, target_id, original_json, corrected_json from ai_correction_overrides {where}",
                       [] if event_ids is None else [event_ids]).fetchall()
    for kind, target_id, original_json, corrected_json in rows:
        current = record(con, kind, target_id)
        if current is None:
            raise CorrectionConflict("ai_correction_target_missing")
        original, corrected = json.loads(original_json), json.loads(corrected_json)
        patch = {key: corrected[key] for key in FIELDS[kind] if corrected[key] != original[key]}
        # A reimport may restore the original. Unrelated edits must not be lost.
        for key in current:
            if current[key] not in (original[key], corrected[key]):
                raise CorrectionConflict("ai_correction_replay_conflict")
        if patch:
            update(con, kind, target_id, patch)
            corrected_records[target_id] = record(con, kind, target_id)
    return corrected_records


def conflicts(con):
    issues = []
    rows = con.execute("select kind, target_id, original_json, corrected_json from ai_correction_overrides where original_json <> corrected_json").fetchall()
    for kind, target_id, original_json, corrected_json in rows:
        current = record(con, kind, target_id)
        if current is None:
            issues.append((kind, target_id, "ai_correction_target_missing"))
        elif current != json.loads(corrected_json):
            issues.append((kind, target_id, "ai_correction_replay_conflict"))
    return issues
