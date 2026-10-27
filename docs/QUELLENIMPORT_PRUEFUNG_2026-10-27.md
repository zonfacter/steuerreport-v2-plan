# Uebergabe: automatischer Quellenimport, 0.2.0rc21

Pruefdatum: 27.10.2026 UTC. Ausschliesslich isolierte synthetische Daten und
kontrollierte Providerantworten. Kein echter Exchange-/RPC-Abruf oder produktiver
Finanzimport wurde zum Test gestartet.

## Umsetzung und Nachweis

| Anforderung | Umsetzung | Nachweis |
| --- | --- | --- |
| Konkrete Quelle statt globaler Wallet/Konto-Fallback | `domain/history.py`, `domain/workspace.py` | Zwei Wallets und zwei gleich benannte Konten derselben Boerse bleiben getrennt; Credential-, Event-, Rohbeleg-, Hinweis- und Auftragszuordnung geprueft. |
| Automatische Pagination | `history_solana.py`, `history_cex.py` | Cursorfenster, fehlende Details, Retention, Grenzen und gesaettigte Seiten mit Provider-Mocks geprueft. |
| Pause/Fortsetzen/Abbruch | `history.py`, `request_limits.py` | Persistierte Cursor; kein Wiederanlauf nach Abbruch, auch bei abgelaufenem Workerfenster; Cancellation-Polling nie unter Limiter-Dateisperre. |
| Originale und Dubletten | `history_storage.py`, `source_history_importer.py` | Hash-/Symlinkpruefung, wiederholte Belege, gleiche IDs verschiedener Konten, Inhaltskonflikte und alte CSV-Ueberlappungen geprueft. |
| Isolierte Vorschau und atomare Uebernahme | `history_preview.py` | Vor Freigabe Finanzzustand unveraendert; veraltete Vorschau gesperrt; injizierter Transaktionsfehler rollt alle Finanz-/Audit-Schreibvorgaenge zurueck. |
| Keine erfundene Einordnung | `raw_normalizer.py`, `review.py` | Dokumentarische Belege ohne Buchungswirkung; unklare erfolgreiche Auszahlungen mit blockierendem Klassifikationshinweis statt erfundener Menge/Gebuehr. |
| Bedienung | `HistoryImport.tsx`, `SourceWorkspace.tsx`, `view-state.ts` | Auswahl, URL-Tab, Doppelstart, Fehler, Pause, Vorschaufreigabe, Ruecknavigation und Tastatur mit Chromium geprueft. |
| Dateiimport bleibt zusaetzlich | Quellenansicht, Hilfe und Benutzerleitfaden | Dateiimport weiterhin erreichbar; bisherige Vorschau-/Freigaberegeln nicht umgangen. |

## Ausgefuehrte Pruefungen

Der erste monolithische lokale Testlauf wurde vor Abschluss beendet und wird
nicht als bestandener Lauf gewertet. Die Sammlung am Feature-Baseline-Commit
`8904b02` mit **1.773
Tests** wurde anschliessend in disjunkten Teilmengen vollstaendig ausgefuehrt:

- Bestehende Backend-/Fachregressionen ohne die gesonderten Gruppen:
  **1.494 bestanden, vier uebersprungen**.
- Historienjobs, Solana- und CEX-Adapter: **227 bestanden**.
- Unabhaengige Review-Regressionen, Quellenisolation und bestehende
  Workspace-/Wallet-Lesemodelle: **47 bestanden**.
- Zusaetzlicher Test gegen Umleitung des Records-Verzeichnisses per Symlink:
  **ein Test bestanden**.
- Summe: **1.769 bestanden, vier uebersprungen, keine Fehler**.
- `ruff check src tests scripts`, `git diff --check`, Frontend-Build sowie
  URL-/Decimal-Zustandspruefung in UTC und Europe/Berlin erfolgreich.
- OpenAPI-, Endpoint-, Importformat- und KI-Leitfaden-Driftpruefungen erfolgreich.
- Benutzerleitfaden 13, Importformat-Referenz zehn und KI-Leitfaden neun
  PDF-Seiten; Version geprueft, alle unter der 100-Seiten-Grenze.

Es verbleiben die bekannten vier `load_module`-Deprecation-Warnungen und die
Vite-Warnung zum grossen Hauptbundle; keine verschwiegenen Buildfehler.

## Browser

- `scripts/check_history_import_browser_v2.py`: **zwoelf von zwoelf Szenarien**,
  15 synthetische Screenshots; kontrollierte API-Antworten, kein echtes Backend.
- `scripts/check_history_backend_browser_v2.py`: echtes isoliertes FastAPI-/
  DuckDB-Backend und gebautes Frontend; Provider-Collector als Mock-Grenze.
  Eine Vorschau veraendert keine Finanzzeilen. Erst Person und beide
  Bestaetigungen importieren genau einen Transfer plus eine Netzwerkgebuehr
  auf Wallet A; Wallet B bleibt unberuehrt. Hinweis-/Quellen-Rueckweg geprueft.
  20 synthetische Screenshots, keine externen Requests/JavaScript-Fehler.
- Viewports jeweils 390, 768, 1280 und 1440 CSS-Pixel. Kein Seiten-/Paneloverflow;
  Tabellen duerfen einen eigenen horizontalen Scrollbereich besitzen.
- Bestehender gefuehrter UX-Browserlauf samt 24 Arbeitsablauf-Szenarien und
  R1-Ladezustandsregression erfolgreich; bestehender Wallet-Einrichtungslauf
  und echter Backend-Review-Browserlauf F1/F2/F3 ebenfalls erfolgreich.
- Der neue Import-Tab wurde im URL-Parser ergaenzt. Alte Browserassertionen
  wurden ausschliesslich von Quelle synchronisieren auf die jetzt fachlich
  eindeutigere Beschriftung Bestand aktualisieren angepasst; Wirkungs-,
  Doppelstart- und Fehlerassertionen bleiben erhalten.

Synthetische Nachweise liegen lokal unter `artifacts/source-history-browser/`
und `artifacts/source-history-backend-browser/`; CI archiviert diese ebenfalls.
Screenshots produktiver Konten gehoeren nicht in oeffentliche Releases.

## Sicherheitspruefung und Grenzen

Gitleaks im sauberen Software-Staging: zehn exakt einzeln gepruefte
Nicht-Secret-Treffer, kein ungepruefter Treffer. Der neue Treffer ist ein
deutscher API-Beleg-Hinweistext, ausschliesslich ueber seinen exakten
Quellzeilenhash freigegeben; keine globale Scanner-Ausnahme. Kompilierte
Assets werden vor einem Release zusaetzlich gescannt.

Abgleich gegen 132 bekannte private Kennungen sowie aktuelle private
Laufzeitwerte: keine Treffer in Software/gesamten lokalen Git-Objekten.
Leere private Beispielkonfiguration und Quellenregistry bleiben erhalten.

Dies ist keine fachliche Freigabe echter Steuerjahre oder vollstaendige
Anbieterabnahme. Offizielle Aufbewahrungs-/Produktgrenzen stehen in
[Provider-Referenzen](HISTORY_CEX_PROVIDER_REFERENCES.md), Bedienung und
gesonderte Freigaben in [Automatischer Quellenimport](AUTOMATISCHER_QUELLENIMPORT.md).
Echte Anbieterzugriffe und Kosten wurden nicht getestet. Ein automatischer
Zeitplan, universelle Historienabdeckung, eine technische Identitaetspruefung
der freigebenden Person oder globale Benutzeranmeldung wurden nicht hinzugefuegt.

## Ergaenzung: Trade und Preisbelege in rc22

Die unabhaengige Speicherpruefung hat einen vorsorglich geaeusserten Verdacht
auf fehlende Preisuebernahme widerlegt. `DuckDbStore.add_price_points` ist
eine API-Bezeichnung; die tatsaechliche Tabelle heisst `price_ledger` und
steht bereits in `DERIVED_TABLES`. Keine weitere Pipeline-Schreibtabelle
fehlte in der atomaren Uebernahme; keine Fachlogik wurde nachtraeglich geaendert.

Ein zusaetzlicher Integrationstest in `test_history_jobs.py` verwendet die
tatsaechlichen Binance-Profilzeilen fuer Kauf eines BTC fuer 20.000 EUR und
Verkauf fuer 25.000 EUR. Er prueft die unveraenderte produktive Datenbasis vor
Freigabe, beide abgeleiteten Preise nach Freigabe, den identischen vorhandenen
Originalpreis, das Entfernen eines veralteten abgeleiteten Preises sowie
5.000 EUR Gewinn und denselben Summenstand nach erneutem Pipeline-Lauf.
Der Test besteht ohne Aenderung am Produktivcode. Die allgemeinen Rollback-
Assertions schliessen nun ausserdem die Preistabelle ein. Der Baseline-Nachweis
oben bleibt historisch unveraendert; die Ergaenzung wird separat und im neuen
CI-Lauf mitgefuehrt.

Eine vorsorgliche Software-Ruecknahme auf rc20 wurde vor Wiederaktivierung
durchgefuehrt. Datenbank und Konfiguration waren identisch zur Sicherung,
Historienjobs und produktive Finanzimporte null; es wurden keine Daten aus
der Sicherung zurueckgeschrieben. Produktive Screenshots bleiben privat.
