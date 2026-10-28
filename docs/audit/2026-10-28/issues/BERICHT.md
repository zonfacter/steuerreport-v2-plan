# GitHub #2 und #3: Umsetzung und Nachweise

Entwicklungsstand `0.2.0rc33.dev0`, nicht veroeffentlicht. Der laufende
rc32-Container, dessen Volume, Methoden und Archivpakete bleiben unveraendert.
Diese Uebergabe ist keine steuerliche Jahresfreigabe oder Deploymentfreigabe.

## Aenderungen

| Auftrag | Umsetzung | Nachweis und Grenze |
| --- | --- | --- |
| #2 Date-CSV | Bitget-Zeitspalte Date, explizite Offsets vorrangig | Unveraenderte oeffentliche 15-Fall-Probe und CI-Referenzen |
| #2 Futures und Funding | Gemeinsamer Cash-Vertrag fuer Ledger und Derivate; native Amount plus signierte Fee, positive Rabatte; ausdrueckliche Netto-Spalte ohne erneuten Abzug | Mengen und unabhaengig vorgegebene EUR-Werte; keine Gleichsetzung von Margin/Ordervolumen und Ertrag |
| #2 neutrale Margin-Aktionen | adjust_margin_ifm/adjust_down_leverage erzeugen keinen erfundenen Wallet-Zufluss | Originalrohdaten bleiben unveraendert |
| #2 generisches derivative | Expliziten Typ und separates Gebuehrenbein erhalten | Kein allgemeines Raten unbekannter Gebuehrenkonventionen |
| #2 Altstaende | Falsche Brutto-/Netto-Normalisierung, alte Ledger-/Derivate-Ergebnisse und nicht berechnetes Funding blockieren | Zwei zusaetzliche unabhaengige Altstandproben; keine automatische Korrektur |
| #3 Einrichtung | Backend-Version, stabile/RC-Kanaele, gespeichertes Opt-in, Statusindikator und direkte Route #admin?tab=updates | Echte API, lokale Testdaten, vier Browserbreiten |
| #3 Abrufsteuerung | Cache-only GET, begrenzter fester GitHub-Release-Abruf, hostlokale Dateisperre, Cooldown, ETag, Fehler-/Teilstatus | Mock-HTTP und kontrollierte Uhr, kein echter GitHub-Lasttest |
| #3 Auftrag | Release-ID und Metadatenhash binden Ziel, kopierbarer Text sowie identisches TXT/JSON; Zwischenablagefallback | Spaeteres Release ersetzt gewaehltes Ziel nicht; keine Docker-/KI-Ausfuehrung |
| #3 Sicherheitsgrenzen | Fremde Notizen nur Text, keine Aufnahme in Handlungsanweisungen, keine Secrets in Anfrage/Fehlern | Commit und Image-Digest bleiben ausdruecklich unbekannt; keine automatische Image-Verifikation behauptet |

Massgebliche Dateien: `domain/derivative_cash.py`, `domain/derivatives.py`,
`ledger/balance.py`, `domain/review.py`, `importers/raw_normalizer.py`,
`importers/source_profiles.py`, `domain/updates.py`, `contracts/updates.py`,
`api/updates.py`, `frontend/src/VersionUpdates.tsx`, Router in `main.tsx` und
`workspace/view-state.ts`. Vollstaendige source-relative Pfade stehen im Diff.

## Fachliche Grenzen und bestehende Daten

Eine unklare Fee-Konvention wird nicht durch einen geratenen Abzug ersetzt.
Drittassetgebuehren bleiben trotz nachvollziehbarer Cash-Beine ein Reviewfall
fuer Lotverbrauch/Kostenzuordnung. Die hier korrigierte Derivate-Cashbewertung
ist keine pauschale Freigabe fuer jede Derivateart oder private/betriebliche
Zuordnung.

Bereits importierte Canonical Events werden nicht beim Lesen umgeschrieben.
Ein alter Derivate- oder Ledgerlauf wird gegebenenfalls als neu zu berechnen
markiert. Bei falscher Normalisierung reicht ein blosses Neuberechnen nicht;
zuerst ist die gebundene Originalzeile kontrolliert neu zu normalisieren.
Produktive Wiederholung/Migration benoetigt einen eigenen Auftrag mit
Sicherung, Vorschau und erklaerten Differenzen. Keine Review-Entscheidung
wurde angenommen, kein historisches Finanzdatum veraendert.

Update-Praeferenzen und Release-Cache sind nichtfinanziell. Die beiden exakten
Admin-Schluessel sind vom finanziellen Eingabehash ausgeschlossen; alle
anderen fachlichen Einstellungen bleiben gebunden. Die Fingerprint-Version
steigt auf v3, sodass eine bereits gebundene v2-Vorschau nicht still als neu
gepruefter Stand uebernommen werden darf.

## Testnachweise

Die Originalausgaben liegen bytegleich unter `evidence/`, SHA256 und exakter
Quellcommit in `evidence/manifest.json`. `changes.patch` ist der binaersichere
Diff gegen den vorher auf GitHub vorhandenen Auditstand. Vorherfehler werden
bewahrt und sind keine erwarteten Fehler des CI-Gates.

- Oeffentliche Originalprobe #2: rc32 vier von 15 bestanden, elf fachliche
  Fehler, keine Ausfuehrungsfehler. Neuer Stand 15 von 15 bestanden.
- Zwei unabhaengige Altstandproben: zuvor zwei Fehler, danach bestanden.
- Zwei Cache-/Sperrreproduktionen: zuvor falsches aktuell bzw. alter Fehler
  nach fertigem Lauf; im integrierten fokussierten Backendlauf bestanden.
- Fokussierte Backend-/Fingerprint-Pruefung: 102 bestanden.
- Gemeinsamer HTTP-Transport, Update-API und Cache: 103 bestanden. Zusaetzlich
  drei Defaultpfad-Proben mit echtem Limiter fuer Folgeseiten, 429 ohne Retry
  und fail-closed Koordinatorausfall bestanden.
- Fokussierte Bitget-/Bestandspruefung: 57 bestanden, drei bekannte private
  Belegskips; keine echten Belege durch synthetische Daten ersetzt.
- Urspruengliche unabhaengige Referenzen: 52 bestanden. Erweiterte Referenzen:
  104 bestanden. Die 17 neuen Bitget-Proben sowie der unveraenderte
  oeffentliche Reproducer sind verpflichtender Bestandteil des CI-Gates.
- Fuenf UI-Szenarien mit kontrollierten Antworten und ein zusaetzlicher
  Browserlauf gegen echten UpdateService/FastAPI mit gemocktem GitHub.
  Cooldown und lokale Wiederabfrage, Sechs-Stunden-Opt-in, gebundenes Ziel,
  Clipboardfallback sowie TXT/JSON geprueft. Keine Browserfehler, keine realen
  externen Anfragen, Finanz-Tabellen unveraendert.
- Responsive-Browsernachweise fuer 390/768/1280/1440 CSS-Pixel. Zusaetzliche
  Komponentenproben bei 380 Pixel. Kein unbeabsichtigter Seitenoverflow.
- Frontendbuild erfolgreich; vorhandene Warnung fuer ein Bundle ueber
  500 kB bleibt. Ruff, URL-/Decimal-Pruefung in UTC und Europe/Berlin,
  OpenAPI-/Endpoint-/Import-/KI-Dokumentationsdrift und private Defaults
  geprueft. Vollsuitenresultat siehe Manifest, bekannte Skips mit Originaltext.

Vorlaeufige Testadapterfehler sind gesondert bewahrt: Vergleich von
Create-/persistierten UTC-Datumsobjekten, erneutes Oeffnen eines schon
verwendeten httpx-Clients und ein Reproducer-Aufruf ohne den fuer dev0
erforderlichen `--expected-version`-Parameter. Diese Fehlversuche sind weder
fachliche Vorherfehler noch erfolgreiche Nachweise. Beim ersten Browseradapter
fehlte die Health-Fixture; der korrigierte isolierte Lauf ist separat bestanden.
Die erste Vollsuite ergab 2711 bestanden, vier bekannte Skips und einen echten
Integrationsfehler: Ein direkter httpx-Client verletzte das gemeinsame
HTTP-Limitierungsgebot. Der Guard wurde nicht gelockert. GitHub verwendet nun
den zentralen Transport mit zusaetzlich verschaerftem 512-KiB-Antwortlimit,
keinen Transport-Retries, maximal fuenf Starts und begrenzter Gesamtdeadline.
Der vollstaendige erneute Lauf wird separat als `unit.xml` eingefroren.

## Reproduktion

Aus dem Repository, Python-Abhaengigkeiten gegen `requirements-runtime.lock`
installieren, fuer `-n 4` zusaetzlich `pytest-xdist==3.8.0` installieren,
im Frontend die vorhandene Lockdatei verwenden:

```sh
PYTHONPATH=src python -m pytest tests/unit -n 4 --dist loadfile -q
PYTHONPATH=src python scripts/check_reference_baseline_v2.py
PYTHONPATH=src python -m pytest docs/audit/2026-10-28/acceptance_tests.py -q
PYTHONPATH=src python -m pytest tests/acceptance -q
PYTHONPATH=src python docs/audit/2026-10-28/issues/issue2-original.py --expected-version 0.2.0rc33.dev0
npm --prefix frontend run build
node scripts/check_workspace_state_v2.cjs
TZ=Europe/Berlin node scripts/check_workspace_state_v2.cjs
PYTHONPATH=src:scripts python scripts/check_updates_browser_v2.py --output /tmp/updates-ui
PYTHONPATH=src:scripts python scripts/check_updates_backend_browser_v2.py --output /tmp/updates-backend
```

Fuer Browserproben Playwright samt Chromium installieren oder
`--browser-executable` auf eine vorhandene kompatible Installation setzen.
Die Tests erzeugen nur eigene temporaere synthetische Datenbanken.

## Offene uebergeordnete Blocker

Die eindeutige Zuordnung der laufenden Legacy-V2-Datenbank, semantische
Alt-/Neu-Paritaet mit identischen Eingaben/Methoden, positive Kostenbasisbelege
und menschliche Einordnungen sind weiterhin nicht durch diese Issuearbeit
geschlossen. Gleiches gilt fuer eine produktive Migration mit neuem Image und
Restore-Nachweis. Die vorherige G01-G25-Matrix bleibt eine begrenzte synthetische
Referenzabnahme; die 52+104 Referenzlaeufe ersetzen keine fehlenden Originalbelege.
GHCR-Sichtbarkeit wird durch eine Release-Erkennung nicht bestaetigt.
