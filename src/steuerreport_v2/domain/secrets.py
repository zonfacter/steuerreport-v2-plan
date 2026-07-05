from __future__ import annotations

import json
from datetime import datetime

from steuerreport_v2.contracts.admin import AdminSetting, AdminSettingWrite
from steuerreport_v2.db.duckdb_store import DuckDbStore


SECRET_PREFIX = "secret."
REDACTED_SECRET_JSON = '"***"'


def is_secret_key(key: str) -> bool:
    return key.strip().lower().startswith(SECRET_PREFIX)


def redact_setting(setting: AdminSetting) -> AdminSetting:
    if not is_secret_key(setting.key):
        return setting
    return AdminSetting(
        key=setting.key,
        value_json=REDACTED_SECRET_JSON,
        updated_at=setting.updated_at,
    )


def secret_value_from_json(value_json: str) -> str:
    try:
        value = json.loads(value_json)
    except json.JSONDecodeError:
        return ""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def upsert_secret(store: DuckDbStore, key: str, value: str) -> AdminSetting:
    value = value.strip()
    if not value:
        raise ValueError("secret_value_required")
    return store.upsert_admin_setting(
        AdminSettingWrite(key=key, value_json=json.dumps(value))
    )


def resolve_secret_value(store: DuckDbStore, key: str) -> str:
    for setting in store.list_admin_settings():
        if setting.key == key:
            return secret_value_from_json(setting.value_json)
    return ""


def secret_metadata(store: DuckDbStore, keys: list[str]) -> dict[str, int | datetime | None]:
    wanted = set(keys)
    rows = [setting for setting in store.list_admin_settings() if setting.key in wanted]
    updated_values = [setting.updated_at for setting in rows if setting.updated_at is not None]
    return {
        "keys_present": len({setting.key for setting in rows if secret_value_from_json(setting.value_json)}),
        "keys_required": len(keys),
        "updated_at_latest": max(updated_values) if updated_values else None,
    }
