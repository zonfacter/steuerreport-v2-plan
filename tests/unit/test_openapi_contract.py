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
    assert (
        payload["data"]["authentication_mode"]
        == "lan_reads_and_scoped_mobile_connector_sessions"
    )
    assert payload["data"]["internet_exposure_safe"] is False
    assert (
        payload["data"]["mobile_api_status"]
        == "experimental_read_pairing_wallet_ownership_and_document_inbox"
    )
    assert payload["data"]["operation_count"] == len(_operations(app.openapi()))
    assert any(
        row["path"] == "/api/v1/portfolio/as-of"
        for row in payload["data"]["recommended_read_endpoints"]
    )
    assert any(
        row["path"] == "/api/v1/connectors/mobile/documents"
        for row in payload["data"]["recommended_write_endpoints"]
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
    mobile_session = schema["paths"]["/api/v1/connectors/mobile/session"]["get"]
    mobile_pairing = schema["paths"]["/api/v1/connectors/mobile/pairings"]["post"]
    mobile_exchange = schema["paths"]["/api/v1/connectors/mobile/sessions"]["post"]
    mobile_document_upload = schema["paths"][
        "/api/v1/connectors/mobile/documents"
    ]["post"]
    mobile_document_inventory = schema["paths"][
        "/api/v1/connectors/mobile/documents"
    ]["get"]
    wallet_challenge = schema["paths"]["/api/v1/connectors/wallet/challenges"]["post"]
    filing_readiness_refresh = schema["paths"][
        "/api/v1/tax-methodology/bmf-filing-readiness-snapshot"
    ]["post"]
    filing_usage_confirmation = schema["paths"][
        "/api/v1/tax-filing-snapshots/{snapshot_id}/usage-confirmation"
    ]["post"]
    manual_price_preview = schema["paths"][
        "/api/v1/prices/historical/manual-previews"
    ]["post"]
    assert cockpit["x-mobile-surface"] == "recommended-read"
    assert cockpit["x-data-effect"] == "read-only"
    assert admin_write["x-mobile-surface"] == "expert-or-internal"
    assert admin_write["x-data-effect"] == "write"
    assert mobile_session["x-mobile-surface"] == "recommended-read"
    assert mobile_session["x-data-effect"] == "read-only"
    assert mobile_pairing["x-mobile-surface"] == "expert-or-internal"
    assert mobile_pairing["x-data-effect"] == "write"
    assert mobile_pairing["security"] == [{"ConnectorSetupBearer": []}]
    assert mobile_session["security"] == [{"MobileConnectorBearer": []}]
    assert "security" not in mobile_exchange
    assert mobile_exchange["x-mobile-surface"] == "recommended-write"
    assert mobile_document_upload["x-mobile-surface"] == "recommended-write"
    assert mobile_document_upload["security"] == [
        {"ConnectorSetupBearer": []},
        {"MobileConnectorBearer": []},
    ]
    assert "anbieterabruf" in manual_price_preview["description"].lower()
    assert manual_price_preview["x-data-effect"] == "write"
    assert mobile_document_inventory["x-mobile-surface"] == "expert-or-internal"
    assert mobile_document_inventory["security"] == [{"ConnectorSetupBearer": []}]
    assert wallet_challenge["security"] == [
        {"ConnectorSetupBearer": []},
        {"MobileConnectorBearer": []},
    ]
    assert filing_readiness_refresh["x-data-effect"] == "write"
    assert filing_readiness_refresh["x-long-running"] is True
    assert filing_readiness_refresh["requestBody"]["required"] is True
    assert filing_usage_confirmation["x-data-effect"] == "write"
    assert filing_usage_confirmation["tags"] == ["Tax"]
    security_schemes = schema["components"]["securitySchemes"]
    assert security_schemes["ConnectorSetupBearer"]["scheme"] == "bearer"
    assert security_schemes["MobileConnectorBearer"]["scheme"] == "bearer"

    decimal_schema = schema["components"]["schemas"]["CockpitSummary"]["properties"][
        "portfolio_value_eur"
    ]
    assert decimal_schema["type"] == "string"
