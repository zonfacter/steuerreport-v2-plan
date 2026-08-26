# Steuerreport V2

Steuerreport V2 ist ein neues Projekt neben der bestehenden V1. V1 bleibt
Referenz, Datenquelle und Vergleichssystem, wird aber nicht direkt umgebaut.

## Verbindliche Entscheidungen

- Datenbank: DuckDB intern, ohne manuelle User-Verwaltung.
- Backend: Python/FastAPI mit klaren Service- und Ledger-Schichten.
- Frontend: React/TypeScript.
- Aufbau: vertikal zuerst, danach horizontal verbreitern.
- KI: lokal zuerst, externe KI nur nach expliziter Aktivierung.
- ELSTER: zuerst vorbereitende Exportdaten, keine direkte ERiC-Uebertragung in
  der ersten Ausbaustufe.
- Steuerrecht: deutsches Recht ab 2020 als Standardrahmen.
- PDF: maximal 100 Seiten je Datei.

## Erster vertikaler Durchstich

Der erste lauffaehige Schnitt muss Ende-zu-Ende funktionieren:

1. Datei im Browser importieren.
2. Rohdaten unveraendert speichern.
3. Raw Objects und Canonical Events sichtbar pruefbar machen.
4. Events in DuckDB persistieren.
5. Balance-Ledger berechnen.
6. Portfolio-Werte aus Bestand mal Marktpreis berechnen.
7. Review-Gates ausgeben.
8. PDF-Testexport mit 100-Seiten-Limit erzeugen.

## Projektstruktur

- `docs/`: menschenlesbare Planung und Architektur.
- `src/steuerreport_v2/api`: HTTP-API und API-Vertraege.
- `src/steuerreport_v2/db`: DuckDB-Verbindung und Schema.
- `src/steuerreport_v2/contracts`: stabile DTOs.
- `src/steuerreport_v2/importers`: Importer und Normalisierung.
- `src/steuerreport_v2/ledger`: Balance-, Preis-, Flow- und Tax-Ledger.
- `src/steuerreport_v2/domain`: fachliche Services.
- `src/steuerreport_v2/ai`: lokale/externe KI-Schnittstelle.
- `frontend/`: React/TypeScript-Frontend.
- `tests/`: Regressionen und Golden Cases.

## Final-Release-Dokumentation

Der aktuelle Abschlussstand hat einen kanonischen Einstiegspunkt:

- `docs/000_START_HERE_BETRIEB_UND_RELEASE_2026-07-05.md`
  - Welche Dokumente wirklich fuer Betrieb, KI-Handoff und Quellen-Setup
    gelesen werden muessen. Alle anderen Docs sind Audit-/Arbeitsarchiv.

- `docs/623_FINAL_RELEASE_DOKUMENTATION_MENSCH_2026-07-05.md`
  - Bedienung, Steuerjahr-Status, Belege, Finanzamtslogik und Grenzen.
- `docs/001_REGELN_UND_ANPASSUNG_STEUERLOGIK_2026-07-05.md`
  - Kanonische Steuer-/FIFO-/Connector-Regeln und Anpassungsleitfaden.
- `docs/624_FINAL_RELEASE_DOKUMENTATION_KI_HANDOFF_2026-07-05.md`
  - Architektur, Invarianten, Validierung, kritische Fachregeln und
    Weiterarbeitsanweisungen fuer KI-Agenten oder Entwickler.
- `docs/625_SYSTEM_SETUP_UND_LOKALE_KI_BETRIEB_2026-07-05.md`
  - Einrichtung, API/systemd-Betrieb, lokale KI-Endpunkte, KI-Jobs und
    Sicherheitsregeln.
- `docs/626_API_ENDPOINT_REFERENZ_VOLLSTAENDIG_2026-07-05.md`
  - Vollstaendige aus dem Code generierte Liste aller API-Endpunkte.
- `docs/007_MOBILE_APP_API_INTEGRATION_2026-08-26.md`
  - Verbindlicher Einstieg fuer Android-/iOS-Clients, Transportregeln,
    Sicherheitsgrenze und SDK-Generierung.
- `docs/openapi/steuerreport-v2-openapi.json`
  - Versioniertes, maschinenlesbares OpenAPI-Schema aller V2-Endpunkte und DTOs.
- `docs/627_QUELLEN_CONNECTOR_SETUP_UND_WALLET_REGISTRY_2026-07-05.md`
  - Einrichtung und Pruefung von Wallets, Binance, Bitget, Pionex, Alchemy,
    Solscan und Jupiter.
- `docs/696_OPENWEBUI_STEUERREPORT_AGENTS_2026-08-23.md`
  - Lokale Qwen-3.8-Agenten fuer BMF, FIFO, Quellen und Stichtag mit
    kontrolliertem Read-only-Zugriff.

## V1 bleibt Referenz

V2 darf Blockpit, V1-Steuerlaeufe und alte Portfolio-Berechnungen nur als
Referenz verwenden. Primaere Wahrheit sind Rohimporte, Canonical Events,
Ledger und nachvollziehbare Review-Entscheidungen.

## Wichtige Live-API-Endpunkte

- `GET /api/v1/raw/objects`: gespeicherte Rohzeilen, optional mit `batch_id`.
- `GET /api/v1/events/canonical`: normalisierte Ereignisse, optional mit `batch_id`.
- `GET /api/v1/export/tax-lines.csv`: Steuerzeilen mit echtem Anschaffungsdatum.
- `GET /api/v1/export/audit.json`: zaehlbare Audit-Sicht auf die Pipeline.

## Lokal starten

Ein frischer Checkout kann an einem beliebigen Ort liegen. Die folgenden
Variablen machen Projekt, DuckDB und private Importablage explizit; die Werte in
`.env.example` sind Beispiele und werden nicht automatisch geladen:

```bash
git clone https://github.com/zonfacter/steuerreport-v2-plan.git
cd steuerreport-v2-plan
export STEUERREPORT_V2_ROOT="$PWD"
export STEUERREPORT_V2_DB="$PWD/data/steuerreport_v2.duckdb"
export STEUERREPORT_USERTRANSFER_ROOT="/pfad/zur/privaten/usertransfer-ablage"
python3 -m pip install -e '.[dev]'
```

Das Repository enthaelt keine echte DuckDB, API-Keys, Steuer-PDFs oder privaten
Rohimporte. Fuer eine bestehende Installation muessen `data/`, `var/`,
`artifacts/` und die private Usertransfer-Ablage getrennt gesichert und
wiederhergestellt werden.

Backend:

```bash
python3 -m uvicorn steuerreport_v2.api.app:app --reload --host 0.0.0.0 --port 8010
```

Frontend:

```bash
cd frontend
npm ci
npm run dev
```

Deploy unter den laufenden V1-Port `8000` plus V2-Backend auf `8010`:

```bash
cd /workspace/steuerreport-v2-plan
bash scripts/start_v2.sh
```

Stop:

```bash
cd /workspace/steuerreport-v2-plan
bash scripts/stop_v2.sh
```

Produktionsbuild Frontend:

```bash
cd frontend
npm run build
```

Tests:

```bash
python3 -m pytest tests/unit
```

## API und Mobile-Clients

Bei laufendem Backend:

- Swagger UI: `http://localhost:8010/docs`
- ReDoc: `http://localhost:8010/redoc`
- Live-Schema: `http://localhost:8010/openapi.json`
- Client-Faehigkeiten: `GET http://localhost:8010/api/v1/meta/capabilities`

Das eingecheckte Schema wird reproduzierbar erzeugt und geprueft:

```bash
python3 scripts/export_openapi_v2.py
python3 scripts/export_openapi_v2.py --check
python3 scripts/generate_api_endpoint_reference_v2.py --check
```

Die GitHub-CI unter `.github/workflows/ci.yml` fuehrt Unit-Tests, Ruff,
OpenAPI-/Endpoint-Driftchecks und den Frontend-Build bei Pushes und Pull
Requests erneut aus. Vier lokale Integrationspruefungen gegen den privaten
Usertransfer-/Solscan-/Blockpit-/RPC-Belegbestand werden auf einem Clone ohne
diese Dateien sichtbar als `skipped` gemeldet; sie bleiben auf dem
Produktivhost ausfuehrbar.

Die API hat derzeit keine eigene Authentifizierung. Sie ist fuer das
vertrauenswuerdige LAN ausgelegt und darf fuer eine Android-/iOS-App erst hinter
TLS und einem Auth-Gateway aus dem Internet erreichbar gemacht werden. Details
stehen in `docs/007_MOBILE_APP_API_INTEGRATION_2026-08-26.md`.
