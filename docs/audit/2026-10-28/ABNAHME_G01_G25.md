# Unabhaengige Abnahme G01-G25

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
Finaler Realrun erst nach Mitteilung des integrierten Commits; dann Aufnahme
dieses Stands in den eigenen Checkout und erneute vollstaendige Ausfuehrung.

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
Koordinatorensourcen wurden nur fuer Schnittstellen/Prototypen gelesen; keine
Implementierung daraus in den eigenen Checkout uebernommen. Angekuendigte
F04/G02/G17/G24-Korrekturen sind in diesem Bericht **noch nicht abgenommen**.
