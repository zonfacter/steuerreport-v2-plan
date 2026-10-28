# Unabhaengige Lot-Herkunftsreferenz

## Grenzen

Basis `87b231b5a40716f41468e56a68048f3abd79f4cc`, eigener Checkout
`/tmp/steuerreport-blockers-20261028-fx`, Branch
`audit/lot-origin-independent-20261028`. AGENTS und LOT_HERKUNFT_VERTRAG
wurden vor dem ersten Edit gelesen und bestaetigt. Eigene Aenderungen nur
`tests/acceptance/test_lot_origin_reference.py` und dieses Handoff.
Zentrale Contracts und Resolver ausschliesslich als bereitgestellte Commits
uebernommen: `a3e3ae5`, `0a088c4`, `84aca336`.
Die zentrale Integration `4c51d8eb8fd80acdeb1d1ffc7089459d9940721f` wurde
ebenfalls unveraendert als Abhaengigkeit uebernommen (lokal `d0ff4c4`).

Alle Inputs sind neu erzeugte synthetische Daten, keine exakte Wiederholung
privater Nutzerfaelle. Keine Produktionsdaten/-datenbanken, externen Aufrufe,
Profilkopien, Produktcode-/Konfigurationsaenderungen, Methodenaktivierung oder
steuerliche Freigabe. Keine neuen EventEvidence-Scopes: NEW nur Stored/Staging,
HNT 2024 fuer EventEvidence. Rohdaten, Tax-Lots/-Lines und Preise werden fuer
Read-only-Assertions direkt aus der eigenen kleinen DuckDB gelesen.

## Unabhaengige Sollwerte

100 HNT / Basis 90 EUR, expliziter Eigenuebertrag A nach B, beleggebundene
100:1-Umstellung zu 1 NEW, Teilverkauf 0.4 NEW fuer 60 EUR. Feste Erwartungen:
Basis 36 EUR, Gewinn 24 EUR, Restmenge 0.6, Restbasis 54 EUR. Einmaliger
Mining-Zugang 90 EUR; Transfer und Umstellung erzeugen kein zweites Einkommen.
Global-/Wallet-Preview, beide Preisvarianten, werden gegen dieselben literalen
Zahlen geprueft. Finanzielle Sollwerte stammen nicht aus Produkt-Hilfsfunktionen.
Die Event-Signaturfunktion im Test dient nur dem vorhandenen Bindungsprotokoll,
nicht als Rechenoracle.

Eigene globale und Wallet-Datenobjekte pruefen direkte Erwerbe, explizite
Rootpfade, fehlendes Lot/Ereignis, verwaiste Links, Zyklus, widersprechende
Line-/Lot-IDs und Erwerbsdaten, doppelte Lot-/Event-Identitaeten, Tiefenlimit,
grosse Mengen und Unveraenderlichkeit. Stored Review prueft HNT-Root trotz
NEW-Symbol, unbekannte Roottypen und mehrere Zeilen ohne verdoppelte Summen
oder Rootzaehlung. ReviewGate muss auch eine Line ohne aktuelles Lot lesen
und `lot_origin_unresolved` mit `blocks_export=True` ausgeben.

Die zusaetzliche Lineage-only-EventEvidence-Probe manipuliert ausdruecklich
nur ein synthetisches Staging-Artefakt: reale Raw-/Canonical-Daten ohne
Eventblocker, 0 EUR Delta, ansonsten non_reward_origin. Das ist eine isolierte
Konsumerpruefung, kein angeblicher vom FIFO erzeugter Resolverfehler.

## Vorherbelege

Auf altem Runtime-Pfad mit additiven Contracts, ohne Resolverimport:

- `baseline-r2.xml`: vier echte Consumerfehler (HNT-Filter, NEW-Rootklasse,
  Staging-Status, verlorene 0-EUR-Reviewzeile).
- `baseline-consumers.xml`: 13 failed, 1 passed, 25 deselected, 11.47 s.
- `baseline-v3.xml`: 15 failed, 2 passed, 25 deselected, 15.11 s. Enthalten
  sind die unveraenderten Consumerfaelle sowie direkter unknown-Roottyp
  (alter Pfad meldete faelschlich strict_ready=True). Direkter EUR-Erwerb
  und die schon zuvor konservative carried-unknown-Kontrolle bestanden.
- `baseline-review.xml`: 3 failed, 43 deselected, 4.33 s. Fehlendes aktuelles
  Lot, verwaister Parent, Zyklus: vorher kein lot_origin_unresolved-Issue.

Alles unter `/tmp/sr-origin-20261028-independent/`. Kein `xfail`, keine
Importfehler als fachliche Baseline: Resolverfaelle wurden erst nach
Uebernahme des Moduls ausgefuehrt. Fruehere Adapterlaeufe mit falschen
synthetischen Tabellen-/Spaltennamen sowie fehlendem Tmp-Elternverzeichnis
sind keine Produktbefunde und bleiben nur als technische Originallogs erhalten.
Vorher-XML/JSON wurden nach Runtimeintegration nicht veraendert.

SHA256 baseline-v3.xml:
`086f75e9f1deeba31c2346c63240a7e69ff0508cab0a67e8daab99ed7780f6de`.
SHA256 baseline-v3-source-freeze.json:
`b54828eab4cc73d10e6da61802ab8c6300e8a051691dc5d8c3276763f507ebac`.

## Zwischenstand Und Nachher

Nach Resolver `84aca336`: 40 passed, 3 erwartete ReviewGate-Fails mit noch
altem Coordinator-Hook, 3 deselected, 12.82 s (`resolver-r1.xml`).
Consumerquellen im Lauf unveraendert.

Nach zentraler Integration: `after-r1.xml`, 46 passed / 1 failed, 20.01 s.
Der neue Lineage-only-Test hatte noch keinen synthetischen HNT-Tageskurs und
konnte deshalb die beabsichtigte Bedingung blocked_events_count=0 nicht
herstellen. Ausschliesslich dieses Fixture erhielt HNT/EUR 0.9 am Erwerbstag
und 1.5 am Verkaufstag, keine numerische Erwartung wurde gelockert.

Der bereinigte Lauf `final.xml` ergab 46 passed / 1 failed, 20.44 s. Dieser
Fehler ist fachlich: blocked_events_count=0, Lineage-Zeile und Gruppe blocked,
aber Gesamtbericht status=review. Die Assertion status=blocked bleibt erhalten;
der Coordinator wurde zur zentralen Statuszusammenfuehrung informiert.
SHA256 final.xml:
`040dc8608e0fbfac375cc8c9c83c70c872e6771e2a39408cadf95c233c2ae5ec`.
SHA256 final-source-freeze.json:
`2d886a146c9125a25af95292d94444c68cbd5e34858a94f1dc4518ef8115c894`.
Die endgueltige Abnahme steht bis zur Nachpruefung dieses Bugs aus.

## Reproduktion Und Speicher

```sh
mkdir -p /tmp/sr-origin-20261028-independent
env PYTHONPATH=src:/tmp/steuerreport-connector-tools-20261026:/tmp/steuerreport-release-tools-20261025 \
  STEUERREPORT_TEST_PRUNE_PASSED_DBS=1 python3 -m pytest -q \
  tests/acceptance/test_lot_origin_reference.py \
  --basetemp=/tmp/sr-origin-20261028-independent/verified \
  --junitxml=/tmp/sr-origin-20261028-independent/verified.xml
```

Baseline-Selektor: `-k 'stored or real_bmf or zero_eur'`; Review-Baseline:
`-k review_gate_reads`. Resolver-Zwischenlauf: `-k 'stored or resolver'`
(dieser selektiert wegen des Namens auch die drei Stored-ReviewGate-Tests).

Tmp-Budget wird im eigenen Fixture auf unter 500 MiB geprueft; keine
Repository-/Datenbankkopien, kein Vollsuitelauf. Hoechster bisher gemessener
Zwischenstand 297 MiB; nach Entfernen der synthetischen Baseline-DuckDBs
und .prepared-Reste 2 MiB. XML, JSON und erzeugte Belegarchive bleiben erhalten.
Bei erfolgreichen Proben entfernt das Fixture eigene DB-/WAL-/prepared-Dateien.
Der Sessionbeleg haelt die verwendeten Consumer-Quellhashes vor/nach fest.

Keine automatische Privat-/Betriebszuordnung aus Herkunft. Eine konsistente
ID-Kette prueft weder Belegechtheit noch Angemessenheit der positiven Basis.
