# Steuerreport V2 0.2.0rc37

Releasekandidat vom 29.10.2026. Diese Version enthaelt begrenzte Korrekturen
und Regressionstests fuer MEXC, Vault-Startschutz, Importkontext und Bitget-CSV.
Sie ist keine vollstaendige Migrationsabnahme oder steuerliche Freigabe.

## Aenderungen

- **GitHub #4:** Eine MEXC-XLSX-Datei mit mehreren Blaettern muss vor einer
  fachlichen Vorschau einem Tabellenblatt zugeordnet werden. Ohne Auswahl
  bleiben Zeilenzaehler, Zeilenpruefung und Importfreigabe gesperrt. Die
  ausgewaehlte synthetische Funding-Datei behaelt Originalbeleg und Zeilenbezug;
  das Ereignis bleibt `unknown` und erzeugt kein Tax-Lot.
- **GitHub #10:** Neue synthetische Entrypoint-Regression: Ein vorhandener
  verschluesselter Zugang mit formal gueltigem, aber falschem Vault-Key darf
  weder Uvicorn starten noch Profile, Schluessel oder Datenbank veraendern.
- **GitHub #13 (Teilumfang):** Die bestehende explizite Binance-Datei-/Konto-
  bindung bleibt erhalten. Die Meldung fuer einen blockierten Historienabruf
  erklaert nun, dass die Kontozuordnung keine CSV/API-Recordidentitaet beweist.
  Es gibt weiterhin keinen interaktiven dauerhaften Matchentscheid fuer
  CSV-/API-Ueberlappungen.
- **GitHub #22 (Teilumfang):** Zusaetzliche leere Bitget-CSV-Felder werden nur in
  der abgeleiteten Parsezeile entfernt; nichtleere unbekannte Felder werden
  nicht still verworfen. Die direkte Preview-/Import-API liefert dazu einen
  strukturierten, zeilengenauen Fehler statt HTTP 500. Datei-Hash, Rohzeile und
  Wiederimport-Idempotenz sind synthetisch getestet.
- **GitHub #26:** Dieselbe Bitget-CSV-Validierung gilt jetzt fuer Text-CSV,
  Base64-Datei sowie die Preview- und Execute-Pfade des Importassistenten.
  Nichtleere Zusatzfelder werden auch hinter den ersten fuenf Vorschauzeilen
  strukturiert abgewiesen, ohne einen Importbatch anzulegen. Die bestehende
  Erkennung von Headern unter einem Exporttitel bleibt erhalten.

## Pruefstand

Ausgefuehrte gezielte Pruefungen:

- `tests/unit/test_connector_bootstrap.py`: 23 bestanden.
- `tests/unit/test_guided_file_import.py` und
  `tests/unit/test_history_review_regressions.py`: 27 bestanden.
- MEXC-API-/Referenz-/Review-Suite: 266 bestanden; die neue
  Mehrblattregression zusaetzlich einzeln bestanden.
- `PYTHONPATH=src:/tmp/steuerreport-v2-test-deps pytest -q
  tests/unit/test_bitget_csv.py tests/unit/test_file_raw_importer.py
  tests/unit/test_guided_file_import.py`: 52 bestanden.
- `ruff check` auf den geaenderten Python-Dateien und `git diff --check`:
  bestanden.
- Synthetische MEXC-Browserpruefung: alle 14 Szenarien bestanden, darunter
  Mehrblatt-Sperre und ausdrueckliche Blattwahl.
- `npm run build`, Python-Ruff auf geaenderten Python-Dateien und
  `git diff --check`: bestanden. Der Frontendbundler meldet weiterhin einen
  grossen JavaScript-Chunk ueber 500 kB.

Die Python-Systemumgebung enthielt zunaechst kein PyNaCl. Die gezielten Tests
liefen anschliessend mit einer isolierten temporaeren Testabhaengigkeit; es
wurde keine Laufzeitabhaengigkeit des Projekts geaendert. Die vollstaendige
Projekt-Testmatrix wurde nicht ausgefuehrt.

## Noch offen

- **GitHub #8, #19 und #20:** Native V1/V2- und Docker-Prozesse sind
  unterscheidbar, aber die aktive DuckDB der nativen V2-Laufzeit ist nicht
  eindeutig zugeordnet. Daher gibt es keinen gebundenen Legacy-Datenstand und
  keinen semantischen Alt-/Neu-Vergleich. Es wurden keine Datenbanken geoeffnet,
  keine produktiven Neuberechnungen gestartet und keine Methoden aktiviert.
- **GitHub #13:** Die genaue, beidseitig belegte CSV/API-Recordzuordnung sowie
  eine persistierte und widerrufbare Matchentscheidung fehlen weiterhin.
- **GitHub #22:** Explizite Bitget-Exportzeitzone mit Persistenz, vollstaendiger
  Produkt-/Kontoskope, Margin-Gebuehrenzuordnung und belegte Handelsbein-
  Verknuepfung bleiben offen.
- **GitHub #26:** Der reproduzierte Text-/Datei-API-Fehler ist im Branch
  behoben und lokal getestet. Das Issue wird erst nach erfolgreichem Merge und
  verpflichtendem CI-Abschluss geschlossen.
- **GitHub #4:** Weitere MEXC-Exporttypen werden nicht pauschal als voll
  unterstuetzt erklaert; Futures/Earn/Transfers brauchen eigenstaendige
  Belegsemantik und Tests.
- Keine vollstaendige steuerfachliche Abnahme realer Bestandsdaten.

## Bereitstellung

Vorgesehene Image-Referenz nach erfolgreichem GitHub-Publish:
`ghcr.io/zonfacter/steuerreport-v2:0.2.0rc37`. Der Image-Digest ist erst nach
erfolgreicher CI-Publikation bestaetigt. Der laufende Produktivcontainer bleibt
unveraendert auf rc36; fuer diesen Releasekandidaten wurde kein Deployment
ausgefuehrt.
