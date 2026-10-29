# Jahresbezogenes PDF: Backend-Schnitt

Stand dieses Dokuments: Issue #18, Branch `fix/issue18-yearly-filing-pdf`, Basis `eee90f24a3b7cda8a7f7bef6f8105185f632a4d1`.

## Backend-Verhalten

Der neue Pfad stellt ausschließlich eine Vorschau aus bestehenden Read-Models dar. Er führt keine eigene FIFO-, Preis-, Steuer- oder Freigabeberechnung aus und bestätigt weder eine Abgabe noch eine menschliche Freigabe.

- `POST /api/v1/tax-years/{year}/reports/pdf` erzeugt einen Jahresbericht. Es gibt kein Seitenzahlfeld. Ohne vorhandenen Steuerlauf wird mit `409 tax_calculation_run_missing` abgebrochen, statt Werte als Null zu erfinden.
- `GET /api/v1/tax-years/{year}/reports/pdf` listet archivierte Berichte des Jahres.
- `GET /api/v1/tax-years/{year}/reports/pdf/{artifact_id}/manifest.json` lädt das gebundene Manifest.
- `GET /api/v1/tax-years/{year}/reports/pdf/{artifact_id}/files/{file_index}` lädt eine konkrete PDF-Datei.

Das PDF enthält die vorhandene Filing-Jahreszusammenfassung, Filing-Zeilen und Checkliste, alle Tax-Line-Positionen des ausgewählten Steuerjahres, Reward-/Income-Assetaggregate und vorhandene Derivatezeilen. Das Manifest bindet Jahr, Berechnungslauf, FIFO-Methode, Eingabefingerprint, Read-Model-Quellen, Zeilenzahlen sowie Größe, SHA-256 und echte Seitenzahl jeder PDF-Datei. Die Seitenzahl wird mit `pypdf` aus dem gerenderten Dokument gelesen; Dateien werden auf höchstens 100 Seiten geteilt und beim Download erneut geprüft.

Der fachliche Bericht und der technische Gate-Status sind getrennte PDF-Abschnitte und getrennte Manifestfelder. Jeder Bericht bleibt `preview`, `final_filing_allowed` bleibt `false`, auch wenn die technischen Gates offen sind oder einen Export zulassen. Ein technischer Status ist keine Steuerfreigabe.

Berichte werden unveränderlich unter `tax_year_report_archive/{year}/{artifact_id}/` relativ zum DuckDB-Verzeichnis gespeichert. Die DuckDB-Tabelle `tax_year_report_pdf_artifacts` registriert Manifest und Bindung. Es gibt in diesem Backend-Schnitt keine Lösch- oder Überschreibroute. Ein neuer Lauf erzeugt eine neue ID und lässt ältere PDF-Bytes unverändert. Die Archivmetadaten sind aus dem Berechnungsfingerprint ausgenommen.

Der bisherige `POST /api/v1/export/pdf`-Pfad bleibt ein technisches Einseiten-Statuspaket, kein Jahresbericht. Das Feld `estimated_pages` ist für Kompatibilität noch im Contract, wird als veraltet markiert und ignoriert; Paketmetadaten melden eine Seite.

## Frontend-Restbedarf

Die React-Oberfläche wurde absichtlich nicht geändert. Der Jahresarbeitsbereich benötigt noch:

1. Eine Aktion „Jahresbericht als Vorschau erzeugen“, die den Pfad für das aktuell ausgewählte Jahr aufruft.
2. Eine Liste bisheriger Bericht-IDs mit Run, Erstellzeit und Vorschaukennzeichnung.
3. Downloadlinks für Manifest und alle Dateien, inklusive mehrteiliger Berichte.
4. Eine sichtbare, getrennte Darstellung von Jahres-Readiness und technischem Gate-Status; niemals ein Label „final“ aus diesem PDF ableiten.
5. Eine verständliche Behandlung von `409` bei fehlendem Berechnungslauf, Bindungskonflikt oder beschädigtem Archiv.
6. Die alte globale Seitenzahl-Eingabe aus dem Statuspaket-Ablauf entfernen; dessen Restaktion ausdrücklich als technisches Statuspaket benennen.

Diese Änderungen sind in diesem Branch nicht implementiert und nicht als abgenommen zu verstehen.

## Grenzen

- Es wurde keine produktive Datenbank gelesen oder verändert, kein Anbieter und keine KI abgefragt und kein Container gestartet.
- Die Tests verwenden synthetische Importdaten und isolierte DuckDB-Dateien.
- Der Bericht reproduziert die bestehenden Jahres-Read-Models. Er validiert nicht unabhängig deren steuerliche Richtigkeit und schließt keine offenen Daten-, Methoden-, Kostenbasis- oder Review-Gates.
- Reward-/Mining-/Staking-Positionen erscheinen als vollständige bestehende Jahresaggregate. Individuelle Einkommensereignisse werden in diesem Read-Model nicht als vollständige Ereignisliste angeboten.
- Derivatezeilen enthalten vorhandene Bewertungswerte, soweit verfügbar; der Bericht leitet keinen eigenen positionsweisen Gewinn/Verlust ab.
- Die vollständige Produktabnahme erfordert Frontend-Integration, Browserprüfung und eine fachliche Prüfung des jeweiligen Jahresstands.
