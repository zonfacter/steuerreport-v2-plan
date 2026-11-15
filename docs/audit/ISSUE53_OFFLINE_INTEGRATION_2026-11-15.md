# Issue 53: Guardintegration und funktionierende Offline-Datenbankkopie

Entwicklungsstand vom 15.11.2026. Kein Release, kein produktiver Containerwechsel,
keine Veraenderung produktiver Finanzdaten. Issue #53 bleibt als Gesamtauftrag
offen. Die Offlinekopie ersetzt kein vollstaendiges Volume-/Vault-Restore.

## Ausgangsstaende und Integration

- Preis-/Auditintegration #58:
  `1125f8da58dd30047170dc07a77b46201cf41f4b`.
- Bisheriger Guard-Draft #55:
  `12f2eca25ef35dc2dc526ab8ee39fe7256182b61`.
- Branch: `codex/issue53-integrated-snapshot-20261115`, beide Eltern erhalten.

Die zwei erwarteten Inhaltskonflikte in den Legacy-Skripten wurden bewusst
aufgeloest: Kein unsicherer Stage-/Live-CLI-Lauf und keine automatische
Hauptdatei-Rueckkopie. Die Preis-Service-Regeln und ihre direkten internen
Aufrufer behalten `require_backfill_pipeline_success` und die Weitergabe von
Abbruchsignalen. Solscan `--fetch-only` bleibt ein getrennter Cache-/Abrufweg,
kein Datenbankimport und keine pauschal lesende Aktion.

Die bisherigen zwoelf Stage-/Live-Fehlerinjektionsfaelle wurden nicht geloescht:
Sie pruefen jetzt mit denselben Preisfehlerarten fuer Dry-Run/Execute, dass
keiner dieser CLI-Aufrufe Fetch, Stage, Live oder Restore erreichen kann.
Die sechs direkten Helper-Fehlerproben bleiben erhalten; zusaetzlich pruefen
die uebernommenen #55-Tests reale aktive und verwaiste WALs und Abbrueche.

## Neuer bedienbarer Weg ohne KI

- `src/steuerreport_v2/db/offline_snapshot.py`: einmalige explizite Kopie einer
  bereits geschlossenen, sauberen DuckDB unter echter read-only-Sperre.
- Modul-CLI `python -m steuerreport_v2.db.offline_snapshot`, im `src`-Paket und
  damit fuer den standardmaessigen Imagebau vorgesehen. Wrapper in `scripts/`
  fuer Checkouts. Noch kein gebautes/veroeffentlichtes Image dieses Standes.
- Jeder oeffentliche Aufruf verwendet einen isolierten kurzlebigen Worker;
  keine Source-FDs im aufrufenden Prozess und keine Aufhebung der Sperren
  anderer Aufrufer beim Schliessen von Streams. Auch die Kopie bleibt bis nach
  der Verzeichnissynchronisation read-only gesperrt. `.wal`-/`.tmp`-Pfade sind
  kein erlaubter Quell-/Zielnamensraum.
- Bestehende Ziele/WALs/Temp-Pfade und nicht eindeutige Dateizuordnungen werden
  abgewiesen. Quelle wird weder migriert noch gecheckpointet. Keine Dienste
  werden gestoppt, keine fremden Neben-/Originaldateien geloescht.
- Kopierhash, erneutes Hashen derselben Quelle, Wiedereroeffnung und vollstaendiges
  Lesen gespeicherter Tabellenwerte. Kleine Lesepakete, keine neue Preis-/KI-API.
- Veroeffentlichung per atomarem nicht ersetzendem Hardlink im Zielverzeichnis,
  Dateisynchronisation, Modus 0600. Wiederherstellung nur in ein neues Ziel,
  optional an vorher aufbewahrten erwarteten SHA256 gebunden.
- Reale synthetische Anwendungsprobe: Journal, Preis-IDs, Warnantwort und
  Wiederholungssperre ueberstehen Kopie und Restore in eine neue Datenbank.
  Das beweist weder externe Dateibelege noch Vault-/Vollanwendungsrestore.

Bedienung und Fehlermatrix: [Offline-Datenbankkopie](../OFFLINE_DATENBANKKOPIE.md).

## Gefundene Fehler und begruendete Korrektur

Ein separater Agent schrieb unabhaengige Testfaelle auf der #58-Basis im eigenen
Worktree. Seine erste Probe fand vier Fehler (42 bestanden, 4 fehlgeschlagen):

1. Zwei echte Subprozessproben widerlegten die gehaltene Lesesperre. Ein
   zusaetzlich geoeffneter und wieder geschlossener Quelldateistream konnte
   unter Linux die POSIX-Dateisperre vorzeitig freigeben. Korrektur: nur ein
   zusaetzlicher Quelldateistream; er bleibt bis nach Veroeffentlichung offen,
   zweites Hashen ueber `seek(0)` ohne erneutes Open/Close. Beide urspruenglichen
   Lockproben bleiben unveraendert und bestehen jetzt.
2. Zwei Proben erzeugten ein Ziel-WAL/Temp unmittelbar beim Verlinken. Fuer
   unabhaengige Dateipfade existiert hier keine atomare Mehrdateipruefung.
   Korrektur: Nachpruefung nach Verlinken, bei Rennen ausdruecklich
   `publication_state_unknown`; keine positive Antwort und kein gefaehrliches
   Loeschen einer inzwischen von einem anderen Writer verwendbaren Datei.
   Die beiden Tests pruefen diese explizite Grenzsemantik, nicht eine nicht
   implementierbare Behauptung, dass niemals eine neue Datei erscheinen kann.

Die vier Gegenproben wurden nicht geskippt oder als xfail versteckt.
46 unabhaengige Proben bestanden anschliessend im Testagenten und erneut
gegen den damaligen Zwischenstand. Das nachfolgende separate Review fand
noch drei Integrationsblocker und fuehrte zu einer groesseren Korrektur:

- Ziel-Lesesperre wurde vor Verlinken/Directory-fsync geschlossen; sie bleibt
  jetzt ueber beide Schritte offen, damit ein Writer den gemeldeten Hash nicht
  schon waehrend der abschliessenden Synchronisation ueberholen kann.
- `<source>.wal` war als neues Ziel zulaessig und wurde bei spaeterem
  Quellschreiben vom DuckDB-Lifecycle entfernt. Reservierte `.wal`-/`.tmp`-
  Pfadkomponenten werden jetzt vor einem Zugriff abgewiesen.
- Ueberlappende Aufrufe oder bereits bestehende Leser konnten durch die
  prozessweiten POSIX-Sperren weiterhin gegenseitig entsperrt werden. Jeder
  oeffentliche Aufruf fuehrt die gesamte Kopie jetzt in einem eigenen Prozess
  aus; der Aufrufer oeffnet keine Quelldatei. Private Worker-Funktionen sind
  keine gleichwertige oeffentliche In-Process-Schnittstelle.

Die acht bisherigen internen I/O-Fehlerinjektionen pruefen nach diesem
Architekturschnitt die Workerfunktion direkt. Ihre Sperr-/Kollisionsassertionen
und echten Testwriter bleiben erhalten; normale Erfolgs-/Ablehnungsfaelle
laufen ueber die oeffentliche Prozessschnittstelle. Zusaetzliche unabhaengige
Proben testen explizit die Aufrufer- und Parallelworker-Isolation. Ein
Kollisionsbeobachter oeffnet nicht mehr selbst die gerade gesperrte Kopie im
selben Prozess, sondern kontrolliert dort nur noch die Groesse; die byte- und
tabellengenaue Validierung ist separat erhalten.

Ein weiterer Fehlerfall stellt sicher, dass
eine fehlgeschlagene Zwischenkopie-Bereinigung keinen privaten Traceback oder
scheinbaren Erfolg erzeugt. Ein erster neuer Journaltest erwartete faelschlich
einen warnfreien Preisabruf; er prueft jetzt die konkreten gespeicherten Werte
und die unveraendert wiederhergestellten vorhandenen Warnungen.

## Lokale Originalnachweise

| Pruefung | Nachweis / Umfang |
| --- | --- |
| Finaler gemeinsamer Backend-/Vertragslauf | 300 bestanden, eine vorhandene Starlette-Warnung; `var/issue53-final-tests-20261115.xml` |
| Unveraenderte Referenzproben nach allen Helperkorrekturen | 52 bestanden, eine vorhandene Starlette-Warnung; `var/issue53-final-reference-results-20261115.xml` |
| Clone-/CLI-/Protokollprobe als enger separater Lauf | 58 bestanden, einschliesslich der 46 urspruenglichen neuen Clone-Proben; `var/issue53-independent-clone-tests-20261115.xml`; Teilmenge der 300 |
| Neue unabhaengige Prozess-/Sperrproben | 15 bestanden, kein Skip/Xfail; `var/issue53-process-isolation-tests-20261115.xml`; zusaetzlich zu den 300 |
| Guard-/Legacy-FX-Vorlauf | 91 bestanden, eine vorhandene Starlette-Warnung |
| Wrapper/Modul und Journal-Erhalt | Echte lokale CLI-/API-Proben mit synthetischen Daten, keine Providerverbindung |
| Ruff | bestanden fuer `src tests scripts` |
| OpenAPI / Endpunktreferenz | beide Generatoren mit `--check` aktuell; keine neue Web-API |
| Modulbedienung | `python -m steuerreport_v2.db.offline_snapshot --help` erfolgreich |
| Bestehende Python-/Docker-Layer-Unitproben | 4 bestanden; keine lokale Dockerausfuehrung behauptet |
| Referenzbaseline | unveraendert: `09f674b350a9a83943df8980bbceafd88821ee1400e03b5b22ea1ee0f8cd6bfb` |

Original-JUnit-Dateien liegen lokal im ignorierten `var/`. Ihre SHA256:

```text
941d2eea54608dd879dd9586c5476719a29ffe956b38a9a7b74279c041d0699b  issue53-final-tests-20261115.xml
eacbfedc41729e8e290d52c7ec658dedbc32bae1c7ba9b849864c11594ff8c76  issue53-final-reference-results-20261115.xml
ef875bdb9968c0e8fb9de423eafaa255865435e7b964ad93a781a41e007ac197  issue53-independent-clone-tests-20261115.xml
67e42692f2be517a995e31b018e3d272b3b652db80b789e3f2ef1a4aa9169f64  issue53-process-isolation-tests-20261115.xml
```

Die letzten drei Reviewgegenfaelle bestanden beim separaten Autor zweimal;
speicherinterne Negativkontrollen liessen sie gegen die jeweiligen frueheren
Fehler erwartungsgemaess scheitern. Der gepruefte Helper hat SHA256
`d0ffa3279b32f1a9af93e165f5df354d3b93840aea80dd42237fd2e5a82b6b42`.
Bei der Uebernahme wurde nur der private Koordinatorpfad-/Umgebungsfallback
entfernt: Tests muessen immer den Helper ihres aktuellen Repositorys pruefen.
Das abschliessende separate Review meldete keine weiteren kritischen Findings
im beschriebenen Scope und wiederholte 73 Clone-/Isolationsproben erfolgreich;
dies sind ueberlappende Teilproben, keine zusaetzlichen 73 Faelle zur Gesamtzahl.

Neue Unit-Tests laufen ohne Sonderfreigabe im vorhandenen CI-Backendjob; dessen
JUnit-Artefakt wurde in #58 verpflichtend hinzugefuegt. Die unabhaengigen
Originalproben bleiben ein eigener Pflichtjob. Lokale Testergebnisse sind keine
Behauptung eines bereits abgeschlossenen Remote-Laufs fuer diesen neuen Branch.
Der bestehende isolierte Docker-Layerjob prueft neu den Modulaufruf `--help`
in beiden Testimages und archiviert die Ausgabe. Das prueft die Verfuegbarkeit
im gebauten Paket, nicht einen vollstaendigen Container-/Volumesicherungsweg.

Reproduzieren mit bestehender Projektvenv und DuckDB 1.5.2:

```bash
PYTHONPATH=src python -m pytest -q tests/unit/test_current_backfill_partial.py tests/unit/test_external_backfill_partial.py tests/unit/test_legacy_fx_backfill_safety.py tests/unit/test_as_of_price_gate.py tests/unit/test_backfill_legacy_callers.py tests/unit/test_tax_filing_archive_binding.py tests/unit/test_tax_filing_snapshots.py tests/unit/test_tax_filing_audit.py tests/unit/test_read_snapshot.py tests/unit/test_openapi_contract.py tests/unit/test_api_endpoint_reference_generator.py tests/unit/test_legacy_duckdb_fail_closed.py tests/unit/test_offline_duckdb_clone_cli.py tests/unit/test_offline_duckdb_snapshot.py --junitxml=var/issue53-final-tests-20261115.xml
PYTHONPATH=src python -m pytest -q tests/unit/test_offline_duckdb_clone_cli.py tests/unit/test_offline_duckdb_snapshot.py --junitxml=var/issue53-independent-clone-tests-20261115.xml
PYTHONPATH=src python -m pytest -q tests/unit/test_offline_clone_process_isolation.py --junitxml=var/issue53-process-isolation-tests-20261115.xml
PYTHONPATH=src python scripts/check_reference_baseline_v2.py
PYTHONPATH=src python -m pytest -q docs/audit/2026-10-28/acceptance_tests.py --junitxml=var/issue53-final-reference-results-20261115.xml
ruff check src tests scripts
PYTHONPATH=src python scripts/export_openapi_v2.py --check
PYTHONPATH=src python scripts/generate_api_endpoint_reference_v2.py --check
```

## Aktualisierte Abgrenzungs-/Blockermatrix

| Punkt | Implementiert und technisch geprueft | Bleibt offen |
| --- | --- | --- |
| #53 Legacy-Autorestore | Zwei CLI-Pfade gesperrt, Konflikt mit Preis-Guards integriert | Wiederfreigabe eines sicheren Stage-/Live-Imports und andere Legacy-Dateikopierer |
| Offline-Datenbankrestore | Bytegleiche Kopie und hashgebundener Restore in neue Datei, reale Locks und Fehlerproben | Kein Vollvolume-/Vault-/Dateibelegrestore oder existierendes Live-Ziel |
| #49 | Journal-/Preis-/Replay-Erhalt in der neuen DB-Probe | Atomaritaet, Wiederanlauf, neue Request-IDs und Retention |
| #52 | Vorheriger gebundener Aggregatvertrag unveraendert | Vollstaendige Ereignis-/Lot-/Tax-Line-Paritaet und Eingabeaktualitaet |
| Paket A / G25 | Enger neuer Offline-DB-Teilschritt | Aktuelles Image, vollstaendiges Volume, Kaltstart, Rueckweg und echte Legacy-Paritaet |
| Pakete B/C, G01-G24 | Urspruengliche 52 Referenzproben erneut bestanden | Bestehende Bewertungs-/Methoden-/Beleggrenzen unveraendert |
| Pakete D/E | Keine Import-/Reportlogik umgangen | Gesamtvollstaendigkeit und alle fachlichen Berichtszahlen |
| Paket F | Unabhaengige Sollproben und separates lesendes Review | Keine fachliche Gesamtfreigabe |

Keine neuen Datenbank-/API-Schemas oder Methoden aktiviert. Keine Tags,
Releaseversionen, produktiven Datenbanken, Container oder NAS-Sicherungen
veraendert. Kein neuer Docker-Build oder mehrgigabyte-grosser Quelldatenklon.
Der Graph wurde nur zur Eingrenzung des alten CLI-Aufrufers herangezogen;
neue Funktionen sind damit nicht vollstaendig graphbasiert abgenommen.

Der unveraenderte Vorgaenger #58 ist getrennt remote geprueft:
[CI 43719384501](https://github.com/zonfacter/steuerreport-v2-plan/actions/runs/43719384501)
bestand mit fuenf Jobs. Heruntergeladene Originalartefakte weisen 3.248
Backend-Testfaelle aus (0 Fehler/Failures, 4 Skips), 52 Originalreferenzen
und 359 Zusatzreferenzen ohne Skips. Die neuen Tests dieses Nachweises sind
darin noch nicht enthalten. `backend-unit-results`, `mandatory-reference-results`,
`ux-browser-evidence` und `docker-layer-proof` sind dort vorhanden. Vier
Backend-Skips sind keine getesteten Erfolgsfaelle.

Diese vier Skips benoetigen bewusst nicht oeffentliche Originalbelege:
`test_review_decision_suggestions_include_verified_iot_evidence`,
`test_review_tasks_link_solscan_evidence_trace` und
`test_review_decision_suggestion_acceptance_is_idempotent` benoetigen private
Solscan-/Blockpit-/RPC-Belege; `test_import_policy_classifies_known_usertransfer_tree`
benoetigt Opt-in und den privaten Importbaum. Diese realen Belegpfade sind durch
den oeffentlichen CI-Lauf nicht abgenommen. Sie wurden nicht zum Gruenmachen
mit erfundenen oder privaten Repo-Fixtures ersetzt.
