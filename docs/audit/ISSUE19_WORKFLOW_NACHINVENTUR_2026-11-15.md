# #19: Nachinventur der Fachbedienwege

Quellinventur an Basis `8f3681d2d12be430cbb627ed731091bf0ba77a3f`.
Keine erneute reale Legacy-DB-, Container- oder Providerpruefung. Die Tabelle
beschreibt implementierte Wege und vorhandenen Testcode, keinen vollstaendigen
neuen Browser-/Produktionsnachweis. #19 und #20 bleiben offen.

| Bereich | Implementierter Weg ohne obligatorische KI | Persistenz / Code | Nachweisgrenze |
| --- | --- | --- | --- |
| Dateiimport | Daten importieren: Datei, Pruefung, ausdrueckliche Freigabe | `ImportAssistantService.execute`, `FileImportWizard.tsx`; Original/Raw und Kontobindung | Keine Vollstaendigkeit aller privaten Altquellen |
| Konten/Historie | Quellen, Quelle hinzufuegen, Einrichten, automatischer Import | `connections.py`, `workspace/SourceWorkspace.tsx`; stabile Connection-ID, Vault | Speichern ist weder erfolgreicher Test noch vollstaendige Historie |
| Preise/FX | Bedarf, budgetierter Abruf, Vorschau, ausdrueckliche Uebernahme, konkrete Belege und Zeitbestaetigung | `historical_prices.py`, `price_admissions.py`, `PriceWorkspace.tsx`, `PriceImportEvidence.tsx` | Importbindung, Zeitbeleg, Methode und Jahresfreigabe getrennt |
| Korrekturen | Datenkorrekturen im manuellen Modus, Vorschau, zwei Bestaetigungen | `ai_changes.py`, `AiChangesWorkspace.tsx`; Overrides und Reviewhistorie, Raw bleibt | Nur unterstuetzte Targets/Felder; keine automatische Alt-Reviewmigration |
| Lots | Steuerjahr: Ursprungslot; Expertenbereich: vollstaendige CSV/API | `tax.py`, `LotOriginDetails.tsx`, `main.tsx` | UI-Stichproben und einzelne CSVs sind kein vollstaendiger Alt-/Neu-Lotvergleich |
| Jahresstatus | Jahresuebersicht: gebundenen Pruefstand ausdruecklich erzeugen/erneuern | `tax_methodology.py`, `YearWorkspace.tsx`; JSON-Artefakt und Latest-Verweis | Erzeugung ist keine fachliche Freigabe |
| Berichte | Jahres-HTML/ZIP/Checkliste/PDF und archivierte Vorschau | `tax_year_pdf_reports.py`, `TaxYearPdfReports.tsx`; begrenzte PDF-Teile/Register | Jahres-PDF bleibt Vorschau; globale Exporte nicht automatisch jahresgefiltert |
| Archive/Restore | Abgabestand archivieren, Nutzung bestaetigen, Paket herunterladen; Restore ueber Betreiber-CLI | `tax_filing_snapshots.py`, `scripts/docker_state_v2.py` | Restore benoetigt Hostzugriff, aber keine KI; realer Restore/Rollback nicht neu belegt |

Vorhandene gezielte Tests: `test_guided_file_import.py`, `test_connections.py`,
`test_historical_price_workflow.py`, `test_price_admissions.py`,
`test_ai_changes.py`, `test_lot_origin_implementation.py`,
`test_migration_readiness.py`, `test_tax_year_pdf_reports.py`,
`test_tax_filing_snapshots.py`. Eine vorhandene Probe beweist nicht automatisch
ihren aktuellen Lauf; ausgefuehrte Nachweise stehen im jeweiligen Auditbericht.

## Offener Produktpfad #52

Der klassische `TaxFilingSnapshotPanel` und seine HTML-/CSV-Ausgaben vergleichen
weiterhin sechs Aggregate. Der vorhandene separate Auditdienst berechnet
partielle Positionsdeltas, wurde in dieser Nacharbeit integritaetsseitig
abgesichert und kennzeichnet seinen Umfang ausdruecklich als partiell.
Im gelesenen Frontend gibt es keinen gezielten `filing-audit-report`-Bedienweg.
Ein allgemeiner Expertenexport oder eine Paritaetsstichprobe ersetzt ihn nicht.

Naechste vertikale Erweiterung: Referenz/Jahr waehlen, versionierte und
manifestierte Ereignis-/Ursprungslot-/Tax-Line-Details lesen, eindeutige Paare
und Unklarheiten anzeigen, gegenlaeufige Einzelbetraege exakt ueberleiten und
denselben Umfang exportieren. Historische IDs und Belegluecken nicht erfinden.
Normale Fachbedienung, administrativer Restore und reale Legacyparitaet sind
drei verschiedene Abnahmescopes.

## Weiter offene Betriebsbindung

Die Oktober-Inventur und `LEGACY_PARITAET.md` sind historische Belege. Ein
Dateiname, aktueller HEAD oder Prozess-CWD beweist weder die geladene
Python-Modulversion noch die gerade benutzte finanzielle Datenbasis.
`ops_inventory.py` wurde nicht blind erneut ausgefuehrt: es enthaelt aktive
Host-/HTTP-Aufrufe und historische Zielpfade. Keine Finanz-DB wurde fuer diese
Nachinventur geoeffnet oder kopiert. Keine Produkt-/Migrationsfreigabe.
