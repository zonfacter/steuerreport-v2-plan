# Welle E: Reports / UX

## Stand Und Umfang

Basis `29af806c1c700f3b09417e92f1f4f6622dc8ec09`, Branch
`audit/docker-migration-20261028-reports`, eigener Reports-Worktree.
AGENTS und VERTRAG wurden vor Aenderungen gelesen und bestaetigt. Der
vorherige Preis-Worktree blieb unveraendert und sauber. Keine weiteren
Agenten gestartet, keine zentralen Dateien oder fremden Worktrees editiert.

Genau vier eigene Dateien:

- frontend/src/workspace/YearWorkspace.tsx
- frontend/src/workspace/types.ts
- scripts/check_migration_readiness_browser_v2.py
- docs/audit/2026-10-28/REPORTS_UX_HANDOFF.md

## Anzeigevertrag

Die Standardansichten Steuerjahr und Berichte kennzeichnen das Paket als
Vorschau-Belegpaket, solange eine finale Jahresfreigabe nicht bestaetigt ist.
Der Dialog nennt denselben Paketstatus. Buttons behaupten nie allein aufgrund
technischer Downloadbarkeit eine finale Abgabefaehigkeit.

Eine positive Jahresanzeige verlangt gleichzeitig frische, zum angefragten
Jahr passende Status- UND Jahresantworten, preview_available, final_available,
keinen veralteten Berechnungsstand, snapshot_binding_status=current,
can_file_without_review und das Jahr in ready_years. Dies ist eine vorsichtige
Anzeige vorhandener Serveraussagen, keine neue steuerliche Freigabeentscheidung.

Das additive snapshot_binding_status-Feld ist in TypeScript optional, damit
alte Antworten kompatibel bleiben. Fehlendes Feld bedeutet nicht bestaetigte
Bindung, nicht etwa eine unterstellte aktuelle Bindung. missing, unbound,
stale und current erscheinen mit getrennten Klartexten. Loading, HTTP-Fehler,
erneutes Laden und Jahreswechsel entfernen vorherige positive Freigabeanzeigen.
Alte Antwortdaten werden nicht unter dem neu ausgewaehlten Jahr dargestellt.

Die bestehende globale ExportReadiness wird lesend ueber
/api/v1/export/readiness angezeigt: technical_export_allowed bedeutet nur
technischen globalen PDF-Export, keine finale Jahresfreigabe. Fehlendes Feld
oder nicht aktuelle Antwort bedeutet unbestaetigten technischen Status.
allow_export wird nicht als Ersatz fuer final_available verwendet.

Jahrauswahl, Navigation und bestehende Download-URLs bleiben erhalten:
filing-summary.html, evidence-package.zip und filing-checklist.csv. Der
Downloaddialog wird beim Jahreswechsel geschlossen. Kein CSS-/Kartenumbau,
keine Aenderung an Main, Dashboard, PriceWorkspace, API, Backend oder Versionen.

## Nachweise

Dependencies ausschliesslich im eigenen Worktree installiert. Der vorhandene
npm-Cache wurde nur gelesen/kopiert, danach npm ci mit eigenem Cache und
--offline ausgefuehrt. Der temporaere eigene Cache wurde wieder entfernt.

```bash
# Aus dem Reports-Worktree, nur lokale Cachekopie:
cp -a /root/.npm .npm-cache
cd frontend
npm ci --offline --cache ../.npm-cache --ignore-scripts --no-audit --no-fund
npm run build
```

TypeScript und Vite-Build erfolgreich. Bekannte Vite-Warnung fuer den grossen
Application-Chunk (>500 kB); kein Buildfehler und keine Bundle-Refaktorierung.

```bash
# Aus /tmp/steuerreport-migration-20261028-reports:
env PYTHONPATH=/tmp/steuerreport-browser-tools python3 \
  scripts/check_migration_readiness_browser_v2.py \
  --output /tmp/steuerreport-reports-ux-20261028-final \
  --browser-executable /root/.cache/ms-playwright/chromium-1187/chrome-linux/chrome
git -c safe.directory=/tmp/steuerreport-migration-20261028-reports diff --check
```

Ergebnis: **passed**, 100 Screenshots, 344 lokale GET-Anfragen,
0 externe Anfragen und 0 Browser-Seitenfehler. Keine schreibenden API-Aufrufe.
Ein erster 76-Screenshot-Lauf bestand ebenfalls; anschliessend wurden
getrennte Jahresantwortfehler und Legacy-Felder aufgenommen und zurueckgehaltene
Mock-Anfragen vor dem Schliessen abgebrochen. Der Endlauf ist ohne die
Teardown-CancelledError-Ausgaben des ersten Testharness-Laufs.

Matrix fuer beide Standardansichten bei 390, 768, 1280 und 1440 Pixeln:
Status langsam/nicht verfuegbar, Jahresantwort langsam/nicht verfuegbar,
missing, fehlendes Legacy-Feld, unbound, stale, current mit final=false und
positiver synthetischer aktueller Jahresfreigabe als Gegenprobe. Alte/fehlende
Bindungen werden sogar bei widerspruechlichem final=true nicht als final
angezeigt. Danach Refresh und Jahreswechsel unter zurueckgehaltenen Antworten.
Alle globalen technischen Mock-Gates erlauben den Download, behalten aber
final_filing_allowed=false. ZIP-/CSV-Abrufe und HTML-Link bleiben auf 2024;
Navigation Steuerjahr -> Berichte behaelt 2024. Kein Seiten-/Buttonoverflow.

Screenshots und maschinenlesbarer Nachweis liegen unter
`/tmp/steuerreport-reports-ux-20261028-final/`. Mobil/Desktop wurden auch
visuell geprueft. report.json SHA256:
`4ed65eee583ffbfb40998d8b1330ff3166114ef8b0715ca43ac17f1a8d387880`.

## Beweisgrenzen Und Integration

**Nur synthetische kontrollierte API-Antworten. Keine fiskalische Abnahme.**
Der Mock-ZIP enthaelt absichtlich ein synthetisches preview-Manifest und eine
Vorschau-README; dies beweist Downloadpfad und UI-Kennzeichnung, nicht die
korrekte Produktion echter Jahresartefakte. Vollstaendige echte Backend-
Acceptance ist Welle F / Koordinator.

F04 wurde im Koordinator-Worktree nur lesend inspiziert. Die dort vorgesehenen
Paketfelder filing_status=final|preview, input_binding_sha256 und
calculation_run_id sowie die Vorschaukennzeichnung in README/Manifest bleiben
Backend-Verantwortung. Status im heruntergeladenen Paket und gebundener Run
sind massgeblich, nicht eine moeglicherweise inzwischen ueberholte UI-Anzeige.
Alte Pakete werden durch diesen Frontend-Code nicht neu etikettiert.

Die vollstaendige Legacy-Expertenuebersicht und Dashboard-Methodendimension
verbleiben beim Koordinator. Es wurde kein F04-Zwischenstand cherry-gepickt;
die UI verwendet nur den vereinbarten additiven Vertrag und bestehende URLs.
Keine Produktivabfragen/-schreibzugriffe, kein Push, Tag, Release oder Deployment.
