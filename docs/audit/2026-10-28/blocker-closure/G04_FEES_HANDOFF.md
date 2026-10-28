# G04 Gebuehren: Implementierung Und Handoff

Basis `ce51a9d42963e25cb7b96dda19efce0703c55b26`, eigener Branch
`audit/blocker-fees-20261028` in `/tmp/steuerreport-blockers-20261028-fees`.
AGENTS.md und gemeinsamer Blocker-Vertrag vor Edits gelesen/bestaetigt.
Der Koordinator hat das Rechenmodell fuer belegte EUR-Kaeufe/-Verkaeufe und
die generische Wallet-Trade-Anpassung ausdruecklich freigegeben. Das ist
keine individuelle steuerliche Freigabe oder produktive Methodenaktivierung.

## Buchungsvertrag

- EUR-Erwerbsgebuehr: einmal Anschaffungsnebenkosten. EUR-Verkaufsgebuehr:
  einmal Erloesminderung; keine weitere Crypto-Fee-Tax-Line fuer EUR.
- Gebuehr im erworbenen Token: Bruttomenge minus Gebuehr ergibt Nettolot,
  vorhandene Gesamtbasis bleibt erhalten. Kein zweiter Lotverbrauch.
- Separat ausgegebenes Nicht-EUR-Gebuehrenasset: eigener FIFO-Abgang nach dem
  Hauptabgang, mit Original-Event-ID und Lotverweis. Erloes ist der belegte
  Gebuehrenleistungswert, Gewinn dieser Verwertung ist Wert minus historischer
  verbrauchter Basis. Hauptgeschaeft erhaelt denselben Gebuehrenwert genau
  einmal als Erwerbskosten oder Erloesminderung, nicht nochmals die Tokenbasis.
- Belegte EUR-Verkaufskosten werden nicht still auf die Verkaufshoehe gekappt;
  negative Nettoerloese bleiben rechnerisch sichtbar und reviewpflichtig.
- Swap: physischer separater Tokenabgang wird korrigiert, aber kein pauschaler
  Ansatz zusaetzlicher Anschaffungsnebenkosten und keine erfundene Kostenrolle.
  Vorhandene Netto-/Altbewertung wird nicht als fachlich freigegeben ausgegeben.
- Fehlender Fee-Preis bleibt `None` im Fee-Ergebnis. Bestehende Decimal-only
  Tax-Line kann fuer den Mengenverbrauch einen vorlaeufigen Nullerloes zeigen;
  das ist KEIN bekannter Nullwert und darf nicht final freigegeben werden.
- Fehlender Bestand erzeugt unmatched fuer die fehlende Menge. Kein Kauf,
  keine auffuellende Kostenbasis, kein Poolwechsel. Auch explizite Micro-SOL-
  Gebuehren ohne Lot duerfen nicht als irrelevanter Trade-Dust verschwinden.

### Unabhaengige Sollwerte

BNB 1 fuer 20 EUR, Gebuehr 0.1 bei belegtem Kurs 30 EUR:
Rest 0.9 mit Basis 18; Fee-Line Menge 0.1, Basis 2, Erloes 3, Gewinn 1.
EUR-Kauf 100 plus diese Gebuehr: neue Basis 103. Verkauf danach fuer 150:
Gewinn 47 plus Fee-Gewinn 1 ergibt 48, nicht 45 oder 50.
Separater EUR-Verkauf mit Basis 100 und Bruttoerloes 150: Nettoerloes 147,
Gewinn 47 plus Fee-Gewinn 1 ebenfalls 48.

Kontrollen: Kauf 100 + EUR-Fee 2, Verkauf 150 - EUR-Fee 3 ergibt 45 Gewinn.
10 Brutto-Token minus 0.1 Erwerbsassetgebuehr ergibt 9.9 bei Gesamtbasis 100.
Verkauf 10 BTC mit Basis 100, zusaetzlich Fee 0.1 BTC zum Kurs 15 und Basis 1:
Hauptgewinn 48.5, Fee-Gewinn 0.5, Gesamt 49, Rest 0.9/Basis 9 aus 11/Basis 110.
Zwei BNB-Lots 0.04/Basis 0.8 und 1/Basis 30, Fee 0.1 zum Kurs 30:
verbrauchte Basis 2.6, Erloes 3, Gewinn 0.4; Rest 0.94/Basis 28.2.

## Code Und Review-Schnittstelle

`tax.py:TaxService.trade_fee_accounting(event)` liefert `None` ohne relevante
Tradegebuehr, sonst ein internes `_TradeFeeAccounting` mit:

| Feld | Bedeutung |
| --- | --- |
| `asset`, `quantity` | Original-Fee-Asset, absolute separat belegte Menge |
| `value_eur` | Vorhandene historische EUR-Bewertung oder ausdruecklich `None` |
| `separate_disposal` | Nicht-EUR-Fee ist nicht schon in erworbener Nettomenge enthalten |
| `allocation` | Erwerbskosten, Verkaufskosten, enthaltene Nettomenge oder Kostenrollenreview |

`allocation` verwendet exakt `acquisition_cost`, `disposal_cost`,
`included_in_net_quantity`, `review_required`. Alle Swapgebuehren liefern
`review_required`, auch wenn die Mengenbehandlung schon netto erfolgt.
Fehlender `value_eur` bei einer solchen Netto-Swapgebuehr beweist nicht, dass
eine separate Fee-Line oder zweite physische Menge fehlt: `separate_disposal`
bleibt in diesem Fall falsch. Die Kostenrolle bleibt unabhaengig davon offen.
Kein neues zentrales Modell, DB-Feld oder API-Format. Die generischen
Global-/Wallet-Tradepfade nutzen denselben Helfer fuer die EUR-Kostenrolle;
beide konsumieren Gebuehren im jeweils zulaessigen Pool. Spezial-Transfers,
Service-Swaps, Moonpay-Sonderbelege, Redenomination und G19 bleiben unberuehrt.
Wallet-Preview bleibt Preview; keine Rekonstruktion/Aktivierung einer Methode.

### Koordinator-Aufgabe In review.py

Review wird hier NICHT editiert. Erforderliche Unterscheidungen:

1. Ohne Fee oder EUR-Fee kein separater Crypto-Lotnachweis verlangen.
2. EUR-Geschaeft mit `included_in_net_quantity`: keine zweite Fee-Line und
   fehlender `value_eur` nicht faelschlich als fehlende separate Bewertung.
3. Separate Fee mit fehlendem `value_eur`: Bewertungsblocker beibehalten,
   auch wenn die Menge korrekt verbraucht wurde und die Decimal-Zeile 0 zeigt.
4. Fehlender/teilweise fehlender Fee-Bestand: unmatched bleibt blockierend;
   vorhandene Menge darf verbraucht werden, fehlende Menge wird nicht erfunden.
5. Unbewiesene Fee-Lotbasis: bestehende Herkunfts-/Nullbasispruefung erhalten.
6. Bei Swaps bleibt die Kostenrollenzuordnung blockiert, auch bei bereits
   netto behandelter Erwerbsassetgebuehr oder EUR-Gebuehr. Ein bekannter
   Fee-Kurs oder `separate_disposal=False` erteilt keine Swap-Kostenfreigabe.
7. Globaler und Wallet-Modus muessen denselben Bewertungs-/Zuordnungsstatus
   konsumieren; eine gruene Mengenprobe ersetzt keine menschliche Abnahme.

Im gelieferten Basisstand existiert weiterhin der pauschale globale
`fee_token_lot_accounting_review_required`-Blocker. Er wird durch diesen Fix
nicht entfernt; selbst der komplett belegte positive Sollfall kann daher bis
zur gesonderten Koordinatorintegration weiterhin exportgesperrt bleiben.

## Amtliche Grundlage Und Grenze

[BMF 06.03.2025 Rz. 57-60](https://amtliche-handbuecher.bundesfinanzministerium.de/esth/2025/B-Anhaenge/Anhang-04/anhang-4.html)
und [EStG Paragraph 23 Abs. 3](https://www.gesetze-im-internet.de/estg/__23.html)
wurden unabhaengig primaer recherchiert. BMF Rz. 59 unterscheidet
Anschaffungsnebenkosten und veraeusserungsbezogene Werbungskosten; Rz. 60
betrifft die Gegenleistung bei Tokenhingabe fuer Waren/Dienstleistungen.
Das bestaetigt nicht pauschal jede Kostenzuordnung oder Privat-/Betriebssphaere.
Kein universeller Swap-Gebuehrenvertrag aus einem Importlabel abgeleitet.

Die Nutzerberichte wurden in dieser Welle erstmals gelesen, nicht als schon
in vorigen Wellen gelesen ausgegeben. Quellen unter dem nur lesenden
Koordinatorordner `docs/blockpit-analysis`, SHA256:

```text
41f23ab93085d3a48c49d8b27b59067a606d9ac54535264d95d8089e5c18a4f1 BMF-Quellenpruefung-2026-10-28.md
d2c3a08f7b2a8577410b9ff3064cdf64ea0a4b4c40c92927d6861f3d8b4d9fc8 Docker-Nachpruefung-18010-2026-10-28.md
3a32e67add9a42f3da5748c161ae27f492d39abe7f293554b7ddad11729b458e v2-baseline-evidence-2026-10-28/README.md
8f7253ea8c8827f917f32cf87e46b0bc95d5e10313142ddd300965841c3b41eb v2-baseline-evidence-2026-10-28/reproduce.py
c5a35ce005d223e8f93ee411bdb76ce06225d39d0eca2c9f20a7d7a10ef2743d v2-baseline-evidence-2026-10-28/source-manifest.json
e40130dc53b64c062e96fe191d4d1900e2476a93248389703d72a0b064a1b969 v2-baseline-evidence-2026-10-28/results.json
```

Die vier Snapshot-SHA256 stimmen mit dem dortigen Manifest ueberein.
Baseline-Repro und Ergebnis wurden gelesen, nicht ausgefuehrt, da das Skript
sein Original-`results.json` ueberschreibt. Diese engen Altpreis-/Fristproben
enthalten keinen G04-Gebuehrensollwert. Chromeprofil weder gelesen noch kopiert.

## Pruefung

Eigene synthetische DuckDBs, keine produktive DB, keine Netzwerkprovider/AI.
Neue unabhaengige Tests in `tests/unit/test_g04_fee_accounting.py` pruefen beide
Engines, unterschiedliche Gebuehrenassets, Teildeckung, FIFO-Lot-Splitting,
fehlende/alte/kuenftige Preise, fehlende Basis, Pooltrennung und erhaltene
Raw-/Eventdaten. Mengen und Werte werden aus festen Sollzahlen geprueft.
Keine Toleranz-/Erwartungsanpassung fuer gruene Tests, kein xfail/skip.

Die urspruengliche `acceptance_tests.py` bleibt unveraendert. SHA256 vor Lauf:
`09f674b350a9a83943df8980bbceafd88821ee1400e03b5b22ea1ee0f8cd6bfb`.
Unit- und urspruengliche Abnahme laufen in getrennten Prozessen, damit deren
strikte Import-/DB-/Netzwerkisolation nicht andere Tests beeinflusst.
### Ausgefuehrte Laeufe

```bash
export PYTHONPATH=src:/tmp/steuerreport-connector-tools-20261026:/tmp/steuerreport-release-tools-20261025
export STEUERREPORT_TEST_PRUNE_PASSED_DBS=1
pytest -q tests/unit/test_g04_fee_accounting.py tests/unit/test_tax.py tests/unit/test_tax_wallet_fifo.py tests/unit/test_swap_valuation.py tests/unit/test_wallet_fifo_runs.py tests/unit/test_bmf_fifo_staging.py tests/unit/test_solana_service_swap_evidence.py --basetemp=/tmp/steuerreport-blockers-20261028-fees-tests-regression --junitxml=/tmp/steuerreport-blockers-20261028-fees-unit.xml --tb=short -n 2
pytest -q docs/audit/2026-10-28/acceptance_tests.py --basetemp=/tmp/steuerreport-blockers-20261028-fees-tests-acceptance --junitxml=/tmp/steuerreport-blockers-20261028-fees-acceptance.xml --tb=short
pytest -q tests/unit/test_g04_fee_accounting.py --basetemp=/tmp/steuerreport-blockers-20261028-fees-tests-final --junitxml=/tmp/steuerreport-blockers-20261028-fees-final.xml --tb=short
pytest -q docs/audit/2026-10-28/acceptance_tests.py -k 'G02 or G03 or G04 or G05' --basetemp=/tmp/steuerreport-blockers-20261028-fees-tests-final-acceptance --junitxml=/tmp/steuerreport-blockers-20261028-fees-final-acceptance.xml --tb=short
```

| Lauf | Ergebnis | Quellstand |
| --- | --- | --- |
| Erste eigene Sollfaelle | 26 passed, 22.25 s | Vor Ergaenzung von Teildeckung/Microfee/Mehrlotfaellen |
| Breite Regression | 169 passed, 98.50 s | Einschliesslich 34 eigener Faelle; Tax-SHA cfe549fd8a53160a3c85d6221159e34741b4ba47d315216d1308bef4c021fa4a |
| Unveraenderte komplette Originalabnahme | 52 passed, 99.61 s | Derselbe Berechnungsstand wie breite Regression; G04 gruen, keinerlei Originalassertion geaendert |
| Eigener Abschlusslauf | 38 passed, 41.77 s | Endstand: zusaetzliche Swap-Netto-Reviewfaelle, Kennzeichen fuer alle Swapgebuehren auf review_required praezisiert; keine Formel danach geaendert |
| Originalkontrollen G02-G05 | 4 passed, 48 deselected, 8.41 s | Endstand, unveraenderte Proben |

Die komplette 52er-Abnahme und breite Regression werden NICHT als auf dem
spaeteren Reviewkennzeichen-Endstand erneut ausgefuehrt behauptet. Der
abschliessende Lauf prueft alle 38 neuen Faelle und die vier Original-
Gebuehren-/Swapkontrollen auf dem unten eingefrorenen Endstand. Kein
Gesamtsuite-Lauf behauptet. Alle JUnit-Dateien sind lokale eigene Ausgaben
an den oben benannten Pfaden, nicht ueberschriebene Originalergebnisse.

### Eingefrorener Endstand

Vor und nach den Abschlusslaeufen identische SHA256:

```text
dd2e2b013af8bb0689814de42d2faa79ab68c68ac1c4e69a7f3394c97a377b90 src/steuerreport_v2/domain/tax.py
d670275d33dd41a443134b5b0379147e076f86fcd09d91f27ec425584a072147 src/steuerreport_v2/domain/tax_wallet_fifo.py
c7a97679b628e8b81e8a09e302fdbb47f6e6bcb82f795d267eb2a1ade3c4149c tests/unit/test_g04_fee_accounting.py
09f674b350a9a83943df8980bbceafd88821ee1400e03b5b22ea1ee0f8cd6bfb docs/audit/2026-10-28/acceptance_tests.py
```

`git diff --check` ohne Befund. Kein Editeingriff in Review, API, Schema,
zentrale Contracts, CI oder Preisquellen. Keine aktive Methodenentscheidung,
kein Push/Tag/Deployment. Die allgemeine fachliche Gebuehrenabnahme, die
Koordinator-Reviewintegration und ungeklaerte Swapkosten bleiben offen.
