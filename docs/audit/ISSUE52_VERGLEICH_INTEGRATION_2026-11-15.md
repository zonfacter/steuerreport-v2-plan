# Issue 52: funktionsfaehiger gebundener Aggregatvergleich

Entwicklungsstand, keine Produktion und keine fachliche Gesamtfreigabe.
Dieser Stand ersetzt die pauschale Vergleichssperre aus `6ee5146` nur dort,
wo beide Aggregatseiten gebunden gelesen werden koennen.

## Implementierung

- Referenzwerte stammen aus denselben Paketbytes, deren SHA256 geprueft ist;
  Manifest und gespeichertes Summary muessen dazu passen. Keine Veraenderung
  des Originalpakets, kein Ersatz durch numerische Registerspalten.
- Die sechs aktuellen Jahresaggregate stammen aus einem frischen Service und
  einer gemeinsamen DuckDB-READ-ONLY-Transaktion mit dem Register. API, HTML
  und CSV umgehen den bisher verwendeten 60-Sekunden-Summarycache.
- `filing_aggregate_values` verwendet die bestehenden DB-Zahlen aus
  `_status_for_year`, nicht die dateibasierte Erklaerungs-/Wallet-Beilage.
  Die Beispielprobe verbietet den Aufruf dieser Beilagen explizit.
- Eingespeiste fremde/cached Summaries bleiben ungebunden und nicht verglichen.
  Gleiche Aggregate sind kein Ereignis-, Lot- oder Tax-Line-Abgleich.
- CSV schreibt Vergleichsstatus und Detailabgleichsstatus; ohne Vergleich
  bleiben Geldfelder leer. HTML und Webansicht behandeln fehlenden Umfang
  oder ungueltige Referenzwerte nicht mehr als bestaetigte Nulldifferenz.

## Im Review gefundene und behobene Fehler

1. Cent-Aenderung wurde aus dem gerundeten Delta abgeleitet. Jetzt werden die
   separat gerundeten Betraege verglichen: 1,004 -> 1,005 ergibt 1,00 -> 1,01,
   Review erforderlich, exaktes Delta 0,001 und Cent-Delta 0,01.
2. Python summierte die gespeicherten Steuer-/Derivatezeilen zuvor mit
   Standardpraezision. Die beiden Aggregate verwenden jetzt 80 Dezimalstellen
   (38 Stellen je DB-Zeile plus BIGINT-Zeilenanzahl). Die SQL-Rewardsumme bleibt
   im bestehenden Datenbankpfad. Keine gespeicherte Steuerzeile wird geaendert.
3. Die UI behauptete bei reinen Nachweiswert-Aenderungen keine Aggregatdifferenz.
   Die Aussage ist jetzt auf deklarationsrelevante Betraege begrenzt.
4. HTML nutzte ROUND_HALF_EVEN statt der bestehenden HALF_UP-Centregel. HTML
   verwendet nun denselben Rundungshelper; die UI den vorhandenen exakten
   String-/BigInt-Geldformatter statt einer neuen Gleitkommarechnung.

Exaktes `delta_eur` und `rounded_amount_delta_eur` sind verschiedene Werte.
Letzterer wird als Cent-Delta angezeigt. Der Vergleich unterstuetzt technisch
maximal 256 Stellen Praezisionsspanne; darueber `not_compared` mit Erklaerung,
kein stiller Ersatz oder gerundetes Gleichheitssignal. Neue Referenzpakete mit
in DECIMAL(38,18) nicht exakt speicherbaren Betraegen werden vor Archiv-/
Registerschreiben abgelehnt. Vorhandene Dateien bleiben unveraendert.

## Nachweise

- Interleaved API-Test: Ein zweiter Store schreibt nach dem ersten Teilread
  neue Derivate. Der laufende Vergleich sieht noch 0, der naechste 10 EUR.
  Der volle Summary-Aufruf ist in diesem Test verboten.
- Gegenfall: Eine echte synthetische Tax-Line plus Lot mit Kosten 20, Erloes 50
  und Ergebnis 30 erzeugt die unabhaengig erwarteten sechs Aggregatdeltas.
- Archiv-100/Register-0/aktuell-0, fehlende Felder, Null, ungueltige Werte,
  falsches Jahr, doppelte JSON-/Manifestpfade und unveraenderte Paketbytes sind
  durch die Archivbindungsregressionen abgedeckt.
- Der breite Lauf vor der letzten HTML-Formatkorrektur bestand mit 124 Tests.
  Danach bestanden vier gezielte Cent-/Praezisions-/Interleavingproben erneut.
- Isolierter echter React-Vergleichsbaustein in Chromium bei
  390/768/1280/1440 Pixeln: Legacy ohne Scope, nicht verfuegbar, Nachweisdelta,
  Cent-Grenzfall. Kein Seitenoverflow, Cent-Delta nach Tabellen-Scroll im
  Viewport, kein externer Request. Keine schreibende Aktion ausgefuehrt.

```bash
PYTHONPATH=src python -m pytest -q tests/unit/test_tax_filing_archive_binding.py tests/unit/test_tax_filing_snapshots.py tests/unit/test_tax_filing_audit.py tests/unit/test_tax_methodology.py tests/unit/test_cross_year_offsetting_parity.py tests/unit/test_cross_year_fifo_parity.py tests/unit/test_bmf_compliance.py tests/unit/test_read_snapshot.py
python scripts/check_filing_comparison_browser_v2.py
```

Der Browsertest prueft den echten Baustein isoliert, nicht die gesamte App.
Der CSV-Gegenfall ist nicht mehr xfail. Bestehende Starlette- und Bundle-
Warnungen bleiben sichtbar. API-/OpenAPI- und Endpunktreferenz werden generiert.

## Offene Grenzen

Keine Aktualitaetsbindung der gespeicherten Berechnung an alle heutigen
Raw-/Preis-/Methodeneingaben, keine Detailreconciliation oder Freigabe.
Ein enger Aggregatvergleich kann deshalb `equal` melden, obwohl gegenlaeufige
Assetabweichungen bestehen; der Cross-Year-Gegenfall prueft genau das und der
separate Detail-/Parity-Gate bleibt blockiert. `reconciliation_failed` fuer
einen vollstaendigen Einzelpositionsabgleich bleibt offen.

ZIP-Ressourcenlimits, unabhaengige Signatur der Registeranker, reale V1-Paritaet,
produktiver Restore und komplette UI-Abnahme sind nicht nachgewiesen. Die
API-Contracts enthalten nullable Werte und einen neuen Unverfuegbarkeitsstatus;
Altclients muessen diese konservativ behandeln. Dieser Branch ist nicht mit
den ebenfalls offenen Preis-/Journal-Drafts gleichzusetzen. Keine Aktivierung
einer Methode, keine Neuberechnung, kein Containerwechsel.

## Finaler lokaler Pruefstand

- Nach allen Backendkorrekturen: 125 bestanden, eine Starlette-Warnung,
  Original-JUnit lokal unter `var/issue52-test-results-20261115.xml`.
- Zusaetzlicher DECIMAL(38,18)-Maximalwertfall: 1 bestanden; Originalwert und
  exaktes negatives Delta bleiben erhalten.
- Unveraenderte unabhaengige Referenzproben: 52 bestanden; Baselinepruefer
  bestaetigt `09f674b350a9a83943df8980bbceafd88821ee1400e03b5b22ea1ee0f8cd6bfb`.
- Browser: 16 synthetische Baustein-/Viewport-Kombinationen bestanden,
  einschliesslich 1,004 -> 1,005 und im Viewport erreichbarem Cent-Delta.
- Frontend-Build, Ruff und beide generierten Vertragsabgleiche bestanden.
  Der Dashboard-Test-Runner aus dem separaten Preis-Draft existiert auf dieser
  main-Basis nicht; dessen versuchte Ausfuehrung ist kein bestandener Test.
- Vier Reviewbefunde korrigiert; gezielte letzte unabhaengige Lesekontrolle
  meldete keine weiteren Findings. Keine vollstaendige Produktabnahme.
