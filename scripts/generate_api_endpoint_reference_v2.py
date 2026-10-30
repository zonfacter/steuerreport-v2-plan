#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "src/steuerreport_v2/api/app.py"
DEFAULT_OUTPUT = ROOT / "docs/626_API_ENDPOINT_REFERENZ_VOLLSTAENDIG_2026-07-05.md"
METHODS = {"get", "post", "put", "patch", "delete"}
ROW_RE = re.compile(
    r"^\| `(?P<method>GET|POST|PUT|PATCH|DELETE)` \| `(?P<path>[^`]+)` \| "
    r"(?P<purpose>.*?) \| (?P<effect>.*?) \| `[A-Za-z_]+\.py:\d+` `[^`]+` \|$"
)
STAND_RE = re.compile(r"^Stand: (?P<date>\d{4}-\d{2}-\d{2})$")


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    function_name: str
    line: int
    file: str = "app.py"


SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Health und API Meta", ("/health", "/api/v1/health", "/api/v1/meta")),
    ("Administration und Secrets", ("/api/v1/admin",)),
    ("Cockpit und Product Readiness", ("/api/v1/cockpit", "/api/v1/product")),
    ("Contracts", ("/api/v1/contracts",)),
    ("Import und Preflight", ("/api/v1/import",)),
    ("Raw und Canonical Events", ("/api/v1/raw", "/api/v1/events")),
    ("Ledger", ("/api/v1/ledger",)),
    ("Quellen und Connectoren", ("/api/v1/sources", "/api/v1/connectors")),
    ("Portfolio", ("/api/v1/portfolio",)),
    ("Preise", ("/api/v1/prices",)),
    ("Flows und Transfers", ("/api/v1/flows", "/api/v1/transfers")),
    ("Review", ("/api/v1/review",)),
    (
        "Steuer, BMF und Steuerjahre",
        (
            "/api/v1/tax-methodology",
            "/api/v1/tax-years",
            "/api/v1/tax-filing-snapshots",
            "/api/v1/tax",
        ),
    ),
    ("Reports und Exporte", ("/api/v1/reports", "/api/v1/export")),
    ("Stichtag und Zugewinn", ("/api/v1/divorce",)),
    ("KI-Aufgaben", ("/api/v1/ai",)),
    ("V1-Paritaet", ("/api/v1/parity", "/api/v1/v1")),
)


PURPOSE_OVERRIDES = {
    ("POST", "/api/v1/prices/import/v1-fx-cache/preview"): "Zeigt unverbindliche V1-Cache-Kandidaten ohne Uebernahmefreigabe",
    ("POST", "/api/v1/prices/import/v1-fx-cache"): "Blockiert direkte V1-Cache-Uebernahme ohne geprueften Vertrag",
    ("POST", "/api/v1/prices/historical/plan"): "Plant historische Tagespreise lokal mit Jahresuebersicht und reiner Listenpagination",
    ("POST", "/api/v1/prices/historical/manual-previews"): "Prueft einen einzelnen manuellen EUR- oder USD/FX-Originalbeleg in einer isolierten Vorschau ohne Anbieterabruf",
    ("POST", "/api/v1/prices/historical/previews"): "Sammelt bestaetigte Preisbelege und berechnet eine isolierte Vorschau",
    ("POST", "/api/v1/prices/historical/previews/{request_id}/continue"): "Ergaenzt eine kumulative Preisvorschau nach erneuter externer Bestaetigung",
    ("POST", "/api/v1/prices/historical/previews/{request_id}/apply"): "Uebernimmt bestaetigte Preise und Neuberechnung bei unveraenderten Quellen",
    ("GET", "/api/v1/prices/historical/previews/{request_id}/status"): "Liest laufenden oder gespeicherten Preisabrufstatus ohne Anbieterabfrage",
    ("GET", "/api/v1/prices/historical/previews/{request_id}/report.json"): "Exportiert die vollstaendige Preisvorschau und Belegbindung als JSON",
    ("GET", "/api/v1/prices/historical/previews/{request_id}/report.md"): "Exportiert die vollstaendige Jahresauswertung als Markdown",
    ("GET", "/api/v1/prices/historical/previews/{request_id}/report.zip"): "Exportiert saemtliche Jahreszeilen und gepruefte Originalbelege als ZIP",
    ("GET", "/api/v1/workspace/sources/{ref}/history"): "Liest Abruffaehigkeit und gespeicherte Historienauftraege der konkreten Quelle",
    ("POST", "/api/v1/workspace/sources/{ref}/history/jobs"): "Startet bestaetigten externen Abruf und isolierte Vorschau ohne produktiven Finanzimport",
    ("GET", "/api/v1/workspace/sources/{ref}/history/jobs/{job_id}"): "Liest den gespeicherten quellengebundenen Auftragsstatus",
    ("GET", "/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/audit.json"): "Liest Quellenbindung, Originalhashes, Vorschau und Importfreigabe",
    ("POST", "/api/v1/tax-methodology/bmf-filing-readiness-snapshot"): "Erzeugt ausdruecklich den gebundenen BMF-Methoden-Pruefstand fuer den Umfang 2021-2025 ohne Steuerdatenkorrektur oder finale Freigabe",
    ("POST", "/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/pause"): "Speichert eine Pause fuer den laufenden Abruf",
    ("POST", "/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/cancel"): "Bricht Folgeabrufe und Importfreigabe ab; Originalbelege bleiben erhalten",
    ("POST", "/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/resume"): "Setzt den Abruf nach ausdruecklicher Anbieterbestaetigung am gespeicherten Cursor fort",
    ("POST", "/api/v1/workspace/sources/{ref}/history/jobs/{job_id}/import"): "Uebernimmt unveraenderte Vorschau nach Import- und Berechnungsfreigabe atomar",
    ("GET", "/api/v1/tax-filing-snapshots"): (
        "Liefert das append-only Register hashgebundener Abgabe- und Referenzpakete"
    ),
    ("GET", "/api/v1/tax-years/{year}/filing-snapshots"): (
        "Liefert das hashgebundene Snapshot-Register fuer ein konkretes Steuerjahr"
    ),
    ("POST", "/api/v1/tax-years/{year}/filing-snapshots"): (
        "Archiviert den aktuellen Paketstand oder bestaetigt eine konkrete Revision als tatsaechlich eingereicht"
    ),
    ("GET", "/api/v1/tax-years/{year}/filing-snapshot-comparison"): (
        "Vergleicht den eingereichten bzw. archivierten Stand je Einkunftsart mit der aktuellen Berechnung"
    ),
    ("GET", "/api/v1/tax-years/{year}/filing-audit-report"): (
        "Erzeugt bzw. liefert den read-only Einzelpositions-, Ursachen- und Summenabgleich"
    ),
    ("GET", "/api/v1/tax-years/{year}/filing-audit-report.json"): (
        "Liefert das unveraenderliche JSON-Auditartefakt"
    ),
    ("GET", "/api/v1/tax-years/{year}/filing-audit-report.md"): (
        "Liefert das unveraenderliche Markdown-Auditartefakt"
    ),
    ("GET", "/api/v1/tax-years/{year}/filing-snapshot-comparison.html"): (
        "Liefert die druckbare Korrekturpruefungsakte statt einer rohen JSON-Ansicht"
    ),
    ("GET", "/api/v1/export/tax-years/{year}/filing-snapshot-comparison.csv"): (
        "Liefert den Abgabestand-Delta je Einkunftsart als CSV"
    ),
    ("GET", "/api/v1/tax-filing-snapshots/{snapshot_id}/package.zip"): (
        "Liefert ein erneut SHA-256-geprueftes unveraenderliches Abgabepaket"
    ),
    ("POST", "/api/v1/divorce/service-route-evidence/refresh"): (
        "Erzeugt einen SHA-gebundenen Solana-RPC-Lebenszyklusbeleg fuer eine Serviceposition"
    ),
    ("GET", "/api/v1/divorce/service-route-evidence/{tx_id}"): (
        "Liefert den letzten validen Servicepositions-Lebenszyklusbeleg"
    ),
    ("POST", "/api/v1/divorce/service-route-evidence/decisions"): (
        "Bindet eine vollstaendig liquidierte Serviceposition an den Vermoegensfluss"
    ),
    (
        "GET",
        "/api/v1/divorce/service-route-evidence/{tx_id}/artifacts/{filename}",
    ): ("Liefert einen SHA-geprueften komprimierten Solana-RPC-Beleg"),
    ("POST", "/api/v1/prices/as-of-gate/token-review-decisions"): (
        "Akzeptiert eine mint- und stichtagsgebundene Risikotoken-Bewertung"
    ),
    ("GET", "/api/v1/prices/as-of-gate/token-review-decisions.csv"): (
        "Liefert die Stichtags-Risikotoken-Entscheidungen als Beleg-CSV"
    ),
    ("GET", "/api/v1/divorce/inheritance-credit-candidates"): (
        "Liefert datensparsame CAMT-Gutschriften fuer die Erbmittelpruefung"
    ),
    ("GET", "/api/v1/divorce/inheritance-credits.csv"): (
        "Liefert alle freigegebenen Erbmittelzufluesse als Beleg-CSV"
    ),
    ("POST", "/api/v1/divorce/inheritance-credit-decisions"): (
        "Klassifiziert eine konkrete CAMT-Gutschrift hashgebunden als Erbmittel"
    ),
    ("POST", "/api/v1/divorce/inheritance-document-credit-decisions"): (
        "Bindet einen dokumentierten Netto-Erbmittelzufluss an Beleg und Betrag"
    ),
    ("GET", "/api/v1/divorce/coinbase/connector"): (
        "Berechnet Coinbase-Historienabdeckung und Stichtagsbestand"
    ),
    ("GET", "/api/v1/divorce/coinbase/connector.csv"): (
        "Liefert den Coinbase-Historien- und Stichtagsnachweis als CSV"
    ),
    ("POST", "/api/v1/divorce/coinbase/valuation-decisions"): (
        "Bindet den serverseitigen Coinbase-Stichtagswert an das Historienmanifest"
    ),
    ("POST", "/api/v1/divorce/sparkasse-camt"): (
        "Importiert validierte CAMT.052-XML- oder ZIP-Belege"
    ),
    ("GET", "/api/v1/divorce/sparkasse-statements"): (
        "Gleicht Sparkassen-PDF-Auszugbelege read-only gegen CAMT.052 ab"
    ),
    ("GET", "/api/v1/divorce/sparkasse-statements.csv"): (
        "Liefert den datensparsamen PDF-zu-CAMT-Belegabgleich als CSV"
    ),
    ("GET", "/api/v1/divorce/inheritance-documents"): (
        "Liefert den datensparsamen Erbnachweis- und Reviewstatus"
    ),
    ("GET", "/api/v1/divorce/inheritance-documents.csv"): (
        "Liefert den Erbnachweis-Hashindex als CSV"
    ),
    ("POST", "/api/v1/divorce/inheritance-documents"): (
        "Speichert einen validierten formalen Erbnachweis als Kandidat"
    ),
    ("POST", "/api/v1/divorce/inheritance-documents/review-decisions"): (
        "Bindet einen gesichteten formalen Erbnachweis an SHA-256"
    ),
}


def parse_routes(path: Path) -> list[Route]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    routes: list[Route] = []
    prefixes = {"app": ""}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name) and node.value.func.id == "APIRouter"):
            continue
        prefix = next((item.value.value for item in node.value.keywords if item.arg == "prefix"
                       and isinstance(item.value, ast.Constant) and isinstance(item.value.value, str)), "")
        for target in node.targets:
            if isinstance(target, ast.Name):
                prefixes[target.id] = prefix
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id in prefixes
                and decorator.func.attr in METHODS
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
            ):
                continue
            routes.append(
                Route(
                    method=decorator.func.attr.upper(),
                    path=prefixes[decorator.func.value.id] + decorator.args[0].value,
                    function_name=node.name,
                    line=node.lineno,
                    file=path.name,
                )
            )
    if path == APP_PATH:
        factories = {alias.asname or alias.name: APP_PATH.parent / (node.module.rsplit(".", 1)[-1] + ".py")
                     for node in tree.body if isinstance(node, ast.ImportFrom) and node.module
                     and node.module.startswith("steuerreport_v2.api.") for alias in node.names}
        included = {node.args[0].func.id for node in ast.walk(tree) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute) and node.func.attr == "include_router"
                    and node.args and isinstance(node.args[0], ast.Call) and isinstance(node.args[0].func, ast.Name)}
        for module in sorted({factories[name] for name in included if name in factories}):
            routes.extend(parse_routes(module))
    return sorted(routes, key=lambda item: (item.path, item.method, item.function_name))


def existing_metadata(path: Path) -> dict[tuple[str, str], tuple[str, str]]:
    if not path.is_file():
        return {}
    result: dict[tuple[str, str], tuple[str, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = ROW_RE.match(line)
        if match:
            result[(match["method"], match["path"])] = (
                match["purpose"],
                match["effect"],
            )
    return result


def existing_reference_date(path: Path) -> str | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines()[:10]:
        match = STAND_RE.match(line)
        if match:
            return match["date"]
    return None


def section_for(path: str) -> str:
    for title, prefixes in SECTIONS:
        if any(path == prefix or path.startswith(f"{prefix}/") for prefix in prefixes):
            return title
    return "Weitere Endpunkte"


def default_purpose(route: Route) -> str:
    override = PURPOSE_OVERRIDES.get((route.method, route.path))
    if override:
        return override
    words = route.function_name.replace("_", " ")
    return words[:1].upper() + words[1:]


def default_effect(route: Route) -> str:
    if route.method == "POST" and route.path == "/api/v1/prices/import/v1-fx-cache/preview":
        return "Kandidaten ohne Finanzimport; kalter Store kann Schema initialisieren oder migrieren"
    if route.method == "POST" and route.path == "/api/v1/prices/import/v1-fx-cache":
        return "HTTP 409; kein Preisimport und keine Pipeline-Neuberechnung"
    if route.path == "/api/v1/prices/historical/plan":
        return "read-only; keine Anbieterabfrage"
    if route.path == "/api/v1/prices/historical/manual-previews":
        return "speichert private Originalbelege und isolierte Vorschauartefakte; keine externe Anfrage oder produktive Preisuebernahme"
    if route.method == "POST" and route.path in {"/api/v1/prices/historical/previews", "/api/v1/prices/historical/previews/{request_id}/continue"}:
        return "externer Abruf und private Vorschauartefakte; keine produktive Preisuebernahme"
    if route.path == "/api/v1/prices/historical/previews/{request_id}/apply":
        return "bestaetigte Preis-/Ledger-Neuberechnung und Auditspur; keine Ereignisumklassifikation"
    if route.method == "GET":
        return "read-only"
    if route.method == "DELETE":
        return "loescht"
    if route.method in {"PATCH", "PUT"}:
        return "schreibt"
    return "kann Daten oder Artefakte schreiben"


def render(
    routes: list[Route],
    metadata: dict[tuple[str, str], tuple[str, str]],
    reference_date: str,
) -> str:
    counts = Counter(route.method for route in routes)
    lines = [
        "# Vollstaendige API Endpoint Referenz",
        "",
        f"Stand: {reference_date}",
        "",
        "Diese Referenz wird mit `scripts/generate_api_endpoint_reference_v2.py` direkt aus "
        "`src/steuerreport_v2/api/app.py` und seinen statisch eingebundenen Routermodulen erzeugt. "
        "Sie inventarisiert deren statisch deklarierte FastAPI-Routen. Fachliche Request-/Response- und Sicherheitsdetails "
        "stehen in `docs/API_CONTRACTS_V2.md` und zur Laufzeit in `/docs` bzw. "
        "`/openapi.json`.",
        "",
        "## Nutzung",
        "",
        "- `GET` ist read-only, sofern der Fachcontract nicht ausdruecklich einen externen "
        "  Live-Abruf beschreibt.",
        "- Schreibende Methoden koennen Decisions, Imports, Preise, Jobs oder lokale "
        "  Belegartefakte erzeugen. Vor produktiver Nutzung den Fachcontract pruefen.",
        "- Echte Steuerdaten und Secrets gehoeren nicht in Git, Dokumentation oder "
        "  Beispielrequests.",
        "",
        "## Statistik",
        "",
        f"- Endpunkte gesamt: `{len(routes)}`",
        f"- GET: `{counts['GET']}`",
        f"- POST: `{counts['POST']}`",
        f"- PUT: `{counts['PUT']}`",
        f"- PATCH: `{counts['PATCH']}`",
        f"- DELETE: `{counts['DELETE']}`",
        "",
    ]
    grouped: dict[str, list[Route]] = {}
    for route in routes:
        grouped.setdefault(section_for(route.path), []).append(route)
    section_order = [title for title, _prefixes in SECTIONS] + ["Weitere Endpunkte"]
    for title in section_order:
        section_routes = grouped.get(title)
        if not section_routes:
            continue
        lines.extend(
            [
                f"## {title}",
                "",
                "| Methode | Endpoint | Zweck | Schreibwirkung | Code |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for route in section_routes:
            purpose, effect = metadata.get(
                (route.method, route.path),
                (default_purpose(route), default_effect(route)),
            )
            purpose = PURPOSE_OVERRIDES.get((route.method, route.path), purpose)
            if route.path.startswith("/api/v1/prices/historical") or route.path in {
                "/api/v1/prices/import/v1-fx-cache", "/api/v1/prices/import/v1-fx-cache/preview",
            }:
                effect = default_effect(route)
            lines.append(
                f"| `{route.method}` | `{route.path}` | {purpose} | {effect} | "
                f"`{route.file}:{route.line}` `{route.function_name}` |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if args.check:
        reference_date = existing_reference_date(output) or date.today().isoformat()
    else:
        reference_date = date.today().isoformat()
    rendered = render(
        parse_routes(APP_PATH),
        existing_metadata(output),
        reference_date,
    )
    if args.check:
        if not output.is_file() or output.read_text(encoding="utf-8") != rendered:
            print(f"outdated:{output}")
            return 1
        print(f"current:{output}")
        return 0
    output.write_text(rendered, encoding="utf-8")
    print(f"generated:{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
