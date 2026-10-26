# UX-Review: Korrekturen F1 bis F3

Stand: 26.10.2026. Branch: `feat/bedienkonzept-20261026`.
Fortsetzung des Bedienkonzepts; kein produktiver Versionswechsel, Tag, Push
oder Release. Keine steuerfachliche Freigabe aus dieser UX-Prüfung.

## Änderungen und Ursachen

| Befund | Ursache | Umsetzung | Nachweis |
| --- | --- | --- | --- |
| F1: Quelle scheinbar hinweisfrei | Quellenbewertung und Review-Aufgaben waren getrennte Mengen ohne gemeinsame Relation. | `WorkspaceService._review_items` löst gespeicherte Konto-, Quellen- und Ereignisbezüge auf. Quellenliste, Filter, Detail und Review verwenden diese Relation. | Backend-Tests und echter Backend-Browserlauf mit negativer EUR-Position; gleicher Hinweis in allen Ansichten. |
| F2: Kontextverlust | Der Aufgabenlink führte nur zur allgemeinen Quellenroute. | `ReviewContext.tsx` öffnet den passenden Quellenhinweis oder Ledger mit Quelle, Konto und Asset. Rückweg stellt Reviewfilter und Aufgabenpanel wieder her. | Browser: 22 EUR-Ledgerbewegungen statt unspezifischer Quellenliste; Rückweg mit identischer Review-URL. |
| F3: Epochendatum | `fiat_price_point("EUR")` liefert einen festen Referenzwert mit technischem Zeitanker. | `priceReference` zeigt für `fiat:EUR` den EUR-Referenzwert. Unbekannte Zeitpunkte, technische Fiat-Zeitanker und echte historische Preise bleiben unterscheidbar. | Node-Tests unter UTC und Europe/Berlin; Desktop-/Mobil-Browserlauf gegen echte Portfolioantwort. |

Hauptdateien: `domain/workspace.py`, `contracts/workspace.py`,
`SourceWorkspace.tsx`, `ReviewWorkspace.tsx`, `Transactions.tsx`,
`ReviewContext.tsx`, `resource.ts`, `Ui.tsx`, `view-state.ts`.
OpenAPI und generierte Endpunktreferenz wurden entsprechend aktualisiert.

## Verbindliche Trennung der Hinweise

- `issues_count`: unverändert vorhandene Quellen-/Bewertungshinweise, getrennt
  nach `price_issues_count` und `reconciliation_issues_count`.
- `review_tasks_count`: eindeutig zugeordnete Review-Aufgaben.
- `ambiguous_review_tasks_count`: mögliche Bezüge mit ungeklärter Zuordnung.
- `blocking_review_tasks_count`: blockierende Aufgaben unter den eindeutig
  oder möglicherweise zugeordneten Aufgaben; nicht zusätzlich addieren.
- `review_reconciliation_tasks_count`: zugeordnete Review-Aufgaben der
  bestehenden Kategorie Quellenabgleich, einschließlich möglicher Bezüge.
- Der Filter „Abgleich offen“ berücksichtigt Quellenabgleich, zugeordnete
  Abgleichaufgaben und bestehende Quellenwarnungen. „Mit Review-Aufgaben“
  filtert unabhängig davon nach Review-Bezug. Ein Preisproblem allein wird
  nicht automatisch als Quellenabgleich umklassifiziert.

Keine Ableitung aus übersetztem Aufgabentitel oder frei formulierter Beschreibung.
Konten und Ereignisse werden anhand gespeicherter IDs aufgelöst; strukturierte
Quellengruppen verwenden die bestehende Quellen-ID-Funktion. Mehrere passende
Quellen oder unvollständige Kontobezüge werden als mehrdeutig ausgewiesen,
nicht automatisch einer Quelle zugewiesen. Kandidaten bleiben zugänglich.
Fehlt eine Zuordnung, erklärt das Panel die Grenze ausdrücklich.

Das Quellendetail zeigt höchstens 50 Aufgaben, weist auf eine verkürzte Liste
hin und verlinkt die vollständige serverseitig paginierte Reviewliste.
Die Zähler berücksichtigen weiterhin alle Aufgaben. Bestehende Gate-Regeln,
Freigaben, Berechnung und Review-Entscheidungen wurden nicht verändert.

## Ansichtsstatus und Datenschutz

Bestehende Hash-Routen bleiben gültig. Ergänzungen:

```text
#sources?detail=s_<20 Hexzeichen>&detailTab=issues&task=<Aufgaben-ID>
#flows?tab=ledger&source=s_<20 Hexzeichen>&account=a_<20 Hexzeichen>&asset=EUR&task=<Aufgaben-ID>
#review?source=s_<20 Hexzeichen>
```

`account` enthält einen gekürzten SHA256-Bezug, nicht die Kontobezeichnung
oder Wallet-Adresse. Das ist kein Anonymitätsversprechen und keine Berechtigung;
bestehende Zugriffsregeln gelten unverändert. Rohkontonamen bleiben außerhalb
der URL. Der Server validiert die ID und filtert parametrisiert.
Im kontobezogenen Ledger filtert `asset` die tatsächliche Ledgerbewegung;
ein EUR-Prüfhinweis führt deshalb nicht zusätzlich zu allen BTC-Gegenbuchungen.

`task` stellt einen Rückweg zur ursprünglichen Aufgabe bereit. Reviewfilter,
Seitengröße und Seite bleiben beim Wechsel erhalten. Ein zuvor eingegebener
Transaktionssuchtext wird beim gezielten Absprung bewusst verworfen, damit
er den fachlich vorbereiteten Kontext nicht verdeckt. Suchtexte bleiben
weiterhin ausschließlich im Arbeitsspeicher und gelangen nicht in die URL.

## Weitere UX-Nacharbeit

- Mengen werden ohne Gleitkommakonvertierung kompakt angezeigt. Bei gekürzter
  Darstellung ist der unveränderte exakte Wert per Tastatur aufklappbar.
  Speicherung, API-Präzision, CSV-Ausgabe und Berechnung bleiben unverändert.
- Singular-/Pluralformen und Ladeformulierungen der betroffenen Arbeitsansichten
  wurden korrigiert; technische Vorzeicheninterpretation aus der Liste entfernt.
- Konto-/Asset-Prüfbezüge werden im normalen Reviewablauf verständlich benannt;
  technische Herkunft und Rohmetadaten bleiben in Details verfügbar.
- `GET /api/v1/workspace/environment` ist lesend. Nur die ausdrücklich vom
  isolierten Vorschauprozess gesetzte Kennzeichnung aktiviert den sichtbaren
  Hinweis „Synthetische Testumgebung“. Keine Erkennung anhand von Kontonamen.
  Die Hilfeseite bleibt ohne API-Abfrage benutzbar.

## Ausgeführte Prüfung

- Vollständige Backend-Suite einschließlich vorhandener Fachberechnungstests:
  **1.216 bestanden, 4 übersprungen, 0 fehlgeschlagen**; Laufzeit 391,91 Sekunden.
  Befehl: `PYTHONPATH=src:/tmp/steuerreport-release-tools-20261025 STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 pytest -q -n 4 --junitxml=artifacts/ux-review-20261026/backend-junit.xml`.
  Vollständiger Bericht: `ux/2026-10-26-review/backend-junit.xml`.
- Gezielte Workspace-Tests für gleiche Zuordnung, fremdes Konto, Mehrdeutigkeit,
  unvollständige Kontobezüge, Umbenennung, Pagination, DB-Unverändertheit und
  tatsächlichen synthetischen Korrekturimport ohne Review-Entscheidung.
- `ruff check src tests scripts`, Frontend-Typecheck und Vite-Build.
- `check_workspace_state_v2.cjs` unter UTC und Europe/Berlin: URL, Kontext-IDs,
  unveränderte historische Preiszeitpunkte sowie exakte/kompakte Dezimaldarstellung.
- Bestehender synthetischer UX-Browserlauf: Hilfe, Importvorschau, KI und
  A01–A23 einschließlich vier Bildschirmbreiten. Schreibaktionen bleiben gemockt.
- Neuer `check_review_backend_browser_v2.py`: F1–F3 gegen die tatsächliche
  FastAPI-Anwendung und eine isolierte 45-Ereignis-Datenbank. Browserabfragen
  werden an TestClient weitergereicht, nicht durch vorbereitete Fachantworten ersetzt.
  Ausgehende Provider-Verbindungen sind im Vorschauprozess gesperrt.
- Derselbe Backend-Browserlauf und die Zeitzonenprüfung sind in der vorhandenen
  CI ergänzt; sie wurden hier lokal ausgeführt, nicht als GitHub-Lauf behauptet.
- Der zusätzliche Korrekturschritt importiert ausschließlich in diese temporäre
  Testdatenbank eine synthetische EUR-Finanzierung und baut deren Ledger neu auf.
  Danach verschwinden Aufgabe und Abgleichtreffer nach lesender Aktualisierung.
  Original-Importhashes bleiben erhalten, keine Review-Entscheidung wird angelegt.
- Gesamte DB-Fingerprints vor und nach Browser-Leseabläufen müssen übereinstimmen.
  Ein schreibender Pipeline-Aufruf an die Vorschau muss HTTP 403 liefern.
- Gitleaks über den exportierten Git-Dateibestand: neun bereits einzeln
  freigeprüfte Nicht-Secrets, null neue ungeprüfte Treffer, keine Erweiterung
  der Ausnahmeliste. Guard gegen private Standardwerte: null Verstöße.
  Privater Identifikator-Guard über Arbeitsbaum und sämtliche lokalen Git-Objekte:
  null Vorkommen aus dem hinterlegten 132-Einträge-Prüfsatz. Das ist keine
  Garantie gegen alle denkbaren unbekannten Geheimnisse oder personenbezogenen Daten.

Der erste F3-Browserlauf scheiterte an einem zu engen Exakttext-Selektor für
gemeinsamen Tabellenzellentext. Die sichtbare EUR-Referenz war bereits korrekt;
der Text wurde eindeutig ausgezeichnet und der gesamte Ablauf erneut geprüft.
Dies war kein nachgewiesener weiterer Fachfehler.

Screenshots und maschinenlesbare Berichte:
[`ux/2026-10-26-review/`](ux/2026-10-26-review/).
Sie enthalten ausschließlich synthetische Daten. Alte Nachweise unter
`ux/2026-10-26/` bleiben erhalten und werden nicht als neue Prüfung ausgegeben.

Die laufende Vorschau unter `http://192.168.2.122:18014/` wurde ebenfalls
lesend im Browser geprüft: Quellenhinweis, direkter EUR-Ledger, Rückweg und
EUR-Referenz bestehen. Schreibender Pipeline-Aufruf: HTTP 403. Die vorherige
Vorschau-Datenbank bleibt bytegleich erhalten; produktives Docker-Image und
Startzeitpunkt des Containers auf Port 18010 bleiben unverändert.

## Reproduktion

```bash
PYTHONPATH=src pytest -q tests/unit/test_workspace_read_models.py
ruff check src tests scripts
node scripts/check_workspace_state_v2.cjs
TZ=Europe/Berlin node scripts/check_workspace_state_v2.cjs
npm --prefix frontend run build
PYTHONPATH=src python3 scripts/export_openapi_v2.py --check
python3 scripts/generate_api_endpoint_reference_v2.py --check
PYTHONPATH=src:/tmp/steuerreport-browser-tools python3 scripts/check_review_backend_browser_v2.py --browser-executable /root/.cache/ms-playwright/chromium-1187/chrome-linux/chrome --output artifacts/ux-review-20261026
PYTHONPATH=/tmp/steuerreport-browser-tools python3 scripts/check_ux_browser_v2.py --browser-executable /root/.cache/ms-playwright/chromium-1187/chrome-linux/chrome --output artifacts/ux-review-20261026/legacy
```

Die `/tmp`- und Browserpfade sind Voraussetzungen dieser Prüfumgebung und bei
einer anderen Installation anzupassen. Für eine neue schreibgeschützte Vorschau
einen noch nicht vorhandenen Ausgabeordner wählen; keine bestehende DB einsetzen:

```bash
PYTHONPATH=src python3 scripts/run_ux_sandbox_v2.py --directory /tmp/steuerreport-ux-neue-pruefung --host 0.0.0.0 --allowed-host 192.168.2.122 --port 18014
```

## Grenzen

Keine Aussage über echte Exchange-Zugänge, vollständige Originaldaten,
steuerliche Richtigkeit eines Nutzerdatenbestands oder Gerichtstauglichkeit.
Kein produktiver Import, keine historische Finanzdatenänderung und keine
automatische Anerkennung eines Transfers oder einer Review-Entscheidung.
Die aktuelle fachliche Aufgabenberechnung verwendet weiterhin den vorhandenen
ReviewService; sehr große Bestände sind hier nicht lastgetestet.
Bestehende Vite-Warnung zum Haupt-Chunk über 500 kB bleibt offen.
Die responsive Regression ist keine vollständige WCAG- oder Screenreader-Abnahme.
