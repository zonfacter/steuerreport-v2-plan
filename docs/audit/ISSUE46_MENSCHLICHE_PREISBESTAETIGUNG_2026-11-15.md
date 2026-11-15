# #46: Menschliche Preiszeitbestaetigung - Integrationsstand

Stand 15.11.2026. Unveroeffentlichter Entwicklungszweig
`codex/issue46-human-price-admission-20261115`, Basis Draft #65
`88c49a5470839af2f78e60dafe36c59ed1ada6ba`.
Vertrag: `9e449721d3b991e26ab95a4f68f69c656a2f8018`.
Kein Merge nach main, Release, Produktivupdate oder produktive Zustimmung.
Der konkrete Implementierungscommit wird in der PR- und Issue-Uebergabe genannt.

## Implementierter vertikaler Pfad

| Anforderung | Dateien / Verhalten | Nachweisstatus |
| --- | --- | --- |
| Importbindung | Bestehender `price_import_evidence`-Reader; konkrete Preis-ID, Vorschauhash, Originale und aktuelle Identitaet | Gezielte integrierte Tests bestanden |
| Menschliche Angaben | `contracts/price_admissions.py`, `domain/price_admissions.py`; keine clientseitige Erfassungszeit, Decimal, UTC und strikte Pflichtbooleans | Gezielte integrierte Tests bestanden |
| Vorlage / Zustimmung / Widerruf | Unveraenderliche private Belegartefakte, transaktionale append-only Entscheidungen, idempotente Wiederholung | Gezielte integrierte Tests bestanden |
| Stichtags-Gates | `portfolio`, `divorce`, `as_of_price_gate`, `valuation_runs`; nur ausgewaehlte Preis-ID und exakter Cutoff, Belegzustand in vier Gatekopien | Gezielte integrierte Tests bestanden |
| Aktueller Lauf / Archiv | Beleg-/Methodenwechsel, Preiswechsel und Widerruf entwerten aktuellen Nachweis; archivierte Bytes unveraendert | Gezielte integrierte Tests bestanden |
| Nested DuckDB-Lesesnapshot | Bestehende READ-ONLY-Transaktion ausleihen statt widersprechender zweiter Dateiverbindung | Acht Snapshot-Tests bestanden |
| Formular | `PriceAdmission.tsx`, Einbindung unter verifiziertem Importbeleg; zwei Erklaerungen, keine Auto-POSTs, Widerruf getrennt | 352 kontrollierte Browserfaelle bestanden |
| Gateanzeige | `PriceAdmissionEvidence.tsx` getrennt von Legacy-Zeitdiagnose, keine Jahresfreigabe | 100 native Pruefschritte bestanden, vier Breiten |
| CI-Referenzpflicht | Elf Hashpins, genau zwei erlaubte Harnesskorrekturen, 92+3 vollstaendige gruen gepruefte JUnit-Ergebnisse | 46 Guardtests bestanden; GitHub-Lauf noch ausstehend |

## Tatsaechlich ausgefuehrte gezielte Tests

Vollstaendige Backendregression nach den Gate-/Scope-Fixes:

```sh
PYTHONPATH=src STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 python -m pytest tests/unit \
  -q -n 4 --dist loadfile --tb=short \
  --junitxml=var/issue46-admission-unit-frozen.xml \
  --basetemp=/tmp/steuerreport-issue46-admission-unit-frozen-20261115 \
  -o tmp_path_retention_policy=all -o tmp_path_retention_count=1
```

**4852 bestanden, 4 bestehende private Skips, 0 Fehler**, 878,69 Sekunden.
Original-JUnit (4856 Faelle), SHA256:
`9442ea24cc168a26d685f0d6e517f11a028c502d5d77f95753660b713900dc41`.
Vier Starlette-Deprecation-Warnungen wie in den vorherigen Laeufen.
Skips: drei Solscan-/Blockpit-/RPC-Belegfaelle und der ausdruecklich
opt-in-pflichtige private Usertransferbaum. Keine neuen Skips zur Gruenstellung.
Die fehlenden privaten Nachweise sind damit nicht abgenommen. Der nachfolgende
HTTP-Fix veraendert keinen Backendcode; seine UI-Abnahme wird separat ergaenzt.

```sh
PYTHONPATH=src STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 python -m pytest \
  tests/unit/test_price_admission_acceptance_v2.py \
  tests/unit/test_price_admission_identity_acceptance.py \
  tests/unit/test_price_admission_gates.py tests/unit/test_read_snapshot.py \
  tests/unit/test_price_admissions.py -q -n 4 --dist loadfile --tb=short \
  --junitxml=var/issue46-admission-integrated-second.xml \
  --basetemp=/tmp/steuerreport-issue46-admission-integrated-second-20261115
```

Ergebnis: **175 bestanden**, 0 Fehler, 0 Skips, 116,92 Sekunden.
Vier Starlette-Deprecation-Warnungen aus der vorhandenen Testumgebung.
Verwendeter Interpreter:
`/tmp/steuerreport-issue39-ci-venv-20261102/bin/python`, Python 3.11.
Das sind keine Produktivdaten und keine fachliche Methodenabnahme.

```sh
PYTHONPATH=src python scripts/check_price_admission_browser_v2.py \
  --output "$PWD/var/price-admission-integrated-browser-final" \
  --browser-executable /root/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome
```

Ergebnis: **352 Faelle bestanden**, 0 JavaScriptfehler, 0 externe Requests,
390/768/1280/1440 Pixel. Echte Komponente mit kontrollierter Mock-API, **kein**
Nachweis eines echten Backendablaufs. Quellen waehrend des Laufs unveraendert.
Original: `var/price-admission-integrated-browser-final/summary.json`.

```sh
PYTHONPATH=src python -B scripts/check_price_admission_native_browser_v2.py \
  --output "$PWD/var/price-admission-native-cleanup-final" \
  --browser-executable /root/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome
```

Ergebnis: **100 Pruefschritte bestanden**, vier vollstaendige synthetische
Lifecycles (390/768/1280/1440), 0 JavaScriptfehler, 0 blockierte Requests,
0 gemockte Admission-/Gateantworten. Echte React-Komponenten, echte
FastAPI-Routen und isolierte DuckDB; **kein vollstaendiger main.tsx-Test**.
Prepare, zwei Tastatur-Zustimmungen, Apply, Wiederlesen, Methodendownload
mit exakten Bytes, exakter Stichtag positiv, +1 Mikrosekunde negativ,
expliziter Widerruf und anschliessend negatives Gate. Nach Fixtureaufbau
alle 36 Nicht-Review-Tabellen unveraendert; vorhandene Entscheidungen und
Artefakte bleiben unveraendert, nur zwei Reviewzeilen werden angehaengt.
Die Instanz besitzt keine produktiven Daten und keine Providerverbindung.
Die native Browserprobe ist eine beobachtete Direkt-EUR-Quote. USD/FX und
Tagesmethoden werden separat durch die eingefrorenen API-/Bibliotheksproben
und kontrollierten Formularfaelle geprueft, nicht als echter Providerabruf.

Quellen waehrend des Laufs unveraendert. Die eigene UUID-Runtime wurde nach
Erfolg und geschlossenen Browser-/Serverkontexten entfernt. Protokolle,
Gate-/Lifecycle-JSONs, Download und acht Screenshots bleiben erhalten
(insgesamt rund 3 MiB statt 57 MiB mit vier synthetischen DBs). Bei Fehlern
oder `--keep-synthetic-runtime` bleibt die eigene Runtime zur Analyse erhalten.

| Originalnachweis | SHA256 |
| --- | --- |
| `var/price-admission-native-cleanup-final/summary.json` | `72df499242d4ae7e4e37a40a056588115e1dd8c0bc94a4f6ec56166ec18e6c13` |
| `var/price-admission-native-cleanup-final/source-freeze.json` | `77c71adc44338fe003afc338822c964dc1a15ac2718fd6a42ab44e6bc3b73af2` |
| `var/price-admission-integrated-browser-final/summary.json` | `fa923c4c6af62f9d4ca8c99ffac56b26c77cb5e8b01840d62d79e85a1dc22ffb` |
| `var/issue46-admission-integrated-second.xml` | `1fe51594359cdde89644405c024489e66c19704f4339107563c7c0c195dc0d9a` |
| `var/issue46-admission-review-fixed.xml` | `507d3f810eb9ea212d7051085305fea84e3acbf806ea9c86c8bad16d4fd11f97` |
| `var/issue46-admission-review-final.xml` | `f5625c888f89c43d36b8f30bda27affd845d3f15d1f6141c2792d66f5d12ecaa` |
| `var/issue46-admission-errorcache-final.xml` | `51a1e21753ec34ec5c1f8b3952145e224013f82a54a369ed5f77693af22e03cf` |
| `var/issue46-admission-ci-guard-final.xml` | `5f3cbf13e47ea8b0a8c6689c4abe307f7b49e45eec5e00e43ea3dd5d4e69574e` |
| `var/issue46-admission-original52.xml` | `32128bfde79b86db860920e7f1340d371576901a54f9b495878a44766592a0b3` |
| `var/issue46-admission-additional-frozen.xml` (359) | `4a02e129d3ca903b85d9bed286502f8f772b3ec4ab1c6584d4178a9b63318dbb` |
| `var/issue46-admission-originals/fx-identity-source-freeze.json` | `f5164285e89994bfec34db7448a2f2b425a94643e45a09737c475c5f68aa20e3` |
| `var/issue46-admission-originals/bitget-stale-source-freeze.json` | `dc13b5ee9dbc5510e042b519b24766ac97703241919564c22d6a27a89fe8c262` |
| `var/issue46-admission-originals/issue46-admission-additional-frozen-source-freeze.json` | `12bb93915d5b622623e4a65e9ea9ce3cb80aaee1ca566805e47759ba10ba8b98` |

Diese lokalen Originaldateien sind nicht als Produktivdaten oder Release
veroeffentlicht. CI erzeugt eigene Original-JUnit-/Browserartefakte unter
`backend-unit-results`, `mandatory-reference-results` und
`ux-browser-evidence`. Hashpins, Reportguard und beide Browserpruefungen sind
verpflichtend im bestehenden Workflow eingebunden; keine neue Infrastruktur.

Ruff ueber neue Vertrags-/Domain-/Gate-/API-/Test-/Browserdateien erfolgreich.
OpenAPI und vollstaendige Endpunktreferenz neu generiert; abschliessende
Driftpruefung erfolgreich. Sechs Paket-/OpenAPI-Tests bestanden. Frontendbuild
erfolgreich (bekannte Chunkgroessenwarnung), Privacy-Guard meldet 0 Verstosse.
Gitleaks ist in dieser Entwicklungsumgebung nicht installiert; kein neuer
Gitleaks-Nachweis wird behauptet.

## Offengelegte Fehlversuche und Korrektur

- Erste integrierte Probe: 107 bestanden, 54 fehlgeschlagen. Preis-ID wurde
  beim manuellen Integrieren an `snapshot()` statt `as_of_snapshot()`
  uebergeben. Die Auswahl war korrekt, aber die konkrete ID fehlte dem
  nachfolgenden Gate. Korrektur ausschliesslich im Produktcode; kein
  Abschwaechen der Gegenproben. Zweiter integrierter Lauf: alle 175 gruen.
  Original: `var/issue46-admission-integrated-first.xml`.
- Die unabhaengige Originalprobe mit 92 Faellen bleibt unveraendert archiviert.
  Ihr letzter Gateaufruf uebergab zwei UTC-Zeitpunkte als `as_of_date`
  (Datumvertrag). Die korrigierte v2-Probe aendert ausschliesslich diese
  beiden Parameternamen zu `as_of`; alle Sollwertbehauptungen bleiben erhalten.
- Ein frueher gemischter Testlauf wurde waehrend einer Quellcodeaenderung
  ungueltig: der bestehende Plan-Fingerprint sperrte zu Recht den Apply.
  Auch ein erster kontrollierter Browserlauf meldete trotz 352 funktionaler
  Erfolge eine Quellenaenderung. Beide gelten nicht als finaler Nachweis.
- Unabhaengiges Read-only-Review fand drei zusaetzliche Probleme: unveraenderte
  Belegquittung trotz neuer aktueller Preiswahl, positive Einzelquittung bei
  mehrdeutigem Scope und wiederholte All-Record-Scans. Originaler roter
  JUnit: `var/issue46-admission-review-before.xml`, SHA256
  `fb89c80b6bccf400af2835f749241d343e0304ca51f779ae3bf212ce3bc77914`.
  Der erste Nachlauf legte ausserdem einen unvollstaendigen Vergleich der
  verschachtelten Gatekopien offen. Beide Gatekopien je Cutoff werden nun
  gegen den frisch berechneten lesenden Gate verglichen; positive
  Einzelantworten pruefen dieselbe Scope-Eindeutigkeit wie der Resolver.
  Records und auch Scopefehler werden nur aufruflokal im selben Snapshot
  wiederverwendet, nicht ueber Requests hinweg gecacht.
- Nach Korrektur bestanden **232** gezielte Referenz-/Gate-/FIFO-Tests und
  anschliessend **6** Review-/Budgettests inklusive der verschachtelten Kopie.
  Originale: `var/issue46-admission-review-fixed.xml` und
  `var/issue46-admission-review-final.xml`. Eine weitere Nachpruefung bleibt
  getrennt vom Implementierungsnachweis.
- Der erste grosse Aufruf `pytest tests` vermischte die bewusst getrennten
  Unit- und Referenzsammlungen. Das Referenzmodul setzt vor Produktimporten
  ein leeres privates Bootstrap-Profil. Die Unit-FIFO-Fixtures fanden so
  nicht mehr ihre synthetischen Eigentumszuordnungen: 9 Fehler, 1567 Erfolge
  bis zum ausdruecklichen Abbruch. Keine FIFO-Produktkorrektur und kein
  veraenderter Sollwert; alle betroffenen FIFO-Proben liefen danach im
  vorgesehenen Unit-Kontext gruen (oben). CI fuehrt wie bisher
  `pytest tests/unit` und `pytest tests/acceptance` getrennt aus.
  Ein anschliessender Unit-Lauf wurde fuer den verschachtelten Gatefix nach
  1539 Erfolgen bewusst unterbrochen; auch dies ist kein Gesamtnachweis.

## Unabhaengige begrenzte Nachpruefung

Nach dem letzten Fix **6/6 native Gegenproben mit `-W error` bestanden**,
ohne weitere bestaetigte Befunde im vereinbarten Umfang. Enthalten sind
Scope-Mehrdeutigkeit fuer GET/Replay, geaenderte Preiswahl, verschachtelte
Gatekopie, einmaliges Lesen der Records und einmalige Validierung eines
fehlerhaften Scopes. Original im unabhaengigen Checkout:
`/tmp/steuerreport-price-admission-bounded-final-20261115.xml`, SHA256
`c9fc34f826b05e22f9b0a943c8d3043dce1bbd4abe2aeaf4fbc7763d72c4924d`.
Die geprueften Source-SHAs waren vorher/nachher identisch:

- `domain/price_admissions.py`:
  `a24e0ad97d3b6c0e019adb5bd8faa12cee46a37fff042b8be5cd9344dd49e466`.
- `domain/valuation_runs.py`:
  `48bb3b8917e314cd2cc29a5bf84550fc436dac5c8cc6d668977d4c68af046bfc`.

Die urspruenglichen roten Tests bleiben unveraendert archiviert.
Im portablen Unit-Gegenstueck wurde nur der absolute Entwickler-Sourcepfad
durch den vom Testdateipfad abgeleiteten Repositorypfad ersetzt. Die neuen
Fix-/Errorcache-Proben wurden unveraendert uebernommen. Keine Sollwerte
aus Produktivfunktionen, keine steuerliche Fachabnahme durch diese Reviewrunde.

## Bestehende Browserablaeufe

Zusaetzlich unveraendert ausgefuehrt:

- `scripts/check_price_import_evidence_browser_v2.py`: 180 kontrollierte
  Faelle bestanden, vier Breiten, 0 POSTs/Providerrequests/JavaScriptfehler,
  Quellen waehrend des Laufs unveraendert. Neues Formular bleibt geschlossen,
  Originalbindung startet keine Zustimmung.
- `scripts/check_historical_prices_browser_v2.py`: bestehender historischer
  Arbeitsbereich im echten Frontendbuild mit echtem isoliertem Preisrouter,
  26 Checkgruppen und 24 Screenshots bestanden. Originaldownload, manuelle
  Vorschau, bewusstes Apply, Status-Revalidation, Recent-Teil-/Fehlerstaende
  und automatische synthetische Abschnittssammlung bleiben erhalten.
  Providergrenze: `httpx.MockTransport`, 7 Mockaufrufe und 0 echte externe
  Requests. Raw- und Canonical-Objekte unveraendert. Dies ist kein echter
  Provider-/Produktivdaten- oder vollstaendiger Produktabnahmetest.

## HTTP-LAN und gepflegter Hashfallback

Die Schlusspruefung fand im neuen Formular direkte Aufrufe von
`crypto.subtle` und `crypto.randomUUID`. Diese APIs stehen auf einer normalen
HTTP-LAN-Origin nicht zur Verfuegung, siehe
[MDN subtle](https://developer.mozilla.org/en-US/docs/Web/API/Crypto/subtle)
und [MDN randomUUID](https://developer.mozilla.org/en-US/docs/Web/API/Crypto/randomUUID).
Der vorhandene `newRequestId()`-Helfer verwendet stattdessen
[getRandomValues](https://developer.mozilla.org/en-US/docs/Web/API/Crypto/getRandomValues),
das auch in diesem Browserkontext verfuegbar ist. Keine Math.random-UUID.

Neuer Helper `frontend/src/sha256.ts`: WebCrypto bleibt bevorzugt; nur bei
fehlendem `subtle` wird SHA-256 aus `@noble/hashes/sha2.js` verwendet.
Vorhandenes, aber fehlgeschlagenes WebCrypto wird nicht still umgangen.
Keine selbst geschriebene Kryptografie. Der Server prueft die Originalbytes
und deren Hash weiterhin unabhaengig. HTTP-Bedienbarkeit ersetzt keine
Transportverschluesselung, Authentifizierung oder VPN-Absicherung.

Die zuerst erprobte Version 1.8.0 wurde vor dem Commit verworfen: Nach der
[Upstream-Security-Policy](https://github.com/paulmillr/noble-hashes/blob/main/SECURITY.md)
werden nur Versionen ab 2.4.0 unterstuetzt. Der endgueltige Pin ist **2.4.0**,
ohne transitive Laufzeitabhaengigkeiten. SHA512 des geprueften Registry-Tarballs:
`sha512-X5XaVWZIBCT7HHZGm5I7ZQXDwLG+bGXuSrMQAW+7Zvl87h1kmc1ZB1VSRJcpUfoUrGQp4Fkoxm5kZ+Ms+aW+eA==`.
Lockfile und MIT-Volltext unter `frontend/public/third-party/` passen dazu;
keine unbeteiligten Lockeintraege geaendert. Isolierter npm-Audit meldet
0 bekannte Treffer zum Pruefzeitpunkt, keine allgemeine Sicherheitsgarantie.

Node 22 ist die dokumentierte Frontend-Buildbaseline wie im vorhandenen
Dockerfile; CI wurde von Node 20 auf 22 angeglichen. Der neue Enginevertrag
ist mindestens 20.19.0. Der vorhandene Host hat Node 18.20.4: der erfolgreiche
lokale Typecheck/Bundlerlauf ist nur eine Beobachtungsprobe und kein
Unterstuetzungsnachweis fuer Node 18. Es wurde kein Hostupgrade, neues
Node-Archiv oder zusaetzlicher Dockerlauf vorgenommen. Die Node-22-Pruefung
des konkreten Commits muss der GitHub-CI entnommen werden.

Aktuelle integrierte UI-Proben mit Pin 2.4.0:

| Probe | Ergebnis | Original / SHA256 |
| --- | --- | --- |
| Unveraenderte HTTPS-Formularprobe | 352 bestanden, 0 Fehler, keine Sourceaenderung | `var/price-admission-secure-noble240/summary.json`: `cd2bd9f133b3f9f111f65394be60ab1fc51960d0f4932c4849753c6ffbae6187` |
| Echte unsichere HTTP-Origin, kontrollierte Antworten | 52 bestanden, 4 Breiten, 0 JS-/Netzwerkfehler | `var/price-admission-http-noble240/summary.json`: `ee6be15febeae7f3f05006cfd8380f5424ebb5589634e4bbbeb302873af66fd8` |
| Echte Backendrouten / isolierte DuckDB | 100 Schritte bestanden, 4 Breiten, Runtime nach Erfolg entfernt | `var/price-admission-native-noble240/summary.json`: `595d388d5540d755f636494e318331d81bbb966ac5630c4bd15e46302cc8309b` |
| Nativer Source-Freeze | unveraendert | `var/price-admission-native-noble240/source-freeze.json`: `b8150ced3b7ab285d9d66614072c0503119cce0d545ab1a31678b53da02eee90` |
| Registry-/Lock-/Overlay-Pruefung | Integritaet / Lizenz korrekt, alte Umgebung unveraendert | `var/issue46-admission-originals/noble-2.4.0-supply-chain.json`: `947491195c99b528bed77bdae396f62298435a5f51d7ffac04033dccc2cc00e5` |
| Isolierter npm-Audit | 0 bekannte Treffer | `var/issue46-admission-originals/noble-2.4.0-isolated-audit.json`: `846fc260eb0bf70e6b21419d4cab9fcc61c224c7362324d4cbc8aebf8355f9bd` |

Die HTTP-Probe entfernt oder simuliert keine Browser-APIs: tatsaechlich
`isSecureContext=false`, `subtle` und `randomUUID` nicht vorhanden.
SHA-Sollwerte stammen aus Python hashlib und bekannten festen Vektoren,
nicht aus dem geprueften JavaScripthelper. Geprueft: leerer Hashvektor,
1 Byte, ASCII, UTF-8 und 2 MiB; leere/zu grosse Uploads bleiben gesperrt.
HTTP-Script und Original-352 laufen getrennt; letzteres blieb bytegleich
(`cc611225ccd8f7b5da922e6aceb528625e053ce77f1d32051b45779bf3ae65a4`).
Die neue HTTP-Probe ist ebenfalls ein verpflichtender CI-Schritt mit
Originalartefakten, kein echter Provider- oder voller Main-App-Test.

## Grenzen und offene Abschlussarbeiten

Abschliessende Zusatzregression nach dem gepflegten Pin 2.4.0:

```sh
PYTHONPATH=src STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 python -m pytest tests/acceptance \
  -q --tb=short --junitxml=var/issue46-admission-additional-noble240.xml \
  --basetemp=/tmp/steuerreport-issue46-admission-additional-noble240-20261115
```

**359 bestanden**, 0 Fehler/Skips, 288,44 Sekunden. Alle drei Original-Freezes
unveraendert. Der FX-/Identitaets-Freeze bindet 459 Dateien; deren aktuelle
Bytes wurden anschliessend nochmals vollstaendig mit dem Freeze verglichen.

| Original | SHA256 |
| --- | --- |
| `var/issue46-admission-additional-noble240.xml` | `17ccb483cbdbef59ad147af9bba3f43d489a5c661e90913c430628155c5dbc5f` |
| `var/issue46-admission-originals/noble240-fx-identity-source-freeze.json` | `2c73c61394b78e07764b672562443961029b4d1c333568e01cbb7c3577744559` |
| `var/issue46-admission-originals/noble240-bitget-source-freeze.json` | `dc13b5ee9dbc5510e042b519b24766ac97703241919564c22d6a27a89fe8c262` |
| `var/issue46-admission-originals/noble240-lot-origin-source-freeze.json` | `b7e474b1faf9a2f61c50198135249f59bc475e57bb85e1987c269cecc4f304d5` |
| `var/issue46-admission-final-guards.xml` | `0ac4ee639c28173110ae7fbbd20e3bfc64ea9812d95cf3c1848374b06c68e517` |

Finale Guard-/Softwarepaketprobe: 49 bestanden. Ruff, Privacy-Guard (0
Verstoesse), OpenAPI- und Endpunkt-Driftchecks erfolgreich. Frontendbuild
mit Pin 2.4.0 erfolgreich; bisherige Chunkgroessenwarnung bleibt bestehen.

- GitHub-CI fuer den veroeffentlichten Implementierungscommit noch offen;
  erfolgreiche lokale Laeufe ersetzen diesen Status nicht.
  Unveraenderte Original52: 52 bestanden, keine Fehler/Skips, 82,08 Sekunden.
  Zusatzreferenzen: 359 bestanden, keine Fehler/Skips, 363,73 Sekunden;
  alle drei Original-Source-Freezes unveraendert. Ein spaeter gefundener
  HTTP-LAN-Fix betrifft nur das Frontend und wird vor Uebergabe gesondert
  getestet; diese erste 359er-Probe bindet noch den vorherigen UI-Stand.
- Der abgefragte Code-review-Graph meldete `not_ready/empty_graph`.
  Keine graphbasierte Vollstaendigkeitsaussage; geprueft wurde mit
  Quellcode, festen Gegenproben und kontrollierten Laufzeit-/Browsertests.
- Keine Legacy-Datenparitaet, realen Providerbelege, produktive Zustimmung,
  neue Steuerregeln, Methodenaktivierung, Jahresfreigabe oder amtliche Abnahme.
- Personenfeld ist keine Authentifizierung. Hashes beweisen Bytebindung,
  nicht inhaltliche Richtigkeit oder Manipulationssicherheit gegen einen
  Administrator, der Software und Daten gemeinsam ersetzt.
- Legacy-Gegenproben bleiben unveraendert; Same-Day- und Tokenrisikoregeln
  werden nicht durch eine menschliche Preisbestaetigung ersetzt.
