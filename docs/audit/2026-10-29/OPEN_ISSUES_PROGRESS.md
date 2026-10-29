# Offene GitHub-Issues: Arbeitsstand vom 29.10.2026

Repository-Basis: `zonfacter/steuerreport-v2-plan`, Ausgangscommit
`bd5a5fbb13d78a5b708bd9cb20ec5b9cd9a8617d` (`0.2.0rc36`). Dieser Bericht
trennt Codekorrektur, gezielten Test, Legacy-Nachweis und fachliche Abnahme.

## Status

| Issue | Ergebnis dieser Runde | Status |
| --- | --- | --- |
| #4 MEXC-XLSX | Mehrblattdatei verlangt explizite Tabellenauswahl; neue Backend-, Frontend- und Browserregression. Weitere Exporttypen bleiben bewusst begrenzt. | Teilweise behoben, offen |
| #8 Docker-/Migrationsabnahme | Aktuelle Issue-Matrix aktualisiert; native aktive Datenbank/semantischer Vergleich nicht nachgewiesen. | Offen |
| #10 Vault-Key-Restore | Bestehender Entrypoint-Fix verifiziert; zusaetzliche Regression deckt formal gueltigen, aber inkompatiblen Schluessel und unveraenderten Zustand ab. | Behebung nach Tests belegbar |
| #13 Datei-/API-Ueberlappung | Vorhandene Binance-Dateibindung und Kontoisolation erneut getestet; Sperrmeldung erklaert die fehlende Recordidentitaet. Dauerhafte Zuordnungsentscheidung fehlt. | Teilweise behoben, offen |
| #19 Legacy-Laufzeit | Native V1/V2-Dienste und Docker sind als getrennte Laufzeitbereiche bestaetigt. Aktive DuckDB der nativen V2 ist nicht sicher zugeordnet. | Offen, Datenquellenblocker |
| #20 Semantischer Alt-/Neu-Vergleich | Kein gebundener, konsistenter nativer Datenstand. Kein Ergebnisvergleich behauptet. | Offen, abhaengig von #19 und gesicherter Kopie |
| #22 Bitget-CSV | Leere Ueberhangfelder werden kontrolliert toleriert; nichtleere Extras liefern strukturierten Zeilenfehler. Datei-Hash und Wiederimport getestet. | Teilweise behoben, offen |
| #26 CSV-/Datei-API-Paritaet | Bitget Text-, Base64- und Assistant-Pfade nutzen gemeinsame Ueberhangregeln; Strukturfehler erzeugen keinen Batch und kein HTTP 500. | Im Branch umgesetzt, lokal getestet; Merge/CI ausstehend |

## Laufzeit- und Datenschutzgrenze

Die Laufzeitpruefung war lesend und auf Prozess-, Service- und Image-Metadaten
begrenzt. Keine Datenbank, kein Vault-Schluesselinhalt und kein Secret wurde
gelesen. Kein Health-/Admin-Aufruf mit moeglicher Schemainitialisierung, keine
Dateiuebernahme, keine Neuberechnung, keine Methodenaktivierung und kein
Containerwechsel erfolgte. Die aktive native V2-Datenbank bleibt unbekannt;
Pfadkandidaten oder ein aehnliches Dashboard sind kein Beweis der aktiven
Rechenbasis.

Der angefragte semantische Legacyvergleich braucht einen kontrolliert
gebundenen, konsistenten Snapshot der tatsaechlich verwendeten nativen V2-Daten
einschliesslich Raw-Belegen, Profil/Konfiguration, Vault-Schluessel, aktiver
Methode und Reviewentscheidungen. Eine Produktivdatei wurde in dieser Runde
nicht kopiert. Erst ein isolierter Restore mit nachgewiesener Herkunft darf
fuer #20 verglichen werden. Der Docker-rc36-Stand ist kein Ersatz dafuer.

## Tests

- `tests/unit/test_connector_bootstrap.py`: 23 bestanden.
- `tests/unit/test_guided_file_import.py` und
  `tests/unit/test_history_review_regressions.py`: 27 bestanden.
- MEXC-API-/Referenz-/Review-Suite: 266 bestanden; die neue Mehrblattregression
  zusaetzlich einzeln bestanden.
- Bitget-CSV- und Bitget-Referenztests: 22 bestanden.
- Bitget-CSV-/Datei-/Assistent-Paritaet nach #26: 52 Tests bestanden
  (`test_bitget_csv.py`, `test_file_raw_importer.py`,
  `test_guided_file_import.py`).
- `scripts/check_mexc_import_browser_v2.py`: alle 14 Browser-Szenarien
  bestanden mit synthetischen API-Antworten; keine echten Providerrequests.
- Frontend-Produktionsbuild, Python-Ruff auf geaenderten Python-Dateien und
  `git diff --check`: bestanden.
- Kein vollstaendiger Projekttestlauf und keine vollstaendige Browsermatrix.

## Naechste belegbare Arbeit

1. #19: Aktive native V2-Datenbank nur ueber einen betrieblich freigegebenen,
   schema-/side-effect-sicheren Snapshotpfad eindeutig an den Prozess binden.
2. #20: Snapshot isoliert wiederherstellen; Cross-Schema-Manifest sowie
   Ereignis-, Lot-, Tax-Line- und Jahresdifferenzen mit gebundenen Methoden
   erstellen. Keine heuristische Zusammenfuehrung nur nach Zeit/Menge.
3. #13/#22: Exakte Provider-Record-ID plus finanzieller Digest und
   explizit widerrufbare, revisionsgebundene Zuordnungsentscheidung
   spezifizieren, bevor Buchungswirkung beeinflusst wird.
4. #4: Weitere MEXC-Layouts erst nach getrennten Originalschema-Belegen und
   synthetischen Normalisierungs-/Ledgerregressionen aktivieren.

Produktiv-Docker bleibt auf rc36. Dieser Arbeitsstand beinhaltet keine
Umschaltung, Datenmigration, Steuerkorrektur oder finale fachliche Freigabe.
