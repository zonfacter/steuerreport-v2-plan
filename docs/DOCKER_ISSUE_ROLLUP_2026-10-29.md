# Docker-Issue-Rollup 2026-10-29

## rc36-Kandidatenstand vor PR-Einreichung

Stand: 29.10.2026. Der Releasekandidat `0.2.0rc36` wurde als Tree-Diff auf
einem sauberen Branch ab `main` `eee90f24a3b7cda8a7f7bef6f8105185f632a4d1`
vorbereitet. Die Runtime-Commit-Historie mit privaten Kontodaten wurde nicht
uebernommen. Zum Zeitpunkt dieses Eintrags waren GitHub-PR, Merge, Release,
Image-Publish und Produktivupdate noch ausstehend. Das Produktivvolume blieb
unangetastet.

Verifikation auf dem sauberen Kandidatenbaum:

- Kombinierte gezielte Backendregression: **254 passed**, 1 bestehende
  DeprecationWarning, 0 failed, 481.88 s. Enthalten waren Installation,
  Ownership-Loader, Containerstart/Vault, Releasepaket, Publikationsgate,
  MEXC-API, Binance-Earn-Historie, historische Preise, Methodik und
  Jahres-PDF-Vorschau.
- `ruff check src tests scripts`: bestanden.
- OpenAPI, API-Referenz, Importformate, KI-Leitfaden und private Defaults:
  aktuell; `privacy_default_violations=0`.
- Frontend TypeScript/Vite-Produktionsbuild: bestanden. Bekannter Hinweis:
  Hauptbundle 943 kB unkomprimiert.
- Benutzer-, Import- und KI-PDF: 16 / 11 / 9 Seiten; rc36 sichtbar,
  rc35-Kennung nicht mehr vorhanden.
- Gitleaks 8.30.1, SHA256-geprueft, auf einem sauberen Quellarchiv:
  52 einzeln freigegebene synthetische/Review-Treffer, 0 ungepruefte Treffer,
  0 private Konto-Defaults. Ein Lauf im lokalen Runtime-Worktree wurde wegen
  ignorierter binaerer Build-/Cachedateien verworfen und nicht als Nachweis
  gewertet.

Der vollstaendige GitHub-CI-Lauf sowie Release-Image-Digest, Backup/Restore und
Produktiv-Smoke muessen nach PR-Erstellung bzw. vor einem Containerwechsel
separat nachgewiesen werden. Kein fachlicher Steuerabschluss wird behauptet.

## Frueherer lokaler Integrationsnachtrag (vor Release-Metadaten)

Dieser Abschnitt ist der aktuelle lokale Integrationsstand und ersetzt fuer
die unten genannten Issues die aelteren Zwischenstatus. Branch:
`codex/docker-issue-integration-20261029`; letzter Merge-Commit `aec5bce`,
aktueller HEAD `414b27e`. Es wurde nichts gepusht, veroeffentlicht oder
deployed; Live-Container, produktive Datenbanken und externe Anbieter blieben
unangetastet.

| Issue | Lokaler Stand | Nachweis und Grenze |
| --- | --- | --- |
| #4 | MEXC Spot-Import integriert (`d68d783`), Importansicht korrigiert (`414b27e`) | Referenz-/Review-/API-Tests bestanden; Gesamtregression unten. TypeScript-Fehler in der Importansicht gefunden und behoben; Build bestanden. Keine produktive MEXC-Verbindung oder steuerliche Klassifikation abgenommen. |
| #9 | Container-Publish-Workflow-Gate integriert (`d7adb16`) | Synthetischer Dateiimport bis Report, Abgabepaket und Neustart-Persistenz ist vor und nach Image-Publish in CI verdrahtet. Das Script lief lokal auf einem **separaten frischen Container** aus dem vorhandenen rc35-Image erfolgreich; der neue Integrationsbuild und GitHub Actions wurden nicht ausgefuehrt. |
| #12 | Strikte Ownership-Konfiguration integriert (`35d148b`) | Im kombinierten Lauf enthalten: ungueltige/fehlende Konfiguration und Normalisierung getrennt geprueft; keine Schreibfreigabe oder produktive Reparatur. |
| #14 | Binance-Earn in kontengebundene HistoryJobs integriert (`f60c821`) | Fake-HTTP und bestehende History-Suiten bestanden. Kein echter Binance-Aufruf; vollstaendige Anbieterabdeckung und Produktivimport bleiben offen. |
| #22 | CSV-Vorschau-Teilfix integriert (`aec5bce`) | Leere Endfelder werden toleriert, nichtleere Ueberhangfelder abgewiesen, Raw-Zeile bleibt belegt. Vier weitere im Issue genannte Bitget-Themen bleiben offen: Zeitzone, Konto/Produkt-Scope, Margin-Fee-Duplikate und Quote-Leg-Paarung. |

### Originale Testnachweise dieses Laufs

- Integrierte Issue-4/9/12/14-Regression vor #22: **436 passed, 1 bestehende
  DeprecationWarning, 0 failed, 669.56 s**. Ausgefuehrt mit
  `STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 PYTHONPATH=src:/tmp/steuerreport-connector-tools-20261026 pytest -q --basetemp=/tmp/test-issue-integration-final-20261029 tests/acceptance/test_mexc_native_reference.py tests/acceptance/test_mexc_native_review.py tests/unit/test_mexc_import_api.py tests/unit/test_binance_earn_history_jobs.py tests/unit/test_binance_earn.py tests/unit/test_history_jobs.py tests/unit/test_external_http.py tests/unit/test_history_provider_workflow.py tests/unit/test_installation_settings.py tests/unit/test_raw_normalizer.py`.
- #22 plus gemeinsame CSV-/MEXC-Regression: **242 passed, 1 bestehende
  DeprecationWarning, 0 failed, 228.56 s**. Befehl:
  `STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 PYTHONPATH=src:/tmp/steuerreport-connector-tools-20261026 pytest -q --basetemp=/tmp/test-issue22-integration-20261029 tests/unit/test_file_raw_importer.py tests/unit/test_csv_raw_importer.py tests/acceptance/test_mexc_native_reference.py`.
- `ruff check src tests scripts`, Python-Compile des Container-E2E-Scripts,
  OpenAPI-Driftcheck, API-Referenz- und Importformat-Driftchecks sowie
  `check_private_data_v2.py` bestanden (`privacy_default_violations=0`).
- Frontend: TypeScript-Pruefung und Vite-Produktionsbuild bestanden **nach**
  JSX-Korrektur. Der vorherige Typecheck hatte den Renderfehler offengelegt.
  Vite meldet weiterhin ein Hauptbundle ueber 500 kB.
- Lokaler Docker-Runtime-Nachweis: Der E2E-Ablauf wurde gegen einen separaten Container mit dem
  vorhandenen Image `steuerreport-v2:issue9-e2e-local` ausgefuehrt, Labelversion
  `0.2.0rc35`, Quellrevision `9fc6de8cd770c16575b557562b918fcaa8ed8441`,
  Image-ID `sha256:35e10a13c4909ebbf3ef8f355708c742106bb8fc4098a96b40fe606c84104221`.
  Der Test verwendete ein neues anonymes `/state`-Volume, `--network none`,
  Read-only-Root und danach entfernten wir genau diesen Testcontainer samt Volume.
  Ergebnis `passed`: 3 synthetische Canonical Events, Kaufkosten 40 EUR,
  Erlos 60 EUR, Gewinn 20 EUR, Restlot 6 TEST mit 60 EUR Basis; fehlender Preis
  und Lot blockieren den Jahresstatus. Report-Manifesthash
  `7e5c4c396aac8fcc85cd8c6a031e122aa747179eb1072711573fb40c50827b4e` und
  Snapshot-Pakethash
  `bcacaabf8abdbf5a3b869f33887306da8587db00df54ef83d565fcf82b16d641` waren
  nach Neustart unveraendert; KI-Endpunktaufrufe 0. Das belegt den rc35-
  Ausgangsimage-Pfad, nicht den neuen Integrationsbuild.
- GitHub Actions/Publish, Restore/Rollback und Browserabnahme wurden nicht
  ausgefuehrt. Tests belegen nur die oben aufgefuehrten isolierten synthetischen
  Pfade.

### Weiterhin offen

- Read-only-Abfrage der oeffentlichen Issue-Liste am 2026-10-29: offen sind
  #4, #8, #9, #10, #12-#20 und #22; keine neue Issue-ID gegenueber dem
  vorherigen Abgleich.
- #19/#20: Keine eindeutige, lesend belegte Zuordnung der nativen Laufzeit zur
  tatsaechlich verwendeten Legacy-Datenbank; damit weder konsistente Sicherung
  noch semantischer Alt-/Neu-Vergleich oder Datenparitaet bestaetigt.
- #10: Kein isolierter Docker-Kaltstart mit vorhandenem Profil/DB und fehlendem
  Vault-Key nachgewiesen.
- #13: Globaler CSV/API-Identitaetsabgleich und persistierte Matchentscheidung
  fehlen; #14 ist eine implementierte Earn-History-Erweiterung, keine
  unabhaengige Anbieter- oder Produktivabnahme.
- #15 bis #18, #8 und weitere Issues sind durch diesen Nachtrag nicht neu
  abgenommen. Die frueheren Tabellen sind historische Zwischenstaende.
- Die angeforderten Dateien unter `/tmp/blockpit-analysis` waren in dieser
  Laufumgebung nicht vorhanden; der Nachtrag erfindet daraus keine neuen
  Ergebnisse.
- Kein neues Docker-Image wurde gebaut oder ersetzt. Kein Push, Release, Issue-Update,
  produktiver Import, Rechenlauf oder Methodenwechsel.

## Archivierter Zwischenstand vor Fortschreibung

> Die folgenden Abschnitte sind als damaliger Zwischenstand erhalten. Wo sie
> den Issues #4, #9, #12, #14 oder #22 widersprechen, gilt ausschliesslich der
> aktuelle Nachtrag am Anfang dieses Dokuments.

## Stand

Lokaler Integrationszweig `codex/docker-issue-integration-20261029`, Basis
`0.2.0rc35` (`eee90f24a3b7cda8a7f7bef6f8105185f632a4d`). Die Issueslices
stehen teils in lokalen Commits und teils in einem noch ungecommitteten Slice.
Der Stand wurde weder gepusht noch veroeffentlicht oder deployed. Produktion und produktive Finanzdaten blieben
unveraendert. Es wurde keine KI oder externe Anbieterabfrage fuer die neuen
Arbeitsablaeufe benoetigt.

## Integrierte Slices

| Issue | Lokaler Commit | Umsetzung | Nachweis / verbleibende Grenze |
| --- | --- | --- | --- |
| #12 | lokaler Slice, noch nicht committet | Gemeinsamer strikter Ownership-JSON-Vertrag fuer Schreib-API und Normalizer; Auditmetadaten bleiben erhalten; fehlende Datei ist optional, kaputte Datei blockiert den Import und ist in der Einrichtung erkennbar/revisionsgebunden reparierbar | `test_installation_settings.py` und `test_raw_normalizer.py`: **96 passed**, 1 bestehende DeprecationWarning. Lint, py_compile und diff-check bestanden. Issue bleibt bis Gesamtintegration offen. |
| #10 | im Integrationszweig | Entrypoint blockiert bei vorhandenem Profil/DB und fehlendem oder ungueltigem Vault-Key vor weiteren Zustandsdatei-Schreibzugriffen und vor Uvicorn; explizite Profil-only-Erstbereitstellung | **36 Tests bestanden** fuer Startlogik und Installationseinstellungen. Noch kein Docker-Image-/Kaltstartnachweis; Issue bleibt bis zur isolierten Imagepruefung offen. |
| #13 | `66653c2` | Explizite Binance-Verbindungsbindung fuer Spot-Dateiimporte; Batch speichert die ausgewaehlte Connection-ID; fehlende Zuordnung blockiert | Integrierte Tests bestanden. Nur Spotdateien; globaler CSV/API-Identitaetsabgleich und persistierte Matchentscheidung fehlen. Issue bleibt offen. |
| #14 | `4028503` | Binance-Earn-Service kann Credentials nach Verbindung lesen; kein globaler Credential-Fallback im gebundenen Modus | Fokustests im Agentenworktree bestanden; integrierte Suite bestanden. HistoryJob-/Importpfad, Kontenscope und Pagination nicht abgeschlossen. Issue bleibt offen. |
| #15 | `ebbb4b5` | Hashgebundener manueller Belegpfad fuer EUR bzw. USD mit separatem FX-Beleg, isolierter Vorschau und ausdruecklichem Apply | Agentennachweis: 62 Tests, Build und OpenAPI. Kein eigener Browser-/Accessibility-Nachweis fuer genau diesen Ablauf; fachliche manuelle Belegpruefung bleibt erforderlich. |
| #16 | `3eb2cf7` | Ausdrueckliche Erzeugung eines BMF-Methodenpruefstands 2021-2025 mit Eingangsbindung und Konfliktbehandlung | Agentennachweis: 109 Tests und Browserprobe. Synchroner API-Aufruf statt Hintergrundjob; keine finale Freigabe. |
| #17 | `6f0e968` | Manuelle Korrekturentwuerfe behalten stabile Ziel-, Aufgaben-, Quellen- und Belegreferenzen | Agentennachweis: 52 fokussierte Tests und synthetischer Browserablauf. Keine automatische KI-Entscheidung oder Produktivkorrektur. |
| #18 | `31098ff`, `9fc6de8`, `1705bc2` | Jahresbezogene PDF-Vorschau, append-only Archiv, Manifest/Hash-/Dateidownloads und Jahresansicht | Backend-Tests in der integrierten Suite; synthetischer Browsertest Desktop/Mobil bestaetigt Erzeugen und Downloads. PDF bleibt Vorschau, nicht finale Abgabe. |

Die Changelog-Eintraege kennzeichnen #13 und #14 ausdruecklich als Teilumfang.
Es wurden keine Issues geschlossen und keine Releaseversion geaendert.

## Validierung dieses Integrationsstands

Integrierte Backend-Regressionen: **342 passed, 1 DeprecationWarning, 0 failed**
in 983.90 Sekunden. Der Befehl lief mit isoliertem pytest-Tempverzeichnis und
synthetischen Testdaten:

```sh
PYTHONPATH=src:/tmp/steuerreport-connector-tools-20261026 pytest -q --basetemp=/tmp/pytest-issue-integration-20261029 \
  tests/unit/test_guided_file_import.py tests/unit/test_import_batches.py \
  tests/unit/test_history_review_regressions.py tests/unit/test_history_jobs.py \
  tests/unit/test_history_provider_workflow.py tests/unit/test_import_assistant.py \
  tests/unit/test_file_raw_importer.py tests/unit/test_csv_raw_importer.py \
  tests/unit/test_raw_normalizer.py tests/unit/test_history_source_isolation.py \
  tests/unit/test_binance_earn_connection_binding.py \
  tests/unit/test_historical_price_workflow.py tests/unit/test_tax_methodology.py \
  tests/unit/test_ai_changes.py tests/unit/test_workspace_read_models.py \
  tests/unit/test_tax_year_pdf_reports.py tests/unit/test_exports.py \
  tests/unit/test_openapi_contract.py
```

Weitere Checks:

- `ruff check src tests scripts` — bestanden.
- `python3 -m py_compile scripts/check_tax_year_pdf_reports_browser_v2.py` — bestanden.
- `scripts/export_openapi_v2.py --check` — bestanden.
- `scripts/generate_api_endpoint_reference_v2.py --check` — bestanden.
- `npm run build -- --outDir /tmp/steuerreport-issue-integration-dist` — bestanden;
  Vite meldet weiterhin das grosse Hauptbundle.
- `scripts/check_tax_year_pdf_reports_browser_v2.py` mit synthetischer API,
  Chromium und den Viewports 1280x900 sowie 390x844 — bestanden; genau ein
  Bericht-POST, PDF und Manifest heruntergeladen, null externe Requests,
  Mobilansicht ohne horizontalen Ueberlauf.
- Screenshots (synthetisch, nicht committet):
  `/tmp/steuerreport-issue-integration-pdf-preview.png` und
  `/tmp/steuerreport-issue-integration-pdf-preview-mobile.png`.

Die pytest- und Buildtemporaerdateien dieses Laufs wurden entfernt. Freier
Speicher auf `/tmp` danach: 12 GB. Die vollstaendige Projektsuite, GitHub CI,
Image-Publish, Restore-/Rollback-Test und produktive Datenparitaet wurden in
diesem Lauf nicht nachgewiesen.

## Noch offen

- #13/#14: vollstaendige Import- und Kontenabgrenzung gemaess obigen Grenzen.
- #15: separater Browser-/Accessibility-Nachweis des manuellen Preisbelegs.
- #19/#20: nativer Dienst auf Port 8010 ist identifiziert, aber ein sicherer,
  nicht mutierender Nachweis vom aktiven Prozess zur tatsaechlich verwendeten
  Datenbankdatei fehlt. Der aktuelle passive Check fand weder passendes offenes
  DB-Handle noch Mapping; das beweist nicht, dass keine DB genutzt wird. Das ist
  die Voraussetzung fuer eine gebundene Sicherung und den semantischen
  Alt-/Neu-Vergleich. Keine Bestandsparitaet behaupten, bevor Quelle, Sicherung,
  Schema und aktive Methode eindeutig belegt sind.
- Weitere zuvor gelistete offene Themen #4, #8, #9 und #22 sind in
  diesem Integrationszweig nicht umgesetzt oder abgenommen. Sie muessen anhand
  des aktuellen Issuebodys erneut einzeln abgegrenzt werden.
- Keine umfassende steuerrechtliche oder fachliche Freigabe durch diese
  Softwaretests; keine neue Methode wurde aktiviert.

## Bereitstellung

Es wurde nicht auf `main` gemergt, nicht gepusht, kein Tag/Release/Image
erstellt und kein Docker-Container ersetzt. Vor einer Bereitstellung sind
Review, vollstaendige CI, verbleibende Issue-Slices, Docker-Image-/Volume-
Identitaet, konsistente Sicherung/Wiederherstellung und ein ausdruecklicher
Updateauftrag erforderlich.
