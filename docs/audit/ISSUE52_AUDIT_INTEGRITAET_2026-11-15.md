# #52: Audit-Integritaet und belastbare Teilzuordnung

## Software und Abgrenzung

Implementierung: `7886c536ddfac87b3da665335fb2cb15707d8949`.
Nachtrag I/O-Fehlerguard und35-Pflichtreferenzen:
`d4ffd5ef82d29a926c9560b417f3a91ce8cde60d`.
Letzter begrenzter Nachtrag gegen scheinbare Nullpositionen bei unlesbaren
Referenzdetails: `10c5667b747fe56b7469e5a9ef5f4e43b5ac639e`.
Sicherheitsnachweise und reine, exakt gebundene Hash-Fundfreigaben:
`e1b8d1938b50c7fc91d4f9ce0fb39fe8aae425f9`.
Basis: `8f3681d2d12be430cbb627ed731091bf0ba77a3f` (Draft #66).
Diff: `git diff 8f3681d2d12be430cbb627ed731091bf0ba77a3f 10c5667b747fe56b7469e5a9ef5f4e43b5ac639e`.
Vertrag: `ISSUE52_AUDIT_INTEGRITAET_VERTRAG_2026-11-15.md`.

Entwicklungsstand, keine neue Versionsnummer, kein Release, Imagebau,
Containerwechsel, produktiver Datenzugriff oder Methodenentscheid. #52 bleibt
offen. Ein partieller Audit ist kein vollstaendiger Alt-/Neu-Abgleich.

## Implementiert

| Anforderung | Dateien | Nachweisumfang |
| --- | --- | --- |
| Erklaerte Differenz ist nicht Summengleichheit | `domain/tax_filing_audit.py` | Echtes synthetisches FIFO: Kosten10, Erloes20, Gewinn10; sechs erklaerte Aggregatdeltas, aber Summen nicht identisch |
| Gemeinsamer aktueller DB-Lesestand | gleicher Dienst, vorhandener `read_initialized_snapshot` | Kein Root-Connect/Schema-Init; physischer RO-Reader, Materialisierung erst nach Transaktionsende |
| Frische Eingangsbindung | vorhandener `_fingerprint` aus `ai_changes.py` wird konsumiert | Aenderung gespeicherter Inputs trotz gleicher Tabellenzaehler aendert den Auditstand; DB und Laufzeitkonfiguration, kein universeller externer Dateibeweis |
| Keine gemeinsam genutzten Vorschau-Caches | `tax_wallet_fifo.py`, `tax_methodology.py` | Audit nutzt nur eigene Instanz-Caches; Preview-Diskcache und drei klassenweite RAM-Caches werden nicht uebernommen |
| Archivierte IDs erhalten | `tax_filing_audit.py` | `Source_Event_ID`, `Lot_ID`, `Anschaffungs_Event_ID`; Canonical-Zuordnung ausschliesslich durch eindeutige explizite Event-ID |
| Keine Zeit-/Asset-Ersatzidentitaet | gleicher Dienst | Widersprechende IDs, mehrdeutige Duplikate und mehrere Lots getrennt; keine Tagesheuristik |
| Unbekannt ist nicht null | Audit-Contract und Leser | Fehlende Referenz: null/not_available; fehlende Positionsbetraege kontrolliert abgelehnt; unbekannter Altstatus beweist keine Umklassifizierung |
| Keine erfundene Ursache | gleicher Dienst | Importbeleg allein beweist keinen neuen Import; EUR-Differenz ohne Provenienz beweist keinen Preis-/FX-Wechsel; unknown hat konkrete Erklaerung |
| Exakte Rechnung | gleicher Dienst | Lokale Decimal-Praezision80; DECIMAL(38,18)-Differenz von 1e-18 bleibt erhalten; Aufruferkontext unveraendert |
| Manipulation aufdecken | `audit_artifacts.py`, Auditdienst | JSON-Kernhash, erwarteter Inhalt, kanonische JSON-Bytes, regeneriertes Markdown und Vollbyte-Siegel; keine Reparatur |
| Kein Ueberschreiben bei Rennen | gleicher Helper | fsync, temporare Datei, atomarer Hardlink ohne Replace, begrenztes flock, regulaere Dateien mit NOFOLLOW/NONBLOCK |
| Versionierter Umfang | Contract, OpenAPI | `tax-filing-audit-v3`, explizit partial/not_available und initialisierter RO-Lesestand; neue Inhalts-IDs, alte Archive unveraendert |
| Pflichtreferenzen | CI, `check_reference_baseline_v2.py` | Vier unabhaengige Dateien mit festen SHA256, verpflichtender CI-Schritt und35 Faelle im geprueften Original-JUnit ohne Skip/Fehler |

JSON/Markdown/Integritaetssiegel entstehen im privaten Auditarchiv, nicht in der
Finanz-DB. Der Standard-GET kann diese Dateien erzeugen und benoetigt auch beim
Wiederlesen ein schreibbar oeffnbares Lockfile. `materialize=False` unterdrueckt
diese Ablage. Kein genereller schreibfreier API- oder Cold-Start-Nachweis.

Maximal64MiB je Audit-JSON/Markdown; kein Aufteilen grosser Finanzberichte in
diesem Schritt. Elternverzeichnisse muessen vertrauenswuerdig sein: der Helper
verhindert abschliessende Symlinks, nicht jede Parent-Symlink-Traversierung.
Ein Administrator kann Daten samt Hashankern ersetzen; keine WORM-/amtliche
Zertifizierungsbehauptung. Ein unvollstaendiges Trio wird nicht still repariert.

## Unabhaengige Vorher-/Nachher-Proben

Originale unter `2026-11-15/issue52-integrity-evidence/` bleiben bytegleich:

| Original-JUnit | Ausgang | SHA256 |
| --- | --- | --- |
| `audit-review-before.xml` | 3 failed / 1 passed gegen sauberes 8f3681d | `322ced8ab428fe8bc11618a81038552790a2aead4a99391e4e48f55b415d56a0` |
| `audit-identity-review-8f-exact-red.xml` | 12 failed / 2 passed gegen exaktes, in-memory geladenes altes Auditmodul; uebrige aktuelle Imports | `2446f1c679e5c3153bbcb0eb89ad233812f273f86aff1976c4601289b200c788` |
| `audit-additional-review-original.xml` | 9 failed / 19 passed einschliesslich Original14 gegen zwischenzeitlichen Arbeitsstand | `c5423844b77c7ebef96b7ff725355f2d5eb472d26f5687796088a5b6f4b5db58` |
| `audit-io-review-before.xml` | 3 failed gegen7886c53: mkdir-Fehler entkommen roh | `8a98a1ae91681c87bdba9063db0d5c3e6649811ee01a80f99c4c253e9bfa3648` |

Testdateien unveraendert, kein Abschwaechen roter Assertions:

- `test_tax_filing_audit_independent_review.py`: `df62c3379bf5464abe7c3fef6f052b629715bc1e7d072c5c0e7469890c7f31bf`.
- `test_tax_filing_audit_identity_review.py`: `7f500d2d8a253819c70a7837016e54c565bd70d97d29acbbeacaf2f9399f2142`.
- `test_tax_filing_audit_additional_review.py`: `1d6255f969e8b9e90275caa80ef4a8516e10693deff55680fb5a75e82a4a8ff9`.
- `test_tax_filing_audit_io_review.py`: `26cf95f5758fa3972b0ab6a4e598bcc7687564baf7cb9cb02dff722682af648e`.

Zusatzhelper:86 eigene I/O-, JSON-, Abbruch-, Lock- und Race-Proben;
Testdatei-SHA `1621c7e24ecebc832d78159134062e3ec43d9c2b7149c5dc024f7a4032e78cbd`.
Neue Primitiven sind keine unabhaengige steuerliche Sollrechnung.

Gezielte Zwischennachweise:187 bestanden vor der letzten Cache-Isolation
(`var/issue52-final-focused.xml`, SHA `2d6caff5a85a833962021f5f2e012d946ec1e177c094ab4c5d548364045af195`);
danach89 bestanden mit Cache-Isolation, Original32 und bestehendem Referenzguard
(`var/issue52-cache-final.xml`, SHA `789b089ec822ec8acab707e526e49ce5e1c032190a81f55f4c4b01b67af74bd1`).
Dies sind unterschiedliche Laeufe, keine addierte Zahl eindeutiger Tests.

## Nachpruefung des vorherigen Drafts

Lauf43757705832 fuer exakt8f3681d ist in allen fuenf Jobs erfolgreich.
Originale heruntergeladen und XML ausgewertet: Backend4852 bestanden,
vier bekannte private/Opt-in-Skips, keine Fehler. Pflichtreferenzen u.a.
Original52, Zusatz359, Preisbestaetigung92+3 jeweils ohne Skip/Fehler.
Backend-JUnit-SHA `ce7e3351570f3445995ef1cca77cf73ccfc6da1a16ad5d0833c11d2770e6c465`.
Diese CI-Ergebnisse gelten NICHT automatisch fuer die neue Revision.

## Verbleibende Pakete und G-Matrix

Die Detailgrenzen der bisherigen Matrix bleiben erhalten:
`2026-10-28/blocker-closure/MATRIX.md`. Kein G-Fall erhaelt hier eine fachliche
Jahresfreigabe. Die nachfolgenden Kennzeichnungen beziehen sich auf den
synthetischen Scope, nicht auf produktive Vollstaendigkeit.

| Paket | Stand dieser Nacharbeit | Noch offen |
| --- | --- | --- |
| A Betrieb | Kein produktiver Eingriff; Quellinventur gelesen | Heutige reale Legacy-Zuordnung, Restore und Image-/Volume-Paritaet |
| B Bewertung | Bestehende Regeln unveraendert; Provenienz im Audit nicht erfunden | Reale Providerbelegdeckung und gebundene alte Preis-/FX-Entscheidungen |
| C Steuerlogik | Keine Steuerformel/Methode aktiviert oder geaendert | Sachverhaltsfreigaben, Depotaktivierung, historische Kostenbasis |
| D Import/Konten | Keine Originalimporte veraendert | Vollstaendige alte Quell-/Konten-/Reviewuebernahme |
| E Reports | Audit-Integritaet und partielle ID-Zuordnung implementiert | Vollstaendiger Detail-Sidecar; normaler UI-Weg und PDF/CSV/JSON-Fachzahlenabgleich |
| F Abnahme | Neue unveraenderte35-Gegenproben im Pflicht-CI | Reale Migration und unabhaengige fachliche Gesamtfreigabe |

| ID | Unveraenderter synthetischer Pruefumfang | Weiterhin keine allgemeine Abnahme |
| --- | --- | --- |
| G01 | EUR-Kauf/Teilverkauf/Restbasis | Alle Report-Fachzahlen |
| G02 | EUR-Erwerbs-/Verkaufskosten | Individuelle Kostenrolle |
| G03 | Nettoerwerb mit Tokengebuehr | Jeder Connectorvertrag |
| G04 | Drittasset-Lotverbrauch und Kostenrollen | Swapkostenrolle/Sachverhaltsbelege |
| G05 | Verknuepfter Token-Tausch | Spezialprotokolle/Slippage |
| G06 | Historischer Stablecoin-EUR-Kurs | Alle Beschaffungswege |
| G07 | Depeg statt Paritaet | Produktive Belege |
| G08 | Beide USD/EUR-Quotierungsrichtungen | Individuelle Ausfuehrungskurse |
| G09 | Begrenzter dokumentierter FX-Vortag | Universelle fachliche Referenztagsfreigabe |
| G10 | Alt-/Zukunftspreis blockiert | Saemtliche Altprovenienz |
| G11 | Global aktiv/Depotvorschau getrennt | Produktive Depotmethodenaktivierung |
| G12 | Eigenuebertrag mit Basis/Datum | Alle Netzwerkgebuehren |
| G13 | Rewardzugang und Verwertung | Privat-/Betriebssachverhalt |
| G14 | Unklare Herkunft bleibt Review | Vollstaendige Sphaerenklassifikation |
| G15 | Kalenderfrist/Jahrestag/Schaltjahr | Reale Originalzeitsemantik |
| G16 | Berliner Jahres-/DST-Grenzen | Exhaustive Zeitzonenabnahme |
| G17 | Preis-/Kauf-/Anfangsbestandluecken | Alle Kostenbasisbelege |
| G18 | Chain-/Contractidentitaet und Kollision | Generischer Multichain-FIFO |
| G19 | Belegte100:1-Konvertierung | Bridge/LP/zeitversetzte Umstellung |
| G20 | Idempotente Referenzimporte | Jeder Anbieter-/Formatwechsel |
| G21 | Eingangsbindung von Vorschauen | Jede externe private Quelldatei |
| G22 | Offline semantische Wiederholung | Generische PDF-Byte-/Prozessgleichheit |
| G23 | Vorschau ist keine finale Freigabe | Alle Fachzahlen aller Exportformate |
| G24 | Jahresregel und strikte Freigrenze | Persoenliche Gesamtsteuer |
| G25 | Unveraenderte Archive/Revisionen, synthetischer Restore | Neuer realer Image-/Restore-/Rollbacknachweis |

## Tatsaechlich ausgefuehrte Nachweise

Interpreter fuer alle folgenden Pythonbefehle: vorhandene gemeinsame
Python3.11-Testumgebung. Keine neue Venv, keine Paketinstallation fuer die Tests.
Umgebung: `PYTHONPATH=src STEUERREPORT_TEST_PRUNE_PASSED_DBS=1`.

| Befehl / Umfang | Ergebnis und Softwarebindung | Original-JUnit / SHA256 der unkomprimierten Bytes |
| --- | --- | --- |
| `python -m pytest tests/unit -n 4 --dist loadfile -q --basetemp=/tmp/steuerreport-issue52-unit-final-20261115 -o tmp_path_retention_policy=all -o tmp_path_retention_count=1 --junitxml=var/issue52-unit-final.xml` | 4981 bestanden /4 bekannte Skips /0 Fehler;870.42s. Runtimecode7886c53 vor einzeiligem I/O-Nachtrag,244 Runtime-/Konfigurationsdateien bytegleich. CI-Pruefskript und weitere Tests wurden separat erweitert; kein vollstaendiger Freeze aller Repositorydateien fuer diesen Lauf behauptet. | `unit-7886c53.xml.gz` / `729eb522da2d55729cb9fafab142a9a890073ae499706c62a3c027519733d9fa` |
| `python -m pytest docs/audit/2026-10-28/acceptance_tests.py -q --junitxml=var/issue52-reference-original-final.xml` | 52 bestanden /0 Skips/Fehler;100.85s; Runtime7886c53, noch vor I/O-Guard. Keine Sollwert- oder Oracleaenderung. | `reference-original-7886c53.xml` / `8956f773735391dfd633c31871b6075640e555fa403b4291f8956c5634c87508` |
| `python -m pytest tests/unit/test_tax_filing_audit_independent_review.py tests/unit/test_tax_filing_audit_identity_review.py tests/unit/test_tax_filing_audit_additional_review.py tests/unit/test_tax_filing_audit_io_review.py -q --basetemp=/tmp/steuerreport-issue52-reference-audit-final-20261115 --junitxml=var/reference-filing-audit.xml` | 35 bestanden /0 Skips/Fehler;5.74s; Runtime und Pruefskript d4ffd5e | `reference-filing-audit.xml` / `bdec3a0b0e8e93f335b1eb3ce3129cae85c91f4f838f27a9e90eecb216445e15` |
| `python -m pytest tests/unit/test_tax_filing_audit_api_errors.py tests/unit/test_tax_filing_audit_integrity.py tests/unit/test_audit_artifacts.py tests/unit/test_checkpoint_reference_guard.py tests/unit/test_audit_reference_guard.py -q --basetemp=/tmp/steuerreport-issue52-final-regression-20261115 --junitxml=var/issue52-final-regression.xml` | 166 bestanden /0 Skips/Fehler;7.61s; d4ffd5e, einschliesslich aller drei API-409-Pfade ohne DB-/Blockerdateiaenderung und des unveraenderten alten Admission-Guards | `final-regression.xml` / `e1feb0112b18bd5a98add52123e0032ee242fa529c3c3cb39b8ef422bf1c9224` |
| `python -m pytest tests/acceptance -q --basetemp=/tmp/steuerreport-issue52-additional-frozen-20261115 --junitxml=var/issue52-additional-frozen.xml` | 359 bestanden /0 Skips/Fehler;279.03s; d4ffd5e und460 vollstaendig unveraenderte Runtime-/Config-/Frontend-/Skript-/Abhaengigkeitsdateien vor/nach Lauf | `additional-d4ffd5e.xml` / `366ae4a3d1321ab4f4dc5b7e9afabcb65c6a00ec378886c2c15ddf0f91a8aeef` |
| `python -m pytest tests/unit/test_tax_filing_audit.py tests/unit/test_tax_filing_audit_api_errors.py tests/unit/test_tax_filing_audit_integrity.py tests/unit/test_tax_filing_audit_independent_review.py tests/unit/test_tax_filing_audit_identity_review.py tests/unit/test_tax_filing_audit_additional_review.py tests/unit/test_tax_filing_audit_io_review.py tests/unit/test_tax_filing_snapshots.py tests/unit/test_audit_artifacts.py tests/unit/test_checkpoint_reference_guard.py tests/unit/test_audit_reference_guard.py tests/unit/test_migration_readiness.py -q --basetemp=/tmp/steuerreport-issue52-api-final-20261115 --junitxml=var/issue52-api-final.xml` | 247 bestanden /0 Skips/Fehler;61.93s; 10c5667 nach dem letzten reinen Audit-Fehlerguard, einschliesslich der unveraenderten35 und sechs API-409-Proben | `api-final-10c5667.xml` / `df228ffb92c98ddefda975bec98114055506882db63868dcb159bc56b847fe05` |

Alle JUnit-Namen der Tabelle beziehen sich auf
`2026-11-15/issue52-integrity-evidence/`. Gzip-Dateien entpacken zu den originalen
JUnit-Bytes; Metadaten nicht entfernt. Zahlen verschiedener Laeufe werden nicht
zu einer vermeintlich eindeutigen Gesamt-Testzahl addiert.

Vollstaendiger Freeze-Beleg des359-Laufs: `source-freeze-d4ffd5e.json`,
SHA `3bdca26a2dcb1a9221b13c14f26b8cfb59c6bfbd4b69559e324f4c081b7dc163`;
`inputs-d4ffd5e.sha256` enthaelt dieselben460 Eingangsdateien.
Nach diesem Lauf wurde ausschliesslich die Ausnahmebehandlung fuer unlesbare
Audit-Referenzdetails verschaerft; keine Preis-/FX-/FIFO-/Steuerregel geaendert.
Die anschliessenden247 decken diesen Nachtrag ab. Keine Behauptung,4981 oder359
seien nach dem letzten Nachtrag erneut auf dem kompletten Stand ausgefuehrt.
Die neue GitHub-CI muss den integrierten Head separat pruefen.

Weitere ausgefuehrte Checks: `ruff check src tests scripts`,
`python scripts/export_openapi_v2.py --check`,
`python scripts/generate_api_endpoint_reference_v2.py --check`,
`python scripts/check_private_data_v2.py`,
`python scripts/check_reference_baseline_v2.py`,
`python scripts/check_reference_baseline_v2.py --audit-probes` und
`python scripts/check_reference_baseline_v2.py --audit-results var` bestanden.
Der neue Guard verlangt exakt35 erfolgreiche Faelle ohne Skip/Fehler.
Eine vorhandene Starlette/httpx-DeprecationWarning bleibt dokumentiert.

## Fehlversuche nicht als bestanden zaehlen

- Vorab-Unitlauf kontrolliert nach2282 erfolgreichen Faellen abgebrochen,
  Exit2/KeyboardInterrupt, um eine gefundene Cache-Isolationsluecke zu korrigieren.
  Kein vollstaendiger Erfolg. Original lokal `var/issue52-unit-frozen.xml`,
  SHA `66096592a0533cf4fec199a8c9ba582ffd1f6586fbf2132f404917c98e9e938a`.
- Falscher kombinierter Aufruf der Original52 mit `tests/acceptance`:
  16 failed/317 errors; der prozessweite DB-/Netzwerkguard der Originalprobe
  kollidiert mit der zweiten Suite. Getrennte Prozesse sind vorgeschrieben;
  kein Produktfehler und keine Abschwaechung der Guards.
  `combined-invalid-harness.xml.gz`, unkomprimierte SHA
  `b5ca92270c4254a885653ea0dcc97d20598720fc6110aedabf35811f30096ae7`.
- Erster getrennter Zusatzlauf:359 fachliche Assertions bestanden, aber ein
  abschliessender Freeze-Fehler wegen meines waehrenddessen erweiterten
  `scripts/check_reference_baseline_v2.py`. Daher NICHT als bestanden gewertet.
  `source-freeze-failed.xml.gz`, unkomprimierte SHA
  `543f19b30799b01841f1991a388941a2bc8766532d8050fb1e1ccaeea8be4e80`.
- Neue Guardprobe verwendete zuerst ein nicht installiertes optionales YAML-Modul:
  Collectionfehler, kein Produktfehler. Danach vorhandenes textbasiertes
  CI-Pruefmuster des Projekts verwendet, keine neue Abhaengigkeit; beide
  Referenzguards gemeinsam66 bestanden. Keine unveraenderte Oracledatei editiert.
- Zusaetzliche Koordinatorprobe mit manifestiertem, hashgueltigem CSV ohne
  Anschaffungskosten: drei API-Pfade antworteten zunaechst200 statt409 und
  materialisierten einen Vergleich trotz Lesefehler. Original
  `invalid-detail-before.xml`, SHA
  `e5b39649ac800934caccee30a11a3e7f9d86e2f4e7a676684b64da212a4898be`;
  3 failed/3 passed. Mit10c5667 kontrollierter Abbruch ohne Auditdatei,
  unveraendertes Referenz-ZIP; dieselben Assertions in den247 bestanden.

## Sicherheit und Betrieb

Gitleaks8.30.1 wie im Publishworkflow, Download-SHA verifiziert:
`551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb`.
Verzeichnispruefung einer isolierten Kopie der verfolgten Quellstanddateien mit
`.gitleaks.toml`, `--redact=100 --ignore-gitleaks-allow`; kein Git-History-Audit.
Zwischenstand:52 Rohfunde, alle52 exakt durch vorhandene individuelle
Quellzeilen-SHA freigegebene Test-/Beispielwerte;0 ungepruefte Funde,
0 private Kontodefaults. Kein neues pauschales Allowlisting.
Abschliessend80 Rohfunde: Die28 neuen Treffer sind14 jeweils zweimal
protokollierte Quellzeilen-SHA im460-Dateien-Freeze-Beleg, keine Zugangswerte.
Saemtliche460 Werte wurden mit den tatsaechlichen Git-Blobs von d4ffd5e
neu berechnet und abgeglichen. Fuer diese14 exakten Zeilen-/Regel-/Dateiwerte
wurde die vorhandene Einzelfreigabeliste ergaenzt; die bisherigen52 Eintraege
und Scannerregeln bleiben unveraendert. Keine Pfad- oder Regelpauschalausnahme.
Resultat:0 ungepruefte Funde und0 private Kontodefaults.
Prueflisten-SHA: `9bd3ecd9e888270d25d95080b50609d9cca049901f8e0ab8b19a8c9ce676b22c`.
Die Aenderung betrifft keine Steuerformel; sie erweitert die konservative
Laufzeit-Konfigurationsbindung. Nach diesem Sicherheitsnachtrag nochmals71
Release-/Referenzguard- und16 Publikationsproben bestanden. Kein erneuter
vollstaendiger4985-Testlauf auf diesem Nachtrag behauptet.
Kein Image gebaut, kein Release oder Deployment ausgeloest.

## Bedienbarkeit und Speicher

Gesonderte Nachinventur: `ISSUE19_WORKFLOW_NACHINVENTUR_2026-11-15.md`.
Keine neue Frontendansicht in diesem Diff, daher kein neuer Browsernachweis
behauptet. Der fehlende normale Detailaudit-Bedienweg bleibt in #52 offen.

Vorhandene Pythonumgebung wiederverwendet; keine Docker-Builds oder neuen
Venvs/Node-Installationen. Eigene beendete synthetische Testverzeichnisse wurden
nach Sicherung der Original-JUnit-Dateien entfernt, einschliesslich der rund
1GiB abgebrochenen und1.5GiB abgeschlossenen Unit-DB-Kopien. Keine produktiven
DBs, Originalimporte, alten globalen Belegordner oder Docker-Volumes geloescht.
Die Quellen-/Nachweisablage im Repo ist klein; grosse JUnit-Dateien liegen
verlustfrei gzip-komprimiert vor. Gemeinsame historische Testroutinen mit
festem /tmp-Root bleiben eine separate #30-Aufgabe, kein pauschales Prune.
