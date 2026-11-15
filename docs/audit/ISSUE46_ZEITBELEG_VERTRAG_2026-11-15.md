# Issue 46: Stichtag und Zeitbeleg, Vertrag des naechsten Integrationsschritts

Basis `8e96422e65d809fdc206d2881f353f55b5bdc5e3` (Draft #61).
Nur Entwicklung mit synthetischen Daten, kein produktiver Zugriff. Bestehende
Preise, Raw-Objekte, Reviews und archivierte Pakete nicht aendern.

## Ausgangsbefund und Ziel

Ein gleiches UTC-Datum ist eine Aussage ueber einen gespeicherten Referenzwert,
nicht ueber einen belegten Beobachtungs-/Veroeffentlichungszeitpunkt. Der
bestehende As-of-Backfill setzt Tagesreferenzen auf Mitternacht. Ein frueherer
FX-Quelltag oder ein unbekanntes Quellenlabel schliesst diese Belegluecke nicht.
Kein zeitliches Qualitaetsmerkmal aus einem freien Label, Confidencewert oder
erfolgreichen Preis-Checkpoint ableiten.

Dieser vertikale Schritt macht diese Luecke im bestehenden Stichtags-Gate,
As-of-Bericht und UI explizit. Vorhandene Zahlen bleiben als vorlaeufige
Referenzen sichtbar; globale steuerliche Tagespreisregeln und FIFO bleiben
unveraendert. Keine neue Steuer-/Familienrechtsauslegung.

## Gemeinsamer technischer Vertrag

Neue reine Lesemodelle in `contracts/price_time.py` und Klassifikation in
`domain/price_time.py`, ohne Schemaaenderung, neues Preisregister oder Writer.

`PriceTimeAssessment`:

- `policy_id = "stichtag-temporal-evidence"`, `policy_version = 1`.
- `asset: str`, `status`: `fixed_eur_identity`, `unverified_time`, `missing`,
  `future_reference` oder `non_positive`; `strict_eligible: bool`.
- `reference_kind`: `fixed_identity`, `daily_reference_candidate`,
  `derived_reference_candidate` oder `unknown`. Kandidatenklassifikation
  beschreibt nur den vorhandenen Labelhinweis, keinen geprueften Rohbeleg.
- `stored_reference_at: datetime | None`: vorhandener Ledger-Zeitwert,
  UTC-normalisiert. Nie automatisch als `observed_at` uebernehmen.
- `observed_at`, `period_start`, `period_end`, `price_published_at`,
  `fx_published_at`: jeweils `datetime | None`, hier ohne Originalbeleg `None`.
- `valuation_method_id: str | None`, `valuation_method_version: int | None`,
  `price_evidence_ref: str | None`, `fx_evidence_ref: str | None`:
  kein erfundener Beleg oder Methodenfreigabewert.
- `reason_codes: list[str]`, `explanation: str` (verstaendliches Deutsch).

Reine Funktion:

```python
assess_price_time(*, asset: str, price_source: str | None,
                 priced_at: datetime | None, price_eur: Decimal | None,
                 valuation_at: datetime) -> PriceTimeAssessment
```

Einzig bereits beweisbarer positiver Sonderfall ist echte EUR-Identitaet:
Asset `EUR`, Wert exakt 1 und Quelle exakt `fiat:EUR`. `fiat:EUR` an einem
anderen Asset, eine EUR-Marktpreiszeile anderer Quelle oder USD-Stablecoins
sind kein solcher Nachweis. Die Identitaet ist zeitlos; Epoche wird nicht als
Kursereignis ausgegeben. Alle anderen heutigen nicht beleggebundenen
Referenzen sind nicht `strict_eligible`, auch bei hoher Confidence, anderem
Label oder exakter Uhrzeit im frei gesetzten Ledgerfeld. Fehlend, kuenftig
und nicht positiv bleiben getrennt. Naive bestehende Ledgerzeiten werden
wie bislang als UTC interpretiert, ohne daraus einen Originalbeleg zu machen.

## Einbindung durch Koordinator

- `DivorceValuationGate`: additive `price_time_policy_id`,
  `price_time_policy_version`, `unverified_price_time_count`.
- As-of-Kandidat: additive `price_time: PriceTimeAssessment`.
- As-of-Bericht: additive `time_review_count` (Assets; Gatezaehler sind
  Positionen). Gleicher Tag plus nicht geeigneter Zeitbeleg ist `time_review`,
  kein `satisfied` und kein Versprechen, ein weiterer Tagesabruf loese dies.
- Gate blockiert bei fehlendem Zeitnachweis unabhaengig von Tokenannahmen.
  Ein nicht belegter kleiner Kurswert darf nicht selbst beweisen, dass die
  Position unter der Materialitaetsschwelle liegt. Bestehende Mengen/FIFO und
  Zahlen werden nicht repariert oder geloescht.
- Vorhandene Tokenentscheidung bleibt separat. Sie macht den Zeitbeleg nicht
  gueltig; UI darf sie nicht als Intraday-Freigabe bezeichnen. Keine Entscheidung
  im Test auf produktiven Daten ausfuehren.
- Cache-/Run-Wiederverwendung pruefen: alte streng-positive Ergebnisse nicht
  als aktuellen Nachweis fuer diese neue Lesepolicy verwenden. Archivierte
  Runs unveraendert belassen; fruehere Policy muss erkennbar bleiben.
- UI: eigener Zeitbelegpruefpunkt, klare Trennung von gespeichertem
  Referenzzeitwert und nicht belegter Beobachtungszeit. Keine neuen Abruf-
  oder Reviewaktionen allein beim Lesen.

## Pflichtpruefungen und offene volle Abnahme

Unabhaengige Gegenproben vor Implementierung: Bewertung 01:00 UTC bei
unbelegtem Tagesanker, frueherer FX-Tag, unbekanntes Label, abgeleiteter
Preis, kleiner ungepruefter Wert, Tokenentscheidung, naive/UTC-Zeiten,
echte EUR-Identitaet versus gefaelschtes EUR-Label, unveraenderte Preis- und
Steuerzeilen sowie veraltete streng-positive Runs.

Die vollstaendige #46-Abnahme bleibt davon getrennt: Es fehlt weiterhin die
positive beleggebundene Zulassung echter Nicht-EUR-Intradaybeobachtungen
und explizit freigegebener Tagesmethoden mit Originalantworten, Asset- und
FX-Identitaet, Periode, Beobachtung und Veroeffentlichungs-/Verfuegbarkeitszeit.
Diese Daten duerfen nicht rueckwirkend aus Altlabels erfunden werden. Das
gemeinsame Ziel ist ein nutzbarer belegter Ablauf, nicht dauerhaft pauschales
Sperren aller Nicht-EUR-Quellen. #44 Snapshot/WAL/Planhash ist eine zugehoerige
Abhaengigkeit. Keine Schliessung oder fachliche Gesamtabnahme dieses Issues
nur aufgrund eines negativen Guards.
