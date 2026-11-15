# Issue 49: Integration und Pruefnachweise

Entwicklungsstand vom 15.11.2026, aufbauend auf Draft #60,
`7397c63fd32750b42003189f12937a3252656223`. Kein Release, keine Main-
Integration, keine produktive Neuberechnung, Methodenaktivierung oder
Containerumschaltung. Alle hier neuen Daten sind synthetisch. Der konkrete
Commit ist im zugehoerigen Draft-PR angegeben; Diffbasis ist der obige Hash.

## Ergebnis und Grenzen

| Gegenstand | Implementiert | Nachweis / Grenze |
| --- | --- | --- |
| Preiszeilen und dauerhafter Speicherbeleg | Ja, eine DuckDB-Transaktion mit CAS | Native synthetische Fehler-/Abbruchproben, kein atomarer Rollback der gesamten Pipeline |
| Pipelinephasen | Startabsicht vor Aufruf, validiertes Finaljournal | `running_or_interrupted` ist weder Lebenszeichen noch sicherer Call-Eintritt |
| Gleiches Apply erneut / parallel | Persistente Reservierung vor Providerzugriff, getrennte Typnamensraeume | Getestet fuer gleiche Kennung; neue Kennung ist bewusst neuer Auftrag, keine globale Deduplizierung |
| Historische Direktabrufe | Eigene optionale UUID, eigene Statusroute | Keine Vermischung mit moderner historischer Sammlung / Plan / Vorschau / Apply |
| Ergebnis lesen | Bestehende Current- und neue Historical-Statusroute | Kein Provider-/Pipelineaufruf; kalte Stores koennen bestehende Schemainitialisierung ausfuehren |
| UI | Ein gemeinsames Panel, getrennte Sessionkeys, Abbruch veralteter Antworten | Genau eine UUID je Typ; kein Wiederanlaufautomat und kein unbegrenzter Finanzdatencache |
| Alte Journale | Ergebnisbytes / Reservierungen bleiben erhalten | Ohne Checkpoint kein nachtraeglicher Speichernachweis; implizite Altauftraege ohne UUID nicht per UUID-UI aufloesbar |
| Fachliche Freigabe | Unveraendert | Weder gespeicherte IDs noch Pipelineerfolg erteilen eine neue Jahresfreigabe |
| Restore | Gegenproben mit isolierter nativer Datenbankkopie | Kein aktueller produktiver oder neuer lokaler Docker-Restorelauf fuer diesen Aenderungsstand |

Die Tabelle `current_price_backfill_requests` bleibt erhalten, mit additiven
Spalten `operation_kind` und `checkpoint_json`. Schemahauptversion bleibt 3.
Dies ist keine In-Place-Downgradezusage. Vor produktiver Migration bleiben
Sicherung, Wiederherstellung und freigegebener Updateauftrag erforderlich.

## Anforderung, Dateien, Validierung

| Anforderung | Dateien | Validierung |
| --- | --- | --- |
| Speichertransaktion, CAS und Phasen | `db/duckdb_store.py`, `contracts/prices.py` | 56 unabhaengige Gegenproben, Store- und Domain-Tests |
| Kein falscher Rollback-/Erfolgshinweis | `domain/external_price_backfill.py`, `api/app.py` | Abbruch vor/nach Speicherung, Commit-Ack-Verlust, Marker-/Pipeline-/Journalfehler |
| Lesender Status mit Typ-/Integritaetspruefung | dieselben Domain-/API-Dateien | Corrupt JSON, doppelte Keys, falscher Typ, IDs, SHA, Datum und widerspruechliche Phasen |
| UI fuer Current und historischen Direktabruf | `frontend/src/workspace/CurrentPriceRequestStatus.tsx`, `frontend/src/main.tsx` | 552 kontrollierte Browserfaelle, zusaetzlich echter isolierter Backendpfad |
| Verbindliche unabhaengige Proben | `.github/workflows/ci.yml`, `scripts/check_reference_baseline_v2.py` | Originalprobe und beide neuen Dateien sind hashgebunden; normale Backend-Suite prueft neue Proben ebenfalls |
| API-Dokumentation / Softwarepaket | OpenAPI, Endpunktreferenz, `scripts/build_software_release_v2.py` | Drift-Checks, Paket-Whitelisttests |

Pfade unter `db`, `contracts`, `domain` und `api` beziehen sich auf
`src/steuerreport_v2/`. Fachberechnung, Rundung und Preisqualitaetsregeln sind
nicht Gegenstand dieses Teilfixes.

## Unabhaengige Rot-/Gruennachweise

- Basis `7397c63`: neue unveraenderte 56 Gegenproben lieferten **49 Fehler,
  7 bestanden**, keine Skips. Nicht alle Fehler sind Produktgegenbeispiele:
  34 pruefen zuvor fehlende Vertragsfunktionen, 11 explizite bestehende
  Gegenbeispiele, 4 weitere Rebind-/Replay-/Restoreluecken.
  Original-JUnit: `before.xml`, SHA256
  `105f645bd8c0ae8d0c511a25f669ac92736777341844c13baec0493fe7ff6447`.
- Die zusaetzliche unabhaengige Quellpruefung fand einen Readerwiderspruch:
  `failed` / `not_started` akzeptierte zugleich ein eingebettetes
  Pipelineergebnis. **4 Fehler / 8 bestanden** vor der Korrektur, danach
  **12 bestanden**. Assertions unveraendert; lediglich der absolute lokale
  Importbootstrap wurde beim Einordnen ins Repository entfernt.
- Sechs zusaetzliche Store-Gegenbeispiele wurden rot reproduziert und der
  Writer entsprechend gehaertet; die zehn Storefaelle bestanden danach.
- UI-Haertung des letzten Folgeschritts: **24 neue Fehler bei 368
  Gegenproben**, danach **552/552** im vollstaendigen kontrollierten Lauf.
  Dies sind Browserfixtures, nicht 552 echte Backendlaeufe.
- Abschliessende begrenzte, rein lesende Store-/API-/Domainpruefung fand
  keine neuen konkreten Befunde. UI und Mehrprozessgarantien waren nicht
  Teil dieser unabhaengigen Quellpruefung. Keine Gesamtfreigabe daraus.

Hashgebundene Pflichtproben (nicht zum Gruenmachen angepasst):

| Datei | SHA256 |
| --- | --- |
| `docs/audit/2026-10-28/acceptance_tests.py` | `09f674b350a9a83943df8980bbceafd88821ee1400e03b5b22ea1ee0f8cd6bfb` |
| `tests/unit/test_price_backfill_checkpoint_acceptance.py` | `68beedb2b00d9b87c55b03f0c6da8a89c87a8e78529467fb34562072dc2b5f48` |
| `tests/unit/test_price_backfill_checkpoint_review.py` | `db10e6259ba1953792a66eb7a8396ccc4841810bf0818264b2dd6fd8670ac337` |

## Ausgefuehrte Abschlusspruefungen

Die folgenden Abschlusslaeufe sind beendet. Lokal bestanden ist nicht
gleichbedeutend mit erfolgreicher GitHub-CI, Integration oder Fachabnahme.

| Befehl (Repositoryroot, sofern nicht anders genannt) | Ergebnis |
| --- | --- |
| `pytest tests/unit -n 4 --dist loadfile -q` | 3.967 erfasste Faelle: 3.963 bestanden, 4 bestehende Skips, 0 Fehler / Errors, 781,73 s; vier Starlette-Abkuendigungswarnungen |
| `pytest docs/audit/2026-10-28/acceptance_tests.py -q` | 52 bestanden, 0 Skips / Fehler, eine Starlette-Abkuendigungswarnung |
| `pytest tests/acceptance -q` | 359 bestanden, 0 Skips / Fehler, Source-Freeze-Teardown erfolgreich; eine Starlette-Abkuendigungswarnung |
| `pytest tests/unit/test_price_backfill_checkpoint_acceptance.py tests/unit/test_price_backfill_checkpoint_review.py -q` | 68 bestanden, 0 Skips / Fehler; eine Starlette-Abkuendigungswarnung; diese 68 sind auch Teil der Backend-Suite, nicht zusaetzliche eindeutige Backendfaelle |
| `python docs/audit/2026-10-28/issues/issue2-original.py --expected-version 0.2.0rc40` | 15/15 bestanden, 0 Fehler; unveraenderter oeffentlicher Bitget-Repro |
| `python scripts/check_current_price_status_browser_v2.py --node-modules <vorhandene Module> --output <neues /tmp-Verzeichnis>` | 552 bestanden; 390 / 768 / 1280 / 1440 px; keine Provider-/Pipeline-/unerwarteten Requests |
| `python scripts/check_price_checkpoint_backend_browser_v2.py --node-modules <vorhandene Module> --output <neues /tmp-Verzeichnis>` | 64 bestanden; echte unveraenderte FastAPI-TestClient-Antwortbytes, echte eigene DuckDB, beide Typen / 8 Zustaende / 4 Breiten; DB-Fingerprint unveraendert, 0 Provider-/Pipeline-/Apply-/Store-Schreib-/Netzwerkaufrufe nach Seed |
| `npm run build` in `frontend` | Erfolgreich; bestehende Warnung zu grossem Hauptchunk |
| `node tests/run-dashboard-tests.mjs` in `frontend` | 10 bestanden; SSR-`useLayoutEffect`-Warnungen |
| `node --test tests/dashboard-navigation.browser.mjs` in `frontend` | 1 bestanden mit vorhandener neuerer Playwright-Node-Laufzeit und gesetzten lokalen Browserpfaden |
| `node scripts/check_workspace_state_v2.cjs` (UTC und `TZ=Europe/Berlin`) | Beide erfolgreich |
| `ruff check src tests scripts` | Erfolgreich |
| `python scripts/export_openapi_v2.py --check` | Erfolgreich |
| `python scripts/generate_api_endpoint_reference_v2.py --check` | Erfolgreich |
| `python scripts/check_reference_baseline_v2.py` | Alle drei SHA256-Bindungen bestaetigt |
| `python scripts/check_private_data_v2.py` | 0 private Kontovorgaben gefunden; kein Ersatz fuer universellen Secret-Scan |
| Workflow-YAML strukturell lesen | 5 Jobs; alle Schritte haben `run` oder `uses` |
| `git diff --cached --check` | Erfolgreich |

Die vier bestehenden Skips: drei Reviewfaelle benoetigen private Solscan-/
Blockpit-/RPC-Belege, ein Import-Coverage-Fall explizites Opt-in und einen
privaten Originalimportbaum. Diese Nachweise wurden weder beschafft noch
ersetzt und zaehlen nicht als abgenommen. Die neuen Checkpointproben haben
keine Skips.

Tatsaechliche Pytest-Aufrufe (jeweils vorangestellt
`env PYTHONPATH=src STEUERREPORT_TEST_PRUNE_PASSED_DBS=1` und mit dem
vorhandenen Interpreter `/tmp/steuerreport-issue39-ci-venv-20261102/bin/python`):

```bash
python -m pytest tests/unit -n 4 --dist loadfile -q \
  --basetemp=/tmp/steuerreport-issue49-final-unit-20261115 \
  --junitxml=var/issue49-final-unit.xml
python -m pytest docs/audit/2026-10-28/acceptance_tests.py -q \
  --basetemp=/tmp/steuerreport-issue49-final-reference-original-20261115 \
  --junitxml=var/issue49-final-reference-original.xml
python -m pytest tests/acceptance -q \
  --basetemp=/tmp/steuerreport-issue49-final-reference-additional-20261115 \
  --junitxml=var/issue49-final-reference-additional.xml
python -m pytest tests/unit/test_price_backfill_checkpoint_acceptance.py \
  tests/unit/test_price_backfill_checkpoint_review.py -q \
  --basetemp=/tmp/steuerreport-issue49-final-checkpoint-reference-20261115 \
  --junitxml=var/issue49-final-checkpoint-reference.xml
```

Der Backend-Browsernachweis verbindet den isoliert gebauten echten React-
Statusbaustein mit TestClient; er startet keinen HTTP-Server und ersetzt
keine komplette Installations-/Gesamtseitenpruefung. Vier Screenshots
zeigen Current und Historical bei 390 bzw. 1440 px; sie wurden auch visuell
geprueft. Der kontrollierte 552er-Lauf deckt weitere Fehlantworten, Race-
Conditions und Validierungsgegenproben ab. Die beiden Zahlen duerfen nicht
zu 616 echten Backendlaeufen umgedeutet werden.

| Lokales Originalartefakt | SHA256 |
| --- | --- |
| `var/issue49-final-unit.xml` | `980bf9ad919c434976698d0dec64d7fc0a21d5e5aa316043cc1ae7edd1db6c73` |
| `var/issue49-final-reference-original.xml` | `e895970f47e93dbd87bb5ef2e18fd2406a1604100e8917802e6e2eef22f2c150` |
| `var/issue49-final-reference-additional.xml` | `74de50e79dc6d843ec7319f7a739ab65d4765696afdd9aaba2673bfc81201572` |
| `var/issue49-final-checkpoint-reference.xml` | `5d0cdff002e60b885c12f654f316734a6c49b99dfe33f563c25dde63ccc5fd2c` |
| `var/issue49-final-bitget-original.json` | `1d375f5266a4932e80ec2fdd703ea739b6f0d32102950d84927a5b2e5c70db39` |
| `/tmp/steuerreport-issue49-final-ui-20261115/summary.json` | `f61fabcb3a3e69b8938bb91038db8bba51e7c4049d1aa73b642c0be423d609b4` |
| `/tmp/steuerreport-issue49-final-backend-browser-20261115/summary.json` | `0a51225a577cc425b27583a2274ed62e9d04a31517a518f827eb8f9493b0ae7d` |

Backendbrowser-Quellenbindung:
`23c744198f93883dc217e6a61ef9ab049716252e6d6e7d0cc3d73d78696cf7e0`.
Der JSON-Nachweis enthaelt die Einzelhashes aller zehn gebundenen Dateien;
diese werden nach dem Lauf erneut geprueft. Die Dateien werden lokal
erhalten; der Draft-CI-Lauf erzeugt eigene zeitabhaengige Originalartefakte
unter `backend-unit-results`, `mandatory-reference-results` und
`ux-browser-evidence`. Lokal gemessene SHA-Werte gelten nicht fuer diese
erst noch zu pruefenden CI-Wiederholungen.

Testumgebung: vorhandenes Python-3.11-Venv, vorhandene Node-Module und
Playwright/Chromium; keine neuen Venvs oder npm-Installationen. Kein dauerhaft
gestarteter Entwicklungsserver. `PYTHONPATH=src` und
`STEUERREPORT_TEST_PRUNE_PASSED_DBS=1` bei den Pytest-Laeufen;
`--basetemp` und JUnit-Ausgaben getrennt unter `/tmp` bzw. ignoriertem `var/`.
Das ist keine pauschale Zusage, dass jede private Testfixture die
Prune-Umgebungsvariable erhaelt oder alle Dateireste entfernt.

Bekannte ungueltige / wiederholte Testaufrufe werden nicht verschwiegen:

- Ein frueherer erweiterter Referenzlauf hatte 359 bestandene Testfaelle,
  aber einen Source-Freeze-Teardownfehler, weil der Koordinator waehrenddessen
  den Paketbuilder erweiterte. **Kein gueltiger gruener Nachweis.** Der
  Abschlusslauf erfolgt nach Integration / Staging der Runtimequellen.
- Der erste lokale Dashboard-Browseraufruf hatte keine Browserpfade; der
  zweite verwendete Node 18, das die vorhandene Playwright-Version nicht
  unterstuetzt. Mit deren bereits vorhandener neuerer Node-Laufzeit bestand
  der unveraenderte Test. Keine Produktkorrektur dafuer vorgenommen.
- Workflow-YAML war im Test-Venv mangels PyYAML nicht lesbar; mit dem
  bestehenden System-Python erfolgreich. Keine Zusatzinstallation.

## Offene Aufgaben

- #49 bleibt offen bis zur Integration und zum passenden Gesamtumfang:
  kein automatischer Wiederanlauf nach Prozessabbruch, keine nachtraegliche
  UUID fuer implizite Altauftraege, keine globale Write-Path-Deduplizierung,
  keine Aufbewahrungs-/Mehrhostgarantie. Ein Ergebnis-Panel ist kein
  vollstaendiger Jobmanager.
- Same-Store-Gate im bestehenden Einprozessbetrieb, keine neue koordinierte
  Mehrprozessarchitektur. Lesende Statusabfragen koennen hinter einer langen
  Pipeline auf den Store warten.
- #44 / #46: Bewertungsqualitaet, Herkunft und Quellenregeln bleiben eigene
  Aufgaben; dieser Commit macht aus unbekannten Preisen keine gueltigen.
  Die anschliessende begrenzte Quellinventur bestaetigt insbesondere:
  V1-Cacheuebernahme ist konservativ blockiert, aber der V1-spezifische
  unveraenderliche Snapshot-/WAL-/Planhashvertrag fehlt noch. Der bestehende
  As-of-Backfill setzt Tagesreferenzen weiterhin auf Mitternacht, und eine
  bestehende As-of-Probe erwartet danach `strict_ready=True`. Dieses gruene
  Testergebnis ist **kein** Nachweis des fehlenden Intraday-Belegs. Als
  naechstes sind unabhaengige Gegenproben fuer 01:00 UTC sowie explizite
  Beobachtungs-/Tagesperioden-/Veroeffentlichungszeiten erforderlich;
  bestehende Tests duerfen nicht als steuerliches Sollorakel dienen.
- #11 / #53: Die in Draft #60 nachgewiesene synthetische CI-Vollrestoreprobe
  ist nicht der echte Betreiberrestore und nicht der Nachweis neuer
  Checkpointzeilen im Docker-Restore dieses Commits.
- #19 / #20 / #52: Produktive Legacy-Zuordnung und vollstaendiger semantischer
  Ereignis-/Lot-/Steuerzeilenvergleich bleiben getrennt offen.
- Keine fachliche Abnahme G01-G25 oder allgemeine Migrationsfreigabe aus
  diesen technischen Preisauftragsproben. Bereits bestehende Matrizen und
  Grenzen werden nicht durch neue Testzahlen geschlossen.

## Bedienung und Vertraege

Siehe [Preisauftraege ohne KI pruefen](../ISSUE_49_AKTUELLE_PORTFOLIOPREISE.md),
[Checkpointvertrag](ISSUE49_CHECKPOINT_VERTRAG_2026-11-15.md) und
[historische Sammlung](../HISTORISCHE_EUR_PREISE.md).

Auftragskennungen stehen ausschliesslich im POST-Body bzw. in je einem
Sessionfeld, nicht in URL-Parametern. Die neue historische Direktstatusroute
ist `/api/v1/prices/backfill/external/status`; die bestehende Current-Route
bleibt erhalten. Checkpoint-SHA256 bindet gespeicherte JSON-Bytes, nicht die
Browser-Neukodierung. IDs beweisen damalige Speicherung, nicht heutigen
Bestand, aktuelle Preisqualitaet oder abgegebene Steuererklaerungen.
