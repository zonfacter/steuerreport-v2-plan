import importlib.util
from pathlib import Path
import sys


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "generate_api_endpoint_reference_v2.py"
)
SPEC = importlib.util.spec_from_file_location(
    "generate_api_endpoint_reference_v2",
    SCRIPT,
)
assert SPEC is not None and SPEC.loader is not None
generator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = generator
SPEC.loader.exec_module(generator)


def test_reference_includes_source_history_and_existing_account_routers():
    routes = {(route.method, route.path): route for route in generator.parse_routes(generator.APP_PATH)}
    history = routes[("POST", "/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/import")]
    assert history.file == "history.py" and history.function_name == "apply"
    assert ("GET", "/api/v1/admin/connections") in routes
    assert ("GET", "/api/v1/admin/request-limits") in routes


def test_endpoint_reference_check_preserves_documented_date(tmp_path, monkeypatch):
    output = tmp_path / "endpoints.md"
    routes = generator.parse_routes(generator.APP_PATH)
    output.write_text(
        generator.render(routes, {}, "2000-01-01"),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--output", str(output), "--check"],
    )

    assert generator.main() == 0
    assert generator.existing_reference_date(output) == "2000-01-01"


def test_v1_cache_guard_overrides_stale_endpoint_metadata():
    routes = generator.parse_routes(generator.APP_PATH)
    metadata = {
        ("POST", "/api/v1/prices/import/v1-fx-cache"): ("Alter Import", "schreibt Preise"),
        ("POST", "/api/v1/prices/import/v1-fx-cache/preview"): ("Alte Vorschau", "schreibt"),
    }
    rendered = generator.render(routes, metadata, "2000-01-01")
    assert "Blockiert direkte V1-Cache-Uebernahme ohne geprueften Vertrag" in rendered
    assert "HTTP 409; kein Preisimport und keine Pipeline-Neuberechnung" in rendered
    assert "Zeigt unverbindliche V1-Cache-Kandidaten ohne Uebernahmefreigabe" in rendered
    assert "Kandidaten ohne Finanzimport; kalter Store kann Schema initialisieren oder migrieren" in rendered
    assert "Alter Import" not in rendered and "Alte Vorschau" not in rendered
