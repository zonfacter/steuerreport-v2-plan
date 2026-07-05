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

Der aktuelle Abschlussstand ist in zwei Einstiegspunkten dokumentiert:

- `docs/623_FINAL_RELEASE_DOKUMENTATION_MENSCH_2026-07-05.md`
  - Bedienung, Steuerjahr-Status, Belege, Finanzamtslogik und Grenzen.
- `docs/624_FINAL_RELEASE_DOKUMENTATION_KI_HANDOFF_2026-07-05.md`
  - Architektur, Invarianten, Validierung, kritische Fachregeln und
    Weiterarbeitsanweisungen fuer KI-Agenten oder Entwickler.
- `docs/625_SYSTEM_SETUP_UND_LOKALE_KI_BETRIEB_2026-07-05.md`
  - Einrichtung, API/systemd-Betrieb, lokale KI-Endpunkte, KI-Jobs und
    Sicherheitsregeln.
- `docs/626_API_ENDPOINT_REFERENZ_VOLLSTAENDIG_2026-07-05.md`
  - Vollstaendige aus dem Code generierte Liste aller API-Endpunkte.
- `docs/627_QUELLEN_CONNECTOR_SETUP_UND_WALLET_REGISTRY_2026-07-05.md`
  - Einrichtung und Pruefung von Wallets, Binance, Bitget, Pionex, Alchemy,
    Solscan und Jupiter.

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

Backend:

```bash
cd /workspace/steuerreport-v2-plan
python3 -m uvicorn steuerreport_v2.api.app:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd /workspace/steuerreport-v2-plan/frontend
npm install --no-bin-links
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
cd /workspace/steuerreport-v2-plan/frontend
npm run build
```

Tests:

```bash
cd /workspace/steuerreport-v2-plan
python3 -m pytest tests/unit
```
