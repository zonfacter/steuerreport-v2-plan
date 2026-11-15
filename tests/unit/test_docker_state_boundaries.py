"""Isolierte Sicherheitsregressionen; nur synthetische lokale Dateien/DBs."""
from __future__ import annotations

import argparse
import errno
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import tarfile

import duckdb
import pytest

from steuerreport_v2.domain.secret_vault import encrypt_secret_setting
from steuerreport_v2.paths import configured_import_path
from steuerreport_v2.private_settings import _read_profile


_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "docker_state_v2.py"
_SPEC = importlib.util.spec_from_file_location("docker_state_boundary_ops", _SCRIPT)
assert _SPEC and _SPEC.loader
ops = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ops)


@pytest.fixture(autouse=True)
def prohibit_operator_processes(monkeypatch: pytest.MonkeyPatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Boundary tests must not invoke Docker or external processes")

    monkeypatch.setattr(ops, "_docker", forbidden)
    monkeypatch.setattr(ops.subprocess, "run", forbidden)
    monkeypatch.setattr(ops.subprocess, "Popen", forbidden)
    for key in tuple(os.environ):
        if key.startswith("STEUERREPORT_"):
            monkeypatch.delenv(key)
    _read_profile.cache_clear()
    yield
    _read_profile.cache_clear()


@pytest.fixture
def state(tmp_path: Path):
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    for name in ("data", "keys", "imports", "configs"):
        (root / name).mkdir(mode=0o700)
    key = bytes(range(32))
    key_file = root / "keys/vault.key"
    key_file.write_bytes(key)
    key_file.chmod(0o600)
    token = root / "keys/connector-setup.token"
    token.write_bytes(b"synthetic-only-token")
    token.chmod(0o600)
    profile = root / "private_profile.json"
    profile.write_text(json.dumps({"import_root": str(root / "imports")}), encoding="ascii")
    profile.chmod(0o600)
    database = root / "data/steuerreport_v2.duckdb"
    with duckdb.connect(str(database)) as con:
        con.execute("CREATE TABLE schema_meta (key VARCHAR PRIMARY KEY, value VARCHAR)")
        con.execute("INSERT INTO schema_meta VALUES ('schema_version', '3')")
        con.execute("CREATE TABLE admin_settings (key VARCHAR PRIMARY KEY, value_json VARCHAR)")
        con.execute("INSERT INTO admin_settings VALUES (?, ?)", [
            "secret.synthetic.api_key",
            encrypt_secret_setting("secret.synthetic.api_key", "SYNTHETIC-ONLY", key),
        ])
    database.chmod(0o600)
    mount = {
        "id": "m000", "kind": "volume", "target": str(root), "read_only": False,
        "archive_prefix": "mounts/m000", "helper_root": str(root),
    }
    runtime_paths = {
        "STEUERREPORT_STATE_DIR": str(root),
        "STEUERREPORT_V2_DB": str(database),
        "STEUERREPORT_PRIVATE_PROFILE": str(profile),
        "STEUERREPORT_PRIVATE_CONFIG_DIR": str(root / "configs"),
        "STEUERREPORT_USERTRANSFER_ROOT": str(root / "imports"),
        "STEUERREPORT_V2_SECRET_VAULT_KEY_FILE": str(key_file),
        "STEUERREPORT_V2_CONNECTOR_SETUP_TOKEN_FILE": str(token),
    }
    return {"mounts": [mount], "runtime_paths": runtime_paths}


def _root(payload: dict) -> Path:
    return Path(payload["mounts"][0]["helper_root"])


def _archive(payload: dict, path: Path, monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    class BinaryOutput:
        buffer = io.BytesIO()

    output = BinaryOutput()
    with monkeypatch.context() as local:
        local.setattr(ops.sys, "stdout", output)
        ops._helper_archive(payload)
    path.write_bytes(output.buffer.getvalue())
    path.chmod(0o600)
    return ops._safe_archive_records(path, payload["mounts"])


def _backup(payload: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    inventory = ops._helper_inventory(payload, semantic=False)
    snapshot = ops._helper_inventory(payload, semantic=True)
    directory = tmp_path / "backup"
    directory.mkdir(mode=0o700)
    archive = directory / "state.tar.gz"
    records = _archive(payload, archive, monkeypatch)
    assert records == inventory["archive_members"]
    tables = snapshot["tables"]
    manifest = {
        "format_version": ops.FORMAT_VERSION,
        "source_image": {"image_id": "sha256:" + "a" * 64, "revision": "b" * 40,
                         "version": "synthetic-test", "platform": "linux/amd64"},
        "mounts": [{key: row[key] for key in ("id", "kind", "target", "read_only", "archive_prefix")}
                   for row in payload["mounts"]],
        "runtime_paths": payload["runtime_paths"],
        "schema_version": snapshot["schema_version"], "database_present": True,
        "database_tables": tables, "database_table_count": len(tables),
        "database_row_count": sum(row["rows"] for row in tables.values()),
        "database_semantic_sha256": snapshot["database_semantic_sha256"],
        "vault": snapshot["vault"], "archive_members": records,
        "archive_size_bytes": archive.stat().st_size, "archive_sha256": ops._sha256(archive),
        "wal_files": [],
    }
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="ascii")
    manifest_path.chmod(0o600)
    ops._load_backup(directory)
    return directory


@pytest.mark.parametrize("form", ["parent_traversal", "home_expansion"])
def test_inventory_rejects_effective_profile_path_outside_mount(
    state: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, form: str,
) -> None:
    outside = tmp_path / "external"
    outside.mkdir()
    (outside / "reference.csv").write_bytes(b"synthetic-source,1\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    value = "../../external/reference.csv" if form == "parent_traversal" else "~/external/reference.csv"
    profile = _root(state) / "private_profile.json"
    profile.write_text(json.dumps({"import_root": str(_root(state) / "imports"),
                                   "blockpit_reference_file": value}), encoding="ascii")
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", str(profile))
    effective = configured_import_path("blockpit_reference_file").resolve()
    assert effective.read_bytes() == b"synthetic-source,1\n"
    assert not effective.is_relative_to(_root(state))

    with pytest.raises(ops.OpsError):
        ops._helper_inventory(state, semantic=False)


@pytest.mark.parametrize("operation", ["inventory", "snapshot", "archive"])
def test_directory_io_error_must_not_silently_omit_originals(
    state: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    hidden = _root(state) / "imports" / "unreadable"
    hidden.mkdir()
    (hidden / "original.csv").write_bytes(b"synthetic-original,123\n")
    scandir = os.scandir

    def failing_scandir(path):
        if Path(path) == hidden:
            raise OSError(errno.EIO, "synthetic filesystem read error", str(path))
        return scandir(path)

    monkeypatch.setattr(ops.os, "scandir", failing_scandir)
    with pytest.raises(ops.OpsError, match="persistent_mount_directory_unreadable"):
        if operation in {"inventory", "snapshot"}:
            ops._helper_inventory(state, semantic=operation == "snapshot")
        else:
            _archive(state, tmp_path / "incomplete.tar.gz", monkeypatch)


@pytest.mark.parametrize("path", ["/unmounted/database.duckdb", "relative/database.duckdb"])
def test_verified_manifest_must_resolve_runtime_db_inside_persistent_mount(
    state: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str,
) -> None:
    directory = _backup(state, tmp_path, monkeypatch)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    manifest["runtime_paths"]["STEUERREPORT_V2_DB"] = path
    manifest_path.write_text(json.dumps(manifest), encoding="ascii")

    with pytest.raises(ops.OpsError):
        ops.verify(argparse.Namespace(backup_dir=str(directory), max_uncompressed_bytes=4 * 1024 * 1024,
                                      max_archive_bytes=4 * 1024 * 1024,
                                      max_expanded_archive_bytes=8 * 1024 * 1024))


def test_corrupt_secret_json_must_not_count_as_decryptable_vault(state: dict) -> None:
    with duckdb.connect(state["runtime_paths"]["STEUERREPORT_V2_DB"]) as con:
        con.execute("UPDATE admin_settings SET value_json = '{truncated-envelope'")

    with pytest.raises(ops.OpsError):
        ops._helper_inventory(state, semantic=False)


@pytest.mark.parametrize("change", ["view_definition", "column_default"])
def test_schema_mutation_must_not_pass_after_start_equality(state: dict, change: str) -> None:
    database = state["runtime_paths"]["STEUERREPORT_V2_DB"]
    with duckdb.connect(database) as con:
        con.execute("CREATE VIEW derived_state AS SELECT 1 AS result")
        con.execute("CREATE TABLE future_imports (amount INTEGER DEFAULT 1)")
    before = ops._helper_inventory(state, semantic=True)
    with duckdb.connect(database) as con:
        if change == "view_definition":
            con.execute("CREATE OR REPLACE VIEW derived_state AS SELECT 999 AS result")
            assert con.execute("SELECT result FROM derived_state").fetchone() == (999,)
        else:
            con.execute("ALTER TABLE future_imports ALTER amount SET DEFAULT 999")
            default = con.execute("SELECT column_default FROM information_schema.columns "
                                  "WHERE table_name='future_imports'").fetchone()[0]
            assert default == "999"
    after = ops._helper_inventory(state, semantic=True)
    assert before["tables"] == after["tables"], "Existing table-row hash policy must stay unchanged"
    assert before["database_semantic_sha256"] == after["database_semantic_sha256"]
    assert before["database_catalog_sha256"] != after["database_catalog_sha256"]
    before_db = next(row for row in before["archive_members"] if row["path"].endswith(".duckdb"))
    after_db = next(row for row in after["archive_members"] if row["path"].endswith(".duckdb"))
    assert before_db["sha256"] != after_db["sha256"]

    assert not ops._equal_after_start(before, after), "Changed SQL schema was declared unchanged"


def test_extract_rejects_preexisting_parent_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "target"
    root.mkdir(mode=0o700)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    (root / "imports").symlink_to(outside, target_is_directory=True)
    archive_path = tmp_path / "state.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        member = tarfile.TarInfo("mounts/m000/imports/original.csv")
        member.size = 1
        member.uid = os.getuid()
        member.gid = os.getgid()
        member.mode = 0o600
        archive.addfile(member, io.BytesIO(b"x"))
    records = ops._safe_archive_records(archive_path)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"archive_members": records}), encoding="ascii")
    with pytest.raises(ops.OpsError, match="archive_member_path_invalid"):
        ops._helper_extract({"archive": str(archive_path), "manifest": str(manifest_path),
                             "targets": [{"archive_prefix": "mounts/m000", "helper_root": str(root)}],
                             "max_restore_bytes": 1024, "max_expanded_archive_bytes": 65536})
    assert not (outside / "original.csv").exists()


def test_legitimate_small_backup_and_unchanged_schema_pass(
    state: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = ops._helper_inventory(state, semantic=True)
    assert before["vault"]["decryptable"] is True
    assert before["vault"]["encrypted_rows"] == 1
    assert ops._equal_after_start(before, ops._helper_inventory(state, semantic=True))
    directory = _backup(state, tmp_path, monkeypatch)
    _, manifest = ops._load_backup(directory)
    assert manifest["database_table_count"] == 2
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in directory.iterdir())


@pytest.mark.parametrize("semantic", [False, True])
def test_inventory_exposes_known_catalog_hash_in_both_modes(state: dict, semantic: bool) -> None:
    result = ops._helper_inventory(state, semantic=semantic)
    assert result["database_catalog_sha256"] == ops._db_catalog_digest(
        Path(state["runtime_paths"]["STEUERREPORT_V2_DB"])
    )
    assert len(result["database_catalog_sha256"]) == 64


@pytest.mark.parametrize("value", [None, "", "invalid", "A" * 64, 123, True, []])
@pytest.mark.parametrize("side", ["before", "after"])
def test_comparison_requires_known_valid_catalog_hash(value, side: str) -> None:
    before = {"database_catalog_sha256": "a" * 64, "tables": {}, "database_archive_paths": [],
              "archive_members": [], "schema_version": 3, "vault": {"decryptable": True}}
    after = json.loads(json.dumps(before))
    (before if side == "before" else after)["database_catalog_sha256"] = value
    assert not ops._equal_after_start(before, after)


def test_two_missing_catalog_hashes_do_not_prove_equality() -> None:
    snapshot = {"tables": {}, "database_archive_paths": [], "archive_members": [],
                "schema_version": 3, "vault": {"decryptable": True}}
    assert not ops._equal_after_start(snapshot, snapshot)


@pytest.mark.parametrize("value", [None, "", "invalid", "A" * 64, 123, True, []])
def test_manifest_rejects_present_but_invalid_catalog_hash(
    state: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value,
) -> None:
    directory = _backup(state, tmp_path, monkeypatch)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    manifest["database_catalog_sha256"] = value
    manifest_path.write_text(json.dumps(manifest), encoding="ascii")
    with pytest.raises(ops.OpsError, match="backup_database_catalog_manifest_invalid"):
        ops._load_backup(directory)


def test_legacy_manifest_missing_catalog_hash_stays_integrity_verifiable(
    state: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = _backup(state, tmp_path, monkeypatch)
    _, manifest = ops._load_backup(directory)
    assert manifest["format_version"] == 1
    assert "database_catalog_sha256" not in manifest
    result = ops.verify(argparse.Namespace(backup_dir=str(directory), max_uncompressed_bytes=4194304,
                                          max_archive_bytes=4194304, max_expanded_archive_bytes=8388608))
    assert result["status"] == "verified"
    assert "database_catalog_sha256" not in result
    manifest["database_catalog_sha256"] = ops._db_catalog_digest(
        Path(state["runtime_paths"]["STEUERREPORT_V2_DB"])
    )
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="ascii")
    assert ops._load_backup(directory)[1]["database_catalog_sha256"] == manifest["database_catalog_sha256"]


@pytest.mark.parametrize("runtime_key", ["STEUERREPORT_V2_DB", "STEUERREPORT_PRIVATE_CONFIG_DIR",
                                        "STEUERREPORT_SPARKASSE_CAMT_DIR"])
@pytest.mark.parametrize("value", ["relative/file", "~/file", "/unmounted/file", "//state/file", "/state/\x00file"])
def test_all_configured_runtime_paths_must_have_proven_mount_scope(
    state: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runtime_key: str, value: str,
) -> None:
    directory = _backup(state, tmp_path, monkeypatch)
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    manifest["runtime_paths"][runtime_key] = value
    manifest_path.write_text(json.dumps(manifest), encoding="ascii")
    with pytest.raises(ops.OpsError):
        ops._load_backup(directory)


@pytest.mark.parametrize("form", ["profile_root", "runtime_root"])
def test_known_relative_import_file_uses_only_explicit_absolute_import_root(
    state: dict, form: str,
) -> None:
    root = _root(state)
    (root / "imports/reference.csv").write_bytes(b"synthetic,1\n")
    profile = {"blockpit_reference_file": "reference.csv"}
    if form == "profile_root":
        profile["import_root"] = str(root / "imports")
    (root / "private_profile.json").write_text(json.dumps(profile), encoding="ascii")
    result = ops._helper_inventory(state, semantic=False)
    assert result["complete"] is True
    assert result["configured_path_count_checked"] == len(profile)
    assert any(row["path"] == "mounts/m000/imports/reference.csv" for row in result["archive_members"])


@pytest.mark.parametrize("profile", [
    {"import_root": "relative-root"},
    {"blockpit_reference_file": "~/reference.csv"},
    {"unknown_file": "reference.csv"},
    {"blockpit_reference_file": "file:///outside/reference.csv"},
])
def test_ambiguous_profile_path_context_is_blocked_explicitly(state: dict, profile: dict) -> None:
    (_root(state) / "private_profile.json").write_text(json.dumps(profile), encoding="ascii")
    with pytest.raises(ops.OpsError, match="configured_profile_path_context_unavailable"):
        ops._helper_inventory(state, semantic=False)


def test_relative_import_without_explicit_root_is_not_resolved_from_helper_cwd(state: dict) -> None:
    (_root(state) / "private_profile.json").write_text(
        json.dumps({"blockpit_reference_file": "reference.csv"}), encoding="ascii"
    )
    state["runtime_paths"].pop("STEUERREPORT_USERTRANSFER_ROOT")
    with pytest.raises(ops.OpsError, match="configured_profile_path_context_unavailable"):
        ops._helper_inventory(state, semantic=False)


@pytest.mark.parametrize("value", ["{truncated", '{"a":1,"a":2}', "NaN", "Infinity", "-Infinity", "42", "[]"])
def test_secret_json_parse_errors_are_reported_unreadable(state: dict, value: str) -> None:
    with duckdb.connect(state["runtime_paths"]["STEUERREPORT_V2_DB"]) as con:
        con.execute("UPDATE admin_settings SET value_json = ?", [value])
    summary = ops._vault_summary(Path(state["runtime_paths"]["STEUERREPORT_V2_DB"]),
                                 Path(state["runtime_paths"]["STEUERREPORT_V2_SECRET_VAULT_KEY_FILE"]))
    assert summary["decryptable"] is False
    assert summary["unreadable_rows"] == 1


@pytest.mark.parametrize(("field", "value"), [("version", True), ("algorithm", "other"),
                                               ("key_id", "0" * 16), ("nonce", 123), ("ciphertext", [])])
def test_secret_envelope_metadata_must_match_key_and_format(state: dict, field: str, value) -> None:
    with duckdb.connect(state["runtime_paths"]["STEUERREPORT_V2_DB"]) as con:
        envelope = json.loads(con.execute("SELECT value_json FROM admin_settings").fetchone()[0])
        envelope[field] = value
        con.execute("UPDATE admin_settings SET value_json = ?", [json.dumps(envelope)])
    summary = ops._vault_summary(Path(state["runtime_paths"]["STEUERREPORT_V2_DB"]),
                                 Path(state["runtime_paths"]["STEUERREPORT_V2_SECRET_VAULT_KEY_FILE"]))
    assert summary["decryptable"] is False
    assert summary["unreadable_rows"] == 1


@pytest.mark.parametrize("prefix", ['"version":1,', '"unused_metadata":NaN,'])
def test_strict_json_rejects_ambiguous_but_otherwise_decryptable_envelopes(state: dict, prefix: str) -> None:
    with duckdb.connect(state["runtime_paths"]["STEUERREPORT_V2_DB"]) as con:
        original = con.execute("SELECT value_json FROM admin_settings").fetchone()[0]
        con.execute("UPDATE admin_settings SET value_json = ?", ["{" + prefix + original[1:]])
    summary = ops._vault_summary(Path(state["runtime_paths"]["STEUERREPORT_V2_DB"]),
                                 Path(state["runtime_paths"]["STEUERREPORT_V2_SECRET_VAULT_KEY_FILE"]))
    assert summary["decryptable"] is False
    assert summary["unreadable_rows"] == 1


@pytest.mark.parametrize("value", ['"legacy-plaintext"', '""', "null"])
def test_strict_json_does_not_change_legacy_plaintext_or_null_policy(state: dict, value: str) -> None:
    with duckdb.connect(state["runtime_paths"]["STEUERREPORT_V2_DB"]) as con:
        con.execute("UPDATE admin_settings SET value_json = ?", [value])
    assert ops._helper_inventory(state, semantic=False)["vault"]["decryptable"] is True


@pytest.mark.parametrize(("setup", "mutation"), [
    ("CREATE VIEW v AS SELECT 1 AS n", "CREATE OR REPLACE VIEW v AS SELECT 2 AS n"),
    ("CREATE TABLE t (n INTEGER DEFAULT 1)", "ALTER TABLE t ALTER n SET DEFAULT 2"),
    ("CREATE TABLE t (n INTEGER CHECK (n > 0))", "DROP TABLE t; CREATE TABLE t (n INTEGER CHECK (n > 10))"),
    ("CREATE TABLE t (n INTEGER)", "CREATE INDEX t_idx ON t(n)"),
    ("CREATE MACRO m() AS 1", "CREATE OR REPLACE MACRO m() AS 2"),
    ("CREATE MACRO m() AS TABLE SELECT 1 AS n", "CREATE OR REPLACE MACRO m() AS TABLE SELECT 2 AS n"),
    ("CREATE SEQUENCE seq START 1", "DROP SEQUENCE seq; CREATE SEQUENCE seq START 100"),
    ("CREATE SEQUENCE seq START 1", "SELECT nextval('seq')"),
    ("CREATE TYPE mood AS ENUM ('a','b')", "DROP TYPE mood; CREATE TYPE mood AS ENUM ('a','c')"),
    ("CREATE TYPE shape AS STRUCT(x INTEGER)", "DROP TYPE shape; CREATE TYPE shape AS STRUCT(x VARCHAR)"),
    ("CREATE SCHEMA extra", "CREATE SCHEMA another"),
])
def test_catalog_digest_binds_each_persistent_catalog_kind(tmp_path: Path, setup: str, mutation: str) -> None:
    path = tmp_path / "catalog.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute(setup)
    before = ops._db_catalog_digest(path)
    assert ops._db_catalog_digest(path) == before
    with duckdb.connect(str(path)) as con:
        con.execute(mutation).fetchall()
    assert ops._db_catalog_digest(path) != before


def test_catalog_digest_is_independent_of_file_name_and_object_creation_order(tmp_path: Path) -> None:
    statements = ["CREATE TABLE t (n INTEGER DEFAULT 1 CHECK (n > 0))", "CREATE VIEW v AS SELECT 1 AS n",
                  "CREATE MACRO m() AS 1", "CREATE TYPE shape AS STRUCT(x INTEGER)", "CREATE SEQUENCE seq START 1"]
    paths = [tmp_path / "one.duckdb", tmp_path / "two.duckdb"]
    for path, order in zip(paths, [statements, list(reversed(statements))]):
        with duckdb.connect(str(path)) as con:
            for sql in order:
                con.execute(sql)
    expected = ops._db_catalog_digest(paths[0])
    assert ops._db_catalog_digest(paths[1]) == expected
    copied = tmp_path / "copied.duckdb"
    shutil.copyfile(paths[0], copied)
    assert ops._db_catalog_digest(copied) == expected


def test_catalog_queries_cannot_be_shadowed_by_persistent_macros(tmp_path: Path) -> None:
    path = tmp_path / "shadow.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE MACRO current_database() AS 'not-the-real-catalog'")
        con.execute("CREATE MACRO duckdb_views() AS TABLE SELECT 1 AS bogus")
        con.execute("CREATE MACRO typeof() AS 'bogus-type'")
        con.execute("CREATE TYPE shape AS STRUCT(x INTEGER)")
        con.execute("CREATE VIEW v AS SELECT 1 AS n")
    before = ops._db_catalog_digest(path)
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE OR REPLACE VIEW v AS SELECT 999 AS n")
    assert ops._db_catalog_digest(path) != before


@pytest.mark.parametrize("definition", ["m(x) AS x+1", "m(x, y := 1) AS x+y",
                                        "m(x, y := 999) AS x+y", "m(x) AS TABLE SELECT x AS n"])
def test_parameterized_macros_block_unverifiable_default_argument_provenance(
    tmp_path: Path, definition: str,
) -> None:
    path = tmp_path / "macro.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE MACRO " + definition)
    with pytest.raises(ops.OpsError, match="database_catalog_macro_parameters_unverifiable"):
        ops._db_catalog_digest(path)


def test_catalog_inspection_never_executes_view_or_macro_bodies(tmp_path: Path) -> None:
    path = tmp_path / "metadata_only.duckdb"
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE VIEW poison AS SELECT error('must not execute view') AS n")
        con.execute("CREATE MACRO poison_macro() AS error('must not execute macro')")
    before = path.read_bytes()
    digest = ops._db_catalog_digest(path)
    assert ops._db_catalog_digest(path) == digest
    assert path.read_bytes() == before
    assert not Path(str(path) + ".wal").exists()


def test_catalog_metadata_failures_are_not_treated_as_empty_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MissingCatalog:
        closed = False

        def execute(self, query):
            if query != "BEGIN TRANSACTION":
                raise duckdb.CatalogException("synthetic missing metadata API")

        def close(self):
            self.closed = True

    connection = MissingCatalog()
    monkeypatch.setattr(ops, "_db_connection", lambda path: connection)
    with pytest.raises(ops.OpsError, match="database_catalog_snapshot_failed"):
        ops._db_catalog_digest(tmp_path / "unused.duckdb")
    assert connection.closed
