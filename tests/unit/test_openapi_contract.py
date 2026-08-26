from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.db.duckdb_store import DuckDbStore


HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def _operations(schema: dict) -> list[tuple[str, str, dict]]:
    return [
        (path, method, operation)
        for path, path_item in schema["paths"].items()
        for method, operation in path_item.items()
        if method in HTTP_METHODS
    ]


def test_api_capabilities_exposes_mobile_transport_contract(tmp_path):
    app = create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb"))
    client = TestClient(app)

    response = client.get("/api/v1/meta/capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["api_prefix"] == "/api/v1"
    assert payload["data"]["decimal_transport"] == "string"
    assert payload["data"]["tax_day_timezone"] == "Europe/Berlin"
    assert payload["data"]["authentication_mode"] == "none_lan_only"
    assert payload["data"]["internet_exposure_safe"] is False
    assert payload["data"]["operation_count"] == len(_operations(app.openapi()))
    assert any(
        row["path"] == "/api/v1/portfolio/as-of"
        for row in payload["data"]["recommended_read_endpoints"]
    )


def test_openapi_documents_every_operation_for_generated_clients(tmp_path):
    app = create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb"))

    schema = app.openapi()
    operations = _operations(schema)

    assert schema["info"]["title"] == "Steuerreport V2 API"
    assert schema["servers"] == [
        {"url": "/", "description": "Aktueller Steuerreport-V2-API-Host"}
    ]
    assert len(operations) >= 367
    assert len({operation["operationId"] for _, _, operation in operations}) == len(operations)
    assert all(operation.get("description") for _, _, operation in operations)
    assert all(operation.get("tags") for _, _, operation in operations)
    assert all(operation.get("x-data-effect") for _, _, operation in operations)
    assert all(operation.get("x-mobile-surface") for _, _, operation in operations)
    assert all("x-long-running" in operation for _, _, operation in operations)

    cockpit = schema["paths"]["/api/v1/cockpit/summary"]["get"]
    admin_write = schema["paths"]["/api/v1/admin/settings"]["patch"]
    assert cockpit["x-mobile-surface"] == "recommended-read"
    assert cockpit["x-data-effect"] == "read-only"
    assert admin_write["x-mobile-surface"] == "expert-or-internal"
    assert admin_write["x-data-effect"] == "write"

    decimal_schema = schema["components"]["schemas"]["CockpitSummary"]["properties"][
        "portfolio_value_eur"
    ]
    assert decimal_schema["type"] == "string"
