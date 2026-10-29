"""Initialize a new private volume; never seed operator accounts or imports."""
from __future__ import annotations

import json
import os
from pathlib import Path

VAULT_KEY_FILE_ENV = "STEUERREPORT_V2_SECRET_VAULT_KEY_FILE"
INITIAL_VAULT_KEY_PROVISION_ENV = "STEUERREPORT_V2_ALLOW_INITIAL_VAULT_KEY_PROVISIONING"


def _path_is_present(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        raise RuntimeError("installation_state_unreadable; check_private_paths_and_permissions") from None
    return True


def _explicit_initial_key_provisioning_enabled() -> bool:
    return os.environ.get(INITIAL_VAULT_KEY_PROVISION_ENV, "").strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _validate_existing_secret_rows(database: Path) -> None:
    connection = None
    try:
        import duckdb

        connection = duckdb.connect(str(database), read_only=True)
        table_exists = connection.execute(
            """
            select 1
            from information_schema.tables
            where table_schema = 'main' and table_name = 'admin_settings'
            limit 1
            """
        ).fetchone()
        rows = (
            connection.execute(
                """
                select key, value_json
                from main.admin_settings
                where lower(key) like 'secret.%'
                order by key
                """
            ).fetchall()
            if table_exists
            else []
        )
    except Exception:
        raise RuntimeError(
            "existing_secret_vault_compatibility_check_failed; verify_database_and_original_key"
        ) from None
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                raise RuntimeError(
                    "existing_secret_vault_compatibility_check_failed; verify_database_and_original_key"
                ) from None

    try:
        from steuerreport_v2.domain.secret_vault import ENVELOPE_TYPE, decode_secret_setting

        for raw_key, raw_value in rows:
            key = str(raw_key)
            value_json = str(raw_value)
            if not key.strip().casefold().startswith("secret."):
                continue
            try:
                envelope = json.loads(value_json)
            except json.JSONDecodeError:
                continue
            if isinstance(envelope, dict) and envelope.get("type") == ENVELOPE_TYPE:
                decode_secret_setting(key, value_json)
    except Exception:
        raise RuntimeError(
            "existing_secret_vault_key_incompatible; restore_original_key_without_overwriting"
        ) from None


def initialize_state() -> None:
    os.umask(0o077)
    state_setting = os.environ.get("STEUERREPORT_STATE_DIR")
    state = (
        Path(state_setting).expanduser()
        if state_setting and state_setting.strip()
        else Path.home() / ".local/share/steuerreport"
    )

    profile_setting = os.environ.get("STEUERREPORT_PRIVATE_PROFILE")
    if profile_setting is None:
        profile = state / "private_profile.json"
    elif profile_setting == "":
        profile = None
    else:
        profile = Path(profile_setting).expanduser()
    database_setting = os.environ.get("STEUERREPORT_V2_DB")
    database = (
        Path(database_setting).expanduser()
        if database_setting and database_setting.strip()
        else state / "data/steuerreport_v2.duckdb"
    )
    key_setting = os.environ.get(VAULT_KEY_FILE_ENV)
    if key_setting is not None and not key_setting.strip():
        raise RuntimeError("secret_vault_key_path_missing; configure_a_private_key_file")
    key_file = Path(key_setting).expanduser() if key_setting else state / "keys/vault.key"

    profile_exists = profile is not None and _path_is_present(profile)
    database_exists = _path_is_present(database)
    key_exists = _path_is_present(key_file)
    fresh_installation = not (profile_exists or database_exists or key_exists)
    initial_profile_provision = (
        profile_exists
        and not database_exists
        and not key_exists
        and _explicit_initial_key_provisioning_enabled()
    )

    if not key_exists and not (fresh_installation or initial_profile_provision):
        raise RuntimeError(
            "secret_vault_key_missing; restore_the_original_key_before_starting_existing_state"
        )

    if not state_setting or not state_setting.strip():
        os.environ["STEUERREPORT_STATE_DIR"] = str(state)
    if profile is not None:
        os.environ.setdefault("STEUERREPORT_PRIVATE_PROFILE", str(profile))
    if not database_setting or not database_setting.strip():
        os.environ["STEUERREPORT_V2_DB"] = str(database)
    if not os.environ.get("STEUERREPORT_USERTRANSFER_ROOT", "").strip():
        os.environ["STEUERREPORT_USERTRANSFER_ROOT"] = str(state / "imports")
    if key_setting is None:
        os.environ[VAULT_KEY_FILE_ENV] = str(key_file)

    if key_exists:
        if key_file.is_symlink():
            raise RuntimeError("existing_secret_vault_key_invalid; restore_original_key_without_overwriting")
        from steuerreport_v2.domain.secret_vault import load_vault_key

        if load_vault_key() is None:
            raise RuntimeError("existing_secret_vault_key_invalid; restore_original_key_without_overwriting")
        if database_exists:
            _validate_existing_secret_rows(database)

    for name in ("data", "var", "imports", "configs", "keys"):
        (state / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    if profile is not None:
        profile.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            with profile.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps({}) + "\n")
        except FileExistsError:
            pass
    if not key_exists:
        key_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            descriptor = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            from steuerreport_v2.domain.secret_vault import load_vault_key

            if load_vault_key() is None:
                raise RuntimeError("existing_secret_vault_key_invalid; restore_original_key_without_overwriting") from None
        else:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(os.urandom(32))
                handle.flush()
                os.fsync(handle.fileno())
    os.environ.setdefault("STEUERREPORT_V2_REQUIRE_ENCRYPTED_SECRETS", "true")
    from steuerreport_v2.domain.secret_vault import load_vault_key

    if load_vault_key() is None:
        raise RuntimeError("existing_secret_vault_key_invalid; restore_original_key_without_overwriting")
    if fresh_installation and "STEUERREPORT_V2_CONNECTOR_SETUP_TOKEN_FILE" not in os.environ:
        from steuerreport_v2.domain.connector_bootstrap import initialize_token
        initialize_token()


def main() -> None:
    initialize_state()
    import uvicorn

    uvicorn.run("steuerreport_v2.api.app:app", host="0.0.0.0", port=8010, workers=1)


if __name__ == "__main__":
    main()
