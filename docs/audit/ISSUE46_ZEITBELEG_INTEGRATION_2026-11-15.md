# Issue 46: Zeitbelegpruefung und Integrationsnachweise

Stand 15.11.2026. Basis Draft #61,
`8e96422e65d809fdc206d2881f353f55b5bdc5e3`; Vertragscommit
`9f2908f39d6e2435a417cdcd2ba4eef809396036`.
Aktueller Commit und begrenzter Diff stehen im zugehoerigen Draft-PR.
Keine Main-/Release-/Containerumschaltung, kein produktiver Datenzugriff,
keine Methodenaktivierung oder automatische steuerliche Korrektur.

## Implementiert, nicht mit voller Abnahme verwechseln

| Anforderung | Umsetzung | Grenze |
| --- | --- | --- |
| Tagesanker ist kein beobachteter Intraday-Kurs | Reine versionierte `PriceTimeAssessment`-Lesepolicy, getrennte Referenz-/Beobachtungs-/Perioden-/Veroeffentlichungsfelder | Ohne Originalbindung bleiben die Belegfelder `None`; keine positive Nicht-EUR-Zulassung implementiert |
| Unbelegter Same-Day-Wert oeffnet kein strenges Gate | Gate zaehlt `unverified_price_time_count`; As-of-Bericht zeigt `time_review` und Assetzaehler | Globale steuerliche Tagespreisregeln, FIFO und gespeicherte Werte unveraendert |
| Kleiner ungepruefter Wert ist kein Materialitaetsbeweis | Nur belegte EUR-Identitaet darf die bestehende Wertschwelle nutzen | Keine persoenliche Unterhalts-/Steuerbewertung |
| Tokenentscheidung ersetzt keinen Zeitbeleg | Tokenstatus und Zeitpruefung bleiben getrennt; Hinweise/naechste Aktionen benennen die Luecke | Vorhandene Entscheidungen nicht geloescht oder neu angenommen |
| Echte EUR-Identitaet zeitlos | Asset EUR, Wert exakt 1, Quelle exakt `fiat:EUR`; Epoche nicht als Beobachtung ausgeben | Kein Stablecoin- oder fremdes Labelprivileg |
| Alte positive Runs kein aktueller Nachweis | `latest()` prueft vier Policy-ID/-Versionspaare; alte Dateien bleiben per ID lesbar | Keine allgemeine Datenaktualitaets-/Integritaetsgarantie fuer beliebige alte Runs |
| Benutzerfuehrung | Eigene Zeitbelegdetails im bestehenden Stichtagsbereich, fehlende Preise nicht als bekannte Null anzeigen | Vollstaendiger Dossierseiten-/Screenreader-Audit nicht behauptet |
| Verbindliche unabhaengige Gegenproben | 43 unveraenderte Proben zusaetzlich hashgebundenes CI-Gate | Kein Schliessen G01-G25 oder #46 allein aus diesem negativen Guard |

Keine DB-Schemaaenderung, keine neuen Preiszeilen, kein Belegregister und kein
Writer durch die Lesepolicy. `same_day_price_count` bleibt ein technischer
Kompatibilitaetszaehler fuer Tagesreferenzen einschliesslich EUR-Identitaet,
kein Zaehler bestaetigter Marktbeobachtungen. Gatezaehler betreffen Positionen;
As-of-`time_review_count` betrifft Assets. Beide Mengen bleiben erklaerbar.

## Dateien und Datenfluss

- `contracts/price_time.py`, `domain/price_time.py`: reines Leseassessment,
  Decimal/UTC, keine aus freien Labels abgeleitete Freigabe. Ein Labelhinweis
  auf Tages-/Derivedreferenz bleibt ausdruecklich ungepruefter Kandidat.
- `domain/divorce.py`: Zeitpruefung getrennt von Datum, Materialitaet und
  Tokenannahmen; Werte und steuerliche Klassifikation nicht neu berechnet.
- `domain/as_of_price_gate.py`, `contracts/prices.py`, `contracts/divorce.py`:
  additive Felder, passende Aufgaben und Ursachen statt pauschalem Re-Fetch.
- `domain/valuation_runs.py`, `api/app.py`: alte Policy nicht nachtraeglich
  als aktuelle ausgeben. Defaultfelder sind `None`, nicht die neue Policy-ID.
  Latest-API liefert bei Legacy eine Warnung und `data=None`; gezieltes
  Archivlesen bleibt moeglich, mit Hinweis auf die historische Bedeutung.
  `include_archived=true` ist ein ausdrueckliches lesendes Opt-in fuer die
  vorhandene Oberflaeche: alte Daten mit Warnung und sichtbarem Altstand statt
  verstecktem Download. Das Standardverhalten bleibt fail-closed.
  Originaldateien werden nicht umgeschrieben. Die additive API-Serialisierung
  ist nicht der originale Datei-Bytestrom fuer alte Hashpruefungen.
- `frontend/src/main.tsx`, `workspace/PriceTimeEvidence.tsx`: neue Details,
  defensive Legacy-Gateanzeige und unveraenderte Route / bestehender Stil.
- CI und Referenzguard: vier unveraenderte SHA-Bindungen, zusaetzliche
  Zeitbeleg-Referenzpruefung und drei Browserpfade unter erlaubtem `var/`.

Backendpfade sind relativ zu `src/steuerreport_v2/`.
Der Codegraph meldete fuer das registrierte andere Checkout einen veralteten
Commit. Beziehungen wurden deshalb im tatsaechlichen Quellstand mit `rg`,
Dateilesen und Laufzeittests verfolgt; kein alter Graph als aktuelle Analyse
ausgegeben und keine grosse neue Graphdatenbank erzeugt.

## Unabhaengige Rot-/Gruenbelege

Agent mit eigenem Checkout, derselben Basis und eigenen synthetischen DBs:
**43 Faelle, zuvor 35 failed / 8 passed**, keine Errors oder Skips.
Aufteilung: 27 reproduzierte Falschpositive, sieben additive Vertragsluecken,
eine EUR-Zeitlosigkeitsabweichung. Die acht bestehenden Kontrollen bestanden.

Unveraenderte Datei:
`tests/unit/test_as_of_temporal_evidence_acceptance.py`, SHA256
`06d4d1115cf1f5dfa1ff240d37a87c23709685e151d7df7902432a3fb5a3fdc8`.
Original-`before.xml` im isolierten Testcheckout, SHA256
`20577a10920e1d2efe56ad19109130a294b3385b9087d05798ea4ff4bb16096c`.

Erste Integration: 42 passed / ein Fehler, weil das Gate die gueltige
EUR-Identitaet trotz korrektem Assessment noch als alten Marktkurs behandelte.
Korrigiert ausschliesslich fuer die validierte Identitaet. Danach
**43 passed**, unveraenderte Assertions, keine Skips / Errors.
Eine begrenzte rein lesende Gate-/Legacy-/API-Quellpruefung ergab keine
konkreten Findings in ihrem Umfang. Sie ersetzte nicht die nachfolgende
gemischte UI-Probe und ist keine Gesamt- oder Fachabnahme.

Die erste fokussierte Alt-Testsuite hatte acht Fehler / 122 passed:
alte Assertions setzten Same-Day oder Tokenannahme noch mit strenger
Freigabe gleich. Diese Statusassertions wurden gezielt auf den neuen Vertrag
angepasst und Zeitzaehler ergaenzt. Alle Betrags-/Mengen-/Mint-/Decision-/CSV-
Assertions bleiben erhalten. Die 43 unabhaengigen Proben wurden dafuer nicht
veraendert. Danach **130 passed**. Die spaetere EUR-Korrektur ist separat
durch die 43 Gegenproben und den nativen Browserpfad gedeckt.

Der erste Gesamtlauf hatte **4.099 passed, einen Fehler, vier bestehende
Skips**, keine Errors. Eine weitere alte Diagnoseprobe behauptete aus einem
vorhandenen BTC-Tageswert von 7 EUR eine strenge Freigabe. Wert-/Lookup-/
Diagnoseassertions blieben erhalten; nur diese Statusannahme wurde durch
`time_review` plus explizit fehlende strenge Eignung ersetzt. Ein zusaetzlicher
eigener Test prueft Legacy-API-Default, ausdrueckliches Archiv-Opt-in, Warnung
und unveraenderte Dateien. Der anschliessende fokussierte Lauf bestand mit
**59 Faellen**. Der erste Gesamtlauf wird nicht als gruener Nachweis ausgegeben.
Der erneute gesamte Backendlauf bestand mit **4.101 passed / vier bestehenden
Skips**, null Fehlern/Errors und vier bestehenden Starlette-Warnungen in
731,94 Sekunden. Die Skips benoetigen private Referenzimporte und werden
nicht als abgedeckte Faelle gezaehlt.

Eine weitere unabhaengig vom Produktstatus formulierte UI-Probe mischte
aktuelle Top-Level-Gates mit historischen Summary-Gates. Sie reproduzierte
noch ein falsches `strict_ready`-Label. Die Anzeige prueft nun wie der
Backendlesepfad alle vier Policy-ID/-Versionspaare. Dieselbe Probe bestand
danach zusammen mit Legacy-, aktuellem und leerem Zustand: **16 Faelle**.
Kein alter Run oder Archiv wurde dafuer veraendert.

Der echte App-Browserpfad machte zudem einen mobilen Seitenoverflow von
390 auf 429 Pixel sichtbar. Nur Headerumbruch genuegte nicht; die
Grid-Minimalbreiten wurden eng auf den Stichtagsarbeitsbereich begrenzt.
Danach kein Seitenoverflow in den 16 Faellen bei 390/768/1280/1440 Pixeln.
Die erste Agentenfassung dieses Fixtures ohne HTML-Doctype ist kein
Layoutnachweis. Der finale Lauf verwendet Standardsmodus und prueft die
Dokumentbreite ausdruecklich.

## Tatsaechliche Pruefungen

| Pruefung | Ergebnis |
| --- | --- |
| Ganze Backend-Suite `pytest tests/unit -n 4 --dist loadfile -q` | 4.101 passed / vier bestehende Skips, keine Fehler/Errors |
| Neue reine Policy plus As-of/Divorce/Run-Tests | 130 passed nach gezielter Korrektur der Statusassertions |
| Unabhaengige Zeitbeleg-Gegenproben | 43 passed unveraendert |
| Originalreferenzen | 52 passed, keine Skips / Fehler |
| Erweiterte Referenzen `tests/acceptance` | 359 passed, keine Fehler/Errors/Skips, 278,597 Sekunden; Quellen unveraendert |
| Referenzguard und Paketwhitelist nach Dokumentationserweiterung | 8 passed; vier Referenzhashes bestaetigt |
| Frontend-Build | TypeScript und Vite erfolgreich; bestehende Chunkgroessenwarnung |
| Dashboardchecks | 10 passed; bestehende SSR-`useLayoutEffect`-Warnungen |
| Zeitbelegkomponente, kontrollierte Daten | 284 Faelle / 71 Szenarien, vier Breiten, keine API-/Provider-/Reviewaktionen |
| Echte API -> Komponente mit eigener DuckDB | 12 Faelle / drei Szenarien / vier Breiten; unveraenderte Antwortdaten und DB-Fingerprints, keine Provider-/Pipeline-/Reviewaufrufe |
| Echte App mit kontrollierten API-Antworten | 16 Faelle / vier Zustaende / vier Breiten; Archivzugang bleibt sichtbar, gemischte Policy nicht freigegeben, keine schreibenden/externalen Aktionen oder Downloads |
| Ruff | Erfolgreich |
| OpenAPI-/Endpunktdrift | Erfolgreich |

Die 43 neuen Proben und die 93 reinen Policy-Unitfaelle sind Teil der
Backend-Suite, keine zusaetzlichen eindeutigen Backendfaelle.
Die 16 App-Faelle decken alt, gemischte Policy, aktuell blockiert und keinen
Lauf ab; kein aktuell vollstaendig freigegebener Gesamtseitenfall enthalten.
Komponentenfixture und nativer Browserbridge sind keine vollstaendige
Produktseiten- oder finanzfachliche Abnahme. Vier native Screenshots,
20 kontrollierte Komponentenaufnahmen und vier App-Aufnahmen enthalten
ausschliesslich Testdaten. Der App-Pfad nutzt echte `main.tsx`, aber
kontrollierte Antworten; die native Bridge nutzt echte API/DuckDB mit der
Komponente. Diese beiden Nachweise nicht als einen vollstaendig nativen
Gesamtseitenlauf ausgeben. Ein rc32-Badge aus der synthetischen Updateantwort
ist kein Nachweis einer laufenden Produktivversion.

Alle Pytest-Aufrufe mit vorhandenem Python-3.11-Venv,
`PYTHONPATH=src STEUERREPORT_TEST_PRUNE_PASSED_DBS=1` und getrenntem
`--basetemp` unter `/tmp`. Beispiele der echten Abschlussbefehle:

```bash
python -m pytest tests/unit -n 4 --dist loadfile -q \
  --basetemp=/tmp/steuerreport-issue46-final-unit-20261115 \
  --junitxml=var/issue46-final-unit.xml
python -m pytest tests/acceptance -q \
  --basetemp=/tmp/steuerreport-issue46-reference-final-repeat-20261115 \
  --junitxml=var/issue46-reference-final-repeat.xml
python -m pytest tests/unit/test_as_of_temporal_evidence_acceptance.py -q \
  --basetemp=/tmp/steuerreport-issue46-temporal-acceptance-final-20261115 \
  --junitxml=var/issue46-temporal-acceptance-final.xml
python scripts/check_price_time_evidence_browser_v2.py \
  --node-modules <vorhandene Module> --output /tmp/steuerreport-issue46-widget-css-final-20261115
python scripts/check_price_time_backend_browser_v2.py \
  --node-modules <vorhandene Module> --output /tmp/steuerreport-issue46-native-browser-css-final-20261115
python scripts/check_price_time_archive_browser_v2.py \
  --node-modules <vorhandene Module> --output /tmp/steuerreport-issue46-archive-mixed-final-20261115
```

| Lokales Originalartefakt | SHA256 |
| --- | --- |
| `var/issue46-focused-after.xml` | `c8c91f4fd5f0e5d9e9976b03c12bb4538465aab883d67b587b1a9c614ae41c5e` |
| `var/issue46-temporal-acceptance-after.xml` (42 / 1) | `9350bcddf4048f911bba6e597facfa0e23b3e395864f6f2c36e40c9a3859b6b2` |
| `var/issue46-temporal-acceptance-final.xml` | `7f0124986120f8e41799ceb4864a0dca3024c673f0d7b86f945cc1cadc4cca0d` |
| `var/issue46-reference-original.xml` | `31d634225eb1b333495e54968c2792610d0395610b601f6a23161664e4619b7c` |
| `var/issue46-reference-final-repeat.xml` | `ad99ba9d966cfad7ac8d7bc1bbfadb8cec35839967a43edf5a08bdb8a10081fd` |
| `/tmp/steuerreport-blockers-20261028-reference-tests/bootstrap-053t0oox/source-freeze.json` (`unchanged=true`) | `2923b2eb4ac136a5b651970e43af87b2021658a9a58c1392ed3d07cc20d38e5b` |
| `var/issue46-final-unit.xml` | `002da0b28bfd305a6fa5370a940c5f21ff58d7e26e7a137b0e022c41c232da75` |
| `var/issue46-archive-final-focused.xml` | `a6c0d9cbbb24a9b500f35af9eb81408ae46582d1aed58682ca3d5b1f7064bffe` |
| `var/issue46-package-final.xml` | `b4f228c87cbe7c54db4e84c39364caf5a831b4fbe08b7d8b6e2c3f6f0e6c2521` |
| `/tmp/steuerreport-issue46-widget-css-final-20261115/summary.json` | `5a899b41c17e6064698bf5f0ca2370c219051b3ccb75bc5e109fe53839c95cad` |
| `/tmp/steuerreport-issue46-native-browser-css-final-20261115/summary.json` | `75df7afa451a602f1a02b062411493b20437e5e1c3f85edca1df99060339ab11` |
| `/tmp/steuerreport-issue46-archive-mixed-final-20261115/summary.json` | `37f3d6995f3c9a2aad54a361a4a8812ee8d6e7037d05b38a5e915f7ec41fa5c1` |

Native Browser-Quellenbindung ueber 16 Dateien:
`dfe0b542bd8a94c81aa38de3d9ddd7643eb0a98ada8de87586d34662a28342f0`.
Lokale Hashes sind keine Behauptung ueber die erst folgende CI-Wiederholung.
CI laedt JUnit und Browsernachweise als Originalartefakte hoch.
Ein vorheriger Abschlussversuch wurde mit SIGTERM (143) ohne vollstaendiges
JUnit-Ergebnis beendet. Dieser ist weder bestanden noch als Produktfehler
gewertet. Erst nach bestaetigtem Prozessende wurde der unveraenderte Stand
erneut ausgefuehrt; die 359 Faelle oben stammen aus dieser Wiederholung.
Die erneute abgegrenzte Nur-Lese-Quellpruefung des finalen Vier-Gate-/API-
Deltas ergab keine neuen konkreten Findings; dabei keine Tests gestartet.
Neue UI mit alten oder unbekannten Policy-Markern bleibt konservativ.
Ein beliebiges zukuenftiges Archivschema wird damit nicht unterstuetzt.

## Speicher und Produktionsgrenzen

Keine neuen Venvs/npm-Installationen oder lokalen Docker-Images. Vorhandene
Abhaengigkeiten wiederverwendet, keine dauerhaft gestarteten Testserver.
Nur der beendete selbst erzeugte #49-Backend-Testbestand unter
`/tmp/steuerreport-issue49-final-unit-20261115` (rund 728 MB) entfernt;
Original-JUnit-SHA256 unveraendert bestaetigt. Keine fremden Tempdaten,
Originalimporte, Arbeitszweige, Docker-Volumes oder Finanzdaten geloescht.
Aggregierte freie Kapazitaet ist keine per-Release-Speicherzuordnung.

## Verbleibende Arbeit und Abnahmegrenzen

- #46 bleibt offen: positive Nicht-EUR-Belegzulassung und explizit
  freigegebene Tagesmethoden mit Originalantwort, Identitaet, Kurs-/FX-Zeit,
  Periode und Verfuegbarkeit fehlen weiterhin. Keine Daten aus Labels erfinden.
- Die generische Frontendabfrage transportiert API-Warnungen bislang nicht
  generell. Fuer den hier betroffenen Dossierpfad ist das nicht ausreichend:
  der explizite Archivabruf und die defensive Pruefung aller vier Policy-Paare
  kennzeichnen den alten Stand direkt im Panel. Eine allgemeine Ueberarbeitung
  aller fremden Warnpfade oder ein umfassender Job-Recoverymanager ist damit
  nicht implementiert.
- #44 Snapshot-/WAL-/Planhash und Tickerbindung bleiben eigenstaendige
  Voraussetzungen, die konservative V1-Importsperre bleibt bestehen.
- Die benannte Datei `/tmp/blockpit-analysis/BMF-Quellenpruefung-2026-10-28.md`
  war aktuell nicht vorhanden, auch am zuerst benannten Workspacepfad nicht
  gefunden. Daher keine neue amtliche Rechts-/Methodenfreigabe behauptet.
  Technische Negativproben ersetzen diesen Abgleich nicht.
- #19/#20/#52: keine produktive Legacy-Zuordnung oder vollstaendige
  Ereignis-/Lot-/Tax-Line-Paritaet aus diesen Stichtagsproben ableiten.
- G01-G25 bleiben in ihrem bisherigen Umfang offen/abgenommen; dieser
  Guard ist keine pauschale neue finanzfachliche Abnahme aller Referenzfaelle.

[Vertrag](ISSUE46_ZEITBELEG_VERTRAG_2026-11-15.md) und
[Bedienhinweise](../STICHTAG_ZEITBELEGE.md).
