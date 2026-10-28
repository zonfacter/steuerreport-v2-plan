# Paket B: Historische Bewertung / F02

## Auftrag Und Grenzen

AGENTS.md und Koordinatorvertrag VERTRAG.md wurden vor Codeaenderungen gelesen
und bestaetigt. Worktree: `/tmp/steuerreport-migration-20261028-prices`, Branch
`audit/docker-migration-20261028-prices`. Ausgangsstand:
`1aecfb131d189267a01a6303f5a9b67a5a99efe2`.

Eigener Schreibbereich: `domain/price_lookup.py`, `domain/valuation.py`, neuer
schmaler `domain/price_policy.py`, Preisregressionen und diese PRICES-Dokumente.
Die ausdruecklich nachtraeglich genehmigte Erweiterung umfasst
`domain/derived_prices.py` und zugehoerige Regressionen, um die Neudatierung
alter Quote-Kurse durch Ableitung zu verhindern. Kein eigener Eingriff in
Tax-/FIFO-Methoden, zentrale Contracts, Store/Schema, API, Versionen, aktuelle
Portfolio- oder eigene Divorce-Stichtagsmethoden. Keine Produktion, keine
Methodenfreigabe, keine produktive Anwendung von Preis-Preview-Paketen, kein Push/Release.

Koordinatorlieferungen wurden unveraendert cherry-gepickt:

- `ef24dbab505517944de1a546cefc840a99dd81d9`: additive zentrale
  PriceLookup-Contracts und Vertrag; lokaler Pick `fbd23d6`.
- `438cbd3dac11b0f0bfcc7f308f583f3837de5f85`: explizites
  `DuckDbStore.list_price_points(limit=None)` und 501-Punkte-Regression;
  lokaler Pick `b256ea0`. Default 500 und oeffentliche Listen bleiben begrenzt.

## Technische Policy

ID `historical_same_utc_day_not_after_event`, Version `1`:

- Zeitstempel werden nach UTC normalisiert; bisher naive Zeitstempel gelten
  wie bisher als UTC.
- Ersatzkurs strikt positiv, gleicher UTC-Kalendertag, Kurszeit nicht nach
  Ereigniszeit. Auch ein nur eine Sekunde alter Vortageskurs ist unzulaessig.
- Innerhalb dieser zugelassenen Menge gehen nicht abgeleitete Kurse vor
  abgeleiteten vor. Danach bleiben Zeit, Quellrang, Confidence, Quelle,
  Decimal-Kurs und vorhandene price_id die deterministischen Auswahlfelder.
- `allow_derived=False` verbietet Quellen mit normalisiertem `derived:`-Praefix.
  Die bestehende Solana-RPC-Coverage verlangt weiterhin nicht abgeleitete
  Kurse. SQL und Python behandeln auch fuehrende Tabs/Unicode-Leerzeichen gleich.
- Nur EUR besitzt die synthetische Identitaet EUR/EUR = 1. Kein USD-/Stablecoin-
  oder FX-1-Fallback. Belegte EUR-Gegenleistungen und getrennte Gebuehrenbeine
  werden nicht durch Marktkurse ersetzt.

Das ist eine ausdrueckliche konservative technische Zulassungsregel, NICHT die
Behauptung, das BMF verbiete eine dokumentierte genehmigte Tagesschlussmethode.
Andere Methoden brauchen einen eigenen gebundenen Methoden-/Freigabenachweis.
Dieser Auftrag erteilt weder einen solchen Nachweis noch eine Jahresfreigabe.

`price_policy.py` stellt Zulassungsgrund, Auswahl-Key und SQL-Praedikat bereit.
Lookup und DerivedPriceService laden explizit den vollstaendigen Preisbestand;
die fruehere Grenze von 1.000.000 geladenen Punkten entfaellt. SQL-Coverage und
Requirements verwenden dasselbe Praedikat fuer Asset-, Quote- und Fee-Rollen.

## Additive Entscheidungsschnittstelle

`HistoricalPriceLookup.at_or_before(asset, priced_at, allow_derived=True)`
behaelt `PricePoint | None` bei. Die additive Domain-API lautet
`explain(asset, priced_at, allow_derived=True, candidate_limit=50)`.
Sie ruft denselben Selektor auf, ist read-only und kein neuer HTTP-Endpunkt.

Vom Koordinator vereinbarte und gelieferte Felder:

| Modell | Felder |
| --- | --- |
| PriceLookupDecision | policy_id, policy_version, asset, event_time, allow_derived, status, rejection_reason, selected_price, candidates, candidate_count, candidates_truncated |
| PriceLookupCandidate | price (vollstaendiger vorhandener PricePoint), rejection_reason, selected, provenance_status |

Status: `selected`, `missing` oder `fiat`. Fehlende Auswahl:
`no_candidates` oder `no_eligible_candidate`. Kandidatenablehnung in fester
Prioritaet: `non_positive`, `future`, `different_utc_day`, `derived_disallowed`.
Ein zugelassener, aber nicht ausgewaehlter Punkt hat keinen Ablehnungsgrund und
`selected=False`; dies ist keine weitere Methodenentscheidung.

Diagnostik standardmaessig 50, harte Obergrenze 1000, Untergrenze 0. Die
Kandidatenzahl zaehlt den vollstaendigen Asset-Snapshot. Bei Kappung bleibt
`selected_price` vollstaendig erhalten, auch bei Limit 0. In einer nichtleeren
Diagnostik steht der ausgewaehlte Punkt zuerst, danach zeitlich nahe Kandidaten.

PricePoint enthaelt price_id, Asset, Decimal-Kurs, Quelle, Kurszeit und
Confidence, aber keine strukturierten Raw-/FX-Belegbeziehungen. Deshalb
`provenance_status=not_linked`; Quellnamen sind kein erfundener FX-Nachweis.
Nur EUR-Identitaet meldet `synthetic_fiat_identity`. Vorhandene Quellzeichenketten
werden unveraendert transportiert, daraus werden keine neuen Hashes oder
Belegverweise abgeleitet.

## Verbraucher-Trace

Alle folgenden bestehenden `at_or_before`-Aufrufer erben die Policy, ohne dass
ihre Module hier editiert wurden. Die Liste stammt aus Quellcode-Trace, nicht
aus der Behauptung, jede Fachfunktion sei in dieser Teilaufgabe voll getestet.

| Verbraucher | Nutzung / Grenze |
| --- | --- |
| tax.py:_asset_value_eur | Historische Asset-/Quote-/Gebuehrenbewertung; fehlender Preis kann vorlaeufig 0 erzeugen. |
| tax_years.py:_event_price_context, Stablecoin-Preview | Preisdiagnose durch HistoricalPriceLookup. Separater Income-Index siehe G01. |
| valuation.py:PriceCoverageService | Python-Pruefung und SQL fuer Report/Requirements; Solana weiterhin nicht abgeleitet. |
| derivatives.py:_line_from_event | Fehlender Preis = 0 mit price_source=None und fehlendem Preis im Summary. |
| flows.py | Event-EUR-Gegenleistung bleibt vorrangig, sonst Historien-Lookup. |
| swap_valuation.py | Historische erhaltene/gegebene Beine. |
| bmf_event_evidence.py:_one_price | Preis-Evidenzdiagnose; fehlender Punkt bleibt missing. |
| blockpit_solana_preflight.py | Historische Preisdeckung fuer Referenzzeilen. |
| bitget_strategy_reconstruction.py | Historische Rekonstruktionsdiagnose. |
| moonpay_receipts.py | Historische Receipt-/Wertdiagnose. |
| raw_normalizer.py:Binance Small Assets | Historische nicht abgeleitete Preisgewichte; bestehender Mengenfallback unveraendert. |
| portfolio.py | Historische Checkpoints/Serien, teils allow_derived=False; geerbte Lookup-Aenderung, keine eigene Portfolio-Methodenaenderung. |
| divorce_capital_flows.py | Historische Ereigniswerte erben Policy. |
| divorce_service_routes.py | SOL-Wert am angefragten Zeitpunkt erbt Policy. |
| scripts/run_hnt_legacy_reward_price_repair_20260626.py | Bestehender Reparaturplan konsumiert Lookup; Skript nicht ausgefuehrt. |

Zusaetzlicher Ableitungspfad: DerivedPriceService prueft Quote->Asset,
Asset->Quote und gleichzeitige Gegenfluesse mit demselben Python-Helfer.
Fehlende, nichtpositive, alte oder kuenftige Anker erzeugen keine neuen
EUR-Kurse. Im transienten Ableitungsbestand werden PricePointCreate-Objekte
ohne erfundene price_id gefuehrt; vorhandene PricePoints behalten ihre IDs.
Primaerquellen gehen auch hier vor spaeteren gleichtaegigen abgeleiteten vor.

`fiat_price_point`-only-Verbraucher (sources, cockpit, workspace, review,
observed_price_requirements) erhalten weiterhin nur EUR/EUR = 1. Eigene
Latest-/Stichtagslisten sind nicht versehentlich in diese Domain-API integriert.

Weitere SQL-Pfade wurden abgegrenzt:

- `observed_price_requirements.py` bindet positive Tageskurse bereits an den
  fruehesten beobachteten Ereigniszeitpunkt. Kein alter/Zukunfts-Fallback.
  Es ist eine breitere Planungsinventarsicht, keine steuerliche Freigabe.
- `wallet_fifo_runs.py` liest `priced_at <= cutoff` fuer Input-Fingerprints
  und Inventar, nicht als Kursauswahl. Nicht einschraenken.
- `db.price_point_at_or_before` hat keinen Produktionsaufrufer im Trace,
  nur einen Portfolio-Test; unbenutzte Roh-Store-Hilfe nicht umdefiniert.
- `divorce.py:_prices_as_of`, aktuelle Portfolio-/Quelllisten und
  TaxService.holding_period_report verwenden separate Stichtags-/Latest-
  Semantik. Nicht in dieser Teilaufgabe geaendert oder pauschal freigegeben.

## Unabhaengige Repros Und Nachweis

Die angekuendigten Nutzer-V1/V2-Reprodateien lagen nicht vor. Die neuen Tests
sind eigene Repros mit echter DuckDB und realen Domain-Services, kein exakter
Replay und kein Vergleich mit einem behaupteten V1-Sollergebnis. Netzwerk ist
durch die bestehende Testfixture gesperrt. Keine Produktivdatenbank verwendet.

Baseline der bestehenden Tests: 55 bestanden, 3 belegbedingt uebersprungen.
Eigene Repros VOR Implementierung: 4 fehlgeschlagen, 4 bestanden:

- 1.642 Tage alter HNT-Kurs 7 wurde fuer 4 verkaufte HNT als 28 EUR Erloes
  zugelassen; Coverage/Requirements meldeten keine Luecke, Export war offen.
- Alter USDT-Kurs konnte ueber alle drei Ableitungsrichtungen frisch datierte
  HNT-Kurse erzeugen und in den Steuerpfad gelangen.
- Zukunftskurse wurden in diesen acht Ausgangstests bereits abgelehnt.

Unabhaengige Algebra der korrigierten Repros: Kauf 10 HNT fuer 20 EUR,
Verkauf 4 HNT ohne zugelassenen Kurs: Anschaffungskosten 4/10*20 = 8 EUR;
Erloes 0 ist nur vorlaeufig, nicht steuerlich final. Coverage und Requirements
nennen HNT/2025/Ereignis und Review blockiert mit
`price_coverage:asset:HNT:year:2025:source:manual-test:event_type:trade:role:asset`.
ExportReadiness ist false, Paket ist blocked und nicht renderbar. Die
EUR-Gegenprobe mit 28 EUR belegtem Verkaufserloes bleibt 8 EUR Basis und
20 EUR Differenz. Ein abgeleiteter fehlender Einkommenskurs bleibt ebenfalls
0-Basis mit expliziter Income-Preis-Luecke und gesperrtem Export.

Zwei bestehende Ableitungstests erhielten ausdrueckliche gleichtaegige
USDT/EUR-Fixtureanker am 02.01.2021 bzw. 01.03.2021. Vorher beruhten diese
Szenarien auf stiller Wiederverwendung des Kurses vom 01.01.2021. Keine
bestehende numerische Erwartung wurde gelockert oder geaendert. Die fehlende
Ankerdeckung ist separat mit negativen Repros getestet.

Drei bestehende Nettofluss-/Wallet-Merge-Tests benoetigen ebenso explizite
Tagesanker fuer den zweiten Ereignistag (29.04.2021 bzw. 02.01.2024).
Auch dort bleiben alle bestehenden Erwartungen und Aliasregeln unveraendert.
Ein eigener Flow-Repro prueft stattdessen die fehlende Bewertung eines nur
mit 1.642 Tage altem Kurs belegten Transfers.

## Verbleibende G-Punkte

- G01: `tax_years.py:_income_price_at` hat einen eigenen Preisindex. Die
  Steuer-Agentin/der Steuer-Agent uebernimmt den Policy-Hook; kein eigener
  Tax-Dateiedit. Integrierten Nachweis muss der Koordinator fuehren.
- G02: `not_linked` ist eine Beleggrenze. Bereits vorhandene Derived-Zeilen
  ohne strukturierte Elternbelege koennen nicht nachtraeglich als korrekt
  bewiesen werden. Ein isolierter Ableitungs-Neulauf verhindert neue
  stale->fresh-Ableitung; bestehende produktive Staende wurden nicht angefasst.
- G03: Gate-/Artefaktkennzeichnung und Jahresfreigabe ausserhalb des getesteten
  ExportService-Pfads bleiben Paket F04/Koordinator. Nullzeilen duerfen daraus
  nicht allein als finale Steuerwerte interpretiert werden.
- G04: Nicht vorliegende Nutzer-Repros und fehlende lokale Spezialbelege
  bleiben offen. Keine Behauptung eines exakten Replay oder einer Vollsuite.
- G05: Eigene aktuelle Portfolio-/Divorce-Stichtagsmethoden sind ausdruecklich
  nicht Gegenstand dieser Korrektur. Geerbte Lookup-Aufrufer sind oben benannt.

Die vollstaendigen Testbefehle und Endergebnisse stehen im PRICES_HANDOFF.md.
