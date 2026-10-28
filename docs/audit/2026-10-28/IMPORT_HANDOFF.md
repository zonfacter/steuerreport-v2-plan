# Paket D Handoff

Nur `/tmp/steuerreport-migration-20261028-import`, Branch
`audit/docker-migration-20261028-import`, Basis
`438cbd3dac11b0f0bfcc7f308f583f3837de5f85`.
Der vorherige Tax-Worktree wurde sauber belassen. Keine Produktivdaten,
echten Credentials, Provider-/AI-Aufrufe, Pushes, Tags oder Deployments.

## Lieferung

- IMPORT_KONTEN.md: vorhandene Multiaccount-/Quellbindung, Imports,
  Handels-/Fee-Semantik, unvollstaendige Historien und Grenzen.
- REQUESTPFADE.md: manuelle/test/history/retry/pagination/enrichment-Pfade
  zum Limiter, explizite interne Relay-Ausnahme, GET-/POST-Effektunterschiede.
- `tests/unit/test_migration_import_accounts.py`: echte Services mit
  Fake-Transport; zwei gleichnamige Konten, getrennte Credentials, neun
  gemeinsame Starts mit Retry/Folgeseite, API-/CSV-Wiederholung und DB-Kopie
  mit Raw-/Review-/Kontenzuordnung. GET-/POST-Read-Effekte gegen Jupiter-GET.

Kein Produktionscode veraendert. Kein kritischer Produktfehler durch die
gezielten Repros bestaetigt. Keine pauschale Erfuellung von G20/G25 und keine
vollstaendige API-/Hersteller-/Rechtszertifizierung behauptet. Gesonderter
API-Pruefauftrag nicht verfuegbar, daher nicht als gelesen bezeichnet.

## Befehle

```bash
export PYTHONPATH=src:/tmp/steuerreport-connector-tools-20261026:/tmp/steuerreport-release-tools-20261025
export STEUERREPORT_TEST_PRUNE_PASSED_DBS=1
pytest -q tests/unit/test_migration_import_accounts.py tests/unit/test_connections.py tests/unit/test_history_cex.py tests/unit/test_external_http.py tests/unit/test_csv_raw_importer.py --basetemp=/tmp/steuerreport-migration-20261028-import-tests-final -n 2 --tb=short
git diff --check
git ls-files -z src | xargs -0 sha256sum | sha256sum
```

Testverzeichnis absichtlich ausserhalb des Softwarebaums, nur eigene
wegwerfbare Datenbanken. Der vorherige Zweiertest bestand mit 2 passed in
14.78 s. Erweiterter Abschlusslauf: **225 passed in 37.06 s**, darunter drei
eigene Tests. Kein Skip/xfail, keine gelockerten Erwartungen. `git diff --check`
ohne Befund. Dies ist ein gezielter Regressionstest, kein Gesamtsuite-Lauf.

Eingefrorener Produktionsquellstand vor Abschlusslauf:
`a94f57b4dad6fd2292e49b900aa91a7fcf4c10be64bd7f557ee105b84de941ce`.
Nach dem Lauf derselbe Hash bestaetigt. Test-/Dokumentdateien sind nicht
Bestandteil dieses Produktionsquellhashs. SHA256 der eigenen Testdatei:
`edba250cf979e9a4f9a0d3b671c2df14a9acab50d55f5c0c5893344d79a2e5b2`.

## Offene Grenzen

Die Kopie ist keine laufende Docker-Volume-Restoreprobe. Vaultkey bleibt eine
getrennte Voraussetzung; keine Schluesselweitergabe oder Erzeugung im
Quellbaum. Roh-/Review-Bindung getestet, nicht jedes Artefakt oder laufende
Job-Szenario. Generische Cross-CSV/API-Formaterkennung, fremde/unbelegte
Ownership, geschlossene historische Walletkonten, alle Bottypen und alle
Anbieterprodukte sind nicht vollstaendig abgedeckt. Providerreferenzen wurden
nicht neu als aktuell verifiziert: keine neuen externen Tarif-/Ratenzusagen.
Die Requestpfadpruefung ist statisch breiter als die dynamische Binance-/
Jupiter-Fixture; die bestehenden Adaptertests ergaenzen isolierte Semantiktests.
