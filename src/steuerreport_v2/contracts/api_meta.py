from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MobileApiEndpoint(BaseModel):
    method: str
    path: str
    purpose: str


class ApiCapabilities(BaseModel):
    generated_at: datetime
    api_version: str
    api_prefix: str = "/api/v1"
    openapi_url: str = "/openapi.json"
    swagger_url: str = "/docs"
    redoc_url: str = "/redoc"
    operation_count: int = Field(ge=1)
    path_count: int = Field(ge=1)
    decimal_transport: str = "string"
    timestamp_transport: str = "ISO-8601 UTC"
    tax_day_timezone: str = "Europe/Berlin"
    ui_currency_format: str = "de-DE, EUR, two fractional digits"
    authentication_mode: str = "lan_reads_and_scoped_mobile_connector_sessions"
    internet_exposure_safe: bool = False
    mobile_api_status: str = (
        "experimental_read_pairing_wallet_ownership_and_document_inbox"
    )
    recommended_read_endpoints: list[MobileApiEndpoint]
    recommended_write_endpoints: list[MobileApiEndpoint]
    methodology: str
