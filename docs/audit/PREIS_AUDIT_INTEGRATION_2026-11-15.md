# Preisabruf und Auditvergleich: Integrationsnachweis

Entwicklungsstand vom 15.11.2026, keine produktive Bereitstellung und keine
fachliche Gesamtfreigabe. Dieser Nachweis ergaenzt die bisherigen Uebergaben,
ohne deren engere Pruefgrenzen oder offene Punkte zu entfernen.

## Gebundene Ausgangsstaende und Diff

| Bestandteil | Unveraenderlicher Commit | Umfang |
| --- | --- | --- |
| Preis-/Journal-Draft #56 | `a5da06b42d7fc6e13ef4374f9e79a9bb4c7c592d` | Teilfehler, persistente Reservierung, lesende Auftragsauskunft und UI |
| Archiv-/Vergleichs-Draft #57 | `c748a2b9f3e722254c8e21c6ecdfc176584a427e` | Archivbindung, konsistenter Aggregatlesestand, Centdarstellung und Vergleichsumfang |

Der Integrationsbranch `codex/price-audit-integration-20261115` erhaelt beide
Elternstaende. Manuell zusammengefuehrt wurden die Frontendimports; OpenAPI
und Endpunktreferenz sind neu generiert. Hinzu kommen ein gemeinsamer
API-Regressionstest, CI-Ergebnissicherung und die beiden isolierten
Browserpruefungen als Pflichtschritte. Keine Versions-/Tag-Aenderung.

Reviewbarer Diff nach dem Commit:

```bash
git diff a5da06b42d7fc6e13ef4374f9e79a9bb4c7c592d...codex/price-audit-integration-20261115
```

## Neue gemeinsame Sollprobe

`test_partial_price_job_and_filing_comparison_share_state_without_reexecution`
verwendet ausschliesslich eine disponible synthetische Datenbank:

1. Ein synthetisches Referenzpaket enthaelt sechs Nullaggregate.
2. Zwei gemockte Preisabrufe speichern zwei Preise. Die nachfolgende Pipeline
   speichert einen synthetischen Derivatewert von 10 EUR und bricht dann ab.
3. Die API meldet Warnung und Pipelinefehler statt eines vollstaendigen Erfolgs.
4. Der gebundene Vergleich zeigt 10 EUR, eine Aggregatdifferenz und offenen
   Detailabgleich. Er erteilt keine Bestaetigung fuer eine Abgabe.
5. Die reine Statusabfrage liefert die urspruengliche Teilfehlerantwort. Ein
   erneuter Start derselben Kennung wird blockiert; Provider und Pipeline
   laufen jeweils nur einmal. Journal und Originalpaket bleiben unveraendert.

Das ist ausdruecklich kein Nachweis, dass eine teilweise ausgefuehrte Pipeline
aktuelle vollstaendige Steuerzahlen liefert. Der Vergleich liest gespeicherte
Aggregate; deren Bindung an alle Raw-/Preis-/Methodeneingaben bleibt offen.

## Tatsachlich ausgefuehrte lokale Pruefungen

| Pruefung | Ergebnis | Originalnachweis |
| --- | --- | --- |
| Gemeinsame Backend-/Vertragsauswahl | 218 bestanden, eine Starlette-Warnung | `var/price-audit-integration-tests-20261115.xml` |
| Unveraenderte unabhaengige Referenzproben | 52 bestanden, eine Starlette-Warnung | `var/price-audit-reference-results-20261115.xml` |
| Referenz-Integritaetspruefer | bestanden | Baselinehash `09f674b350a9a83943df8980bbceafd88821ee1400e03b5b22ea1ee0f8cd6bfb` |
| Frontend-Zustandstests | 10 bestanden | `node tests/run-dashboard-tests.mjs`; vorhandene SSR-Warnungen |
| Frontend-Build | bestanden | `npm run build`; vorhandene Warnung fuer grosses Bundle |
| Ruff | bestanden | `ruff check src tests scripts` |
| OpenAPI-/Endpunktreferenz | beide aktuell | Generatoren jeweils mit `--check` |
| Workflow-YAML | mit System-PyYAML lesbar, 5 Jobs | Testvenv enthaelt kein PyYAML; kein dortiger Parserfolg behauptet |
| Lesende Auftragsauskunft im echten React-Baustein | bestanden, 390/1440 Pixel | 8 synthetische Screenshots; keine externen Anfragen |
| Echtes React-Vergleichspanel | bestanden, 390/768/1280/1440 Pixel | 16 synthetische Screenshots; keine externen Anfragen |
| Historischer Preisablauf, isoliertes Backend | bestanden, alle vier Breiten | 12 Screenshots und `result.json`; 7 kontrollierte Mock-Anfragen, Raw/Canonical unveraendert |

SHA256 der beiden lokalen Original-JUnit-Dateien (keine nachtraeglich
zusammengestellte Ergebnisliste):

```text
790d24bbfbd60fd1417202938de01b3b5f7d03fc1d7416e8a682a56f3446dd86  price-audit-integration-tests-20261115.xml
9e8055aa3f993692e08f061cee6ed145f36e2fe4d45891a185ae929b0d3c3f47  price-audit-reference-results-20261115.xml
```

Die Dateien liegen lokal unter dem ignorierten `var/`, nicht als behauptete
GitHub-Artefakte vor. Der CI-Workflow erzeugt seine eigenen Originaldateien:
`mandatory-reference-results`, neu `backend-unit-results` und
`ux-browser-evidence` einschliesslich beider neuer Browserablaeufe. Ein lokaler
Erfolg behauptet keinen bereits abgeschlossenen Remote-Lauf.

Reproduzierbare Befehle ab Repositorywurzel, mit installierter Projektvenv:

```bash
PYTHONPATH=src python -m pytest -q tests/unit/test_current_backfill_partial.py tests/unit/test_external_backfill_partial.py tests/unit/test_legacy_fx_backfill_safety.py tests/unit/test_as_of_price_gate.py tests/unit/test_backfill_legacy_callers.py tests/unit/test_tax_filing_archive_binding.py tests/unit/test_tax_filing_snapshots.py tests/unit/test_tax_filing_audit.py tests/unit/test_read_snapshot.py tests/unit/test_openapi_contract.py tests/unit/test_api_endpoint_reference_generator.py --junitxml=var/price-audit-integration-tests-20261115.xml
PYTHONPATH=src python scripts/check_reference_baseline_v2.py
PYTHONPATH=src python -m pytest -q docs/audit/2026-10-28/acceptance_tests.py --junitxml=var/price-audit-reference-results-20261115.xml
PYTHONPATH=src python scripts/export_openapi_v2.py --check
PYTHONPATH=src python scripts/generate_api_endpoint_reference_v2.py --check
python scripts/check_current_price_status_browser_v2.py --output /tmp/steuerreport-price-status-browser-integration-20261115
python scripts/check_filing_comparison_browser_v2.py --output /tmp/steuerreport-filing-browser-integration-20261115
PYTHONPATH=src python scripts/check_historical_prices_browser_v2.py --output /tmp/steuerreport-price-audit-historical-browser-20261115
ruff check src tests scripts
cd frontend
node tests/run-dashboard-tests.mjs
npm run build
```

## Aktualisierte Integrationsmatrix

| Bereich | Implementiert / technisch geprueft | Weiter offen / keine Abnahme |
| --- | --- | --- |
| #49 Preis-Teilzustand | Gemeinsamer API-Test, persistente Warnantwort, kein erneuter Abruf beim Lesen, gleiche Kennung blockiert | Atomare Preis-/Pipeline-/Journaltransaktion, Wiederanlauf, Aufbewahrung und vollstaendige Idempotenz; neue Kennung kann erneut schreiben |
| #52 Vergleich | Hashgebundenes Archiv und ein gemeinsamer read-only DB-Lesestand; Delta/Cent-/Scope-Anzeige | Eingabeaktualitaet und vollstaendiger Ereignis-/Lot-/Tax-Line-Abgleich mit `reconciliation_failed` |
| A Betrieb / #53 | Keine produktive Aenderung; #55 absichtlich nicht integriert | Funktionierender neuer Restore, WAL-/CLI-Konflikte, Rollback und reales Image-/Volume-Manifest |
| B Bewertung | Vorhandene Preis-/FX-Sicherungen gemeinsam erneut getestet | Reale Anbieter-/Quellenabdeckung und alle fachlichen Bewertungsfreigaben |
| C Steuerlogik | Originale 52 Referenzproben unveraendert erneut bestanden | Keine Aktivierung einer Methode oder Jahresfreigabe; fruehere Grenzen gelten weiter |
| D Import/Konten | Raw und Canonical im isolierten Preis-Browserlauf unveraendert | Keine allgemeine Importvollstaendigkeit oder vollstaendige Konten-/Anbieterparitaet |
| E Reports/UX | Preiswarnung und Vergleichsumfang gemeinsam geprueft; neue Browserablaeufe in CI | Vollstaendiger PDF/CSV/JSON-Fachzahlen- und Detailabgleich |
| F unabhaengige Pruefung | Zweiter Agent pruefte Integration lesend und fuehrte Teiltests erneut aus; keine neuen Findings | Keine unabhaengige fachliche Gesamtfreigabe oder Produktabnahme |

Fuer G01-G25 bleibt die differenzierte
[Referenzmatrix](2026-10-28/blocker-closure/MATRIX.md) massgeblich. Dieser Lauf
wiederholt die unveraenderten Originalproben, erweitert deren sachlichen
Geltungsbereich aber nicht. Insbesondere schliesst er G25 nicht als aktuellen
Docker-Restore und G18 nicht als generische Multichain-FIFO ab.

## Review, Graph und Betriebssicherheit

- Unabhaengiges lesendes Integrationsreview ohne neue Findings; dessen
  Teiltestzahlen werden nicht zu den 218 Tests addiert.
- `code-review-graph` fuer den integrierten Arbeitsstand aufgebaut: 622 Dateien,
  12.369 Knoten, 172.129 Kanten. Dynamisch aufgeloeste Store-Aufrufe sind nicht
  lueckenlos zugeordnet; der Graph ersetzt weder Quellcode noch Laufzeittests.
- Alle Datenbanken und Anbieterantworten der neuen Tests sind synthetisch.
  Keine produktiven Container, Finanzdaten, Methoden oder Vaults geaendert.
- Keine Docker-Builds, grossen Datenbankkopien oder Loeschaktionen. Kontrollwert
  des Root-Dateisystems am Ende der lokalen Pruefung: 225 GiB frei. Das ist
  keine Zuordnung des Speicherverbrauchs zu einzelnen Releases.
- Kein vollstaendiger Gitleaks-Nachweis: das Werkzeug fehlt in PATH. Der
  Push-Privatsphaerencheck ist getrennt zu beurteilen.

Offene Issues bleiben offen; ein Draft ist weder ein Release noch eine
produktive Bereitstellung. Die bestehende Software bleibt unveraendert aktiv.
