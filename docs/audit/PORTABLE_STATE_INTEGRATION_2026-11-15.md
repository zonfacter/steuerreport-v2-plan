# Portabler Dockerstand: Integration von PR 11 und Issue 53

Entwicklungsnachweis vom 15.11.2026. Keine produktive Migration, kein Release,
keine Aktivierung einer Steuermethode und keine fachliche Jahresfreigabe.
Die offenen Gesamtauftraege #8, #19, #20, #52 und #53 bleiben offen.

## Herkunft und pruefbarer Diff

- Integrationsbasis PR #59:
  `11e6ed5d92816f7d8e61caec36b7108a33dbe149`.
- Bestehender Operator aus Draft-PR #11:
  `62bee0ba1031984fd8593107b3d3a19e7baf3da2`.
- Nachvollziehbare unveraenderte Uebernahme seiner drei Dateien in
  `dd13c3bd410e5ea121cea6e65a737c314a2eb704`; kein Merge der alten
  Entwicklungsumgebung oder ihrer privaten Commitmetadaten.
- Erste Steuerpfadkorrekturen in
  `759193f9467e7b7e8599a8e68c7746d5ec016e85`.
- Katalog-/Vault-/Pfadgrenzen, separate native Sperre und eindeutige
  Ressourcenbereinigung in `b8ae0e4d235e4c73ce2681bef249f02556b7f709`.
- Reviewbarer Gesamtdiff: `git diff 11e6ed5d92816f7d8e61caec36b7108a33dbe149 HEAD`.
  Die endgueltige PR-Revision und ihre CI-Laeufe binden die nachfolgenden
  Integrationskorrekturen; ein SHA kann nicht im eigenen Commit stehen.

PR #59 hatte vor dieser Erweiterung fuenf erfolgreiche CI-Jobs, Lauf
`43721373946`. Das ist kein Restore-Nachweis fuer den neuen Operator.

## Implementierung und Beweisgrenzen

| Bereich | Aenderung | Nachweis / Grenze |
| --- | --- | --- |
| Bedienung ohne KI | Vorhandene CLI `backup`, `verify`, `restore-check`, `restore` wiederverwendet | Runbook in [DOCKER_BACKUP_RESTORE.md](../DOCKER_BACKUP_RESTORE.md); Hostwerkzeug, kein Docker-Socket in der Webanwendung |
| Vollstaendiger Scope | Persistente Mounts, private Konfiguration, Originaldateien, Vault-Key und Ciphertext | Nicht persistierte anwendungsspezifische Env-Overrides blockieren; keine stille Secret-Klartextuebernahme |
| Stoppgrenze | Quelle vor/nach Archivierung gebunden und sauber gestoppt, keine laufenden Docker-Mitnutzer | Externe Belegdateien benoetigen weiterhin bestaetigte Schreibpause |
| DuckDB-Sperre | Separater nativer RO-Guard fuer Inventar, Snapshot und Archiv | Vier echte Prozess-/Writer-Gegenproben; keine Checkpoints oder Finanz-DB-Aenderungen |
| Vollstaendigkeit | Lesefehler, unbekannter Pfadkontext und fehlerhafte Vault-Strukturen blockieren | 95 unabhaengige Grenzproben; keine Behauptung vollstaendiger Unterstuetzung aller Makrotypen |
| Semantik | Tabellenwerte plus persistenter Kataloghash; vor/nach Start und Neustart | Aeltere Format-1-Archive ohne Katalogbindung werden transparent gekennzeichnet |
| Ressourcen | Nonce-Labels, neue zufaellige Volumenamen, feste Container-IDs | Neun Identitaetsproben; Docker-Administratoren bleiben vertrauenswuerdige Betriebsinstanz |
| Unklare Erstellung | Fehlende Ressource nach unklarem Create ist kein positiver Bereinigungsnachweis | Begrenzte erneute Beobachtung, danach ausdruecklich unbekannt statt Erfolg |
| Archiv | SHA, Groessen-/Eintragsgrenzen, keine Links/Geraete/Pfadtraversierung | Private Archive sind nicht verschluesselt und enthalten entschluesselbare Zugangsdaten; nur geschuetzter Speicher |
| Softwarepaket | Operator, Offline-DB-CLI und Runbooks im bestehenden Sourcebundle | Neue Ausschlussproben fuer gaengige Archivformate; kein Vollbeweis gegen jeden moeglichen privaten Dateityp |
| CI | Bestehende zwei synthetische Docker-Layerimages fuer Vollrestore nutzen | Nur geheimnisfreie Ergebnisflags als Artefakt; keine realen Provider oder produktiven Volumes |
| Abbruch | Operator in eigener Sitzung, begrenztes Warten auf Bereinigung, unklaren privaten Zustand erhalten | 250 Harness-Proben, darunter fuenf echte synthetische SIGINT-/SIGTERM-/Deadline-Proben; kein erzwungenes Kill eines Operators als Erfolg |

Die vier nativen Sperrproben scheiterten vor der Korrektur vollstaendig und
bestehen danach. Bei neun zuletzt ergaenzten Identitaetsproben scheiterten acht
vor der Korrektur, eine bereits erfuellte Kontrollprobe bestand. Alte Tests
erhielten die neuen realen IDs/Labels in ihren Mocks; die Sicherheitsassertionen
wurden nicht durch pauschal erfolgreiche Cleanup-Mocks ersetzt.

## Lokale Testnachweise

Alle Eingaben synthetisch; gemeinschaftlich genutzte bestehende Python-Umgebung,
`PYTHONPATH=src`, DuckDB 1.5.2. Keine neue Venv, kein lokaler Dockerbuild,
keine private Quelldatenbank kopiert oder geoeffnet. JUnit-Dateien bleiben im
ignorierten `var/`, oeffentliche Originalnachweise entstehen als CI-Artefakte.
Ueberlappende Testzahlen werden nicht addiert.

| Lauf | Tatsaechliches Ergebnis |
| --- | --- |
| Importierter alter Operator | 28 bestanden |
| Erste neue Kontrollproben vor Korrektur | 16 fehlgeschlagen |
| Unabhaengige Grenzproben vor Korrektur | 82 fehlgeschlagen, 13 bestanden |
| Native Guard-Proben vor Korrektur | 4 fehlgeschlagen |
| Neue Identitaetsproben vor Korrektur | 8 fehlgeschlagen, 1 bestanden |
| Operator/Harness/Softwarepaket nach Identitaetskorrektur | 398 bestanden; `portable-state-second-final.xml` |
| Zusaetzliche unabhaengige Host-Lifecycle-Gegenproben | 20 bestanden; unveraendert bis auf checkoutrelativen Modulpfad in Backend-CI aufgenommen; `portable-state-host-review.xml` |
| Abschliessende integrierte Operator-/Harness-/Paketprobe | 440 bestanden, kein Skip; `portable-state-integrated-final.xml`; enthaelt die 20 Host-Gegenproben und alle 250 Harness-Proben |
| Breiter Vorlauf vor letzter Identitaetskorrektur | 708 bestanden, kein Skip; `portable-state-broad-final.xml`, kein Schlussnachweis fuer spaetere Aenderungen |
| Unveraenderte urspruengliche Referenzen | 52 bestanden, kein Skip; `portable-state-reference-final.xml` |
| Zusaetzliche verpflichtende unabhaengige Referenzen | 359 bestanden, kein Skip, eine vorhandene Starlette-Warnung; `portable-state-independent-reference.xml` |
| Finale angrenzende Preis-/Archiv-/API-/Legacy-/Offlinekopie-/Paketregressionen | 319 bestanden, kein Skip, eine vorhandene Starlette-Warnung; `portable-state-adjacent-final.xml` |
| Ruff `src tests scripts` | bestanden |
| OpenAPI und Endpunktreferenz `--check` | aktuell; kein neuer Webvertrag |
| Private Defaultwerte | `privacy_default_violations=0`; kein vollstaendiger Gitleaks-Scan behauptet |

Unveraenderte Referenzbaseline:
`09f674b350a9a83943df8980bbceafd88821ee1400e03b5b22ea1ee0f8cd6bfb`.

SHA256 der unveraendert aufbewahrten lokalen Originalnachweise:

```text
143960f49400f1c5b43736ece33b81464177a0d2bf9cd84d55df731c07755bb4  portable-state-control-before-complete.xml
82bf950196ee8c0bd679a04caa956f2e1cc6e2e8ff6d9cda18e4c5b712d24cd0  portable-state-boundaries-before.xml
18a6cee42f709a9721046ea62b2f5187ed56a7b480fb1a9fd7c38fe5164c08e0  portable-state-guard-before.xml
8e5a333ecebcc5c351f129aa663856f261f997cc14a9cf5aa6d827c3fac66863  portable-state-identity-before.xml
7eb2e3df238b9c01bf8688381f41cf555997295f4d328a124526aaa076a3040d  portable-state-identity-after.xml
22859c8e94e44c1b927d2a991d8d8ffb78eca16b66f9aed366eea02e04021c9a  portable-state-second-final.xml
2a50073ae838f0477f3c314efe15bf6eb0a5a0dfc9ffe01a7c792a97e0b7bf95  portable-state-host-review.xml
6bb593689c1631ef1e960ed3b8d8601d1f572356c93825b0c3ca160910acc04c  portable-state-reference-final.xml
9308da643d387ea04337d1616c028da8b25fdf829477f805ae2bbc888e7cdb9d  portable-state-integrated-final.xml
60fb97095c35c708aef7862366618d8b7168d6b86fca1010067eb6f74558289c  portable-state-independent-reference.xml
112972cf55ba68aa17fbe461f967c9a4083440f512fabf17ecb6e8981f746195  portable-state-adjacent-final.xml
```

Ausgefuehrte Befehle fuer diesen Scope:

```sh
PYTHONPATH=src python -m pytest -q tests/unit/test_docker_state_v2.py tests/unit/test_docker_state_control.py tests/unit/test_docker_state_identity.py tests/unit/test_docker_state_boundaries.py tests/unit/test_docker_state_guard.py tests/unit/test_portable_state_ci.py tests/unit/test_software_release.py --junitxml=var/portable-state-second-final.xml
PYTHONPATH=src python -m pytest -q docs/audit/2026-10-28/acceptance_tests.py --junitxml=var/portable-state-reference-final.xml
PYTHONPATH=src STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 python -m pytest -q tests/acceptance --junitxml=var/portable-state-independent-reference.xml
PYTHONPATH=src STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 python -m pytest -q tests/unit/test_docker_state_identity.py tests/unit/test_docker_state_host_review.py tests/unit/test_docker_state_control.py tests/unit/test_docker_state_v2.py tests/unit/test_docker_state_boundaries.py tests/unit/test_docker_state_guard.py tests/unit/test_portable_state_ci.py tests/unit/test_software_release.py --junitxml=var/portable-state-integrated-final.xml
PYTHONPATH=src STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 python -m pytest -q tests/unit/test_current_backfill_partial.py tests/unit/test_external_backfill_partial.py tests/unit/test_legacy_fx_backfill_safety.py tests/unit/test_as_of_price_gate.py tests/unit/test_backfill_legacy_callers.py tests/unit/test_tax_filing_archive_binding.py tests/unit/test_tax_filing_snapshots.py tests/unit/test_tax_filing_audit.py tests/unit/test_read_snapshot.py tests/unit/test_openapi_contract.py tests/unit/test_api_endpoint_reference_generator.py tests/unit/test_legacy_duckdb_fail_closed.py tests/unit/test_offline_duckdb_clone_cli.py tests/unit/test_offline_duckdb_snapshot.py tests/unit/test_offline_clone_process_isolation.py tests/unit/test_python_dependency_compatibility.py tests/unit/test_dockerfile_dependency_cache.py --junitxml=var/portable-state-adjacent-final.xml
PYTHONPATH=src python scripts/check_reference_baseline_v2.py
PYTHONPATH=src python scripts/export_openapi_v2.py --check
PYTHONPATH=src python scripts/generate_api_endpoint_reference_v2.py --check
PYTHONPATH=src python scripts/check_private_data_v2.py
ruff check src tests scripts
```

## Aktualisierte Paketmatrix

| Paket | Implementiert / technisch geprueft | Noch nicht abgenommen |
| --- | --- | --- |
| A Betrieb | Bestehenden portablen Operator integriert und gehaertet, generischer isolierter CI-Restore vorgesehen | Aktueller echter Image-/Volume-/Vault-Restore beim Betreiber, produktive Identitaet und Rollback |
| B Bewertung | Vorhandene Preis-/FX-Vertraege unveraendert, Originalreferenzen erneut gruen | Produktive Quellen-/Methodenabdeckung und offene #44/#46/#49 |
| C Steuerlogik | Keine Formel-/FIFO-/Frist- oder Freigabeaenderung | Individuelle Einkunftssphaere, Swapkostenrolle und alle zuvor offenen Belege |
| D Import/Konten | Keine neuen Importe; Persistenz umfasst vorhandene Dateien und verschluesselte Einstellungen | Providerhistorienvollstaendigkeit, CSV/API-Ueberlappungen und echte Kontenparitaet |
| E Reports/UX | Bestehende Archivpakete unveraendert sichern, keine automatische Neuberechnung | Vollstaendiger ereignis-/lotbezogener Alt-/Neu- und PDF/CSV/JSON-Abgleich |
| F Unabhaengige Abnahme | Getrennte Agenten fuer Grenzen und Harness, neue Gegenproben und Pflicht-CI | Keine fachliche Gesamtfreigabe; technisches Mock-/Synthetik-PASS ist keine reale Datenparitaet |

## Referenzmatrix G01-G25

Die unveraenderten technischen Annahmen und offenen Fachgrenzen aus
[MATRIX.md](2026-10-28/blocker-closure/MATRIX.md) gelten weiter. Diese Tabelle
kennzeichnet den Beitrag dieses Inkrements, nicht einen neuen 25-Faelle-End-to-End-
Freigabeanspruch. Kein Fall ist hier fachlich abgenommen.

| ID | Beitrag / technischer Status in diesem Inkrement | Offene Grenze |
| --- | --- | --- |
| G01 | Originalreferenz erneut bestanden | Kein neuer kompletter PDF-Abgleich |
| G02 | Originalreferenz erneut bestanden | Individuelle Kostenrolle |
| G03 | Originalreferenz erneut bestanden | Nicht jeder Connector-Nettovertrag |
| G04 | Originalreferenz erneut bestanden, keine neue Steuerregel | Swapkostenrolle und persoenliche Kostenbasisherkunft |
| G05 | Originalreferenz erneut bestanden | Sonderprotokolle und Slippage |
| G06 | Originalreferenz erneut bestanden | Produktive Stablecoinbelege |
| G07 | Originalreferenz erneut bestanden | Reale Depegabdeckung |
| G08 | Bestehender FX-Vertrag unveraendert, unabhaengige Consumerproben erneut bestanden | Keine persoenliche Bewertungsmethodenfreigabe |
| G09 | Bestehende begrenzte Referenztagsregel unveraendert, unabhaengige Consumerproben erneut bestanden | Keine universelle Quellenfreigabe |
| G10 | Originalreferenzen erneut bestanden | Produktive Altpreis-/Provenienzlaengen |
| G11 | Originalreferenz erneut bestanden | Keine Depotmethodenaktivierung |
| G12 | Originalteilprobe erneut bestanden | Vollstaendige Netzwerkgebuehrenbelege |
| G13 | Originalreferenz erneut bestanden | Private/betriebliche Herkunft |
| G14 | Originalteilprobe erneut bestanden | Vollstaendige Herkunftsentscheidung |
| G15 | Originalreferenzen erneut bestanden | Reale Quellzeit und Einzelfall |
| G16 | Originalreferenzen erneut bestanden | Kein exhaustiver Zeitzonenbeweis |
| G17 | Originalreferenzen erneut bestanden | Nicht jede positive unbelegte Kostenbasis |
| G18 | Bestehender Identitaetsguard unveraendert, unabhaengige Konfliktproben erneut bestanden | Kein generischer positiver Multichain-FIFO |
| G19 | Bestehender enger Konvertierungspfad unveraendert, unabhaengige Proben erneut bestanden | Keine universelle Bridge-/LP-/Wrappingneutralitaet |
| G20 | Originalreferenz erneut bestanden | Nicht alle API-/Formatwechsel |
| G21 | Originalreferenzen erneut bestanden | Nicht jede externe private Quelldatei |
| G22 | Originalreferenz erneut bestanden | Keine allgemeine PDF-Byteidentitaet |
| G23 | Originalreferenzen erneut bestanden | Kein Spezialfall-Fachzahlenvollabgleich |
| G24 | Originalreferenzen erneut bestanden | Keine persoenliche Einkommensteuerberechnung |
| G25 | Guard/Katalog/Vault/Cleanup synthetisch erweitert; neuer Docker-CI-Pfad | Betreiberrestore, gebundene reale Migration und Rollback bleiben offen |

## Naechste gesperrte Schritte

1. Neuen CI-Vollrestore gegen die integrierte Revision tatsaechlich bestehen
   lassen und Ergebnisflags pruefen. Bestehende #59-CI ist kein Ersatz.
2. Danach genehmigten, geschuetzten Betreiberrestore und reale Legacy-Zuordnung
   fuer #19/#20 durchfuehren. Keine unsichere Kopie einer laufenden DuckDB.
3. Vollstaendigen Einzelpositionsvergleich #52 und Wiederanlauf/Atomizitaet #49
   schliessen. Summengleichheit oder ein DB-Klon allein reichen nicht.

Kein Container-/Volumewechsel, kein Versions-Tag, keine Releaseveroeffentlichung
und keine Entscheidung ueber produktive Finanzdaten durch dieses Inkrement.
