# Preisbeleg-Zulassung und historischer Uebernahmenachweis

Entwicklung vom 15.11.2026 auf Draft #62,
`376bea69e80d7172049adfb3b57e70ca2b14d9eb`. Vertrag zunaechst in
`3c63df9` und `60aa074` festgehalten. Der vollstaendige integrierte
Commit und der begrenzte Diff stehen im Folge-Draft. Produktion, Container,
echte Finanzdaten und Freigaben wurden nicht verwendet oder veraendert.

## Ausgangsstand separat nachgewiesen

[CI 43741138133](https://github.com/zonfacter/steuerreport-v2-plan/actions/runs/43741138133)
fuer exakt `376bea69e80d7172049adfb3b57e70ca2b14d9eb`: alle fuenf Jobs
erfolgreich. Originalartefakte gelesen, nicht nur Workflowlabels:

| Artefakt | Tatsaechlicher Nachweis |
| --- | --- |
| `14173001149` Backend | 4.105 Faelle: 4.101 bestanden, vier bestehende private Skips, null Fehler/Errors; XML-SHA256 `e00f2eaa7ae011beda085f617f0f5144f00237995da3d9acc38a59fd2d92481b` |
| `14172149325` Referenzen | 52 Original + 359 erweitert + 68 Checkpoint + 43 Zeitbeleg, jeweils ohne Fehler/Skips. Zeitbeleg-XML `c75e64f1f40c65ce4fb47b3e954b4bb6f86556362f25bcdeaa5eaaa18a3e1bc9` |
| `14172468906` Browser | Vorhanden, nicht erneut als grosse Bildsammlung heruntergeladen. Joblog `132894345414` bestaetigt 284 Komponenten-, zwoelf native API/DuckDB-Komponenten- und 16 kontrollierte Appfaelle; native Quellenbindung `dfe0b542bd8a94c81aa38de3d9ddd7643eb0a98ada8de87586d34662a28342f0` |
| `14172218932` Docker | Beide synthetischen Vollbackup-/Verify-/Restore-/Restart-/Vault-Pruefungen erfolgreich; beide `result.json` mit SHA256 `d9d0d973b385d6ab3ca70297bcc21438f88fd07109284541bbf9ca2ab9385991` |

Diese Belege gelten fuer den Ausgangscommit, nicht ungeprueft fuer den
Folgebranch. Sie beweisen weder reale Alt-/Neu-Paritaet noch fachliche Freigabe.

## Anforderungen und Umsetzung

| Anforderung | Dateien | Implementiert / Grenze |
| --- | --- | --- |
| #63: keine Uebernahme nur aufgrund gleicher Entscheidungs-ID | `domain/historical_prices.py` | Typ, ID, Scope, Belegreferenz, exakter Previewhash-Payload, Erstellungs-/Aenderungsmetadaten pruefen; dieselbe Pruefung vor idempotenter Rueckkehr |
| Vorhandene lokale Quittung darf nicht widersprechen | gleicher Dienst | Wert, Typ, ID, Preisanzahl und Dateityp pruefen; keine stille Reparatur. Fehlende Quittung nach bestaetigtem Commit bleibt wiederherstellbar |
| Falsche alte Erfolgsaussage zuruecknehmen | `frontend/src/workspace/PriceWorkspace.tsx` | Bei Bindungs-/Integritaetsfehler alten Stand sichtbar, aber ungeprueft markieren; Erfolgstext entfernen, betroffenen Listeneintrag umbenennen, Uebernahme/Downloads sperren. Erfolgreiches erneutes Lesen setzt die Sperre zurueck |
| #46: ausdrueckliche positive Zulassung statt dauerhafter Nicht-EUR-Sperre | `contracts/price_evidence.py`, `domain/price_evidence.py` | Reiner versionierter Baustein: menschlich gepruefte Originalzuordnung und gebundene Zustimmung; Direkt-EUR, USD/FX und dokumentierte Tagesreferenzen. Noch kein nutzbarer Anwendungsablauf |
| Tatsachen nicht aus Labels erfinden | gleiche Module | Beobachtung, Tagesperiode, Publikation, Erfassung, Originalintegritaet und menschliche Inhaltspruefung getrennt. Kein amtliches/anbieterbestaetigtes Guetesiegel aus Dateihashes |
| Abgesicherte Referenzen | Referenzguard und CI | Zusaetzliche 131 plus 15 unveraenderte unabhaengige Gegenproben hashgebunden; bestehende Referenzdateien nicht angepasst |

Backendpfade relativ zu `src/steuerreport_v2/`. Kein neues DB-Schema, keine
Produktionsmigration, kein neuer Providerabruf oder Preiswriter durch die
reine Zulassungsfunktion. Sie liest Originalbytes aus einem bereitgestellten
Mapping, nicht aus Benutzerpfaden; Zeitzonenberechnung nutzt die IANA-Daten
der Laufzeitumgebung.

## Tatsaechliche Zwischen- und Abschlusspruefungen

| Pruefung | Ergebnis |
| --- | --- |
| #63 erste Gegenproben | 20 fehlgeschlagen; ein Teil der Vorab-Fixtures noch nicht voll isolierend, nicht als finale Abnahme gewertet |
| #63 bereinigte Rotprobe | 22 fehlgeschlagen, keine Errors; Original-JUnit erhalten |
| Historischer Preisworkflow nach Fix | 76 bestanden; danach zwei zusaetzliche SQL-Metadatenproben und Receipt-POST-/Unveraendertheitsassertions ergaenzt |
| Finaler historischer Preisworkflow | 78 bestanden, keine Fehler/Skips; vier bestehende Starlette-Warnungen. 24 neue Schutzfaelle sind Teil dieser Zahl |
| Native Browserpruefung | Gesamter bestehender Preisworkflow mit echtem Router und eigener DuckDB bestanden; sieben Mock-Provideraufrufe, null echte externe Anfragen, null Browserfehler. Zusaetzlich Bindungsfehler beim Lesen, Zuruecknahme alter Erfolgsaussage, erfolgreiche Neuvalidierung und abgelehnter Apply mit anschliessend gesperrten Eingaben. 16 Screenshots, vier Breiten |
| Neue positive Zulassung | Zunaechst 124 eigene + 131 unabhaengige Proben bestanden; nach Review-Korrekturen 126 eigene + 131 unabhaengige + 15 unabhaengige Reviewproben + 93 Legacy-Zeitproben = 365 bestanden |
| Referenzguard und Softwarewhitelist | Zehn bestanden, sechs unveraenderte Referenzhashes bestaetigt |
| Vollstaendiger integrierter Backendlauf | 4.399 bestanden / vier bestehende private Skips, null Fehler/Errors, vier bestehende Starlette-Warnungen, 766,21 Sekunden |
| Unveraenderte erweiterte Referenzen | 359 bestanden, null Fehler/Errors/Skips, eine bestehende Starlette-Warnung; 326,58 Sekunden |
| Frontend-Build | TypeScript/Vite bestanden, bestehende Warnung zur Chunkgroesse |
| Ruff, OpenAPI-/Endpunktdrift und private Defaults | Bestanden; `privacy_default_violations=0`, kein universeller Secret-Nachweis |
| CI-YAML-Struktur | Fuenf Jobs, verpflichtender Schritt mit beiden Referenzdateien, keine leeren Run-Schritte; System-PyYAML 6.0 verwendet, im Testvenv fehlend, nichts nachinstalliert |

Die vier uebersprungenen Test-IDs stimmen mit dem separat gelesenen
#62-CI-Original ueberein. Die fokussierten 78-/365-/10er-Laeufe und beide
neuen Referenzdateien sind bereits Bestandteil der 4.403 Backendfaelle;
nicht als zusaetzliche eindeutige Backendfaelle zaehlen.

Die neue 131er-Datei wurde vor Implementierungslekture eingefroren:
`tests/unit/test_price_evidence_acceptance.py`, SHA256
`da94ef9bc2c4b3031d640dfa12d56242ae286ba3b05d501f64e77451ff1bb325`.
Auf der Basis fehlten die Module: Exit 2, **ein Collection-Importfehler**,
keine der 131 Fachproben ausgefuehrt. Dies ist kein Nachweis von 131 vorherigen
Rechenfehlern. Der erste integrierte Lauf bestand mit allen 255 Faellen.

Die unabhaengige Nachpruefung fand trotz dieser positiven Unitproben:
zweite Mitternacht statt vollstaendigem lokalem Kalendertag (Havana) und
geerbte Decimal-Traps/Exponentgrenzen. Die neue unabhaengige Reviewdatei
ergab vor Korrektur sieben Fehler / acht bestandene Faelle. Sie enthaelt auch
die legitime Mitternachtsluecke von Sao Paulo. Hinzu kamen zwei eigene
rote Gegenproben gegen eine menschliche Umdefinition der Basis-EUR-Identitaet.
Die Korrekturen verwenden einen vollstaendig isolierten Decimal-Kontext,
vollstaendige lokale Tagesgrenzen und die bestehende EUR-Reservierung.
Danach alle 365 oben genannten Faelle bestanden. Beide unabhaengigen Dateien
bleiben unveraendert; die erneute begrenzte Quellpruefung fand keine weiteren
konkreten Befunde in diesem Delta, ist aber keine Gesamt-/Fachabnahme.

Reviewdatei `tests/unit/test_price_evidence_review.py`, SHA256
`841ab5bb008e8e435087118dd0c97df940090eaa9fccaf062dd555719e7d252d`.

## Befehle und Originale

Alle Pythonchecks mit vorhandenem Python-3.11-Venv,
`PYTHONPATH=src STEUERREPORT_TEST_PRUNE_PASSED_DBS=1` und disponiblen
Testverzeichnissen. Keine neuen Abhaengigkeiten installiert.

```bash
python -m pytest tests/unit -n 4 --dist loadfile -q --tb=short \
  --basetemp=/tmp/steuerreport-issue46-bound-full-unit-20261115 \
  --junitxml=var/issue46-bound-full-unit.xml
python -m pytest tests/acceptance -q --tb=short \
  --basetemp=/tmp/steuerreport-issue46-bound-reference-final-20261115 \
  --junitxml=var/issue46-bound-reference-final.xml
python -m pytest tests/unit/test_historical_price_workflow.py -q --tb=short \
  -n 4 --dist loadfile --basetemp=/tmp/steuerreport-issue63-apply-binding-final-20261115 \
  --junitxml=var/issue63-apply-binding-final.xml
python scripts/check_historical_prices_browser_v2.py \
  --output /tmp/steuerreport-issue63-native-browser-extended-20261115 \
  --browser-executable /root/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome
python -m pytest tests/unit/test_price_evidence.py \
  tests/unit/test_price_evidence_acceptance.py -q \
  --junitxml=var/issue46-bound-evidence-first.xml
python -m pytest tests/unit/test_price_evidence.py \
  tests/unit/test_price_evidence_acceptance.py tests/unit/test_price_evidence_review.py \
  tests/unit/test_price_time.py -q --junitxml=var/issue46-bound-evidence-final.xml
python scripts/check_reference_baseline_v2.py
npm run build # im vorhandenen frontend, gemeinsame node_modules nur verlinkt
ruff check src tests scripts
```

| Original | SHA256 |
| --- | --- |
| `var/issue46-bound-full-unit.xml` (4.399 bestanden / vier Skips) | `346efae9e57b2906e45c3a795e7f433bc612692132c1def3aa3e0cf7f3274670` |
| `var/issue46-bound-reference-final.xml` (359 bestanden) | `2c5334172cf2d6e910d8cff2d000a3337ac715da8b1267f20a8eb5756bab4677` |
| `/tmp/steuerreport-blockers-20261028-reference-tests/bootstrap-1g9xfoe6/source-freeze.json` (`unchanged=true`) | `cb27fa6e3826250b2b37ec753798228210ec6ebea253b835edd8744e0f91422f` |
| `var/issue46-apply-binding-before-final.xml` (22 rot) | `a41b3ddd4e0c6d7c82a137359949d348e691e2d6110626825177b15b5ab6463e` |
| `var/issue63-apply-binding-final.xml` (78 bestanden) | `1c2aa9925482376aa2a8663232f439f04f562d00e2d454c12b377c0f5d2dafb4` |
| `/tmp/steuerreport-issue63-native-browser-extended-20261115/result.json` | `c33543c7ac03b395b6fbbcf41a415d81060b93afc137479c43eee0fc05ba9435` |
| `var/issue46-bound-evidence-first.xml` (255 bestanden) | `06330e7bc90df6bfee534f1b667a8b1e938e57d8d1388652e4a9552f695b56a1` |
| `var/issue46-bound-review-before.xml` (sieben rot / acht bestanden) | `ae00261a1a723333da535711d03714d956828be921060300b2e632726ff6fe0f` |
| `var/issue46-bound-eur-before.xml` (zwei rot) | `433d8565b001af1344ef1b8a075f826aa5a5beab623c46feb6630bc38189263a` |
| `var/issue46-bound-evidence-final.xml` (365 bestanden) | `ee0de7f4ebc7406ab3549a10e2a120e4defd9d2c80462b35ae43f30e8bb3e590` |
| `var/issue46-bound-package.xml` (zehn bestanden) | `226d56fcc06d946516a1b93d760080adaf3c479e2cb6351bc37dc91931e5e04e` |
| Agent-Original `var/issue46-bound-reference/before.xml` | `b41c259c2ba4472580e5ae8044998acbf2c8d7804cb1ff624f6ad785e6decc4b` |

## Offene Integration und Abnahmegrenzen

- #46 bleibt offen: gespeicherte menschliche Entscheidung serverseitig laden,
  konkret ausgewaehlte Preis-ID und Original-Preview/-Apply binden. Keine
  Clientbehauptung als Zustimmung akzeptieren. Metadaten nur mit kenntlicher
  manueller Transkription, nicht als automatisch bestaetigte Originalfakten.
- #63 weiterer Listenpunkt, aus Quelle abgeleitet und noch nicht als neuer
  Browserfall reproduziert: `recent()` faengt ValueError/KeyError ab und
  blendet die betroffene Vorschau aus. Bei ausschliesslich schadhaften Eintraegen
  kann die UI noch faelschlich einen leeren Bestand statt eines Belegfehlers
  suggerieren. Explizite nicht bestaetigte Listeneintraege/Teilstatus und
  passende Browser-/API-Proben sind vor vollstaendiger Abnahme nachzuziehen.
- Ein neuer Reader darf nicht blind `get().applied` verwenden. Der bisherige
  Getter ist jetzt innerhalb einer Read-only-Transaktion; deren erster
  Verbindungsaufbau kann weiterhin `ensure_schema` ausloesen. Keine physisch
  schreibgeschuetzte Erstzugriffsgarantie behaupten.
- Vorschau-/Annahme-API, Benutzerformular, Original-/Methodenpruefung und
  konsistente neue Gate-/Run-Policy sind noch nicht angebunden. Bestehender
  Legacy-Guard bleibt wirksam, kein Preis oder echtes Review neu angenommen.
- Keine neue steuerliche Tageskursregel oder pauschale Uebertragung auf
  Zugewinn-/Unterhaltszwecke. Keine G01-G25-Gesamtabnahme, kein Nachweis
  produktiver Legacy-Paritaet oder einer erfolgreichen echten Jahresfreigabe.
- Zweiter begrenzter Quellreview von #63: keine neuen konkreten Findings;
  dabei genannte Testluecken fuer SQL-Metadaten, Receipt-POST, noch nicht
  uebernommene Vorschau und erfolgreiche Neupruefung anschliessend erweitert
  und lokal ausgefuehrt. Kein vollstaendiger Sicherheits-/Screenreader-Audit.

Siehe [Vertrag](ISSUE46_POSITIVER_BELEGPFAD_VERTRAG_2026-11-15.md) und
[Preisworkflow](../HISTORISCHE_EUR_PREISE.md).

## Speichergrenze

Vorhandenes Venv und gemeinsam verlinkte Frontend-Abhaengigkeiten benutzt;
keine npm-/Python-Installation und keine lokalen Docker-Builds. Nur zwei
beendete selbst angelegte rote Wegwerf-Testverzeichnisse dieser Runde (228
und 251 MiB) nach Sicherung der Original-JUnits entfernt. JUnit-SHA256
danach identisch, Quelltests und Browsernachweise erhalten. Keine echten
Finanzdatenbanken, Backups, fremden Arbeitszweige oder Docker-Volumes geloescht.
