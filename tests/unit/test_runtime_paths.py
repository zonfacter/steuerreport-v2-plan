from steuerreport_v2.db.duckdb_store import DuckDbStore


def test_duckdb_store_uses_configured_default_path(tmp_path, monkeypatch):
    db_path = tmp_path / "configured" / "steuerreport_v2.duckdb"
    monkeypatch.setenv("STEUERREPORT_V2_DB", str(db_path))

    store = DuckDbStore()
    health = store.health()

    assert store.path == db_path
    assert db_path.is_file()
    assert health["exists"] is True
    assert health["schema_version"] == 3
    assert health["path"] == str(db_path)
