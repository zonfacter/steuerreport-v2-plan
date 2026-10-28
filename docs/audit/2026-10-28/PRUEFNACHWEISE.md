# Integrierte Pruefnachweise

28.10.2026. Codefreeze `b036b8ad4212d08d719fedec7dbc7115cf5704a9`.
Nach diesem Freeze nur Dokumentations-/Nachweisdateien geaendert.
**Keine volle fachliche Abnahme: G04 bleibt ein echter Fehler.**

## Ergebnisse

| Pruefung | Tatsaechliches Ergebnis |
| --- | --- |
| Gesamte `tests/unit` |2464passed,4skipped,0failed,520.66s;8getrennte Testworker/DBs |
| Unabhaengige52Teilproben gegen Freeze |51passed,1failed,0skip/xfail,135.51s; unveraenderter Testcode und feste Sollwerte |
| Dieselben52Teilproben im finalen Dockerimage |51passed,1failed,0skip/xfail,83.70s; installierter Imagecode und dessen Laufzeitabhaengigkeiten |
| Einziger roter52er-Fall |G04: DrittassetgebuehrBNB0.1 mindert den BNB-Lotbestand noch nicht von1auf0.9 |
| Gezielt Import/Readiness/Registry |35passed vor finalem Gesamtlauf; vollstaendig im Gesamtlauf enthalten |
| Ops-Hash-/Ownership-/Fehlerguards |7unittest-Tests bestanden, eigener synthetischer Root |
| Ruff `src tests scripts` | bestanden |
| TypeScript/Vite | bestanden; bekannte Warnung Application-Chunk ueber500kB |
| OpenAPI / API-Referenz / Importformate / KI-Leitfaden `--check` | bestanden |
| Router-/Praezisions-State-Checks | Node bestanden mit Standard-TZ und Europe/Berlin |
| PDF-Leitfaeden |16/10/9Seiten, dev0-Kennung geprueft, jeweils unter100 |
| Readiness-Browser |100Screenshots,344kontrollierteGETs,0extern,0Seitenfehler,390/768/1280/1440 |
| Gesamter bestehender UX-Smoke | Hilfe, Einrichtung, KI-Konsens, Importvorschau und WorkspaceA01-A23/R1 bestanden; keine echten API-/Modellaufrufe |
| Alle7zusaetzlichenCI-Browserprogramme |7von7mitExit0, genaue Bereiche unten |
| Leerer finaler Container | offline/read-only, Schema1,0Events,Health200,keinV1 |
| Finales Restore/Neustart | alle Tabellen/Dateien/Keys/Token/Profil erhalten; Produktion unveraendert |

Die8Worker sind ausschliesslich Testprozesse mit eigenen synthetischen DBs.
Die produktive Einprozess-/DuckDB-Architektur wurde nicht erweitert.
Der gruene Unit-Lauf ersetzt die separat rote fachliche Teilprobe nicht.
Ein erster Integrationslauf hatte9Fehler/2434Pass/4Skips; Ursachen und
belegte Korrekturen stehen in BEFUNDE.md. Er wird nicht als Endabnahme genutzt.

## Vier Skips Und Warnungen

Keine neuen Skips oder xfails zur Fehlerkaschierung:

- `test_review_decision_suggestions_include_verified_iot_evidence`
- `test_review_tasks_link_solscan_evidence_trace`
- `test_review_decision_suggestion_acceptance_is_idempotent`
- `test_import_policy_classifies_known_usertransfer_tree`

Die ersten drei brauchen private Solscan-/Blockpit-/RPC-Dateien; die letzte
braucht ausdrueckliches Opt-in und einen privaten Usertransfer-Belegbaum.
Diese privaten End-to-End-Nachweise sind nicht durch synthetische Daten ersetzt.
Der Gesamtlauf meldet8Importlib-DeprecationWarnings; im Container-52er-Lauf
zusätzlich eine Starlette-TestClient/httpx-DeprecationWarning. Kein dafuer
veraendertes Dependencylock und keine behauptete kuenftige Kompatibilitaet.

## Browserprogramme

Alle aus dem Auditcheckout, vorhandenes Chromium, `frontend/dist` aus dem
erfolgreichen Build. Isolierte temporaere Server, synthetische Daten und
kontrollierte Providergrenzen; keine produktive URL als Testbasis.

| Programm | Nachweisroot unter `/tmp/` | Ergebnis |
| --- | --- | --- |
| `check_ux_browser_v2.py` | `steuerreport-migration-final-full-ux` | bestanden; bestehende Workspace-/Review-Rueckwege und Routing |
| `check_migration_readiness_browser_v2.py` | `steuerreport-migration-final-browser` | bestanden; Laden/Fehler/unbound/stale/current/final in Steuerjahr und Export |
| `check_review_backend_browser_v2.py` | `steuerreport-migration-ci-check_review_backend_browser_v2` | F1/F2/F3 bestanden gegen echte isolierte API; Imports nur in Wegwerfdaten |
| `check_wallet_setup_browser_v2.py` | `steuerreport-migration-ci-check_wallet_setup_browser_v2` | geschuetztes Setup, public address, Signatur und unbekannte EUR-Werte bestanden |
| `check_history_import_browser_v2.py` | `steuerreport-migration-ci-check_history_import_browser_v2` |13kontrollierte Workflow-Szenarien bestanden |
| `check_history_backend_browser_v2.py` | `steuerreport-migration-ci-check_history_backend_browser_v2` | echte API; erst ausdrueckliche Freigabe importiert exakt Transfer+Gebuehr aufA;Bunveraendert |
| `check_history_provider_eta_browser_v2.py` | `steuerreport-migration-ci-check_history_provider_eta_browser_v2` |16Szenarien einschliesslich Quellwechsel, Wartezeit, veralteter Antworten bestanden |
| `check_solana_limits_browser_v2.py` | `steuerreport-migration-ci-check_solana_limits_browser_v2` |17Faelle/35Screenshots bestanden, isolierter Koordinator |
| `check_historical_prices_browser_v2.py` | `steuerreport-migration-ci-check_historical_prices_browser_v2` | echter Preisrouter/MockTransport;12Screenshots,3Jahre, begrenztes Sammeln und ausdrueckliche Uebernahme bestanden |

Screenshots enthalten ausschliesslich synthetische Identitaeten. Reale
Providerabdeckung, persoenliche Freigabe und vollstaendige WCAG-/Screenreader-
Konformitaet sind daraus nicht abzuleiten. Beispielansichten wurden auch
visuell geprueft. Die laufenden Testserver und eigenen Restorevolumes wurden
anschliessend beendet beziehungsweise entfernt.

## Reproduktionsbefehle

Auf diesem Host waren die bestehenden lokalen Python-Abhaengigkeitspfade
notwendig. Keine private Konfiguration laden; private Belege sind fuer diese
synthetischen Laeufe absichtlich nicht eingebunden.

```sh
env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory \
 GIT_CONFIG_VALUE_0=/tmp/steuerreport-migration-20261028-coordinator \
 PYTHONPATH=src:/tmp/steuerreport-connector-tools-20261026:/tmp/steuerreport-release-tools-20261025 \
 STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 \
 python3 -m pytest tests/unit -q -n8 --dist loadfile \
 --basetemp=/tmp/steuerreport-migration-final-unit \
 --junitxml=/tmp/steuerreport-migration-final-unit.xml --tb=short
```

Unabhaengiger52er-Befehl und weiterer Kontext in ABNAHME_G01_G25.md. Im
Docker-52er-Lauf wurde nur pytest8.4.2 mit seinen Testhilfen read-only unter
`/test-tools` eingebunden, nicht der Host-Backend-Abhaengigkeitsbaum.
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, `PYTHONPATH=/test-tools` und
`-o pythonpath=` verhindern einen ungewollten Host-/`/audit/src`-Backendimport.
Das Produkt kam aus `/usr/local/lib/python3.11/site-packages/steuerreport_v2`
des getesteten Image, siehe candidate-manifest.json. Software/Quellcheckout
read-only, Netzwerk none, saemtliche DBs in neuem `/tmp`-tmpfs; kein Datenvolume.
Ein erster Testwerkzeugstart brach wegen fehlendem pytest-Hilfsmodul `py` ab;
nach lokalem Einbinden lief der echte52er-Fall. Das war kein Produktfehler.

Weitere vorhandene Checks:

```sh
python3 -m ruff check src tests scripts
python3 scripts/export_openapi_v2.py --check
python3 scripts/generate_api_endpoint_reference_v2.py --check
python3 scripts/generate_import_format_docs_v2.py --check
python3 scripts/generate_ai_usage_guide_v2.py --check
python3 scripts/check_private_data_v2.py
node scripts/check_workspace_state_v2.cjs
TZ=Europe/Berlin node scripts/check_workspace_state_v2.cjs
```

Frontend: `npm ci --offline --ignore-scripts --no-audit --no-fund`, dann
`npm run build`. Je Browserprogramm `--output /tmp/EIGENER-ORDNER` und
`--browser-executable /root/.cache/ms-playwright/chromium-1187/chrome-linux/chrome`.
Build/Restorebefehle und exakte Imagebindung in den Betriebsnachweisen.
Keine Ausfuehrung des produktionsveraendernden Legacy-Startskripts.

## Belegbindung

| Beleg | SHA256 |
| --- | --- |
| `/tmp/steuerreport-migration-final-unit.xml` | `3b27bfb8510dfb7b4aa364ec82e5062c3349b7c658219307e1c0306cb2c67960` |
| Unabhaengig `freeze-b036b8a.xml` | `e2782bc8ae498995dcdbe05313c6d153bac0674a81cd6792f3e441bf00d0175f` |
| Unveraenderte `acceptance_tests.py` | `09f674b350a9a83943df8980bbceafd88821ee1400e03b5b22ea1ee0f8cd6bfb` |
| Readiness-Browser `report.json` | `4ed65eee583ffbfb40998d8b1330ff3166114ef8b0715ca43ac17f1a8d387880` |
| Workspace `workspace-verification.json` | `8edb58c614d4d5f1e038b024317408ab3aed4cc9a8775120d7207a57e47c706b` |
| Gesamter UX-Smoke `verification.json` | `d7e4c9d544516870371c0c950fb5098502e80c3883a47b324da4dcf205d6ce74` |
| Privater finaler Restore `restore-result.json` | `c44bfef54db1898e6ae4921458a02675049cc7568566400155f8d20321adcef1` |

Private Volltabellen-/Dateihashes verbleiben im geschuetzten Evidenceordner.
Keine privaten Datenbanken, Konto-/Walletwerte, Keys oder Anbieterantworten
in diesem oeffentlich geeigneten Quellcodebericht. Der lokale Codegraph wurde
ohne Embeddings aufgebaut und nach Integration inkrementell aktualisiert;
Status ok, kein steuerlicher Beleg. Seine Datenbank wird nicht veroeffentlicht.

## Kompatibilitaet Und Restarbeit

Alte dynamische PDF-Pakete ohne bestaetigte Eingangsbindung werden nicht mehr
aus beliebig neuen Daten gerendert. Neu erzeugte Vorschau verwenden; nicht
die alten Metadaten nachtraeglich freigeben. Unveraenderliche archivierte
Abgabepakete bleiben separat erhalten und hashverifiziert lesbar.

G04, nicht vollstaendige FX-/Contract-/Migrations-/Sphaerenfaelle und private
Legacyparitaet bleiben offen. Fehlende Nutzerdateien sind in VERTRAG.md
benannt. Keine Pushes, Tags, GHCR-Packages, Releases, produktiven Imports,
Methodenentscheidungen oder Containerwechsel im Rahmen dieses Audits.
