# G08/G09 Und Enger G10-Folgefix

## Auftrag Und Vertrag

Basis `ce51a9d42963e25cb7b96dda19efce0703c55b26`, isolierter Worktree
`/tmp/steuerreport-blockers-20261028-fx`, Branch `audit/blocker-fx-20261028`.
AGENTS und Blocker-Vertrag wurden vor Codeaenderungen gelesen/bestaetigt.
Quoteinheiten, Sieben-Tage-Regel und unveraendertes Transportbudget wurden
vorab mit dem Koordinator abgestimmt. V1-FX-Importer und BMF-FX-Helfer wurden
ausdruecklich in den Scope aufgenommen. Keine Taxformel, FIFO-Methode,
zentralen Contracts, Schema-, API- oder CI-Dateien editiert; keine Kinderagenten.

Nutzerquellen wurden jetzt nur lesend geprueft, nicht als bereits frueher
gelesen ausgegeben. Keine Browserprofile geoeffnet und keine Originaldatei
oder results.json ueberschrieben. Keine Originalsnapshots in diesen Commit kopiert.

| Nutzerdatei unter docs/blockpit-analysis/ | SHA256 |
| --- | --- |
| BMF-Quellenpruefung-2026-10-28.md | 41f23ab93085d3a48c49d8b27b59067a606d9ac54535264d95d8089e5c18a4f1 |
| Docker-Nachpruefung-18010-2026-10-28.md | d2c3a08f7b2a8577410b9ff3064cdf64ea0a4b4c40c92927d6861f3d8b4d9fc8 |
| v2-baseline-evidence-2026-10-28/reproduce.py | 8f7253ea8c8827f917f32cf87e46b0bc95d5e10313142ddd300965841c3b41eb |
| v1-baseline-evidence-2026-10-28/reproduce_v1.py | c550b126da25f14c714af01c34d7fc16ae6882e4c653d1e625782bbc2a61d898 |

Die beiden Original-Reproprogramme wurden gelesen, in dieser FX-Aufgabe
aber nicht erneut gestartet. Die neuen G08/G09-Tests sind unabhaengige
Consumerproben, kein behaupteter exakter Replay dieser Originale.

## Primaerquellen Und Technische Policy

Die ECB nennt EUR als Basis ihrer Referenzkurse und eine Veroeffentlichung
an Arbeitstagen, ausgenommen TARGET-Schliesstage. Die Referenzkurse dienen
Informationszwecken und sind nicht als tatsaechliche Ausfuehrungskurse
auszugeben. [ECB-Referenzkursseite](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html)

Frankfurter dokumentiert die Einheiten ueber base/quote/rate und die
Multiplikation des Ausgangsbetrags mit dem Kurs. Providergebundene Routen
verhindern eine unbeabsichtigte Verwendung des standardmaessigen
Provider-Mixes. [Frankfurter v2-Dokumentation](https://frankfurter.dev/),
[v1-Dokumentation](https://frankfurter.dev/v1/).

Die zusaetzlich angegebene ECB-Data-Portal-Methodikseite war beim gezielten
Abruf nicht erreichbar; sie wird nicht als gelesener Zusatzbeleg ausgegeben.
Es wurden nur Veroeffentlichungs-/Dokumentationsseiten konsultiert, keine
Rate-API angefragt und keine realen Kurse fuer Tests uebernommen.

Explizite technische Policy `fx_reference_on_or_before_max_7_calendar_days_v1`:

- Juengster tatsaechlich gelieferter Referenztag mit 0 <= Alter <= 7
  Kalendertagen; kein Rueckgriff auf einen kuenftigen Beobachtungstag.
- Wochenenden/Feiertage erzeugen keine kuenstlichen Beobachtungen. Der
  Oster-Montag-Test verwendet eine explizite Donnerstagsbeobachtung, keine
  aus einer Wochenendformel erfundene Feiertagsrate.
- USD/EUR ist EUR pro USD und wird multipliziert. EUR/USD ist USD pro EUR
  und wird lokal invertiert. Andere/fehlende Paarmetadaten, nichtpositive/
  nichtendliche Werte und widerspruechliche Raten am gewaehlten Tag ergeben
  keine zugelassene Referenz. Kein FX-1-Ersatz.
- In einer gemischten Zeitreihe sind korrekt bezeichnete Zukunftszeilen
  nicht als Referenz waehlbar; sie verhindern keine vorhandene vergangene
  Referenz. Ungueltige Metadaten werden nicht als anderes Paar umgedeutet.
- Decimal-Kontext 60 bei Inversion/Konvertierung; PricePoints erhalten die
  bestehende 18-Nachkommastellen-Speicherpraezision. Originalrate bleibt
  ungerundet als Belegwert erhalten. G08-Soll ist unabhaengig 90 EUR,
  maximale Toleranz 1e-17 EUR fuer den begrenzten Gegenratenstring.

Die Sieben-Tage-Grenze ist eine abgestimmte technische Zulassungsgrenze,
keine aus der ECB-Seite abgeleitete steuerrechtliche Freigabe und keine
Behauptung einer BMF-Zertifizierung. Tageskursmethode/F06 bleibt separat.

## Consumer Und Belegte Korrekturen

1. Historischer Einzelpfad: gemeinsamer Selektor statt abweichendem Parser.
   Vorher wurden inverse Metadaten verworfen, eine gueltige Vergangenheits-
   referenz wegen einer Zukunftszeile abgelehnt und konfligierende gleiche
   Tagesraten still ausgewaehlt.
2. Historischer Batch-/Automatic-Pfad: dieselbe Quotierungs-/Datumsregel;
   Jahres-Rohserie und bereits vorhandene SHA-/Previewbindungen bleiben.
3. ExternalPriceBackfillService: begrenzte Legacy-SQLite-Referenz statt
   unbegrenztem Rueckgriff; Scalar-Schnittstelle bleibt kompatibel.
4. V1FxCacheImporter: gleiche Auswahl, echtes source_rate_date wird nicht
   durch einen juengeren Cache-Zeilentag verdeckt. Legacy-FX-Datei read-only.
5. BMF-Preisremediation: Paar/Datum/Alter/Konflikte validieren statt blind
   Zeile 0 nehmen. Exakter FX-Antwortbody wird zusaetzlich im bestehenden
   Provider-Evidenzartefakt erhalten; SHA bezieht sich auf diesen Originalbody.

Bei vorhandenem source_rate_date-Feld ist ein leerer Wert ungeklaert und
wird abgelehnt. Bei aelteren Cache-Schemata ohne dieses Zusatzfeld ist der
explizite rate_date-Zeilentag die verfuegbare Datumsangabe; daraus wird kein
zusaetzlicher ECB-Publikationsnachweis erfunden. Vorhandener source_rate_date
muss <= Cache-Zeilentag sein und selbst innerhalb der Sieben-Tage-Grenze liegen.

FX-Provenienz im Legacy-Quelllabel ist additiv: bisheriger Praefix plus
`:fxref:` und URL-escaped kanonisches JSON mit base, quote, originalem rate,
reference_date, source und policy_id. Dies ist keine Verschluesselung und
keine neue externe Evidenzbehauptung. SHA-Verweise des neuen historischen
Workflows bleiben auf die echten gespeicherten HTTP-Originalantworten gebunden.

Source-Praefix-/Qualitaetsverbraucher wurden per Trace geprueft: insbesondere
usd_eur-/fx-/ecb-Erkennung in valuation.py und tax_years.py bleibt erhalten;
kein Consumer setzt einen kompletten unveraenderlichen V1-Quellstring voraus.
Die eine bisherige exakte Test-Source-Assertion wurde nach Genehmigung durch
exakte Pruefung von Praefix UND vollstaendigem Metadatensatz ersetzt. Die
bisherige MOBILE-Preisnumerik 0.00182 blieb unveraendert.

## Ausdruecklich Genehmigter G10-Folgefix

ExternalPriceBackfillService.run rief bei fehlendem Ereignistageskurs eine
Suche nach dem ersten spaeteren Kurs auf, verwendete auch dessen spaeteres
FX-Datum und schrieb den Preis auf den urspruenglichen Ereignistag zurueck.
Der Koordinator genehmigte das Stoppen dieses Pfads ausdruecklich.

Der alte Pipeline-Test fuer den 20.04.2023 mit erstem Kurs am 23.04.2023
wurde durch einen negativen Test ersetzt: nur der 20.04. wird angefragt,
kein Preis importiert, asset_usd_missing und keine Exportfreigabe. Dies ist
eine bewusst geaenderte gefaehrliche Erwartung, keine heimliche numerische
Lockerung. Getrennte positive External-Pipeline-Proben belegen einen
gleichdatigen 100-USD-Kurs -> 90 EUR in beiden Quotierungsrichtungen.
Die urspruenglichen Audit-/F52-Sollwerte und Dateien bleiben unveraendert.

## Interfaces Fuer Unabhaengige CI-Proben

- HistoricalPriceService.plan(HistoricalPriceQuery) -> plan_sha256;
  fetch(HistoricalPriceFetch mit request_id, plan_sha256,
  confirm_external_request=True) -> vollstaendige Vorschau.
- provider=defillama, scope=tax_required, strategy=standard prueft den
  Einzelpfad. scope=all_observed oder strategy=automatic prueft den Batchpfad.
- Vorschau: rows[].price_eur, fx_date, evidence_sha256, source; prices,
  prices_count, requests_started und evidence[].{provider,url,params,sha256}.
  Die Antwortbytes liegen unter service.root/evidence/<sha256>.body.
- Einzel-DefiLlama: /prices/historical/<timestamp>/<provider_id> mit
  coins[provider_id].{price,timestamp}; Batch: /batchHistorical mit
  coins[provider_id].prices[].{price,timestamp,confidence}.
- FX-Originalantwort: Liste aus {date,base,quote,rate}; Request bleibt auf
  /v2/providers/ecb/rates mit base=USD, quotes=EUR und begrenztem Datumsbereich.
  Die explizite inverse Paarantwort kann ebenfalls lokal verarbeitet werden.
- historical_price_collection.historical_fx(payload, day, positive, fail)
  behaelt das vorhandene Tuple (Decimal EUR/USD, ISO-Referenztag).
- historical_fx.select_fx_reference(payload, day) -> FxReference | None;
  Originalpaar/-rate, Referenztag, source und normalisierte rate_eur_per_usd.
- ExternalPriceBackfillService._usd_eur_rate(path, ISO-day) -> Decimal;
  fehlend weiterhin Sentinel 0, niemals 1. _usd_eur_reference -> FxReference
  oder None. Der Scalar ist keine neue Beleg-/API-Schnittstelle.
- V1FxCacheImporter.to_price_points(path, confidence) -> (Preview, PricePoints).
- BmfEventPriceRemediationService._fetch_fx(client, date) -> _FxResult | None;
  rate, rate_date, request_url, response_sha256, payload, response_body_utf8.

Transportbudget unveraendert: FX-HTTP-Anfragen und Retries zaehlen im
historischen outbound_scope, Inversion kostet keinen Request. Batch-Serie
wird aus dem bereits gebundenen lokalen Body wiederverwendet. Einzelpfad
cacht nach angefragtem Tag. Legacy-FX-Cachezugriff selbst benoetigt kein HTTP;
der alte External-run-Parameter attempted ist keine neu behauptete globale
Provider-/Tarifbudgetgarantie. Kein Lasttest oder realer Providerzugriff.

## Teststand

Baseline: 126 bestanden in 57.41 s. Neue negative Ausgangsproben nach
Korrektur eines Testadapters fuer ausgelassene optionale Preisfelder:
4 fehlgeschlagen, 24 bestanden in 13.51 s. Die vier echten Fehler sind oben
benannt. Erster breiter Fixlauf: 253 bestanden, nur die genehmigte alte
Source-String-Assertion fehlgeschlagen. Keine anderen alten Erwartungen
gelockert. Endlauf: **277 bestanden** in 124.71 s, keine Fehler/Skips.
Ein vorheriger gruener Lauf mit 274 Proben wurde um drei defensive
Decimal-/Originalbody-Randfaelle erweitert. Unverarbeitbare Daten bleiben None.

```bash
env PYTHONPATH=src:/tmp/steuerreport-connector-tools-20261026:/tmp/steuerreport-release-tools-20261025 \
  STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 python3 -m pytest -q -n 4 \
  tests/unit/test_fx_reference_cases.py tests/unit/test_historical_prices.py \
  tests/unit/test_historical_price_workflow.py tests/unit/test_automatic_price_resolution.py \
  tests/unit/test_pipeline.py tests/unit/test_as_of_price_gate.py \
  tests/unit/test_bmf_event_evidence.py tests/unit/test_bitget_strategy_fifo.py \
  tests/unit/test_blockpit_solana_preflight.py tests/unit/test_price_quality.py \
  --basetemp=/tmp/steuerreport-fx-tests-20261028-verified \
  --junitxml=/tmp/steuerreport-fx-tests-20261028-verified.xml
```

Quellcode blieb im Lauf eingefroren. Der Core wurde separat geliefert, damit
der Koordinator ihn vor dem anschliessend genehmigten AsOf-Callerfix
integrieren kann. Im Core-Commit benutzte AsOf noch den Scalar mit begrenzter Auswahl;
die zusaetzliche Originalpaar-/Referenztagbindung ist im zweiten Commit
separat nachgewiesen. Kein Portfolio-/Tax-Lookup wird dafuer geaendert.

Core-Commit: `d0c8d4f1a49ae5c64bb68a3e1ba7659fd8e530c1`.
JUnit `/tmp/steuerreport-fx-tests-20261028-verified.xml`, SHA256
`ff0280789717cc0759f6ef3f73754e2f333f848178bb6916a1ae17f1159166dd`.

## Zweiter Commit: AsOf-Referenzbindung

Die kleine Caller-Erweiterung wurde anschliessend explizit genehmigt:
AsOfPriceGateService.backfill konsumiert jetzt _usd_eur_reference und bindet
das originale Paar, die originale Rate, Quelle und den tatsaechlichen
Referenztag an Job-/PricePoint-source. Zieltag und FX-Referenztag werden nicht
gleichgesetzt. Das gilt auch fuer Dry-run-Jobs. Konvertierung mit Decimal60
und 18 Speicher-Nachkommastellen, keine neue Methode oder Finalfreigabe.

Neue Caller-Proben pruefen beide Richtungen mit Referenz Freitag 31.05.2024
und Ziel Sonntag 02.06.2024, jeweils Dry-run und echten Import in eine eigene
synthetische Test-DuckDB. Dry-run fuehrt keinen Providerrequest aus.
Stale/future Originalreferenzen werden vor dem ersten Providerrequest
abgelehnt; weder Preise noch FX1 entstehen. Der importierte PricePoint traegt
exakt dieselbe Referenzstruktur wie der Job. Der unveraenderte bestehende
AsOf-Providerwahlpfad wird mit einem DefiLlama-HTTP-Mock konsumiert.

Ein erster Caller-Testadapter erwartete faelschlich CoinGecko; diese zwei
neuen Mock-Erwartungen wurden auf den tatsaechlichen bestehenden Providerpfad
korrigiert. Kein Produkt-Provider-Routing und kein alter Sollwert wurden
dafuer veraendert. Ebenso wurde der gemeldete ungenutzte timedelta-Testimport
entfernt.

```bash
env PYTHONPATH=src:/tmp/steuerreport-connector-tools-20261026:/tmp/steuerreport-release-tools-20261025 \
  STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 python3 -m pytest -q -n 4 \
  tests/unit/test_fx_reference_cases.py tests/unit/test_as_of_price_gate.py \
  tests/unit/test_price_gate_diagnostics.py tests/unit/test_price_policy_regressions.py \
  --basetemp=/tmp/steuerreport-fx-tests-20261028-caller-final \
  --junitxml=/tmp/steuerreport-fx-tests-20261028-caller-final.xml
```

Ergebnis: **139 bestanden** in 53.33 s, keine Fehler/Skips. Ruff --select F
auf allen betroffenen Domain-/Testdateien: bestanden. git diff --check:
bestanden. Die Core-Abnahme mit 277 Proben bleibt ein separater Nachweis;
die 139 Caller-Proben sind keine neue Vollsuite oder produktive Abnahme.
Caller-JUnit SHA256:
`c3adce3e981c775bb8efcbd59c7da9994851d8649193f8a6b84deb9f53b16c06`.

Keine produktive Datenbank geoeffnet, kein Restore/Release/Push/Deployment.
Current-Portfolio-/Latest-FX-Logik und Reparaturskripte ausserhalb der hier
benannten historischen Consumer sind nicht pauschal mit abgenommen.
