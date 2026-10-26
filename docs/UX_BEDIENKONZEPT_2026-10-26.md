# Bedienkonzept V2: Implementierung und Übergabe

Stand: 26.10.2026. Arbeitsbranch: `feat/bedienkonzept-20261026`.
Ausgangspunkt: `4b6eff1e189d602e1e57d95aed9b096c073f68ed` (RC13).
Dies ist ein unveröffentlichter Entwicklungsstand, kein produktives Update.
Kein Push, Release, Tag oder Austausch des laufenden Docker-Containers gehört zu diesem Auftrag.

## Ausgangszustand und Grenzen

- Repository `/workspace/steuerreport-v2-clean` wurde sauber vorgefunden; bestehende Änderungen wurden nicht zurückgesetzt.
- Anweisungen aus `/workspace/AGENTS.md` und dem Repository wurden gelesen; Umsetzung auf eigenem Branch.
- Vorhandene Architektur: React 18, TypeScript, Vite, Lucide, Hash-Navigation; FastAPI, Pydantic, DuckDB und bestehende Fachservices. Keine neue UI-/Testplattform.
- Die bereitgestellten Dateien `Analyse.md`, `UX-Testbericht.md` und `UX-Evidence-Index.json` unter `/workspace/blockpit-analysis/` wurden als Bedienreferenz gelesen. Keine Blockpit-APIs, Marken, Medien, Profile oder Programmdateien übernommen.
- Der produktive RC13 wurde ausschließlich lesend auf `#dashboard`, `#sources`, `#flows`, `#review` bei 1440 und 390 CSS-Pixeln geprüft. Keine JavaScript-Fehler und kein horizontaler Seitenoverflow in diesen Stichproben.
- Diese Stichprobe belegt keine Vollständigkeit importierter Daten. Private Ausgangsbilder bleiben außerhalb des Repository unter `/root/.local/share/steuerreport/ux-baseline-20261026T084149Z/`; sie sind nicht Teil der öffentlichen Übergabe.
- Neue Ablauf-, Fehler-, Schreib- und Exportprüfungen verwenden ausschließlich synthetische Daten. Keine produktive fachliche Entscheidung und kein kostenpflichtiger Abruf wurde ausgeführt.

## Funktionsmatrix und Zuordnung

| Anforderung | Umsetzung / Dateien | Validierung |
| --- | --- | --- |
| P0 Statuswahrheit | `domain/workspace.py`, `contracts/workspace.py`, `workspace/resource.ts`, `Ui.tsx` | DB-Fingerprint, A01–A05, A15, exakte Dezimaltests |
| Navigation, URL und Listenstandard | `main.tsx`, `workspace/view-state.ts`, `Ui.tsx`, `workspace.css` | A06–A10, A13, A19–A21; Node-Zustandsprüfung |
| P1 eigene Quellen und Detail | `SourceWorkspace.tsx`, neue Workspace-Read-Modelle | A03, A05–A08, A11, A20–A22 |
| Geführtes Hinzufügen / Importübergabe | `SourceWorkspace.tsx`, `FileImportWizard.tsx` | Pflichtfelder, verschleierte Eingaben, Abbruch, Helium-Dateiprofil ohne Importausführung |
| P2 Ereignisse / Ledger / Export | `Transactions.tsx`, `ActivityService`, Activity-Verträge und API-Routen | A08–A13, A18, A23; SQL-Pagination, Originalpräzision, CSV-Formelschutz |
| P2 Aufgaben statt Diagnoseblöcke | `ReviewWorkspace.tsx`, `WorkspaceService.review_page` | A14–A15; unveränderte Regeln, geprüfte Ereignislinks, paginierte Aufgaben |
| P3 Dashboard | `DashboardWorkspace.tsx` | A01–A04, A15–A17, vier Breiten |
| P3 Jahreskontext / Berichtsumfang | `YearWorkspace.tsx`, `WorkspaceService.status` | Jahreswechsel zur Berichtsansicht, Vorschau statt neuer Freigabe, Backend-Status-Gates |
| P4 Hilfe / Abnahme | `Help.tsx`, Browser-Skripte, Node-Prüfung, Backend-Tests, CI | A01–A24, nachstehende Befehle und synthetische Bilder |

Die Navigation gruppiert Überblick, Daten, Bearbeitung, Abschluss, Auswertungen und Verwaltung. Einrichtung, KI, Hilfe, Portfolio/Haltefristen, Stichtage und Zugewinndossier bleiben erreichbar.
`Daten importieren` bleibt ein eigener Eintrag: Der bestehende Importassistent bearbeitet mehrere Quellen, Dateivorschau, Dublettenprüfung und Importverlauf. Zusätzlich ist er unter Quellen und im Hinzufügen-Ablauf verknüpft.
Der technische Quellenbereich, bisherige Review-Belegspuren, steuerliche Details und globale Reportwerkzeuge bleiben hinter ausdrücklich benannten Tabs erhalten. Alte Abgabestände, BMF-Nachweise und Freigabeabläufe wurden nicht entfernt.

## Statusableitung

`GET /api/v1/workspace/status?year=2025` ist ein lesendes Aggregat vorhandener Daten und Fach-Gates. Es erteilt selbst keine Freigabe.

1. Datenbasis: eigene konfigurierte/registrierte/importierte Quellen, Ereignisse, Importzeitpunkt und bestehender Berechnungslauf.
2. Jahresbezug: Ereignisanzahl nach der bestehenden Berichtsjahr-Regel, einschließlich der vorhandenen Helium-Perioden-Ausnahme. Kalender-Datumsfilter arbeiten mit Europe/Berlin und UTC-Grenzen.
3. Vorschau: Ereignisse des gewählten Jahres und ein vorhandener Berechnungslauf. Ein nachfolgender Import kennzeichnet den Lauf als veraltet.
4. Finaler Status nur, wenn zusätzlich der bestehende Review-Gate Export erlaubt, die bestehende Readiness `can_file_without_review` bestätigt und das Jahr bereits in `ready_years` steht. Vorhandene Fach-Gates bleiben maßgeblich.
5. Nächster Schritt: Quelle → Import → fehlende/veraltete Berechnung → Review → Jahresprüfung → Bericht. Keine Freigabe allein aus einer leeren Aufgabenliste.

Datenabdeckung, Berechnung, Review, Jahresbestätigung und Export werden getrennt angezeigt. „Berechnungsstand vorhanden“ ist keine Behauptung, dass alle denkbaren Methoden-/Konfigurationsänderungen erkannt wären. Bereits vorhandene feinere BMF-/Filing-Prüfungen bleiben in den Jahresdetails maßgeblich.

Ressourcen unterscheiden initial, Laden, erfolgreiche Daten, fachlich leere Listen, Teilfehler und veraltete vorherige Antworten. Fehler bleiben sichtbar; Wiederholen liest erneut. Eine bisherige erfolgreiche Antwort bleibt mit Zeitstempel erhalten. Veraltete Suchantworten können durch Request-Abbruch und Antwortversionierung keine neueren Ergebnisse überschreiben.

Fehlende Werte erscheinen als „Noch nicht verfügbar“, bestätigte Null als `0,00 EUR`. Auch die vorhandene technische Nullannahme `expected_zero_policy_no_current_live` ist ohne aktuellen Nachweis keine bestätigte Null. Ein belegter leerer API-Bestand bleibt dagegen nach einem späteren Abruffehler erhalten. Dezimalwerte einschließlich Exponentialdarstellung werden ohne Gleitkomma-Konvertierung formatiert und verglichen; Rundung betrifft nur die Anzeige. Preisabdeckung ohne bewertbare Positionen wird nicht als 100-Prozent-Erfolg ausgegeben. Live-Vergleich und berechneter Ledger-Bestand werden nicht addiert oder als ein gemeinsames bestätigtes Vermögen ausgegeben.

## URL- und Ansichtsstatus

Bestehende Hash-Routen bleiben erhalten. Beispiel:

```text
#flows?tab=ledger&year=2025&asset=BTC&sort=oldest&page=2&size=10
#sources?status=failed&sort=issues&detail=s_aaaaaaaaaaaaaaaaaaaa&detailTab=issues
#review?category=evidence&status=high&year=2025
#tax?year=2024
```

| Parameter | Bedeutung / zulässige Werte |
| --- | --- |
| `tab` | Bereichsspezifische erlaubte Tabs; Standard wird nicht ausgeschrieben |
| `year` | 2000–2100; in Listen zusätzlich `all`, Dashboard/Steuerjahre/Berichte mit konkretem Jahr |
| `page`, `size` | Seite ab 1, normalisiert; 10/25/50/100 Zeilen |
| `sort` | Transaktionen `newest`/`oldest`; Quellen `name`/`value`/`issues` |
| `source` | Opaquer Quellenverweis `s_` plus 20 Hash-Zeichen, keine Wallet-/Kontoadresse |
| `asset`, `type` | Begrenztes Assetkürzel bzw. vorhandener Ereignistyp |
| `status` | Quellenstatus, Datenhinweis oder Review-Priorität, je Bereich getrennt validiert |
| `category` | Vorhandene Review-Kategorie |
| `start`, `end` | Geprüfte Kalenderdaten; umgekehrte Spanne wird normalisiert |
| `detail`, `detailTab`, `detailPage` | Stabile Datensatz-ID, erlaubter Detailtab, eingebettete Transaktionsseite |

Unbekannte Parameter, ungültige Tabs und ungültige Werte werden ohne History-Schleife normalisiert. Filteränderungen setzen die Listenseite zurück. Veraltete Antworten dürfen die neue Seite nicht zurücksetzen. Browser-Zurück/Vorwärts und Neuladen stellen den erlaubten URL-Zustand wieder her.

**Datenschutzausnahme:** Freitextsuche wird niemals als `q` oder anderer URL-Parameter serialisiert und nicht in LocalStorage/SessionStorage gespeichert. Sie bleibt maximal 200 Zeichen lang pro Bereich im Arbeitsspeicher des Anwendungstabs; Neuladen leert sie. Nach Neuladen ist deshalb die ungefilterte Textsuche beabsichtigt. Öffnen/Schließen von Details erhält den Suchkontext. Ausgewählte Zeilen bleiben nur im Arbeitsspeicher; Filteränderungen löschen die Auswahl.

Bereichswechsel merken ihren Ansichtsstatus im Speicher; der gemeinsame konkrete Jahreskontext folgt zwischen Dashboard, Steuerjahr und Berichten mit. Ereignis- und Ledger-Tabs beginnen wegen ihrer unterschiedlichen Zeilenbasis bei Seite 1. Die zuletzt verwendete Sektion wird nicht als unbeschränkter Finanzdatencache gespeichert. Zum Import wird ausschließlich ein erlaubter Anbieter-Enum einmalig per SessionStorage übergeben und sofort wieder entfernt; keine Konten, Dateien oder Zugangsdaten.

## Tatsächliche Aktionswirkungen

| Aktion / Vertrag | Wirkung und Schutz |
| --- | --- |
| Ansicht aktualisieren | Nur bereits gespeicherte Daten erneut lesen. Kein Exchange-Sync oder Pipeline-Rebuild. |
| `GET /workspace/sources`, `GET /workspace/sources/{ref}`, `GET /workspace/status` | Lesende UI-Read-Modelle; vorhandene Bewertungs-, Ownership- und Gate-Regeln. Kein Ereignis-Vollscan für Quellendetails. |
| `POST /activity/query` | Lesende, parametrisierte SQL-Abfrage; Filter/Suche im Body, echte serverseitige Pagination, maximal 100 Zeilen pro Seite. |
| `GET /activity/assets`, `GET /activity/events/{id}` | Gespeicherte Auswahlwerte / Originalbeleg, Hash, Zeile, Ledger, vorhandene Steuerzeilen und freigegebene Änderungshistorie. Keine Interpretation wird als Originalbeleg bezeichnet. |
| `POST /workspace/review/query` | Lesende Filterung und Pagination der vorhandenen Review-Regeln; auch exakte Task-ID. Nur nachweislich vorhandene Ereignisse werden verlinkt. |
| `POST /activity/export.csv` | Lesend im Speicher, ohne Paket-/Jobpersistenz; ausdrücklich `filtered`, `selected` oder `all`. Maximal 25.000 Zeilen, darüber HTTP 413 ohne Teilerfolgsbehauptung. CSV mit Originalpräzision und Schutz gegen Formelauswertung in Textzellen. |
| `POST /workspace/sources/{ref}/sync` | Ausdrücklich bestätigter externer Abruf des vorhandenen Bestands-Connectors. Speichert Snapshots, Versuchsprotokolle und ggf. Solana-Preise; dieser Pfad importiert keine Transaktionshistorie. Vorheriger erfolgreicher Stand und jüngster Fehler werden getrennt angezeigt. |
| Globaler Quellenabruf im Expertenmodus | Vorhandener externer Sammelabruf bleibt erreichbar; Wirkung wird jetzt vorher bestätigt. |
| Externe Binance-Earn-Vorschau | Bereits vorhandener **GET mit Anbieterzugriff**; startet nicht mehr automatisch beim Öffnen des Quellenbereichs. Im Expertenmodus nur nach ausdrücklicher Bestätigung. |
| `POST /pipeline/rebuild` | Vorhandene Normalisierungs-/Preis-/Ledger-/FIFO-/Steuer-/Derivate-Pipeline. Kein Anbieterabruf, keine neue fachliche Entscheidung. Neue Oberfläche erklärt Gesamtumfang und bestätigt. |
| Doppelstartschutz | Frontend-Ref-/Busy-Sperren; zusätzlich gemeinsamer nichtblockierender Prozess-Lock für neuen Sync, globalen Snapshotabruf und zentralen Pipeline-Rebuild (409 bei Parallelstart, Freigabe auch im Fehlerfall). Kein neuer verteilter Jobdienst. |
| API-Zugangsdaten speichern | Vorhandener Credential-Vertrag. Der neue Assistent verlangt einen eingerichteten Vault, prüft Pflichtfelder und weist auf das Ersetzen vorhandener Zugangsdaten hin. Keine behauptete externe Verbindungsvalidierung, kein automatischer Sync, Import oder steuerliche Aktivierung. |
| Wallet nachweisen | Vorhandene Challenge/Signatur-Verträge mit unveränderter Schreibfreigabe und ggf. Setup-Token. Kein Private Key und keine Seed-Phrase. Eigentum und steuerliche Aktivierung bleiben getrennt. |
| Review anwenden | Nur über bestehende validierte Entscheidungs-/Korrekturabläufe mit Belegbindung und Audit. Neue Aufgabenansicht trifft keine Entscheidung. |
| Jahresvorschau / Checkliste | Lesende Jahresausgabe; gewähltes Jahr, keine Übernahme von Transaktionsfiltern. Keine neue Freigabe. |
| Jahres-Belegpaket `.zip` | Vorhandener **GET mit schreibendem lokalem ZIP-Cache**. Wirkung korrigiert dokumentiert und vor Aufruf bestätigt. Keine Änderung eines alten Abgabestands. |
| Globale PDF-/Reportwerkzeuge | Vorhandene Fach-Gates unverändert; ausdrücklich global, nicht irreführend als automatisch jahresgefiltert bezeichnet. |

Downloads melden erst nach vollständig empfangener Serverantwort „bereitgestellt“. Die Anwendung behauptet nicht, das lokale Speichern auf dem Endgerät bestätigt zu haben. Es gibt keine neu erfundenen Hintergrund-Jobs oder Polling-Schleifen.

## Abnahmematrix

Belege: `scripts/check_workspace_browser_v2.py`, `scripts/ux_workspace_fixtures.py`, `tests/unit/test_workspace_read_models.py`, `scripts/check_workspace_state_v2.cjs` sowie [Browser-Prüfprotokoll](ux/2026-10-26/workspace-verification.json) und [Backend-JUnit-Protokoll](ux/2026-10-26/backend-junit.xml).
„Bestanden“ bezeichnet genau den genannten synthetischen Prüfrahmen, keine Freigabe produktiver Finanzdaten.

| ID | Ergebnis | Konkreter Nachweis |
| --- | --- | --- |
| A01 | Bestanden | Frisches Konto: Setup statt Portfolio-/Freigabeerfolg; leere Basis nicht als 100 % Preisdeckung. |
| A02 | Bestanden | Jahresstatusantwort zurückgehalten: Laden statt vorläufigem Erfolg. |
| A03 | Bestanden | Bestätigte Null und unbekannter Quellenwert nebeneinander; Node-Prüfung auch `0E-18`. |
| A04 | Bestanden | Einzelner Portfolioabruf scheitert; alte Bestände, andere Daten und Wiederholen bleiben nutzbar. |
| A05 | Bestanden | Quelle zeigt vorherigen Erfolg mit Zeitstempel und jüngsten fehlgeschlagenen Versuch separat. |
| A06 | Bestanden | Quellenstatus, Sortierung und debouncte Suche; zusätzlich verspätete Transaktionsantwort mit ignoriertem AbortSignal. |
| A07 | Bestanden | Suche ohne Treffer, Filter zurücksetzen, Ausgangsliste wiederhergestellt. |
| A08 | Bestanden | Ereignisdetails und Rohbeleg aus Seite 2; danach gleiche URL, Scrollposition und Fokus. |
| A09 | Bestanden | URL-Neuladen erhält Filter, Sortierung, Seite und Größe; Suchtext absichtlich nicht in URL. |
| A10 | Bestanden | Browser zurück/vorwärts zwischen Filtern, ohne Schleife; Node-Test auf identische Navigation. |
| A11 | Bestanden | Leere API-Pflichtfelder blockieren; Abbruch ohne Schreiben. Helium-Dateiquelle öffnet passenden Importassistenten ohne Importausführung. Keine reale Anbieter-Verbindungsprüfung behauptet. |
| A12 | Bestanden | 22 Ereignisse gegenüber 44 Ledger-Bewegungen im gleichen Filterbereich korrekt benannt. |
| A13 | Bestanden | SQL-Pagination, Filterreset auf Seite 1, Sortierung, URL und Seitenanzahl zusammen geprüft. |
| A14 | Bestanden | Aufgabe mit Problem, Auswirkung, Beleg und verifiziertem Ereignislink; bestehender Fachablauf erreichbar. |
| A15 | Bestanden | Leeres Review-Gate bei offener Jahresbestätigung bleibt Vorschau; Backend verlangt alle bisherigen Gates und das konkrete Jahr. |
| A16 | Bestanden | Refresh und Ansichtswechsel erzeugen keinen Sync/Rebuild; alle Browser-API-Aufrufe abgefangen. |
| A17 | Bestanden, synthetisch | Bestätigung, Busy-Sperre, Sync-Fehler, Rebuild-Rückmeldung. Backend-Paralleltest mit gemocktem Provider: 409 für zweiten Sync und Rebuild, Lock nach Fehler wieder frei. Kein realer Abruf. |
| A18 | Bestanden | CSV-Download enthält alle 22 gefilterten Testzeilen statt nur sichtbarer Seite; Backend prüft zusätzlich Auswahl, Gesamtumfang, Obergrenze und Dezimalpräzision. |
| A19 | Bestanden | Ausgefüllte Passwortfelder dauerhaft benannt, Werte nach Fokuswechsel erhalten. |
| A20 | Bestanden, Kernabläufe | Panel-Initialfokus, Tab-Umlauf, Escape/Fokusrückgabe; Quellenmenü per Tastatur. Tabs mit Auswahlzustand, Tastatursteuerung und Tabpanel-Bezug. Keine vollständige WCAG-Zertifizierung. |
| A21 | Bestanden | 390, 768, 1280 und 1440 CSS-Pixel: Hauptansichten, Details und mobile Navigation; Tabellen mit eigenem Scrollbereich. |
| A22 | Bestanden | Quellenregistry / technische Diagnose im Expertenmodus erreichbar, kein automatischer externer Earn-Abruf. |
| A23 | Bestanden | `#flows` bleibt Transaktionseinstieg; Geldflüsse und Transferkandidaten bleiben eigene Tabs. |
| A24 | Bestanden | Abschließender vollständiger Backend-Lauf: **1.211 bestanden, 4 übersprungen**, einschließlich aller 14 neuen Workspace-Tests. Steuer-/FIFO-Tests und Regeln nicht umgeschrieben. Laufzeit 376,99 Sekunden; vier bestehende Deprecation-Warnungen. |

## Browserbelege

Alle folgenden Bilder enthalten ausschließlich synthetische Quellen und Datensätze. Dateinamen nennen die tatsächliche CSS-Viewportbreite. Details sind als Viewportbild aufgenommen; Listen können einen vollständigen Seitenverlauf zeigen. Das JSON protokolliert Viewport, Route, Zustand und Aufnahmemodus. Auch 768 und 1280 Pixel wurden geprüft; ihre vollständigen Bilder liegen im lokalen/CI-Artefaktverzeichnis.

| Bereich | Desktop, 1440 Pixel | Mobil, 390 Pixel |
| --- | --- | --- |
| Dashboard | [Bild](ux/2026-10-26/dashboard-1440.png) | [Bild](ux/2026-10-26/dashboard-390.png) |
| Eigene Quellen | [Bild](ux/2026-10-26/sources-1440.png) | [Bild](ux/2026-10-26/sources-390.png) |
| Quellendetail | [Bild](ux/2026-10-26/sources-detail-1440.png) | [Bild](ux/2026-10-26/sources-detail-390.png) |
| Transaktionen | [Bild](ux/2026-10-26/flows-1440.png) | [Bild](ux/2026-10-26/flows-390.png) |
| Transaktionsdetail | [Bild](ux/2026-10-26/flows-detail-1440.png) | [Bild](ux/2026-10-26/flows-detail-390.png) |
| Review | [Bild](ux/2026-10-26/review-1440.png) | [Bild](ux/2026-10-26/review-390.png) |

Zusätzlich wurde das echte Backend mit isolierter synthetischer DuckDB auf allen sechs neuen Hauptansichten lesend geprüft: keine JavaScript-Fehler, keine API-Fehlerhinweise und kein horizontaler Seitenoverflow bei 1280 Pixeln. Die beabsichtigte fachliche Review-Sperre wegen fehlender Finanzierungsdaten der Testkäufe bleibt sichtbar, sie wurde nicht bestätigt oder umgangen.

## Prüf- und Startanleitung

Vom Repository-Stamm, mit den Projektabhängigkeiten:

```bash
env PYTHONPATH=src STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 pytest -q -n 4
env PYTHONPATH=src STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 pytest -q tests/unit/test_workspace_read_models.py
ruff check src tests scripts
node scripts/check_workspace_state_v2.cjs
env PYTHONPATH=src python3 scripts/export_openapi_v2.py --check
env PYTHONPATH=src python3 scripts/generate_api_endpoint_reference_v2.py --check
env PYTHONPATH=src python3 scripts/check_private_data_v2.py
```

Frontend: in `frontend/` zuerst `npm ci` und `npm run build`. Auf dem vorhandenen NAS-Dateisystem war `npm ci --no-bin-links` erforderlich. Der Build ist erfolgreich; die bereits bekannte Warnung zum großen Haupt-Chunk bleibt bestehen. Auf dieser Maschine liegen Python-Testzusätze isoliert unter `/tmp/steuerreport-release-tools-20261025`, Playwright unter `/tmp/steuerreport-browser-tools`; deshalb wurden diese Pfade bei den entsprechenden Läufen zusätzlich in `PYTHONPATH` gesetzt. Diese temporären Pfade sind keine Produktvoraussetzung.

```bash
python3 scripts/check_ux_browser_v2.py --output artifacts/ux-browser
python3 scripts/check_ux_browser_v2.py --workspace-only --output artifacts/ux-browser
```

Playwright/Chromium müssen installiert sein. Ohne `--base-url` stellt der bestehende Prüfer den Build auf einem freien lokalen Port bereit. **Alle API-Anfragen werden synthetisch beantwortet**, keine echte Datenbank, Börse oder KI wird angesprochen. Lokal wurde Chromium mit explizitem `--browser-executable` verwendet. CI führt den vollständigen Browserlauf und die Node-Prüfung aus und lädt die Bilder als Artefakt hoch.

Für eine bedienbare Vorschau mit echtem Backend, ohne Betreiberprofil:

```bash
env PYTHONPATH=src python3 scripts/run_ux_sandbox_v2.py --directory /tmp/meine-neue-ux-vorschau --port 18014
```

Das Zielverzeichnis muss neu sein; bestehende Datenbanken werden nie überschrieben. Das Skript erzeugt ausschließlich Testdaten, isoliert Profil/Importpfade, verweigert ausgehende Verbindungen und sperrt schreibende API-Aufrufe. Standardbindung ist localhost. Für bewusst gewünschte LAN-Prüfung sind `--host 0.0.0.0` und `--allowed-host <LAN-Adresse-des-Servers>` gemeinsam anzugeben; die Hostprüfung wird nicht pauschal abgeschaltet. Die Vorschau ist nicht der produktive Container.

## Sicherheitsprüfung und bekannte Grenzen

- Keine Betreiberkennungen in neuen Fixtures/Bildern. Der vorhandene Privacy-Guard meldet keine privaten Defaultwerte; der separate lokale Abgleich gegen 132 bekannte private Kennungen fand keine Vorkommen in Arbeitsdateien oder lokalen Git-Objekten.
- Gitleaks wurde am exportierten Repository-Dateistand mit vorhandener exakter Befundprüfung ausgeführt: neun bekannte Quellbefunde, **null ungeprüfte Befunde**, keine privaten Defaultwerte. Ein unbeschränkter Verzeichnisscan umfasst auch ignorierte alte Release-/Build-Artefakte und ist deshalb nicht gleichbedeutend mit dem Repository-Inhalt. Die bisherigen neun bekannten Quellbefunde sind bereits einzeln als öffentliche Assetkennungen, Beispielwert oder Typprüfung dokumentiert; die Freigabeliste wurde für diesen UX-Auftrag nicht erweitert.
- Vorbestehend: große zentrale `main.tsx`/Bundle-Warnung; alte Expertentabellen und Spezialformulare sind nicht vollständig auf das neue Listenmuster migriert. Fachliche Tiefe bleibt dort verfügbar.
- Vorbestehend: Readiness zählt teils noch nicht verwendete Connectoren als Setup-Lücke. Die neue Quellenliste zeigt diese nicht als eigene Quellen, **lockert jedoch nicht** die bestehenden finalen Freigabe-Gates. Eine Bereinigung dieser fachlichen Readiness-Regel braucht einen getrennten Auftrag.
- Vorhandener Quellen-Sync ist ein Bestandsabruf, kein vollständiger Historienimport. Fehlende Historie muss über die angebotenen Importwege beschafft werden; kein erfolgreicher Snapshot wird als Beleg vollständiger Transaktionen ausgegeben.
- Für CEX-Keys existiert kein separater risikofreier Verbindungsprüfvertrag. Die Oberfläche sagt deshalb ausdrücklich nur „Pflichtfelder vorhanden / Zugangsdaten gespeichert“, nicht „Anbieter erfolgreich geprüft“.
- Wallet-Signatur derzeit über öffentlichen Base58-Signaturnachweis und vorhandene Backend-Challenge, kein neuer One-Click-Phantom-/Wallet-Adapter. Die vorhandene Connector-Schreibberechtigung wird nicht erweitert.
- Neuer Transaktions-CSV-Export ist synchron und auf 25.000 Zeilen begrenzt; große Historien nach Zeitraum aufteilen. Detailtabellen sind auf 200 gespeicherte Ledger-/Tax-Zeilen begrenzt und nennen die Gesamtanzahl.
- Der Änderungstab zeigt verknüpfte vorhandene Reviewentscheidungen und aktuell gespeicherte freigegebene Overrides mit Auditlink. Er ersetzt keine vollständige Datenbank- oder Versionshistorie aller früheren Change-Sets; die bestehenden KI-Auditabläufe bleiben dafür erreichbar.
- Aufgaben werden serverseitig gefiltert/paginiert; die vorhandenen Fachservices erzeugen die vollständige Aufgabenbasis intern. Keine Behauptung einer vollständig SQL-paginierten Review-Engine.
- Zentraler Doppelstartschutz gilt innerhalb eines App-Prozesses und für die genannten zentralen Routen, nicht für alle historischen Spezialaktionen oder mehrere Backend-Worker. Kein neuer verteilter Lock/Jobdienst.
- Kein neuer jahresgebundener finaler PDF-Vertrag. Vorhandene globale PDF-Werkzeuge bleiben ausdrücklich global und ihren bisherigen Gates unterworfen.
- WCAG 2.2 AA ist Prüfziel. Die dokumentierten Tastatur-, Fokus-, Label-, Tab- und Responsive-Prüfungen sind keine vollständige manuelle Screenreader-/Kontrast-/WCAG-Zertifizierung sämtlicher Altansichten.
- In frühen Testläufen wurden fehlerhafte Mock-Verträge und Warten auf absichtlich gehaltene Requests korrigiert. Produktfehler waren die kurzzeitig falsche Jahresroute, das Überschreiben eines Filter-Seitenresets durch alte Antworten sowie der Ansichtsstatus beim Wechsel zwischen Steuerjahr und Berichten; diese sind behoben und durch die Browserabläufe abgedeckt.
- Vier bestehende Backend-Tests bleiben übersprungen; vier bestehende Python-Deprecation-Warnungen wurden nicht durch diese UX-Änderung erzeugt. Kein fehlgeschlagener Fachtest wurde als bestanden umetikettiert.

Die Originalbelege, produktiven Finanzdaten, Abgabesnapshots, Freigabeentscheidungen und steuerlichen Berechnungsregeln bleiben unverändert. Der Branch ist zur Prüfung vorbereitet, nicht veröffentlicht oder produktiv ausgerollt.
