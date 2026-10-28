# Unabhaengige Abnahme G01-G25

## Addendum b036b8a

Letzter gepruefter Freeze: **b036b8ad4212d08d719fedec7dbc7115cf5704a9**.
`audit/docker-migration-20261028` wurde vor dem Merge auf exakt diesen SHA
aufgeloest; gemergt wurde der konkrete SHA, nicht ein spaeter fortgeschriebener
Branch. Eigener Merge-Commit: `45349a4bb65e2eaa5647286a93a777621aa11b03`.
Vor Berichtsaenderung war `git diff b036b8a HEAD --stat` leer. Auch der
gesonderte Vergleich von `src`, `configs` und Versions-/Compose-Dateien war leer.

Realrun vom 28.10.2026, Start11:04:40UTC: **52 Teilproben, 51 PASSED,
1 FAILED, 0 skipped/xfail, 0 Collectionfehler, 135,51 Sekunden, Exitstatus1**.
Der strukturierte Vergleich beider XML-Dateien bestaetigt exakt dieselben
52Testnamen und Einzelergebnisse wie im ae8c30e-Lauf. Einziger Fehler bleibt
`test_G04_drittassetgebuehr_lotverbrauch_teilprobe`: BNB-Lotbestand
`1.000000000000000000` statt `0.9` nach der synthetischen Gebuehr0.1.
Dieser Failure bleibt ungefiltert rot, nicht xfail. Die nachstehende
G01-G25-Fallabgrenzung gilt mit unveraenderten Teilumfaengen weiterhin;
insbesondere keine Gesamtfreigabe und G08/G09/G18/G19 weiterhin nicht geprueft.

Der Testcode ist unveraendert, SHA256:
`09f674b350a9a83943df8980bbceafd88821ee1400e03b5b22ea1ee0f8cd6bfb`.
Keine Quellen-, Konfigurations-, Versions-, Fixture- oder Sollwertkorrekturen
durch diesen Abnahmelauf. Nach dem Merge wurde nur dieser Bericht editiert.
Die parallele Vollunit-Suite mit8isolierten Workern ist ein gesonderter
Koordinatorennachweis; ihre Ergebnisse werden hier nicht vereinnahmt.
Die Laufzeit ist unter dieser Parallellast kein Performancevergleich.

```sh
env PYTHONPATH=src:/tmp/steuerreport-connector-tools-20261026:/tmp/steuerreport-release-tools-20261025 \
  python3 -B -m pytest docs/audit/2026-10-28/acceptance_tests.py \
  --basetemp /tmp/steuerreport-migration-20261028-acceptance-tests/pytest-freeze-b036b8a \
  -q --tb=short \
  -o cache_dir=/tmp/steuerreport-migration-20261028-acceptance-tests/pytest-cache \
  --junitxml=/tmp/steuerreport-migration-20261028-acceptance-tests/freeze-b036b8a.xml
```

XML nur im eigenen synthetischen Testroot ausserhalb des Repos, SHA256:
`e2782bc8ae498995dcdbe05313c6d153bac0674a81cd6792f3e441bf00d0175f`.
Keine Produktivdatenbank und kein externer Netzwerk-/API-/KI-Zugriff.

**Neue Aenderungsflaechen nicht pauschal abgenommen:** Die seit ae8c30e
hinzugekommenen AsOf-/Divorce-Last-known-Diagnosepfade, der genaue
blocked-versus-stale-HTTP-Fehlervertrag und Registry-unpriced-Review sind keine
zusaetzlichen eigenen Proben dieses unveraenderten52er-Satzes. Die vorhandenen
G10-Steuer-/Coverage-/Review-/Export-Fixtures bleiben bestanden; das beweist
keine vollstaendige Pruefung aller Diagnoseaufrufer oder aller neuen API-Codes.
G21 prueft die Domain-PDF-Sperre, nicht separat den geaenderten HTTP-Fehlercode.
Ein neuer Blocking-Gate erfuellt weiterhin nicht den fehlenden G04-Lotverbrauch.

## Vorlauf ae8c30e

Gepruefter Freeze: **ae8c30eb3e4f36849a6b31ae26a7aaf35c60636e**.
Eigener Merge-Commit: `7d2f586646f47b325b9e10e9a51cd226cfe783d0`;
`git diff ae8c30e HEAD --stat` war vor Berichtsaenderung leer: treegleicher Stand.
Lauf vom 28.10.2026, Start 10:46:46 UTC: **52 Teilproben, 51 PASSED,
1 FAILED, 0 skipped/xfail, 0 Collectionfehler, 126,23 Sekunden, Exitstatus1**.
Die parallele Vollunit-Suite des Koordinators ist kein Nachweis dieses Berichts.

**Kein positiver Gesamt-Abnahmestempel:** G04 bleibt ein echter Fehler;
G08/G09/G18/G19 sind nicht ausgefuehrt und weitere Faelle nur teilweise
abgedeckt. Ein Blocking-Gate ist kein Ersatz fuer fehlenden Lotverbrauch.
Die 29 anderen zuvor roten Teilproben bestehen jetzt. Das sind Teilproben,
nicht 29 vollstaendig freigegebene Sachverhalte.

`acceptance_tests.py` wurde weder fuer den Freeze noch nach Ergebnissichtung
geaendert: SHA256 weiterhin
`09f674b350a9a83943df8980bbceafd88821ee1400e03b5b22ea1ee0f8cd6bfb`.
Keine Szenarienumdeutung, Formelstubs, Produktfixes oder xfails. Nur der echte
integrierte Stand wurde gemergt, danach ausschliesslich dieser Bericht editiert.
Weiterhin eigene synthetische DBs, Originalarchive und Testroot; kein
Produktivdatenbank-, Netzwerk-, externer API- oder KI-Zugriff und kein OPS-Edit.

### Aktueller Stand G01-G25

| Fall | Freeze-Ergebnis | Gepruefter Umfang / verbleibende Grenze |
| --- | --- | --- |
| G01 | PASS fuer Fixture | CSV -> Raw -> Canonical -> FIFO -> Jahreswerte -> CSV: Kosten40, Gewinn20, Rest6/Basis60. Keine separate PDF-Zahlenprobe. |
| G02 | PASS fuer Fixture | Echter CSV-Kauf100+EUR2 und Teilverkauf60-EUR1: Basis40.8, Gewinn18.2, Restbasis61.2. Keine Ausdehnung auf andere Gebuehrenarten. |
| G03 | PARTIAL PASS | Erwerbsassetgebuehr0.1: Menge9.9/Basis100. Spaeterer Verkauf und Doppelabzug nicht separat geprueft. |
| G04 | **FAIL** | BNB1 fuer20 gekauft, Folgeerwerb mit GebuehrBNB0.1: FIFO-Lotbestand weiter1 statt0.9. Lotverbrauch bleibt hart offen. EUR-Zuordnung und Doppelabzug nicht vollstaendig modelliert/geprueft; neuer Blocking-Gate heilt diese Probe nicht und wurde hier nicht separat als G04-Abnahme getestet. |
| G05 | PASS fuer Fixture |2BTC/Basis40 ->5ETH/Wert60: Gewinn20, ETH-Basis60, kein Fiatdeposit. Slippage/Widerspruchskurse nicht geprueft. |
| G06 | PARTIAL PASS |100USDT mit explizitem EUR-PricePoint0.72 ergeben72. Kein echter FX-Konvertierungs-/Anbieter-Rohantwortlauf. |
| G07 | PASS fuer Tax-Consumer-Fixture |100USDT bei Depeg0.6 ergeben60EUR statt Paritaet. Preisbeschaffung/Originalantwort nicht geprueft. |
| G08 | NICHT GEPRUEFT | Feste Richtungs-/Praezisionssollwerte vorhanden, kein ausgefuehrter FX-Consumeradapter. |
| G09 | NICHT GEPRUEFT | Wochenende/Feiertag mit expliziter FX-Policy und fehlendem FX nicht durchgespielt. |
| G10 | PASS fuer vertikale Fixtures | Alle7Proben bestanden: Alt-/Zukunftslookup abgelehnt, Coverage meldet Luecke, Tax verbraucht nicht den2021Kurs, Review blockiert, keine neue ETH-Ableitung aus Altkurs, JahresZIP vorlaeufig/nichtfinal. Keine Aussage ueber jede Preisquelle/FX-Policy. |
| G11 | PARTIAL PASS | Zwei Depots: Wallet10 vs global20, keine Methodenaktivierung/TaxRunSummary. Kein allgemeiner Methodenfreigabenachweis. |
| G12 | PARTIAL PASS | Eigenuebertrag4 traegt Basis40/Originaldatum2023-01-10 mit Transfertrace. Netzwerkgebuehr/Fremdbelege nicht durchgespielt. |
| G13 | PARTIAL PASS | Reward100 -> Basis100 -> Verkauf150/Gewinn50, Income100 getrennt nach Declaration/Review. Wirtschaftssphaere nicht bewiesen und nicht freigegeben. |
| G14 | PARTIAL PASS | Generisches Income100 bleibt Review-only100/Declaration0. Keine vollstaendige privat/betrieblich- oder Rewardartenmodellierung nachgewiesen. |
| G15 | PASS fuer Kalender-Fixtures | Jahresconsumer, CSV-Jahrestag trotz366Tagen und Berliner Planungsbeginn stimmen;29Feb/Jahrestag/Folgetag separat geprueft. Kein pauschaler Scope fuer Betriebsvermoegen/Derivate/unklare Rewards. |
| G16 | PASS fuer Zeitgrenzen-Fixtures | Winter-/Sommer-Folgekalendertage auch bei365Dauer-Tagen richtig; Berlin-Jahreswechsel, DST03Uhr und SQL-Berichtsjahr stimmen. Keine exhaustive Zeitzonenpruefung. |
| G17 | PARTIAL PASS, breitere Luecke offen | Fehlender Erwerb, Deposit ohne Herkunft, Reward ohne Preis bleiben getrennte Fixtures, ohne erfundene Canonicals/Lots und mit blockierendem Review. Keine vollstaendige Gaptaxonomie und keine Loesung positiver, aber unbelegter Marktbasis bewiesen. Der neue Nullbasisguard ist nicht durch eine zusaetzliche eigenstaendige52er-Probe abgedeckt. |
| G18 | NICHT GEPRUEFT | Kein eigener Chain-/Contract-/Mint-Konfliktlauf; keine automatische Symbolheilung angenommen. |
| G19 | NICHT GEPRUEFT | Belegtes Wrapping/Migrationsverhaeltnis noch ohne eigenen Consumerlauf. |
| G20 | PASS fuer Fixture | Gleicher CSV-Batch/Raw-IDs,2CanonicalEvents, Mengen/Gewinn/Lots nach neuem Rebuild semantisch unveraendert. Kein zusaetzlicher API-Import-Pipelinetest. |
| G21 | PARTIAL PASS | Alle3PDF-Bindungsproben bestanden: Daten, Preis und synthetischer Admin-Regelmarker sperren alten Download. Marker ist kein Nachweis fuer jede Regeldatei; historische Vorschauuebernahme nicht aktiviert/geprueft. Altarchivschutz separat G25. |
| G22 | PARTIAL PASS | Wiederholter Offline-FIFO-Lauf und CSVs fachlich gleich; technische IDs ausgeklammert. Kein separater Prozess-/PDF-Bytevergleich. |
| G23 | PASS fuer Export-Fixtures | Technische Exportierbarkeit von finaler Jahresfreigabe getrennt; echtes JahresZIP mit Vorschau/Runbindung/Dateihashes und README-Kennzeichnung; PDF-Modell und PDF-Inhalt alsVORSCHAU. Keine menschliche Freigabe gesetzt und keine vollstaendige PDF-Fachzahlengleichheit behauptet. |
| G24 | PASS fuer11Route-Fixtures | Reale POST-Route:599.99/600 fuer2023,999.99/1000 fuer2024; explizites confirmed=true bei bekanntem synthetic other0;4unvollstaendige Kontexte bleiben context_required mit Total/ReachedNone;2008/2027 unsupported; String-true wird422. final_filing_allowed bleibtfalse. Nicht jedes Jahr2009..2026 oder alle Negativ-/Validierungskombinationen geprueft. |
| G25 | PARTIAL PASS | Echtes JahresZIP archiviert; geschlossene synthetische DB+Archiv wiederhergestellt, Raw/Review/Secretmarker erhalten. Nach neuem Preisinput neueRevision, altes Archiv byteidentisch. Kein echter Vault-/Token-/Profil- oder Docker-Restore in dieser Welle; keine produktiven Daten herangezogen. |

### Finaler Befehl Und Beleg

```sh
env PYTHONPATH=src:/tmp/steuerreport-connector-tools-20261026:/tmp/steuerreport-release-tools-20261025 \
  python3 -B -m pytest docs/audit/2026-10-28/acceptance_tests.py \
  --basetemp /tmp/steuerreport-migration-20261028-acceptance-tests/pytest-freeze-ae8c30e \
  -q --tb=short \
  -o cache_dir=/tmp/steuerreport-migration-20261028-acceptance-tests/pytest-cache \
  --junitxml=/tmp/steuerreport-migration-20261028-acceptance-tests/freeze-ae8c30e.xml
```

Original XML ausschliesslich im eigenen Testroot, SHA256:
`f03edd35c4dfcb8d23da52b4a1e0096e4134102812fc1fcc80be79e750ddeeb5`.
Einziger Failure:
`test_G04_drittassetgebuehr_lotverbrauch_teilprobe`, unveraenderte Assertion
`remaining == Decimal("0.9")`, Istwert `Decimal("1.000000000000000000")`.
Die Baseline-Sollwerte/Artefakte bleiben zur Vergleichbarkeit erhalten.

## Historische Baseline

Status: Ausgefuehrt auf **unfixed Baseline 438cbd3dac11b0f0bfcc7f308f583f3837de5f85**.
**52 Teilproben: 30 FAILED, 22 PASSED, 0 skipped/xfail, 0 Collectionfehler**
im abschliessenden Baselinelauf (75,61 Sekunden). **Keine finale Abnahme.**
Eigener Branch `audit/docker-migration-20261028-acceptance`; keine Produktcode-
oder OPS-Worktree-Aenderungen, keine Produktivdatenbank und kein externer Zugriff.

Die festen Sollwerte stehen vor Adapterimplementierung in `SOLL` innerhalb
`acceptance_tests.py`. Sie folgen den vereinbarten synthetischen Referenzfaellen,
nicht Ergebnissen der zu pruefenden Preis-/Steuerfunktionen. Dezimalwerte sind
explizit; Zeitgrenzen sind feste Datums-/UTC-Angaben. Sie sind keine individuelle
steuerliche Beurteilung. G02 kapitalisiert belegte EUR-Erwerbskosten und zieht
direkte EUR-Verkaufskosten ab; fehlende Modellierung bleibt ein offener Befund.
G04/G14/G17 erhalten keine neue Annahme, um einen Test gruen zu machen.

Eigener Testroot ausserhalb des Repos:
`/tmp/steuerreport-migration-20261028-acceptance-tests`. Jede Probe erhaelt eine
eigene synthetische DB. Alle INET-Socketverbindungen inklusive localhost sind
gesperrt; HTTP erfolgt nur mit ASGI-TestClient im Prozess. DuckDB-Verbindungen
ausserhalb dieses Testroots sind gesperrt. Produktimporte sehen ausschliesslich
ein leeres synthetisches Privatprofil; Softwarekonfig und private Laufzeitpfade
sind getrennte eigene Verzeichnisse. Gemockt werden nur I/O-Pfade/Isolation,
keine Bewertung, Klassifikation, FIFO-Formel, Reviewentscheidung oder Sollwerte.
Keine globalen Unit-Tests veraendert, kein xfail fuer bekannte Produktfehler.

| Fall | Baseline / Reichweite | Tatsaechlicher Nachweis oder verbleibende Grenze |
| --- | --- | --- |
| G01 | PASS fuer Fixture | Echte CSV -> Raw -> Canonical -> FIFO -> Jahreswerte -> CSV; Kosten40, Gewinn20, Rest6/Basis60. Keine separate PDF-Zahlenprobe. |
| G02 | FAIL | EUR-Erwerbsgebuehr2 wird nicht kapitalisiert: verbrauchte Basis40 statt40.8. Soll Gewinn18.2/Restbasis61.2 bleibt fest. |
| G03 | PARTIAL PASS | Erwerbsassetgebuehr0.1 reduziert Menge10 auf9.9, Basis100 bleibt. Kein spaeterer Verkaufs-/Doppelabzugstest. |
| G04 | FAIL, weitere Teile offen | BNB1 gekauft; bei Folgeerwerb mit GebuehrBNB0.1 bleibt FIFO-Lotbestand1 statt0.9. EUR-Steuerzuordnung/Doppelabzug nicht modelliert oder freigegeben. |
| G05 | PASS fuer Fixture | EUR-Anschaffung von2BTC fuer40, Tausch in5ETH mit belegten EUR-PricePoints60: Gewinn20, ETH-Basis60, kein Fiatdeposit. Slippage/Widerspruchskurse nicht geprueft. |
| G06 | PARTIAL PASS | Steuerverbrauch100USDT mit explizitem EUR-PricePoint0.72 ergibt72. Keine Anbieter-Rohantwort-/FX-Konvertierungsprobe; daher kein vollstaendiger FX-Nachweis. |
| G07 | PASS fuer Tax-Consumer-Fixture | Echter gesetzter Depegkurs0.6 statt Paritaet liefert fuer100USDT60EUR Anschaffungskosten. Preisbeschaffung/Originalantwort nicht geprueft. |
| G08 | NICHT GEPRUEFT | Feste90EUR und Richtungs-/Toleranzsollwerte vorhanden, noch kein realer FX-Consumeradapter. |
| G09 | NICHT GEPRUEFT | Dokumentierte Wochenend-FX-Policy vs fehlender FX offen; keine FX1-Annahme. |
| G10 | FAIL vertikal | Alter2021Preis fuer2025 ausgewaehlt, Coverage meldet0Luecken, Tax verbraucht10EUR, Review erlaubt Export; Derived erzeugt neuen ETH-Kurs aus Altkurs. Jahresarchiv faelschlich export_ready. Zukunftskurs-Lookup ist bereits abgelehnt. |
| G11 | PARTIAL PASS | Wallet-Vorschau Gewinn10 vs global20 bei zwei Depots; kein Rebuild/Methodenaktivierung, keine TaxRunSummary erzeugt. Keine weitergehende Methodenfreigabe. |
| G12 | PARTIAL PASS | Verknuepfter Eigenuebertrag4 traegt Basis40 und Originaldatum2023-01-10, Transfertrace vorhanden. Netzwerkgebuehr/komplizierte Fremdbelege nicht geprueft. |
| G13 | PARTIAL PASS | CSV-Reward100 -> Lotbasis100 -> Verkauf150 -> Gewinn50; Income100, Declaration+Review100. Keine Belegung der privat/betrieblich-Sphaere und keine Freigabe dieser Annahme. |
| G14 | PARTIAL PASS | Generisches ungeklaertes Income100 wird Review-only100, Declaration0. Kein Nachweis fuer alle Rewardarten/Sphaeren oder eine finale Jahresfreigabe. |
| G15 | FAIL | Jahrestag01.03.2024 nach366Tagen faelschlich steuerfrei im Jahresconsumer und CSV; Berliner Planungsbeginn um1Stunde falsch. Folgetag und29Feb-Teilproben passen. |
| G16 | FAIL / Teilproben PASS | Berliner Folgekalendertage mit365Dauer-Tagen bleiben im Jahresconsumer faelschlich steuerpflichtig (Winter/Sommer). Jahreswechsel2024-12-31T23:30Z ->2025, DST03Uhr und SQL-Jahr passen. |
| G17 | PARTIAL PASS, groessere Luecke offen | Getrennte CSV-Fixtures fehlender Erwerb, Deposit ohne Herkunft und Reward ohne Preis: keine neuen erfundenen Canonicals/Lots; Review blockiert. Keine vollstaendige Luecken-Taxonomie oder positive, aber unbelegte Markt-Basis geloest; E/G17-Nullbasisguard noch nicht integriert geprueft. |
| G18 | NICHT GEPRUEFT | Kein Full-Chain-/Contract-/Mint-Konfliktlauf. Das CanonicalEvent-Modell hat keine gesonderten Chain-/Contractfelder; keine Symbol-Heilung erfunden. |
| G19 | NICHT GEPRUEFT | Belegtes Wrapping/Migrationsverhaeltnis100:1 als Soll abgegrenzt, noch kein eigener Consumerlauf. |
| G20 | PASS fuer Fixture | Byteidentische CSV liefert denselben Importbatch/Raw-IDs;2CanonicalEvents, Mengen/Gewinn/Lots semantisch nach erneutem Rebuild gleich. Kein separater API-Import-Pipelinetest. |
| G21 | FAIL / weitere Teile offen | PDF nach Daten-/Preis-/synthetischem Admin-Regelmarker weiter renderbar statt stale gesperrt. Marker ist kein Beweis fuer jede echte Regeldatei. Archivimmutabilitaet separat inG25; keine historische Vorschauuebernahme aktiviert. |
| G22 | PARTIAL PASS | Zwei echte Offline-FIFO-Rebuilds und CSVs semantisch gleich trotz technischer IDs. Kein separater Prozess-/PDF-Bytegleichheitstest; technische Metadaten bewusst nicht als Fachabweichung gewertet. |
| G23 | FAIL vertikal | Technical-only/final-Dimensionen fehlen; echtes JahresZIP export_ready=true, ohne Vorschau/Binding; PDF ohne expliziten Vorschauzustand. Keine menschliche Freigabe gesetzt. |
| G24 | FAIL / Baseline nicht implementiert |11echte Route-Proben:4Grenzen,4unvollstaendige Kontexte,2nichtunterstuetzte Jahre undStrictBool. Alle404 statt zugesagtem Consumer. Kein Fake-Consumer/Stub. |
| G25 | PARTIAL PASS | Echtes vom Produkt erzeugtes JahresZIP als unveraenderliche Referenz archiviert, geschlossene synthetische DB+Archiv wiederhergestellt, Raw/Review/Secretmarker erhalten; neuer Paketstand alsRevision+1, altes Archivbyteidentisch. Kein echter Vault-/Token-/Profilbeweis in dieser Welle. |

Teilproben, Mocks und reine Lookup-Tests erfuellen nicht den Gesamtfall. Echte
Fehler bleiben rot, nicht modellierte Teilumfaenge werden gesondert benannt.
Zum Zeitpunkt dieser Baseline wartete der finale Realrun auf den integrierten
Commit; sein inzwischen vorliegendes Ergebnis steht im ersten Abschnitt.

## Reproduktion Und Belege

```sh
env PYTHONPATH=src:/tmp/steuerreport-connector-tools-20261026:/tmp/steuerreport-release-tools-20261025 \
  python3 -B -m pytest docs/audit/2026-10-28/acceptance_tests.py \
  --basetemp /tmp/steuerreport-migration-20261028-acceptance-tests/pytest-baseline-complete \
  -q --tb=line \
  -o cache_dir=/tmp/steuerreport-migration-20261028-acceptance-tests/pytest-cache \
  --junitxml=/tmp/steuerreport-migration-20261028-acceptance-tests/baseline-complete.xml
```

Exitstatus1 ist fuer die ungefixte Baseline tatsaechlich eingetreten und wird
nicht maskiert. Der Testcode ist bewusst unter `docs/audit` statt der globalen
Unit-Suite. Szenarien bleiben fuer den integrierten Lauf unveraendert; nur eine
belegte Adapter-/Vertragsnamenskorrektur waere gesondert auszuweisen.

SHA256 Testcode im52er-Lauf:
`09f674b350a9a83943df8980bbceafd88821ee1400e03b5b22ea1ee0f8cd6bfb`.
SHA256 des zugehoerigen `baseline-complete.xml`:
`b1203aa0b3db8506b2d4879855fb576034757087cbf9db707c563477294f2818`.

Vorlaeufe: Systempython ohne die oben genannten lokalen Abhaengigkeitspfade
scheiterte an fehlendem `nacl`; nach Verwendung dieser Pfade wurde eine eigene
unpassende Test-Konfigurationsverzeichnisanordnung korrigiert. Der erste
vollstaendige Lauf hatte zudem zwei eigene CSV-Headerzuordnungsfehler (deutsche
Exportspalten statt angenommener englischer Namen). Diese sind behoben und
zaehlen **nicht** als Produktfehler. Der abschliessende52er-Lauf hat keine
Adapter-/Collectionfehler, sondern die oben dokumentierten echten Baselinefails.

Originale synthetische Laufartefakte und XML liegen ausschliesslich im eigenen
Testroot ausserhalb des Repos; keine Datenbank/ZIP/PDF im Commit. Es gab keine
neue Netzinstallation und keine Nutzung anderer aktiver Worker/Produktivdaten.
Zum Baselinezeitpunkt wurden Koordinatorensourcen nur fuer Schnittstellen und
Prototypen gelesen; die damals angekuendigten F04/G02/G17/G24-Korrekturen waren
noch nicht abgenommen. Der finale Abschnitt trennt jetzt deren getesteten
Umfang von weiterhin offenen oder nicht geprueften Sachverhalten.
