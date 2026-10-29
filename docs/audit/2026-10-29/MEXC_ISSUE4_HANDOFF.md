# Issue #4: nativer MEXC-Dateipfad

Stand: 29.10.2026, Entwicklungsbranch feat/mexc-native-xlsx.
Reviewbarer Diff: [PR #7](https://github.com/zonfacter/steuerreport-v2-plan/pull/7).
Basis main: eee90f24a3b7cda8a7f7bef6f8105185f632a4d1, rc35.
Gepruefter Implementierungscommit: d655fedd48bf120ec4b97303971eedafcba0f9e8.
Keine produktive Umschaltung, kein neues Image/Release, keine Finanzdaten-
oder Methodenmigration und keine steuerfachliche Gesamtfreigabe.

## Einschaetzung

Die in #4 beschriebene Luecke war vorhanden: generische Dateilesbarkeit ist
keine korrekte MEXC-Normalisierung. Der erste vertikale Importpfad ist nun
implementiert. Er umfasst bewusst nur belegte Airdrop-Mengen in Spot Statement
und Funding Other als unknown. Ursache, Einkunftsart und Kostenbasis bleiben
offen; der Import erteilt keine Jahresfreigabe.

## Anforderungs- und Nachweismatrix

| Gegenstand aus #4 | Implementierung | Nachweis / Grenze |
| --- | --- | --- |
| Native Quelle, Exportart, Konto | mexc_import, mexc_native, FileImportWizard | Separate UID/Konto-Identitaet, Produktwahl; kein Fallback auf generische Interpretation |
| XLSX/CSV, Header-only, Blatt und physische Zeile | mexc_native.read | Native Referenzproben, leere Exporte nicht als erfolgreiche Buchungen; 10000 Zeilen / 25 MiB / 100 MiB entpackt |
| Zeitbasis | Fester Headeroffset; explizite Time-Zuordnung; Snapshotdatum separat | Sommer-UTC+01:00 wird UTC 11:00; DST-Konflikte blockieren; keine implizite UTC-Annahme |
| Richtung/Praezision | Decimal, XLSX-Zahlenliteral, Ledger-Addition mit lokalem hohen Decimal-Kontext | Negative Outflows nicht doppelt negiert; keine Rundung ausserhalb Decimal(38,18) |
| Doppelbelege / echte gleiche Buchungen | Kandidaten, link_existing / separate, kontogebundene Provider-ID | Wiederholung idempotent; gleicher Betrag allein dedupliziert nicht; gleiche Provider-ID darf nicht separate werden |
| Veraltete Entscheidungen | input_digest plus gespeicherte Kandidatenfakten | Datei, Zeile, Konto, Exportart, Zeitbasis oder Kandidatenwechsel verlangt ausdrueckliche Neubestaetigung |
| Snapshot | Nur Originalbeleg, spezifischer Historien-/Bestandsabgleichpunkt | Null neue Events/Lots; keine gruen behauptete Historie aus einem Snapshot |
| BONUS / andere Produkte | Rohbeleg / offener Review | Keine automatische Gewinn-/Erwerbs-/Rewardklassifikation |
| Airdrop | Quelltext bleibt erhalten; unknown mit Klassifikationsblocker | Keine automatische Mining-, Reward-, private oder betriebliche Zuordnung |
| Raw, Original und Belegspur | Original-SHA, Dateikontext, Zeile, JSON-Trace, Originaldownload | Zwei Originale ergeben nach ausdruecklichem Link genau ein Ereignis; fehlende/verfaelschte Originale sperren Review |
| UI | Quellenwahl, Produkt-/Zeitwahl, Zeilenpanel, Pagination, begruendete Zuordnung, erneute Bestaetigung | 13 isolierte Mock-Browserfaelle; zusaetzlich realer isolierter Import-Backendpfad |
| Legacy-/Metadaten | Strikte Bindungsvalidierung; kein MEXC-Bypass durch fremde Legacy-Marker | Nicht nativ gebundene MEXC-Altimporte erfordern gesonderte Migration; keine automatische Umschreibung |
| Kontohistorie | Herstellergrenze und fehlende Nachweise sichtbar | Self-Service erst ab 01.10.2024; erfolgreicher Import beweist keine vollstaendige Historie |

Spot-Fills, echte externe Ein-/Auszahlungen, Gebuehrenallokation, Migrationen,
Futures, Earn und Send sind hier nicht abschliessend normalisiert. Nur
Headererkennung oder Rohbelegspeicherung bedeutet keine Vollunterstuetzung.
Auch Dubletten in noch nicht zugeordneten fremden Sammelimporten sind durch
diesen kontogebundenen nativen Pfad nicht global ausgeschlossen.

## Unabhaengige Gegenpruefung

Die Testautoren arbeiteten getrennt vom Importer, mit eigenen synthetischen
Dateien, Datenbanken und festen Sollmengen. Im Review des ersten Standes
6228467ce0a1746a4d7e7abe42306bb68f170118 fanden sie reale Luecken. Diese wurden
nicht durch Skips oder weichere Mengen-Sollwerte geschlossen:

| Finding | Korrektur | Gegenprobe |
| --- | --- | --- |
| ID auf Zusatzbeleg ging verloren | Linked-IDs werden dem Root zugerechnet | Gleiche ID mit anderer Menge blockiert vor Batchanlage |
| Gleiche ID per separate verdoppelt | Gleiche belegte Provider-ID nicht uebersteuerbar | Zweite Buchung abgelehnt; verschiedene IDs bleiben legitime Buchungen |
| Snapshot allein wirkte hinweisfrei | Eigener blockierender Bestands-/Historienhinweis | Keine Events/Lots; Review bleibt offen |
| Entscheidung auf andere Datei uebertragbar | Kontext-/Zeilen-/Kandidaten-Digest und explizite Neubestaetigung | Geaenderte Bytes/Konto/Zeitbasis/Kandidaten unveraendert abgelehnt |
| Originalverlust erst beim Download erkannt | Original-SHA/Dateityp im Review-Gate | Fehlend, veraendert, Symlink sperren auch nach Klassifikation/Rebuild |
| Rollenmarker versteckte ungemappte Zeile | Originalfelder/Layout/Rolle/Digest konsistent validieren | Gefaelschte Rolle oder Objektmetadaten sperren |
| Korrigierte Canonical-Menge widersprach Zusatzbeleg | Wirksame Fakten gegen Original-Link pruefen | Mengenabweichung sperrt; reine Typklaerung bei gleichen Fakten bleibt moeglich |

Die zwei Tests fuer ungueltige bestehende Metadaten erwarten nun eine erklaerte
blockierende Vorschau statt einer Exception. Direkter Import bleibt abgelehnt;
DB, Originalarchiv und Bestandsdaten muessen weiterhin unveraendert bleiben.
Der vorhandene Codegraph war auf rc32 indiziert und diente nur der Orientierung,
nicht als Pruefnachweis des aktuellen Codes.

## Ausgefuehrte lokale Pruefungen

Die Originalresultate werden unter mexc-proof/ abgelegt; keine privaten Exporte.
Auf dem Testhost wurden vorhandene isolierte Toolverzeichnisse per PYTHONPATH
eingebunden. Reproduzierbar in einer frischen Entwicklungsumgebung:

```sh
python -m pip install -c requirements-runtime.lock -e '.[dev]'
PYTHONPATH=src pytest tests/acceptance/test_mexc_native_reference.py -q --junitxml=mexc-reference.xml
PYTHONPATH=src pytest tests/acceptance/test_mexc_native_review.py -q --junitxml=mexc-review.xml
PYTHONPATH=src pytest tests/unit/test_mexc_import_api.py -q --junitxml=mexc-api.xml
ruff check src tests scripts
python scripts/check_private_data_v2.py
python scripts/export_openapi_v2.py --check
python scripts/generate_api_endpoint_reference_v2.py --check
python scripts/generate_import_format_docs_v2.py --check
cd frontend
npm ci
npm run build
cd ..
python -m pip install playwright==1.64.1
python -m playwright install chromium
python scripts/check_mexc_import_browser_v2.py --output artifacts/mexc-import-browser
python scripts/check_mexc_import_backend_browser_v2.py --output artifacts/mexc-backend-browser
```

Die Referenztests sperren fremde DuckDB-Dateien und Netzwerkzugriffe. Der echte
Browserpfad nutzt create_app/TestClient und eine temporaere DuckDB; nur andere
Workspace-Anzeigen sind kontrollierte synthetische Antworten. Das ist kein
Test des produktiven Dashboards. Weder Exchange noch KI werden angefragt.
Der Test ruft keine produktive Instanz auf; Originaldownload und JSON-Trace
werden tatsaechlich ueber den isolierten HTTP-/Backendpfad geprueft.

| Pruefung | Tatsaechliches lokales Ergebnis |
| --- | --- |
| Native unabhaengige Referenzproben | 186 bestanden, keine Skips |
| Unabhaengige Review-/Manipulationsproben | 40 bestanden, keine Skips |
| Native API-Proben inkl. Snapshot-Quellenzuordnung und Funding-Status | 12 bestanden; aelteres 9er-Protokoll zusaetzlich erhalten |
| Mock-Browser | 13/13 Szenarien bestanden; auch 320 px und 2003 Zeilen |
| Reales isoliertes Importbackend im Browser | Zwei Raw-Belege, ein Ereignis, Menge 2.5, zwei Trace-Bezuege; Original byteidentisch, Review blockiert; 1440/390 px ohne Seitenoverflow |
| Ruff / Privacy / Vertrags-/Vorlagen-Drift | Erfolgreich; 0 private Standardwerte |
| Gitleaks 8.30.1 | 52 bereits einzeln per Zeilenhash als Nicht-Secrets gepruefte Bestandsfunde, 0 ungepruefte Funde; keine pauschale Ausnahme |
| Privater Prepush-Identifier-Guard | 132 geschuetzte Identifier gegen Arbeitsstand und alle lokalen Gitobjekte: 0 Treffer |

## CI und Abnahmegrenzen

[CI-Lauf des Implementierungsstands](https://github.com/zonfacter/steuerreport-v2-plan/actions/runs/40794782046)
fuehrt die vollstaendige Unit-Suite, Build-/Driftchecks, die vorhandenen
Browserregressionen und beide neuen MEXC-Browserlaeufe aus. Der verpflichtende
Reference-Job umfasst die unveraenderten 52 Originalproben, alle bisherigen
Referenzfaelle plus die 226 neuen MEXC-Proben und den originalen Bitget-Reproducer.
Der aktuelle CI-Abschluss wird im PR/Issue verlinkt; ein gestarteter Job gilt
nicht als bestanden. Screenshots und maschinenlesbare Ergebnisse liegen im
CI-Artefakt ux-browser-evidence, JUnit im mandatory-reference-results.

Der erste integrierte CI-Lauf bestand alle 330 zusaetzlichen Referenzproben,
scheiterte aber im Session-Teardown am bestehenden 500-MiB-Tmpbudget:
1.345.249.104 Bytes behaltener synthetischer Testdateien. Das ist kein gruener
Job und kein fehlgeschlagener Rechen-Sollwert. Der Reference-Job aktiviert nun
dieselbe vorhandene Bereinigung erfolgreicher Test-DuckDBs wie die Unit-Suite.
Budget, Sollwerte, Fehlertests und originale Proben bleiben unveraendert;
fehlgeschlagene Testdatenbanken werden nicht automatisch beseitigt.

Zusaetzliche Abschlusskorrektur: Funding Other darf ein nichtleeres Statusfeld
nicht ignorieren. Solche Zeilen bleiben bis zur belegten Anbietersemantik
offene Rohbelege ohne Bestandsbuchung, auch bei scheinbaren Erfolgsnamen.
Der belegte leere Statuspfad bleibt erhalten. Eigene CSV-/XLSX-Gegenproben
werden dem verpflichtenden Referenzjob hinzugefuegt; die oben archivierten
186/40-Protokolle dokumentieren den davor geprueften Stand, nicht diese neue
Statuspruefung. Der nachfolgende CI-Lauf bindet alle Proben gemeinsam.

Es gibt keine fachliche Gesamtfreigabe, keinen Produktionsimport und keine
gepruefte private MEXC-Historie. Reale Auslegung spezieller Geschaefte und
fehlende Anschaffungskosten bleiben beim bestehenden Review-/Methodenverfahren.

## Betrieb und Rueckweg

Kein Schemawechsel. Neue optionale Anfragefelder; bestehende Quellen und
Dateiwege bleiben erhalten. Das Originalarchiv mexc_originals neben der DuckDB
ist Teil des zu sichernden privaten Datenverzeichnisses. Ohne Originale bleibt
der Import nicht unbemerkt freigegeben. Fuer nicht native MEXC-Altimporte ist
keine automatische Migration enthalten. Ein spaeterer Produktivwechsel braucht
eigenen Versions-/Image-, Backup-/Restore- und Updateauftrag.

Temporaere, abgeschlossene synthetische Test-DuckDBs werden nach Pruefung
laufender Prozesse/offener Dateien entfernt; JUnit, JSON, Screenshots,
Quellcode, Originalbelege, Backups und produktive Volumes bleiben erhalten.
