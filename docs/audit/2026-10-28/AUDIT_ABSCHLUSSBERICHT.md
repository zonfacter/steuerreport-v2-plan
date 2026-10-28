# Audit-Abschlussbericht Zum Docker-Arbeitsplan

Erstellt: 28.10.2026. Gegenstand: integrierter Entwicklungsstand
`0.2.0rc33.dev0`, nicht die produktive Anwendung auf Port18010.

## 1. Gesamturteil

**Technische Korrekturen sind implementiert und im unten begrenzten Umfang
nachgewiesen. Der Arbeitsplan A-F ist nicht vollstaendig fachlich abgenommen.
Eine produktive Migrations- oder Jahresfreigabe wird nicht erteilt.**

- Altpreis-Lookup: korrigiert; alte/future Referenzen werden nicht als
  zugelassene historische Steuerkurse verwendet. Vertikale Regressionen
  pruefen Lookup, Coverage, Tax, Review, Derived und Export zusammen.
- Widerspruechliche Haltefrist: private Kalenderfrist in Europe/Berlin
  zentralisiert; Python, SQL, Planung und CSV bestehen die Grenzfallproben.
- EUR-Erwerbsgebuehr: im getesteten EUR-Kauf einmal kapitalisiert;
  unabhaengige Sollrechnung stimmt.
- Drittassetgebuehr: **nicht behoben**. BNB-Lot bleibt im Test1 statt0,9.
  Ein blockierender Hinweis ist implementiert, aber kein Ersatz fuer den
  fehlenden Lotverbrauch oder dessen fachlich freigegebene Kostenbehandlung.
- Legacy-/Docker-Datenparitaet: **nicht nachgewiesen**. Restore-Erhalt ist
  belegt, aber kein gleichwertiger Ersatz fuer den fehlenden Alt-/Neu-Abgleich.
- G08/G09/G18/G19: keine ausgefuehrte unabhaengige vollstaendige Referenzprobe.

Technische Gesamtsuite: **2464 bestanden,4 uebersprungen,0 fehlgeschlagen**.
Unabhaengige52Teilproben: **51 bestanden,1 fehlgeschlagen**, keine Skips/xfails.
Dieses rote Ergebnis wurde auch mit den installierten Abhaengigkeiten des
finalen Containerimages reproduziert. Jetzt erneut ausgefuehrte Fokusprobe:
**115 bestanden**. Eine gruene Unit-Suite ist keine positive Gesamt-Fachabnahme.

## 2. Exakte Staende Und Diff

| Bezug | Vollstaendiger Commit / Image |
| --- | --- |
| Ausgang rc32, Diffbasis | `1aecfb131d189267a01a6303f5a9b67a5a99efe2` |
| Tatsaechlicher Vorher-Teststand, noch ohne Preis-/Fristkorrekturen | `438cbd3dac11b0f0bfcc7f308f583f3837de5f85` |
| Bewertungsintegration | `29af806c1c700f3b09417e92f1f4f6622dc8ec09` |
| Fristintegration | `df210bf04fb929ef9394430baa57fb8b0d1008df` |
| EUR-Kosten, Runbindung und Freigabentrennung | `ae8c30eb3e4f36849a6b31ae26a7aaf35c60636e` |
| Registry-/Versions-/Fixturekorrekturen | `3e2cad1b44b907256000cd2a5b4451f109e49b54` |
| Finaler Produktcodefreeze / getesteter Imagecode | `b036b8ad4212d08d719fedec7dbc7115cf5704a9` |
| Bisheriger vollstaendiger Uebergabestand einschliesslich Dokumentation, Diffziel | `33bbdbf976405f2fade4fe45b6d167b6c950b740` |
| Lokales getestetes Image, kein Registrydigest | `sha256:fa5ea2b2b817e38b6374d939f03842319cec9776f46abf4af69086e98986dc94` |
| Branch | `audit/docker-migration-20261028` |

Der **vollstaendige binaertaugliche Diff** liegt als
[abschluss/AENDERUNGEN.patch](abschluss/AENDERUNGEN.patch) bei:
94Dateien,6301Zeilen hinzugefuegt,620entfernt, einschliesslich Tests,
Dokumentation, OpenAPI und binaerer PDF-Aenderungen. SHA256:
`2fca6d36a4f19d3dde38dcbc03916f96f6adcb577d90cb972e190614eda12986`.

Der Diff endet ausdruecklich bei33bbdbf und enthaelt nicht sich selbst oder
diesen nachtraeglichen Abschlussbericht. Seit b036b8a sind nur Auditnachweise
und Dokumentation hinzugekommen; Runtime-/Frontend-/Konfigurationsdateien sind
unveraendert. Der Bericht nennt damit einen festen pruefbaren Stand, nicht
einen beweglichen Branchnamen. Neue Berichtsanlagen sind ein eigener Commit.
Keine dieser lokalen Revisionen wurde durch diesen Auftrag gepusht.

Reproduktion des beigefuegten Diffs, ohne Produktivzugriff:

```sh
git diff --binary --full-index \
  1aecfb131d189267a01a6303f5a9b67a5a99efe2 \
  33bbdbf976405f2fade4fe45b6d167b6c950b740
git diff b036b8ad4212d08d719fedec7dbc7115cf5704a9 HEAD -- \
  src configs frontend scripts pyproject.toml requirements-runtime.lock \
  Dockerfile compose.yml README.md
```

Die zweite Abfrage ist fuer den dokumentierten Berichtstand leer. Zum
Anwenden/Pruefen des Patches einen separaten Checkout der Diffbasis verwenden,
nicht den Produktivcheckout oder einen schon aktualisierten Arbeitsbaum.

## 3. Bewertungsmassstab

**Implementiert** bezeichnet vorhandenen Code, nicht erfolgreiche Abnahme.
**Technisch getestet** bezeichnet nur den konkret beschriebenen Testumfang.
**Fachlich abgenommen** verlangt zusaetzlich eine dokumentierte zustaendige
Freigabe der Regeln, Sachverhalte, Datenabdeckung und individuellen Anwendung.
Eine solche menschliche Gesamt-/Jahresfreigabe wurde hier nicht erteilt.
Auch ein bestandener unabhaengiger Zahlenfall ist keine Freigabe aller
Providerprodukte oder privater/betrieblicher Sachverhalte.

## 4. Pakete A-F

| Paket | Implementiert / geliefert | Tatsaechlich getestet | Fachlich abgenommen / Rest |
| --- | --- | --- | --- |
| A Betrieb | Inventar, Image-/Volume-/Methodenmanifest, Funktionsmatrix, Restore- und Rueckweghelfer | Zwei rc32-Restores sowie Entwicklungsimage-Restore; final b036b8a mit Start/Neustart, Volltabellen-/Dateihashes und Key/Profil/Token-Erhalt; leerer Start ohne V1 | Nein. Legacy-Datenparitaet, neuer vollstaendiger Migrationsdatensatz und echter Downgrade auf Vorgaengerimage offen. |
| B Bewertung | Strikte gemeinsame Preiszulassung, voller Preissnapshot, Diagnose und Derived-Sicherung | Preisagent364Pass/3privateSkips; integrierte Unit-Suite; G10vertikal; aktuelle115er-Fokusprobe | Nein. Vollstaendige Raw-/FX-Provenienz alter Derived-Zeilen, G08/G09/G18/G19 und andere genehmigte Tageskursmethoden offen. |
| C Steuerlogik | Gemeinsame private Kalenderfrist; EUR-Erwerbskosten; Nullbasis-/Gebuehrenreview; lesende Freigrenzenprobe | Steueragent249Pass plus57Pass im eigenen Abschlussumfang; integrierte Unit-Suite; G02/G15/G16/G24; aktuelle Fokusprobe | Nein. G04fehlerhaft, Kostenbasisherkunft und Betriebs-/Privatscope nicht allgemein bewiesen. Keine FIFO-Aktivierung. |
| D Import/Konten | Requestpfadmatrix und synthetische Tests fuer Mehrkonten, Retry, Pagination und Wiederholung; keine neue Produktionsimportlogik |225Pass auf Agentenstand;3eigene Tests erneut integriert und in Gesamtsuite; echte isolierte Browser-Importfreigabe | Nein. Nicht jede Anbieterperiode, Bot-/Earn-/Rewardhistorie oder Crossformat-Deduplizierung vollstaendig belegt. |
| E Reports/UX | Vorschau/final getrennt, Run-/Inputbindung, veraltete Downloads gesperrt, Jahres-/Ladezustaende vereinheitlicht |100Readiness-Screenshots/344MockGETs; gesamter UX-Smoke;7weitere CI-Browserprogramme; G21/G23/G25 | Nein. Vollstaendige Fachzahlengleichheit jedes PDF/CSV/JSON und Grossberichte ueber alle Sachverhalte offen. |
| F Unabhaengige Abnahme | Feste Sollwerte, unveraenderte52Teilproben und Matrix fuer25Referenzfaelle | Vorher22Pass/30Fail; nachher51Pass/1Fail; gleiche Test-IDs/Testcode; Ergebnis im finalen Image wiederholt | **Nicht bestanden als Gesamtpaket.** G04rot, vier Referenzfaelle ohne unabhaengigen Consumerlauf, weitere Teilumfaenge offen. |

Agentenlaeufe sind eigene belegte Teilpruefungen, nicht mit identischem
Commit gleichzusetzen. Massgebliche integrierte Laeufe stehen in Abschnitt8.
Alle Finanz-/Schreibtests nutzten disponierbare synthetische Datenbanken.

## 5. Datenparitaet Und Datenerhalt

Die maschinelle [Belegpruefung](abschluss/BELEGPRUEFUNG.json) stellt fest:

| Aussage | Nachweis / Ergebnis |
| --- | --- |
| Laufwege zugeordnet | Legacy8000 liefert altes V2-Frontend mit API8010; Docker18010 liefert eigenes Frontend/API. Backendversionen unterscheiden sich. |
| API-Struktur |390gemeinsame Operationen,73nurDocker,0nurLegacy;10gemeinsame Operationsobjekte unterscheiden sich. Kein Beweis gleicher Inhalte. |
| Legacy-Datentraegerkandidatin dem laufenden Prozess sicher zugeordnet | **Nein.** `runtime_database_mapping_confirmed=false`. |
| Tabellenzaehlungen dieser Kandidatin und Docker identisch | **Nein.** `observed_table_counts_equal=false`. Keine veroeffentlichten privaten Einzelwerte. |
| Beobachteter letzter Methodenname identisch | Ja, aber weder gleiche Inputs noch gleiche Ausfuehrung daraus bewiesen. |
| Ereignis-/Lot-/Tax-Line-/Jahressummenparitaet zwischen laufendem Altbetrieb und Docker | **Nicht nachgewiesen.** Kein vollstaendiger semantischer Differenzlauf. |
| Docker-Backup zu seiner restaurierten Kopie | Vollstaendige logische Tabellen/Dateien beim Start und Neustart erhalten; Keys, Setup-Token und Profil erhalten. |
| Produktivquelle waehrend finalem Restore | Volltabellen-/Dateivergleich sowie Container-/Konfigurations-/Startzeitvergleich unveraendert. |

Der lesende Inventurbeleg hat SHA256
`e730e70455c4cf7b87b909ac1554d317c075ede79ea5b0c5c5413eadfef92443`.
Private Quelldatei lokal:
`/root/.local/share/steuerreport/migration-audit-20261028/coordinator/private-data-inventory.json`.
Der finale Restorebeleg liegt daneben unter `final-restore-b036b8a/`;
Zusammenfassung SHA256
`c44bfef54db1898e6ae4921458a02675049cc7568566400155f8d20321adcef1`.
Die Anlagenpruefung kontrolliert diese Hashes und Erhaltseigenschaften, ohne
Datensaetze oder Secrets auszugeben. Private Vollbelege werden nicht publiziert.

**Restore ist nicht Alt-/Neu-Paritaet.** Die vorhandene Sicherung entspricht
den ueberprueften produktiven Tabellen; neuere Nicht-DB-Vorschauartefakte koennen
gegenueber der aelteren Sicherung abweichen. Vor spaeterer Umschaltung ist eine
neue konsistente Gesamtsicherung und die sichere Legacy-Zuordnung erforderlich.
Weitere Betriebsdetails: [feature-parity.md](feature-parity.md),
[backup-restore-proof.md](backup-restore-proof.md), [rollback.md](rollback.md).

## 6. Korrekturbelege Fuer Die Hauptfehler

### 6.1 Altpreise F02 / G10

Code: [price_policy.py](../../../src/steuerreport_v2/domain/price_policy.py),
[price_lookup.py](../../../src/steuerreport_v2/domain/price_lookup.py),
`derived_prices.py`, `valuation.py`, eigener Income-Preisindex in `tax_years.py`.
`price_rejection_reason` (Zeile29) und `eligible_price_sql` (Zeile55) geben
dieselben Voraussetzungen vor: positiv, gleicher UTC-Tag, nicht nach Ereignis;
`allow_derived` und Solana-Quellgrenzen bleiben zusaetzliche Bedingungen.

| Probe | Vorher | Nachher und Pruefbezug |
| --- | --- | --- |
| G10Lookup2021fuer2025 | Altkurs ausgewaehlt, TestFAIL | Keine Auswahl; `test_G10_lookup_alte_und_zukuenftige_preise_abgelehnt[alt]` PASS |
| Zukunftskurs | Bereits abgelehnt | Bleibt abgelehnt; kein neu behaupteter Vorherfehler |
| SQL-Coverage mit Altkurs | Luecke verdeckt, FAIL | Luecke sichtbar; `test_G10_coverage_sql_meldet_altkurs_als_luecke` PASS |
| Taxverbrauch und Review | Altkurs im Wert, unberechtigt exportierbar, FAIL | Kein Altpreisverbrauch und keine finale Freigabe; zwei entsprechende G10-Proben PASS |
| Neudatierung durch Derived | Frischer Kurs aus altem Anker, FAIL | Keine solche Ableitung; `test_G10_derived_preis_darf_altkurs_nicht_zeitlich_waschen` PASS |
| JahresZIP | Faelschlich final, FAIL | Vorschau, `export_ready=false`; `test_G10_altkurs_jahresarchiv_nicht_final` PASS |

Die separate jetzt erneut bestandene Unit-Probe
`test_stale_or_future_price_cannot_finalize_real_service_chain` verwendet
ausdruecklich **1642Tage** alte beziehungsweise zukuenftige Kurse. Unabhaengige
Algebra:10HNT fuer20EUR gekauft,4veraeussert ->8EUR anteilige Basis. Ohne
zugelassenen Erloeskurs bleibt eine vorlaeufige0/-8-Rechenzeile moeglich,
aber Coverage meldet1Luecke, Review blockiert, PDF-Paketstatus ist blocked.
Die0ist **kein final ermittelter Erloes oder steuerlicher Verlust**.
Quote-/Asset-/Counterflow-Ableitungspfade sind separat parametrisiert getestet.

Alte Referenzen koennen nur in einem gesonderten Stichtags-Diagnosepfad als
alt/prior_day erscheinen. Sie fuellen weder Portfolio- noch Steuerwerte und
duerfen keine Materialitaetsbefreiung ausloesen. Technische Tageszulassung ist
keine Freigabe einer steuerlichen Tagesschluss-/Tagesdurchschnittsmethode.

### 6.2 Haltefrist F03 / G15-G16

Code: [tax_time.py](../../../src/steuerreport_v2/domain/tax_time.py),
insbesondere `private_holding_anniversary`, `private_disposal_within_year`,
`private_disposal_tax_free_at`, SQL-Praedikat und Lot-Fallback. Jahresaggregation,
Berichtskarten, Planung und CSV verwenden diese zentrale Klassifikation statt
einer eigenen365Tage-Regel. `holding_days` bleibt rein beschreibend.

| Feste Erwartung | Ergebnis |
| --- | --- |
| Kauf01.03.2023, Verkauf01.03.2024Berlin | Innerhalb der modellierten Jahresfrist, auch bei366vergangenen Tagen; vorher falsch, jetzt G15-Jahresconsumer und CSV PASS |
| Folgetag02.03.2024Berlin | Ausserhalb; UTC-Grenze01.03.2024um23:00Z, Planung stimmt |
| Kauf29.02.2024, Jahrestag28.02.2025 / Folgetag01.03.2025 | Innerhalb / ausserhalb; Python und DuckDB-SQL PASS |
| Berliner Mitternacht in Winter/Sommer | Keine365Dauer-Tage-Ersatzklassifikation; G15/G16PASS |
| Jahreswechsel und DST | Berliner Steuerjahr, SQL und beide Herbst-DST-Stunden im parametrisierten Test korrekt |

Die festen Datumsorakel stehen in `tests/unit/test_tax_f03_calendar.py:32`,
nicht als zweite Berechnung mit der zu pruefenden Funktion. Echte FIFO-/Jahres-
und Reportservices sowie CSV-Endpunkt werden getestet. Alte archivierte
Tax-Line-Labels werden nicht nachtraeglich mit der neuen Regel ueberschrieben.
Das belegt das implementierte private Fristmodell, nicht die Privatzuordnung
aller Bestandswerte oder die Richtigkeit jeder importierten Handelszeit.
Rechtsquellen/Annahmen: [METHODENKATALOG.md](METHODENKATALOG.md).

### 6.3 Kostenbasis, Swaps Und Gebuehren

Unveraenderte Sollproben im unabhaengigen52er-Satz:

| Fall | Konkrete Rechnung / Resultat |
| --- | --- |
| G01 |10Stueck/100EUR; Verkauf4/60EUR ->Kosten40, Gewinn20, Rest6/Basis60:PASS |
| G02 | Kauf100+EUR2; Verkauf4von10fuer60minusEUR1 ->Basis40,80, Gewinn18,20, Restbasis61,20:vorherFAIL, jetztPASS |
| G03 |10Brutto minus0,1Erwerbsassetgebuehr ->9,9Token/Basis100:PASS im Teilumfang; spaetere Verwertung offen |
| G04 | BNB1fuer20EUR, Folgeerwerb mit BNB0,1Gebuehr ->Istrest1stattSoll0,9:**FAIL** |
| G05 |2BTC/Basis40 in5ETH/Wert60 ->Gewinn20, ETH-Basis60,0EUR-Einzahlung:PASS; keine Slippage-Komplettpruefung |
| G06/G07 |100Stablecoins mit belegtem Testpreis0,72 ->72EUR; Depegpreis0,60 ->60EUR:PASS als Tax-Consumer, kein vollstaendiger Preis-/FX-Beschaffungsnachweis |
| G13 | Rewardzugang100, Basis100, spaeterer Verkauf150 ->getrennt100Zufluss und50Veraeusserungsgewinn:PASS im Teilumfang |
| G17 | Fehlende Herkunft/Basis/Preise bleiben Reviewfaelle; kein umfassender Nachweis positiver, aber unbelegter Kostenbasis |

EUR-Kostenkorrektur: `tax.py:_lot_from_buy` (Zeile651); Drittassetabsicherung
und Nullbasiswarnung: `review.py`. Keine pauschale Kapitalisierung aller
Gebuehren und kein steuerlicher Scope aus einem Rewardlabel abgeleitet.

## 7. Einzelstatus G01-G25

**Fachliche Gesamt-/Jahresfreigabe: NEIN fuer jede Zeile.** PASS bedeutet nur
die beschriebene bestandene technische Sollprobe. Vollstaendige Teilproben-IDs
und Vorher-/Nachher-Ergebnisse stehen in den beiliegenden XML-/JSON-Anlagen.

| ID | Implementierung / Abdeckung | Technischer Teststatus | Noch offen |
| --- | --- | --- | --- |
| G01 | Bestehender EUR-Kauf-/Verkaufspfad | PASS Fixture | Separater PDF-Fachzahlenabgleich |
| G02 | EUR-Erwerbskosten korrigiert | PASS Fixture, vorherFAIL | Andere Gebuehrenarten nicht mit abgenommen |
| G03 | Erwerbsassetgebuehr modelliert | TEILWEISE PASS | Spaeterer Verkauf/Doppelabzug |
| G04 | Lotverbrauch nicht vollstaendig; Reviewguard neu | **FAIL** | BNB-Menge, EUR-Allokation und Doppelabzug konsistent loesen |
| G05 | Gewoehnlicher Token-Swap vorhanden | PASS Fixture | Slippage, abweichende Gegenwerte/Sonderprotokolle |
| G06 | Historischer EUR-PricePoint im Tax-Consumer | TEILWEISE PASS | Originalantwort plus vollstaendiger FX-Verbrauch |
| G07 | Depegwert statt pauschaler Paritaet | PASS Tax-Fixture | Belegter Beschaffungsweg/Originalkurs |
| G08 | Kein neuer durchgaengiger FX-Richtungsadapter geliefert | NICHT GEPRUEFT als unabhaengiger G-Fall | Beide Quotierungsrichtungen und Einheiten im realen Consumer |
| G09 | Kein vollstaendiger Wochenend-/Feiertagslauf geliefert | NICHT GEPRUEFT als unabhaengiger G-Fall | Begrenzte Referenztagsregel und fehlender FX |
| G10 | Lookup/Coverage/Derived/Tax/Review/Export vereinheitlicht | PASS7vertikale Teilproben plus Fokusregressionen | Nicht jede Quelle, FX-Policy oder Altprovenienz |
| G11 | Globale Methode und Wallet-Vorschau getrennt | TEILWEISE PASS | Allgemeine Depotmethodenfreigabe, keine Aktivierung erfolgt |
| G12 | Lotfortfuehrung im Eigenuebertrag vorhanden | TEILWEISE PASS | Netzwerkgebuehr und vollstaendige Fremdbelege |
| G13 | Rewardzugang/Basis/Verwertung getrennt | TEILWEISE PASS | Privat-/Betriebsherkunft und andere Rewardarten |
| G14 | Unklares Income bleibt Review | TEILWEISE PASS | Vollstaendige Sphaeren-/Rewardklassifikation |
| G15 | Zentrale private Kalenderfrist implementiert | PASS Kalender-/CSV-/Planungsfixtures | Konkrete Zeitquelle/Scope jedes Originalvorgangs |
| G16 | Berlin-Jahr und Kalendergrenzen vereinheitlicht | PASS Grenzfixtures | Keine exhaustive Zeitzonenpruefung |
| G17 | Missing-Preis/Herkunft und Nullbasis-Review | TEILWEISE PASS | Vollstaendige Gaptaxonomie, positive unbelegte Basis |
| G18 | Keine vollstaendige Contract-/Chain-Konfliktloesung geliefert | NICHT GEPRUEFT als unabhaengiger G-Fall | Identitaet bei Symbolkollision |
| G19 | Kein neuer belegter Migrations-/Wrappingconsumer geliefert | NICHT GEPRUEFT als unabhaengiger G-Fall | Verhaeltnis und wirtschaftliche Einordnung |
| G20 | CSV-idempotent; Zusatztests fuer API-Wiederholung/Konten | PASS CSV-Fixture und begrenzte D-Tests | Nicht jeder Anbieter/Formatwechsel |
| G21 | Gebundene Vorschau bei Daten/Preis/Admin-Regelmarker veraltet | TEILWEISE PASS | Alle echten Regeldateien/historische Vorschauuebernahme |
| G22 | Offline-FIFO und CSV semantisch reproduzierbar | TEILWEISE PASS | Separater Prozess-/PDF-Bytevergleich |
| G23 | Technischer Export nicht final, Vorschau/Runbindung im Inhalt | PASS Export-Fixtures und Browser | PDF-Fachzahlengleichheit ueber alle Faelle |
| G24 | Lesende jahresabhaengige Freigrenzenprobe, Zusatzkontext Pflicht | PASS11echte Route-Fixtures | Nicht alle Jahre/Negativkonstellationen; keine persoenliche Steuerrechnung |
| G25 | Archivrevision plus synthetischer Restore, zusaetzlich echter isolierter Docker-Restore | TEILWEISE PASS | Produktiver Rollback/Altparitaet/alle Migrationsdaten |

## 8. Tatsaechlich Ausgefuehrte Befehle Und Belege

Die folgenden Befehle wurden ausgefuehrt, nicht nur vorgeschlagen. Der neue
115er-Lauf und die Anlagenpruefung wurden zur Erstellung dieses Berichts
wiederholt. Andere Ergebnisse wurden jetzt anhand ihrer originalen XMLs und
Hashes verifiziert; der520Sekunden-Gesamtlauf wurde nicht nochmals behauptet.

Gemeinsame Hostumgebung fuer pytest:

```sh
export PYTHONPATH=src:/tmp/steuerreport-connector-tools-20261026:/tmp/steuerreport-release-tools-20261025
export STEUERREPORT_TEST_PRUNE_PASSED_DBS=1
```

| Ausgefuehrter Befehl | Resultat / Originalbeleg |
| --- | --- |
| `python3 -m pytest tests/unit -q -n8 --dist loadfile --basetemp=/tmp/steuerreport-migration-final-unit --junitxml=/tmp/steuerreport-migration-final-unit.xml --tb=short` |2464Pass/4Skip/0Fail,520,66s; [unit.xml](abschluss/unit.xml) |
| `python3 -B -m pytest docs/audit/2026-10-28/acceptance_tests.py --basetemp /tmp/steuerreport-migration-20261028-acceptance-tests/pytest-baseline-complete -q --tb=line -o cache_dir=/tmp/steuerreport-migration-20261028-acceptance-tests/pytest-cache --junitxml=/tmp/steuerreport-migration-20261028-acceptance-tests/baseline-complete.xml` |22Pass/30Fail,75,61s, Exit1 auf438cbd3; [F52_vorher.xml](abschluss/F52_vorher.xml) |
| Derselbe52er-Test mit `--basetemp /tmp/steuerreport-migration-20261028-acceptance-tests/pytest-freeze-b036b8a --tb=short --junitxml=/tmp/steuerreport-migration-20261028-acceptance-tests/freeze-b036b8a.xml` |51Pass/1Fail,135,51s, Exit1 aufb036b8a; [F52_nachher.xml](abschluss/F52_nachher.xml) |
| `python3 -m pytest tests/unit/test_price_policy_regressions.py tests/unit/test_tax_f03_calendar.py tests/unit/test_migration_readiness.py -q -n4 --dist loadfile --basetemp=/tmp/steuerreport-audit-abschluss-20261028/pytest --junitxml=/tmp/steuerreport-audit-abschluss-20261028/fokus.xml --tb=short` |115Pass,44,28s, Exit0; [fokus.xml](abschluss/fokus.xml) |
| `python3 -m ruff check src tests scripts` | Exit0 |
| `python3 scripts/export_openapi_v2.py --check`; API-/Import-/KI-Dokumentgeneratoren jeweils `--check` | Je Exit0, Einzelbefehle in PRUEFNACHWEISE.md |
| `npm ci --offline --ignore-scripts --no-audit --no-fund`, `npm run build` im Frontend | Exit0; bestehende Vite-Chunkwarnung ueber500kB |
| `node scripts/check_workspace_state_v2.cjs`, erneut mit `TZ=Europe/Berlin` | Je Exit0, URL-/Privacy-/Decimal-Pruefungen bestanden |
| `python3 -m unittest discover -s docs/audit/2026-10-28 -p test_ops_audit.py` mit passendem `PYTHONPATH` |7Tests bestanden |
| `python3 docs/audit/2026-10-28/abschluss/verify_abschluss.py` | XMLs, unveraenderter52er-Testcode, Diff und lokale Erhaltsbelege erfolgreich geprueft; `full_fiscal_approval=false` |
| `git apply --cached --check docs/audit/2026-10-28/abschluss/AENDERUNGEN.patch` mit separatem `GIT_INDEX_FILE`, vorher `git read-tree` der Diffbasis | Exit0; Patch passt binaertauglich zur angegebenen Basis, echter Index/Arbeitsbaum unberuehrt |
| `gitleaks dir docs/audit/2026-10-28/abschluss --config .gitleaks.toml --redact --no-banner` | Exit0,0Secretfunde in Diff/Original-XMLs/Belegpruefer; keine pauschale Aussage zu allen Git-Historien |

Die damaligen Befehle verwendeten zusaetzlich das reine Git-Vertrauenssetting
`GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory
GIT_CONFIG_VALUE_0=/tmp/steuerreport-migration-20261028-coordinator`.
Das aendert keine Tax- oder Testfunktion. Acht Worker bedeuten acht getrennte
Testdatenbanken, keine parallelen produktiven DuckDB-Schreiber.

Die gleichen52Proben liefen ausserdem im finalen lokalen Image mit
`docker run --rm --pull=never --network none --read-only`, disposable tmpfs,
read-only Testwerkzeugen/-quellen, `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` und
`-o pythonpath=`. Ergebnis:51Pass/1Fail,83,70s. Produktimport kam aus dem
installierten Image, nicht aus dem Hostcheckout. Exakte Laufzeitversionen im
[candidate-manifest.json](candidate-manifest.json). Fuer diesen Zusatzlauf
wurde kein eigener dauerhafter JUnitexport angelegt; das Konsolenergebnis und
der nachgewiesene lokale Imagebezug sind daher schwaechere Anlagen als die
beigefuegten Host-XMLs. Es wird kein fehlendes XML nachtraeglich erfunden.

Browserprogramme, jeweils `python3 scripts/PROGRAMM --output /tmp/EIGENER_ORDNER
--browser-executable /root/.cache/ms-playwright/chromium-1187/chrome-linux/chrome`:

| Programm | Ergebnis |
| --- | --- |
| `check_ux_browser_v2.py` | Gesamt-UX-Smoke und A01-A23/R1 bestanden, nur synthetische Antworten |
| `check_migration_readiness_browser_v2.py` |100Screenshots,344MockGETs,0extern/Seitenfehler |
| `check_review_backend_browser_v2.py` | F1/F2/F3gegen echte isolierte API bestanden, Datenerhalt bei Reads |
| `check_wallet_setup_browser_v2.py` | Setup/Adresse/Signatur/unbekannteEUR gegen isolierte API bestanden |
| `check_history_import_browser_v2.py` |13Workflow-Szenarien bestanden |
| `check_history_backend_browser_v2.py` | Explizite Testfreigabe importiert exakt Transfer/Gebuehr aufA,Bunveraendert |
| `check_history_provider_eta_browser_v2.py` |16Szenarien bestanden |
| `check_solana_limits_browser_v2.py` |17Faelle/35Screenshots bestanden |
| `check_historical_prices_browser_v2.py` | Echter Preisrouter/MockProvider,12Screenshots,0reale externe Requests |

Die maschinenlesbaren Browserprotokolle und Screenshots liegen in den in
[PRUEFNACHWEISE.md](PRUEFNACHWEISE.md) vollstaendig genannten lokalen
Nachweisordnern. Sie sind keine volle WCAG-, Provider- oder Steuerabnahme.

### Skips, Fehler Und Belegintegritaet

Die vier Skips betreffen drei fehlende private Solscan-/Blockpit-/RPC-Belegtests
und einen opt-in-pflichtigen privaten Usertransfer-Belegbaum. Keine neuen
Skips/xfails zum Verdecken vonG04. Die52er-Probe bleibt mitExit1rot.
Der erste Integrationslauf9Fail/2434Pass wurde als Integrationsregression
erfasst und korrigiert, nicht als gruener Abschluss oder vorbestehend umgedeutet.

| Anlage | SHA256 |
| --- | --- |
| `unit.xml` | `3b27bfb8510dfb7b4aa364ec82e5062c3349b7c658219307e1c0306cb2c67960` |
| `F52_vorher.xml` | `b1203aa0b3db8506b2d4879855fb576034757087cbf9db707c563477294f2818` |
| `F52_nachher.xml` | `e2782bc8ae498995dcdbe05313c6d153bac0674a81cd6792f3e441bf00d0175f` |
| `fokus.xml` | `a75921281cf68bb1a90ed4eb5186f095c7943490c4d179d7c1c6ad84955fadc7` |
| Unveraenderter52er-Testcode | `09f674b350a9a83943df8980bbceafd88821ee1400e03b5b22ea1ee0f8cd6bfb` |

Die Anlagen enthalten synthetische Testdaten, keine privaten Belegdateien.
JUnit hat keine erfassten stdout-/stderr-Logs; vier Unit-Properties enthalten
nur synthetische Inventaranzahl/-Laufzeit/-Lesezaehler. Diff und Anlagen wurden
mit Gitleaks geprueft. Die Belegpruefung importiert keine Anwendung, oeffnet
keine DB und fragt keine Anbieter ab; private Erhaltsbelege lassen sich nur
mit berechtigtem lokalem Zugriff vollstaendig nachpruefen.

Der pauschale `git diff --check` ueber das neue Anlagenpaket meldet
Whitespace in originalen Patch-Kontextleerzeilen und einer originalen
Traceback-Leerzeile in `F52_vorher.xml` (Exit2). Diese beiden Belege werden
absichtlich nicht umformatiert, damit ihre Hashes und die Patchanwendbarkeit
erhalten bleiben. Der Check der Quell-/Berichtsdateien mit Ausschluss genau
dieser beiden Originalanhaenge besteht; keine globale Whitespace-Ausnahme.

## 9. Verbleibende Blocker Und Freigabeentscheidung

1. **G04:** physischer Drittasset-Lotverbrauch und konsistente Kosten-/Erloes-
   allokation fehlen; Reviewguard ist nur Absicherung.
2. **G08/G09:** keine vollstaendige unabhaengige FX-Richtungs-/Feiertagsprobe.
3. **G18/G19:** Contractidentitaet/Symbolkollision und Migration/Wrapping offen.
4. **Kostenbasis/Scope:** positive, aber unbelegte Kostenbasis, ungeklaerte
   Privat-/Betriebsherkunft und weitere Gebuehren-/Rewardfaelle nicht geloest.
5. **Alt-/Neu-Paritaet:** Legacy-Laufzeitdatenbank zuordnen und Ereignis-/Lot-/
   Tax-Line-/Jahressummenvergleich mit erklaerten Differenzen erstellen.
6. **Methodik/Abschluss:** Tageskursmethode konsistent belegen, gebundenen
   aktuellen Lauf und erforderliche menschliche Freigaben einholen.
7. **Betrieb:** Registryimagebindung, neue Gesamtsicherung und passender
   getesteter Rueckweg vor spaeterer beauftragter Umschaltung.
8. Benannte BMF-/Docker-Nachpruefdateien und Originalreproordner waren nicht
   auffindbar; keine behauptete Lektuere oder exakte Wiederholung dieser Dateien.

**Entscheidung: keine Gesamt-Fachabnahme und keine produktive Umschaltung.**
Die technisch nachgewiesenen Korrekturen koennen anhand des beigefuegten Diffs
reviewt werden; die restlichen Paketteile sind nicht als erledigt ausgegeben.
Produktion ist unveraendert aufrc32, ohne neue Imports, Berechnungen oder
Methodenaktivierung. Bei der jetzigen lesenden Nachkontrolle entsprachen
Container-ID, Image-ID und Startzeit weiterhin dem Betriebsmanifest; healthy.
Kein Push, Git-Tag, Release oder GHCR-Publish durch diesen Berichtsauftrag.
