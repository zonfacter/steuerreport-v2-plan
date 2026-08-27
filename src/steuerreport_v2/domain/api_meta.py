from __future__ import annotations

from datetime import datetime, timezone

from steuerreport_v2 import __version__
from steuerreport_v2.contracts.api_meta import ApiCapabilities, MobileApiEndpoint


RECOMMENDED_MOBILE_ENDPOINTS = [
    MobileApiEndpoint(method="GET", path="/api/v1/cockpit/summary", purpose="Cockpit-Startansicht"),
    MobileApiEndpoint(method="GET", path="/api/v1/product/readiness", purpose="Abgabe- und Systemstatus"),
    MobileApiEndpoint(method="GET", path="/api/v1/connectors/catalog", purpose="Connector- und Sicherheitsstatus"),
    MobileApiEndpoint(method="GET", path="/api/v1/connectors/connections", purpose="Gepruefte Verbindungen"),
    MobileApiEndpoint(method="GET", path="/api/v1/sources/overview", purpose="Quellen und Wallets"),
    MobileApiEndpoint(method="GET", path="/api/v1/portfolio/snapshot", purpose="Aktueller Portfolio-Snapshot"),
    MobileApiEndpoint(method="GET", path="/api/v1/portfolio/as-of", purpose="Historischer Stichtagsbestand"),
    MobileApiEndpoint(method="GET", path="/api/v1/portfolio/value-history", purpose="Portfolio-Zeitreihe"),
    MobileApiEndpoint(method="GET", path="/api/v1/review/tasks", purpose="Offene pruefbare Aufgaben"),
    MobileApiEndpoint(method="GET", path="/api/v1/tax-years/summary", purpose="Steuerjahr-Uebersicht"),
    MobileApiEndpoint(method="GET", path="/api/v1/reports/center", purpose="Berichte und Belege"),
    MobileApiEndpoint(method="GET", path="/api/v1/divorce/valuation-runs/latest", purpose="Letztes Stichtagsdossier"),
]


class ApiCapabilitiesService:
    def report(self, *, operation_count: int, path_count: int) -> ApiCapabilities:
        return ApiCapabilities(
            generated_at=datetime.now(timezone.utc),
            api_version=__version__,
            operation_count=operation_count,
            path_count=path_count,
            recommended_read_endpoints=RECOMMENDED_MOBILE_ENDPOINTS,
            methodology=(
                "Read-only Einstieg fuer Web-, Android- und iOS-Clients. Decimal-Werte bleiben Strings; "
                "Steuer- und Stichtagslogik verbleibt serverseitig. Wallet-Eigentumsnachweise "
                "verwenden einen lokalen Setup-Bearer; die API besitzt aber noch keine allgemeine "
                "Benutzeranmeldung und darf ohne vorgeschaltetes TLS/Auth-Gateway nicht im Internet exponiert werden."
            ),
        )
