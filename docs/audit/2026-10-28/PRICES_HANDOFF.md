# Handoff Paket B / F02

Branch: `audit/docker-migration-20261028-prices`.
Fachlicher Trace, Vertrag, additive API und G-Grenzen:
[PRICES_F02.md](PRICES_F02.md).

Zentrale Voraussetzungen im Koordinatorzweig:
`ef24dbab505517944de1a546cefc840a99dd81d9` und
`438cbd3dac11b0f0bfcc7f308f583f3837de5f85`.
Diese Commits wurden unveraendert gepickt, nicht von Paket B editiert.
Zur Integration nur den abschliessend gemeldeten eigenen Paket-B-Commit
cherry-picken, wenn beide Voraussetzungen bereits vorhanden sind.

## Befehle

Alle Befehle aus `/tmp/steuerreport-migration-20261028-prices`.

Bestehende unabhaengige Baseline, vor Implementierung:

```bash
env PYTHONPATH=src:/tmp/steuerreport-connector-tools-20261026:/tmp/steuerreport-release-tools-20261025 \
  STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 python3 -m pytest -q \
  tests/unit/test_price_lookup.py tests/unit/test_tax.py \
  tests/unit/test_review.py tests/unit/test_exports.py \
  --basetemp=/tmp/steuerreport-prices-tests-20261028-baseline2
```

Ergebnis: **55 passed, 3 skipped** in 57.98 s.
Fruehe reine Setupversuche: `python` nicht vorhanden, nicht existierendes
`var/` als Temp-Elternverzeichnis, dann `config_location_not_writable` bei
Test-Runtime innerhalb des Repos. Der endgueltige eigene Temp-Pfad ausserhalb
des Repos beseitigte dies ohne Code-/Testlockerung. Keine Baseline-Regression.

Eigene negative Ausgangsrepros vor Implementierung:

```bash
env PYTHONPATH=src:/tmp/steuerreport-connector-tools-20261026:/tmp/steuerreport-release-tools-20261025 \
  STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 python3 -m pytest -q \
  tests/unit/test_price_policy_regressions.py -k 'stale_or_future or old_quote' \
  --basetemp=/tmp/steuerreport-prices-tests-20261028-repro-before
```

Ergebnis: **4 failed, 4 passed, 37 deselected** in 13.39 s. Die Fehler
betreffen den 1.642-Tage-Fallback sowie Quote->Asset, Asset->Quote und
Counterflow-Ableitung alter Anker. Zukunftsvarianten waren bereits blockiert.
Das sind eigene Repros, kein exakter Replay fehlender Nutzerdateien.

Endgueltiger gezielter Regressionsbefehl, Quellcode waehrend Lauf eingefroren:

```bash
env PYTHONPATH=src:/tmp/steuerreport-connector-tools-20261026:/tmp/steuerreport-release-tools-20261025 \
  STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 python3 -m pytest -q -n 4 \
  tests/unit/test_price_lookup.py \
  tests/unit/test_price_policy_regressions.py \
  tests/unit/test_derived_prices.py \
  tests/unit/test_price_store_snapshot.py \
  tests/unit/test_tax.py \
  tests/unit/test_review.py \
  tests/unit/test_exports.py \
  tests/unit/test_derivatives.py \
  tests/unit/test_flows.py \
  tests/unit/test_swap_valuation.py \
  tests/unit/test_price_quality.py \
  tests/unit/test_binance_small_assets_price_evidence.py \
  tests/unit/test_bmf_event_evidence.py \
  tests/unit/test_historical_prices.py \
  tests/unit/test_observed_price_requirements.py \
  tests/unit/test_historical_price_workflow.py \
  tests/unit/test_automatic_price_resolution.py \
  tests/unit/test_evidence_price_package.py \
  tests/unit/test_moonpay_receipts.py \
  --basetemp=/tmp/steuerreport-prices-tests-20261028-final \
  --junitxml=/tmp/steuerreport-prices-tests-20261028-final.xml
```

Endergebnis: **364 passed, 3 skipped** in 117.42 s, **0 failures, 0 errors**
bei 367 Testfaellen. JUnit-Nachweis:
`/tmp/steuerreport-prices-tests-20261028-final.xml`, SHA256
`327a6520516c20ab8b63f36d579f1b6628a620e029e84be8395776546e81c42b`.
Die vier Domain-Dateihashes unten stimmen vor und nach diesem Lauf ueberein.

Die drei Skips in `test_review.py` benoetigen private Solscan-/Blockpit-/RPC-
Belege, die lokal nicht vorliegen:

- test_review_decision_suggestions_include_verified_iot_evidence
- test_review_tasks_link_solscan_evidence_trace
- test_review_decision_suggestion_acceptance_is_idempotent

Vorlaeufiger identischer Lauf vor letzter Fiat-Diagnose-Sicherung:
**363 passed, 3 skipped** in 118.18 s.

## Erwartungen Und Grenzen

Keine bestehende numerische Erwartung wurde geaendert oder gelockert.
Folgende bestehende Szenarien bekamen nur explizite zweite Tagespreisanker,
weil ihre eigentliche Nettofluss-/Ableitungspruefung vorher nebenbei alte
Kurse wiederverwendete:

- test_derived_prices_create_direct_eur_and_stable_quote_prices
- test_derived_prices_make_stable_quote_fifo_lot_nonzero
- test_flow_summary_uses_net_eur_transfers_not_trades
- test_flow_summary_nets_bidirectional_edges
- test_flow_summary_merges_unique_truncated_wallet_alias

Die Vortages-/1.642-Tage-Ablehnung ist in eigenen negativen Repros abgedeckt;
es wurde keine fehlende Produktionsevidenz durch Fixtureanker behauptet.
Der erste breite Lauf vor diesen Flow-Fixtures hatte 359 passed, 3 skipped
und genau die drei genannten Flow-Fehler. Nach den Fixtures war er gruen.

Getestet sind echte DuckDB-Datenbanken und echte Preis-, Ableitungs-, Tax-,
Review- und Exportservices, einschliesslich Algebra 4/10*20 = 8 EUR Basis,
fehlender Erloesbewertung, scopespezifischem blockierendem Reviewissue,
blocked Paket und verweigerter PDF-Renderbarkeit. Ebenso USD ohne FX-1,
EUR-Identitaet, Herkunftsgrenze trotz frei benannter Quelle, vollstaendige
Snapshots, Diagnostiklimit 0/50/1000, UTC-Grenzen und SQL/Python fuer alle
drei Preisrollen und Solana-Quellconstraint. Keine externen Testverbindungen.

Offen zur Integration: G01 eigener Income-Preisindex beim Steueragenten;
G02 Elternprovenienz bereits vorhandener Derived-Zeilen fehlt im PricePoint;
G03 finale Artefakt-/Jahresfreigabe ist F04/Koordinator; G04 Nutzer-Repros und
lokale Spezialbelege fehlen; G05 separate aktuelle Portfolio-/Divorce-
Stichtagsmethoden ausserhalb dieses Pakets. Vollsuite und gemeinsame
Integrationspruefung fuehrt der Koordinator aus. Kein behaupteter Release-
oder Produktivnachweis.

## Quellbindung

SHA256 des eingefrorenen eigenen Domaincodes im Endlauf:

```text
3fe1fcd6285ca3918947058a141e8e7a9dd9b865cdfbcfeac7a7e321a3e2651f  src/steuerreport_v2/domain/price_lookup.py
ddc04ab05d8eb29db736123bed6bea83cfa80f4838cab2b5a5f1b0083ac56cf5  src/steuerreport_v2/domain/valuation.py
2e98bec62aac419462281da11ab89253e091f210e599edc051a3bdae1779b9fc  src/steuerreport_v2/domain/derived_prices.py
a73b953e114ccccefa6682f776bfd8d747c2992ea08db92f5b1deb1088118f1a  src/steuerreport_v2/domain/price_policy.py
```

Keine produktiven DBs, Raw-Imports oder alten Pakete angefasst; keine neuen
Aliases/Paritaetsregeln, keine FIFO-Methodenaenderung. Nur lokale Commits,
kein Push, kein Release und kein Deployment.
