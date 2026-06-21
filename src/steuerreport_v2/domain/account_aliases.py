from __future__ import annotations

import json
import re
import threading
from typing import Any

from steuerreport_v2.db.duckdb_store import DuckDbStore

_ACCOUNT_VALUE_PATTERN = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{24,}$")
_ACCOUNT_FIELD_HINTS = (
    "address",
    "wallet",
    "account",
    "sender",
    "receiver",
    "payee",
    "payer",
)
_ACCOUNT_FIELD_EXCLUDES = ("tx", "hash", "memo", "time", "amount", "status", "coin", "network")
_ALIAS_CACHE_LOCK = threading.Lock()
_ALIAS_CACHE: dict[tuple[str, int, str, int, str, tuple[str, ...]], dict[str, str]] = {}


def normalize_account_label(account: str | None) -> str:
    value = (account or "unassigned").replace("\xa0", " ").strip()
    return value or "unassigned"


def build_account_alias_map(accounts: list[str | None]) -> dict[str, str]:
    labels = [normalize_account_label(account) for account in accounts]
    full_labels = sorted({label for label in labels if "..." not in label})
    aliases: dict[str, str] = {}

    for label in sorted({label for label in labels if "..." in label}):
        parts = label.split("...")
        if len(parts) != 2:
            continue
        prefix, suffix = parts[0].strip(), parts[1].strip()
        if not prefix or not suffix:
            continue
        matches = [
            candidate
            for candidate in full_labels
            if candidate.startswith(prefix) and candidate.endswith(suffix)
        ]
        if len(matches) == 1:
            aliases[label] = matches[0]

    return aliases


def canonical_account_label(account: str | None, aliases: dict[str, str]) -> str:
    label = normalize_account_label(account)
    return aliases.get(label, label)


def unresolved_truncated_account_labels(
    accounts: list[str | None], aliases: dict[str, str]
) -> list[str]:
    labels = sorted({normalize_account_label(account) for account in accounts})
    return [label for label in labels if "..." in label and label not in aliases]


def extract_account_labels_from_payload_json(payload_json: str) -> list[str]:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return []
    labels: list[str] = []
    _collect_account_labels(payload, labels)
    return labels


def build_account_alias_map_for_store(store: DuckDbStore, extra_accounts: list[str | None] | None = None) -> dict[str, str]:
    extra_key = tuple(sorted({normalize_account_label(account) for account in extra_accounts or []}))
    with store.connect() as con:
        raw_count, raw_latest, event_count, event_latest = con.execute(
            """
            select
                (select count(*) from raw_objects),
                coalesce((select max(created_at)::varchar from raw_objects), ''),
                (select count(*) from canonical_events),
                coalesce((select max(event_time)::varchar from canonical_events), '')
            """
        ).fetchone()
    cache_key = (
        str(store.path.resolve()),
        int(raw_count),
        str(raw_latest),
        int(event_count),
        str(event_latest),
        extra_key,
    )
    with _ALIAS_CACHE_LOCK:
        cached = _ALIAS_CACHE.get(cache_key)
        if cached is not None:
            return dict(cached)

    account_labels = list(extra_accounts or [])
    account_labels.extend(event.account for event in store.list_canonical_events())
    for raw_object in store.list_raw_objects(limit=None):
        account_labels.extend(extract_account_labels_from_payload_json(raw_object.payload_json))
    aliases = build_account_alias_map(account_labels)
    with _ALIAS_CACHE_LOCK:
        _ALIAS_CACHE[cache_key] = dict(aliases)
        if len(_ALIAS_CACHE) > 16:
            oldest_key = next(iter(_ALIAS_CACHE))
            _ALIAS_CACHE.pop(oldest_key, None)
    return aliases


def _collect_account_labels(value: Any, labels: list[str], key: str | None = None) -> None:
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            _collect_account_labels(child_value, labels, str(child_key).lower())
        return
    if isinstance(value, list):
        for child_value in value:
            _collect_account_labels(child_value, labels, key)
        return
    if not isinstance(value, str) or key is None:
        return
    if any(excluded in key for excluded in _ACCOUNT_FIELD_EXCLUDES):
        return
    if not any(hint in key for hint in _ACCOUNT_FIELD_HINTS):
        return

    label = normalize_account_label(value)
    if "..." in label or _ACCOUNT_VALUE_PATTERN.fullmatch(label):
        labels.append(label)
