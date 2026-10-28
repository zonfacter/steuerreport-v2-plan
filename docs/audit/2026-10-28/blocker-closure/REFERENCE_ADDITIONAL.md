# Unabhaengiges Zusatzgate G08/G09/G18/G19

Eigenstaendige Fixtures unter
`tests/acceptance/test_fx_identity_conversion_reference.py`, separater
Testcommit `513c8c454ed612316b71c49d97d78e3921959a18`. Keine Unit-Helferimporte,
keine Produktberechnungen als Sollwertoracle. Die urspruenglichen52Proben
wurden nicht editiert und in diesem Zusatzlauf nicht erneut ausgefuehrt.

## Vorher Und Nachher

| Lauf | Runtime-Commit | Ergebnis | Zeit / Exit |
| --- | --- | --- | --- |
| Vorfix, Originalbeleg erhalten | `75adc72ab66ac3f64a2e857e72e874acb6c9d1b7` |38Proben:8FAILED,30PASSED,0skip/xfail/errors |44,20s /1 |
| Nachfix, exakt gefroren | `f8e60d9e74b3d5ef92c710c0ae75d0cd84ac9fd6` | dieselben38Namen und Sollwerte:38PASSED,0skip/xfail/errors |43,37s /0 |

Eigener Nachfix-Merge: `b2ad92453a29c72552b13fd91b1f08e397555ea6`.
Vor Ausfuehrung war der Diff gegen f8e60d9 fuer `src`, `configs`, `frontend`,
`scripts`, `requirements-runtime.lock` und `pyproject.toml` leer.381getrackte
Dateien aus diesen Bereichen wurden am Testanfang/-ende SHA256-geprueft und
blieben identisch. Voller Eingabemanifest und Ergebnisse stehen in
`reference-additional-results.json`; der Nachher-Sourceproof hat SHA256
`84413f8a98b33afa5bb8f4b0a7a93d6231c98665f533c7e21f062137bfacbf73`.

Originale XML-Dateien, nicht ueberschrieben:

- Vorher `/tmp/steuerreport-blockers-20261028-reference-tests/before-fixes-75adc72.xml`,
  SHA256 `dcce6e0e4b6724b374e7244d4e88d0b21420f4b8513dc6f9b1c6e2c198c6af5b`.
- Nachher `/tmp/steuerreport-blockers-20261028-reference-tests/after-fixes-f8e60d9.xml`,
  SHA256 `ab0975c1d9f88bc2a95de4710af88c347b0580454c19d737b599b2b0cbe2301d`.
- Voller Nachher-Sourceproof
  `/tmp/steuerreport-blockers-20261028-reference-tests/bootstrap-sibcgm9c/source-freeze.json`.

Testdatei SHA256 nach mechanischer Formatierung:
`9900efcc93769111556776e624676bab7310be80a748c8eadf4064dd91fa069b`.
Der Vorfixlauf erfolgte vor der Formatierung; AST ohne Positionsattribute ist
vor/nach Formatierung identisch:
`d905cbdbbdfe51afdfcee42cdfb5197f9b2acc6bb5f6367cbb3276926e79fe5d`.
Keine Aenderung von Sollwerten, Assertions oder Szenarien durch den Formatter.

## Wirklicher Umfang

| Gruppe | Proben | Unabhaengiges Soll / Grenze |
| --- | --- | --- |
| G08/G09 |14 | Echter V1FxCacheImporter mit eigener synthetischer SQLite:100USD werden90EUR, beide Quotierungsrichtungen; PricePoint bis FIFO-Lotbasis90 weiterverbraucht. Freitag fuer Sonntag, explizite7Tage-Grenze; fehlende/alte/zukuenftige/rueckdatierte/negative/Null/NaN/falscheEinheit/unbelegte Referenz liefert keinen Kurs und keinen FX1. Keine Anbieter-Netzabfrage und keine rechtliche Wochenendkursfreigabe. |
| G18 |7 | Gleicher Symbolname darf Chain-, Contract- oder Dezimalstellenkonflikt nicht aufloesen; Original-Rawmenge gegen Dezimalstellen. CoinGecko ohne explizite Identitaetsbindung blockiert, gebundene Kontrolle positiv; gebundener WSOL-Coingecko-Provider wird nicht durch Mintprovider ersetzt. WSOL-Mint ist oeffentliche Tokenkonstante, keine Kontoadresse. |
| G19 |15 | Eigener lokaler Primaerbeleg+SHA256 und exakte Boolbestaetigungen.100OLD/Basis90 werden1NEW/Basis90 mit Originaldatum/echterOriginlot-ID und Zieltransfer als source_event_id, global UND Wallet. Teilverkauf0.4 fuer60:Basis36/Gewinn24/Rest0.6/Basis54. Fehlende/geaenderte/absolute/../Symlink-Belege, falschesVerhaeltnis und falscheBool-Acks werden abgelehnt. TXT-Aenderung invalidiert Config-, WalletRun- und gemeinsamen Preview-Inputfingerprint. Keine echte Preis-/KI-Previewuebernahme oder allgemeine steuerneutrale Wrappingfreigabe. |
| Neue P1 / G04 |2 | Eigene alte DB mit bekanntem Gebuehrenpreis, aber ohne gespeicherten Verbrauch bleibt blockiert. Nach echtem Rebuild ist Gebuehrenmenge0.1 belegt; spaetere Preisaenderung macht den Nachweis stale. Keine Produktiv-DB und kein produktiver Methodenwechsel. |

Die8roten Vorherproben sind unverfaelscht erhalten: CoinGecko-unbound,
WSOL-Providerersetzung, falscher Zielsource beider Engines, TXT-Previewbindung,
Rewardlot-Basis180statt90 und beide Fee-Persistenz-/Stale-Faelle. Die eigene
SQL-Invariante summiert nur an Reward-CanonicalEvents gebundene Erwerbskosten:
einmal90, nicht180 durch ein Carry-Lot. Das ist enger als die Behauptung, jeder
Income-Consumer habe im Vorfixstand180angezeigt. `income_report()` wird
zusaetzlich auf90geprueft.

Ein frueher Fixtureadapter nutzte `add_raw_objects` ohne separates batch_id;
das wurde vor dem gewerteten38er-Vorherlauf korrigiert. Ebenso wurden die
etablierten Identitaets- UND Dezimalstellen-Reviewcodes akzeptiert, statt einen
falschen eigenen Codefilter als Produktfehler auszugeben. Keine Runtimefixes
durch diesen Agenten, keine weggefilterten echten Fehler, keine xfails.

## Ausfuehrung Und Lint

```sh
env PYTHONPATH=src:/tmp/steuerreport-connector-tools-20261026:/tmp/steuerreport-release-tools-20261025 \
  python3 -B -m pytest tests/acceptance/test_fx_identity_conversion_reference.py \
  --basetemp /tmp/steuerreport-blockers-20261028-reference-tests/after-fixes-f8e60d9 \
  -q --tb=short -o cache_dir=/tmp/steuerreport-blockers-20261028-reference-tests/pytest-cache \
  --junitxml=/tmp/steuerreport-blockers-20261028-reference-tests/after-fixes-f8e60d9.xml
ruff check tests/acceptance
ruff format --check tests/acceptance
```

Beide Ruff-Pruefungen bestanden. Nur gezielte `noqa:E402` an Imports nach
bewusst vorher eingerichteter isolierter Laufzeit; keine pauschale Ausschaltung.
Netzwerk und fremde DuckDB-Pfade sind gesperrt, eigene DBs/Belege/Testroot
ausserhalb des Repos. Keine Source-/Config-/Versionsedits ausser uebernommener
Koordinatorcommits, kein Push/Release/Deployment. Die parallele Koordinator-
Vollunit-Suite und sein52er-Lauf sind separate, hier nicht vereinnahmte Belege.

**Keine Gesamtfreigabe:** Dieses Gate schliesst die konkret getesteten
Referenzluecken. Es hebt die in `LEGACY_PARITAET.md` dokumentierten Grenzen
nicht auf:8010-DB unbestaetigt, V1-Upstreamblob-Herkunft offen, unterschiedliche
Inputs/Methoden und keine vollstaendige produktive Cross-Engine-Steuerparitaet.
