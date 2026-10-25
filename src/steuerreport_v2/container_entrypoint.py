"""Initialize a new private volume; never seed operator accounts or imports."""
from __future__ import annotations

import json
import os
from pathlib import Path


def initialize_state() -> None:
    os.umask(0o077)
    state = Path(os.environ.get("STEUERREPORT_STATE_DIR", str(Path.home() / ".local/share/steuerreport")))
    for name in ("data", "var", "imports", "configs", "keys"):
        (state / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    profile = Path(os.environ.get("STEUERREPORT_PRIVATE_PROFILE", str(state / "private_profile.json")))
    profile.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with profile.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps({}) + "\n")
    except FileExistsError:
        pass
    os.environ.setdefault("STEUERREPORT_PRIVATE_PROFILE", str(profile))
    os.environ.setdefault("STEUERREPORT_V2_DB", str(state / "data/steuerreport_v2.duckdb"))
    os.environ.setdefault("STEUERREPORT_USERTRANSFER_ROOT", str(state / "imports"))
    key_file = Path(os.environ.get("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", str(state / "keys/vault.key")))
    key_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(os.urandom(32))
            handle.flush()
            os.fsync(handle.fileno())
    os.environ.setdefault("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", str(key_file))
    os.environ.setdefault("STEUERREPORT_V2_REQUIRE_ENCRYPTED_SECRETS", "true")
    from steuerreport_v2.domain.secret_vault import load_vault_key
    if load_vault_key() is None:
        raise RuntimeError("existing_secret_vault_key_invalid; restore_original_key_without_overwriting")


def main() -> None:
    initialize_state()
    import uvicorn

    uvicorn.run("steuerreport_v2.api.app:app", host="0.0.0.0", port=8010, workers=1)


if __name__ == "__main__":
    main()
