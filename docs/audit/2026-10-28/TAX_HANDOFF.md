# Paket C / F03 Handoff

## Umfang Und Status

Nur eigener Worktree `/tmp/steuerreport-migration-20261028-tax`, Branch
`audit/docker-migration-20261028-tax`. Vertrag vor Quellcodeaenderungen
bestaetigt. Kein Push, Tag, Deployment, Produktivdatenzugriff oder
Methodenwechsel. Kein Eingriff in F04 oder in die Dateien von Paket B.
Spaeter explizit hinzugegeben: schmale aktuelle Klassifikation in
`swap_valuation_parallel.py:_Totals.add`; keine Aenderung von Archivlesern.

F03 verbindet Berliner Kalenderfrist, Planung und Python-/SQL-Klassifikation.
Jahrestag bleibt innerhalb, Folgetag ausserhalb; 29. Februar wird gekuerzt.
`holding_days` steuert keine dieser Klassifikationen mehr. Line-Datum hat
Vorrang vor Lot-Fallback. Income-Index verweigert alte/kuenftige Kurse.
Quellen, Herleitung und offene fachliche Grenzen: METHODENKATALOG.md.

Parent-Imports aus `domain.tax_time`:

```python
PRIVATE_HOLDING_POLICY_VERSION = "de_private_calendar_holding_berlin_v1"
private_disposal_within_year(acquired_at: datetime, disposed_at: datetime) -> bool
private_disposal_tax_free_at(acquired_at: datetime) -> datetime
private_disposal_within_year_sql(acquired_at: str, disposed_at: str) -> str
tax_line_within_year_sql(line_alias: str = "tax_lines") -> str
```

`True` bedeutet innerhalb einschliesslich Jahrestag, nicht persoenliche
endgueltige Steuerpflicht. SQL erwartet UTC-naive DB-Timestamps; Python
interpretiert naive Werte als UTC und normalisiert bewusste Offsets.
`private_disposal_tax_free_at` liefert einen bewussten UTC-Zeitpunkt.

## Unabhaengige Fixtures

`tests/unit/test_tax_f03_calendar.py` enthaelt ausschliesslich generierte
Events, eigene DBs und direkte EUR-Gegenleistungen. Keine bereitgestellten
Reprodateien, Referenzimporte oder realen Konten werden verwendet.

- 100 EUR Anschaffung, 150 EUR Verkauf: 50 EUR G/V. Am Jahrestag trotz
  366 Tagen innerhalb; ab dem folgenden Berliner Kalendertag ausserhalb.
- Fest vorgegebene Grenzzeitpunkte statt aus dem Pruefling generierter
  Erwartungen: 29. Februar, Jahreswechsel UTC/Berlin, Sommermitternacht,
  Fruehjahrs-DST und beide Herbst-DST-Stunden.
- SQL mit nichtdeutscher Sitzungszeitzone, naive und bewusste UTC-Zeitpunkte;
  verdrehte `holding_days` koennen Klassifikation nicht beeinflussen.
- Reale DuckDB-Ende-zu-Ende-Verbraucher: FIFO, Jahresdetail, Zahlungstotale,
  Treiber, Asset-Drilldown, Stablecoins, Gain-Evidence und Berichtskarten;
  Wallet-Vorschau separat, aktive Methode bleibt global in der Fixture.
- Offener Lot: Berliner Mitternacht als UTC-Zeitpunkt und lokale Resttage.
- Income-Index: Vortag trotz gleichem Berliner Tag abgelehnt, exakte
  Ereigniszeit erlaubt, Zukunft abgelehnt; Offsetnormalisierung, abgeleiteter
  aktueller statt alter Primaerkurs, nichtpositive Kandidaten abgelehnt.
- Reward-Zufluss und Lotbasis 100, Verwertungsergebnis 50 getrennt;
  fehlender Reward-Preis bleibt im Income-Report fehlend und im Preisgate sichtbar.

Der bestehende Test in `test_tax_years.py` wurde nur auf die sachlich
korrigierte Frist-Bezeichnung umgestellt; die Kategorie `archivieren` und alle
Betragserwartungen bleiben unveraendert. Keine Toleranzerweiterung, Skips
oder entfernten Assertions fuer gruene Tests.

## Testbefehle

Arbeitsverzeichnis ist der eigene Worktree. Fuer alle Laeufe:

```bash
export PYTHONPATH=src:/tmp/steuerreport-connector-tools-20261026:/tmp/steuerreport-release-tools-20261025
export STEUERREPORT_TEST_PRUNE_PASSED_DBS=1
pytest -q tests/unit/test_tax_f03_calendar.py --basetemp=/tmp/steuerreport-migration-20261028-tax/.pytest-f03-fourth -x
pytest -q tests/unit/test_tax_f03_calendar.py tests/unit/test_tax.py tests/unit/test_tax_time.py tests/unit/test_tax_years.py tests/unit/test_reports.py tests/unit/test_tax_wallet_fifo.py tests/unit/test_tax_methodology.py --basetemp=/tmp/steuerreport-migration-20261028-tax-tests-regression -n 2 --tb=short
pytest -q tests/unit/test_tax_f03_calendar.py tests/unit/test_tax_f03_swap.py tests/unit/test_swap_valuation.py tests/unit/test_tax_time.py --basetemp=/tmp/steuerreport-migration-20261028-tax-tests-final --tb=short
```

Gezielter Lauf: 44 passed, 18.58 s. Breitere Regression inklusive dieser 44
Tests: **249 passed, 185.34 s**, keine Erwartung abgeschwaecht. Ein vorheriger
breiter Lauf mit `--basetemp` INNERHALB des Worktrees lieferte 160 passed / 45
failed: der geschuetzte Configpfad verhinderte API-Starts. Korrektur war nur
der eigene externe Testpfad, keine Aenderung an Configschutz oder Quellcode.
Fruehe Entwicklungslaeufe scheiterten an zwei falschen
Testannahmen zum ReportCard-Format (String statt Decimal und existierender
Feldname `tax_free_private_disposals_eur`); keine Produktlogik dafuer gelockert.
Abschlusslauf nach der expliziten Swap-Erweiterung und Policy-Konstante:
**57 passed, 29.98 s**. Hashvergleich des eingefrorenen Endstands nach diesem
Lauf identisch; `git diff --check` ohne Befund. Kein voller Gesamtsuite-Lauf
behauptet; der breite Steuer-/Berichtsregressionssatz und der Abschlusslauf
sind die tatsaechlich ausgefuehrten Pruefumfaenge.

## Eingefrorener Quellstand

Der breite Lauf wurde vor der expliziten Swap-Erweiterung abgeschlossen;
Hashvergleich seines Quellstands war identisch. Danach nur Policy-Konstante
und `_Totals.add` ergaenzt. Nachstehend der VOR dem Abschlusslauf eingefrorene
Endstand, nach dem Lauf erneut verglichen. Dokumentation bleibt getrennt.
Unveraenderte Wallet-/Methodenmodule sind mit erfasst.

```text
3ecab3c84a709320470995d7a068b16634847ea65c1aa9381ce754aab40b0631  tax_time.py
85ffac007bc2f7129de4fd44ae88dde3bd0440a8676c1778ee7a7aff29be4fd2  tax.py
f21d453e32b53021abd5f27085f3158336c02e36c91252790258732c2d241e49  tax_years.py
12face9b87307f593e606206638705d514ba6473dcbc3e9a8564c96d683ff300  reports.py
f2ccce2b802ee38a2124849def4b8143f0d4494b92cd7f956b4f33710a55fa7d  tax_wallet_fifo.py
e61859820cbaf7568797e1156ab38d8ede27d7d3e41536db739efb8a7f6fd14d  fifo_methods.py
ead1be33e0178f55d8cc962da67b601d3c0af1de56eed109e89cde7339c131e8  swap_valuation_parallel.py
d52106d38d8dae8bdf6ffb42424946f1478d7fe39a36fcfdf4e2a50706422753  tests/unit/test_tax_f03_calendar.py
c1096fe52a6e164f10e4cb3e671b2a7b95336e0542c1f40e43e0090a1bee4f67  tests/unit/test_tax_f03_swap.py
533a681d63c3ffb832b81145ef940b877945a6cdbe8a64ad9cb90976385ae651  tests/unit/test_tax_years.py
```

## Nicht Behauptete Freigaben

Kein Zugriff auf reale aktive Global-/Wallet-Methode, keine Originalreview-
Abnahme und kein automatischer Sphaerenwechsel. Fehlende Anschaffungskosten,
synthetische Reward-Urspruenge und persoenliche Gesamtgewinn-/Freigrenzen-
berechnung sind nicht durch diesen begrenzten Fix geloest. G11-G17/G24 ohne
zugaengliche Kennungsdefinition nicht pauschal als erfuellt bezeichnet.
Produktive Neuableitung, gebundene Artefakte und menschliche Jahresabnahme
sind weiterhin Koordinator-/Fachreview-Aufgaben. Alte Pakete bleiben unveraendert.

Parent-Integration benoetigt noch `api/app.py` Zeilen 6984/6987 fuer den
CSV-Ausweis und `tax_filing_audit.py` Zeilen 493/798-817 fuer die Unterscheidung
von aktueller Klassifikation und tatsaechlich verwendeten Archivlabels.
Diese Fundstellen wurden vor Integration gemeldet und nicht in C geaendert.
