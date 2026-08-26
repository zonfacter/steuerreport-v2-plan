from __future__ import annotations

from collections.abc import Iterable

from fastapi import FastAPI
from fastapi.routing import APIRoute


OPENAPI_TAGS = [
    {"name": "System", "description": "Health, API-Faehigkeiten und Laufzeitmetadaten."},
    {"name": "Cockpit", "description": "Aggregierte Startansicht und Product-Readiness."},
    {"name": "Sources", "description": "Wallets, Handelsplattformen, Connectoren und Quellenbelege."},
    {"name": "Import", "description": "Importvorschau, Batches, Normalisierung und Preflights."},
    {"name": "Portfolio", "description": "Live-, Ledger- und historische Portfolioauswertungen."},
    {"name": "Prices", "description": "Historische Preise, Preisdeckung und Qualitaetsgates."},
    {"name": "Transactions", "description": "Canonical Events, Ledger, Flows und Transfers."},
    {"name": "Review", "description": "Review-Gates, Aufgaben, Entscheidungen und Belegspuren."},
    {"name": "Tax", "description": "FIFO, Steuerjahre, BMF-Methodik und Haltefristen."},
    {"name": "Reports", "description": "Report-Center, Exporte und Finanzamtsbelege."},
    {"name": "Valuation", "description": "Stichtagswerte, Zugewinn und Erbmittelbelege."},
    {"name": "Administration", "description": "Lokale Einstellungen, Secrets und Betriebsaktionen."},
    {"name": "AI", "description": "Lokale KI-Aufgaben und pruefbare Ergebnisartefakte."},
    {"name": "Parity", "description": "V1/V2-Vergleich und historische Referenzen."},
]


TAG_PREFIXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Administration", ("/api/v1/admin",)),
    ("Cockpit", ("/api/v1/cockpit", "/api/v1/product")),
    ("Sources", ("/api/v1/sources",)),
    ("Import", ("/api/v1/import", "/api/v1/raw")),
    ("Portfolio", ("/api/v1/portfolio",)),
    ("Prices", ("/api/v1/prices",)),
    ("Transactions", ("/api/v1/events", "/api/v1/ledger", "/api/v1/flows", "/api/v1/transfers")),
    ("Review", ("/api/v1/review",)),
    ("Tax", ("/api/v1/tax", "/api/v1/tax-years", "/api/v1/tax-methodology", "/api/v1/derivatives")),
    ("Reports", ("/api/v1/reports", "/api/v1/export")),
    ("Valuation", ("/api/v1/divorce",)),
    ("AI", ("/api/v1/ai",)),
    ("Parity", ("/api/v1/parity", "/api/v1/v1")),
    ("System", ("/api/v1/meta", "/api/v1/contracts", "/api/v1/health", "/health")),
)


MOBILE_RECOMMENDED_READ_PATHS = {
    "/api/v1/health",
    "/api/v1/meta/capabilities",
    "/api/v1/cockpit/summary",
    "/api/v1/product/readiness",
    "/api/v1/sources/overview",
    "/api/v1/sources/{source_id}",
    "/api/v1/sources/registry/runs/latest",
    "/api/v1/portfolio/snapshot",
    "/api/v1/portfolio/as-of",
    "/api/v1/portfolio/value-history",
    "/api/v1/portfolio/sources",
    "/api/v1/portfolio/token-risk",
    "/api/v1/review/gates",
    "/api/v1/review/tasks",
    "/api/v1/tax-years/summary",
    "/api/v1/tax-years/payment-overview",
    "/api/v1/tax-years/filing-matrix",
    "/api/v1/tax-years/filing-closure-overview",
    "/api/v1/tax-years/{year}",
    "/api/v1/reports/center",
    "/api/v1/divorce/equalization-summary",
    "/api/v1/divorce/valuation-runs/latest",
}


EXTERNAL_READ_MARKERS = ("/refresh", "/search", "/probe", "/backfill")
LONG_RUNNING_MARKERS = (
    "/rebuild",
    "/refresh",
    "/backfill",
    "/pipeline",
    "/wallet-fifo",
    "/bmf-",
    "/valuation-runs",
)
DOWNLOAD_SUFFIXES = (".csv", ".json", ".pdf", ".zip", ".html")


def tag_for_path(path: str) -> str:
    for tag, prefixes in TAG_PREFIXES:
        if any(path == prefix or path.startswith(f"{prefix}/") for prefix in prefixes):
            return tag
    return "System"


def data_effect(methods: Iterable[str], path: str) -> str:
    method_set = set(methods)
    if "DELETE" in method_set:
        return "delete"
    if method_set.intersection({"POST", "PUT", "PATCH"}):
        return "write"
    if any(marker in path for marker in EXTERNAL_READ_MARKERS):
        return "external-read"
    return "read-only"


def _human_name(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def _description(route: APIRoute, effect: str) -> str:
    if route.path.endswith(DOWNLOAD_SUFFIXES) or "/artifacts/" in route.path:
        transport = "Die Antwort kann eine Datei oder HTML enthalten; Content-Type und Content-Disposition auswerten."
    else:
        transport = "JSON-Antworten verwenden das versionierte ApiResponse-Envelope mit trace_id, status, data, errors und warnings."
    effect_text = {
        "read-only": "Der Aufruf liest ausschliesslich gespeicherte oder berechnete Daten.",
        "external-read": "Der Aufruf kann einen externen Provider kontaktieren, schreibt aber nicht automatisch Steuerentscheidungen.",
        "write": "Der Aufruf kann Daten, Entscheidungen, Jobs oder Belegartefakte schreiben.",
        "delete": "Der Aufruf loescht den im Pfad bezeichneten lokalen Datensatz.",
    }[effect]
    return f"{_human_name(route.name)}. {effect_text} {transport}"


def configure_openapi_routes(app: FastAPI) -> None:
    """Add consistent documentation metadata without changing route behavior."""
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = route.methods or {"GET"}
        effect = data_effect(methods, route.path)
        route.tags = [tag_for_path(route.path)]
        if not route.description:
            route.description = _description(route, effect)
        route.openapi_extra = {
            **(route.openapi_extra or {}),
            "x-data-effect": effect,
            "x-mobile-surface": (
                "recommended-read"
                if "GET" in methods and route.path in MOBILE_RECOMMENDED_READ_PATHS
                else "expert-or-internal"
            ),
            "x-long-running": any(marker in route.path for marker in LONG_RUNNING_MARKERS),
        }
