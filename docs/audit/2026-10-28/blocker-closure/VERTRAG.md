# Vertrag Fuer Die Blocker-Nacharbeit

Basis: ce51a9d42963e25cb7b96dda19efce0703c55b26. Separater Auditbranch,
keine Produktion, keine aktive Methodenentscheidung, keine Veröffentlichung.
Maximal drei ausfuehrende Agenten mit eigenen Checkouts/DBs.

## Gemeinsame Grenzen

- Urspruengliche52Referenzproben und feste Sollwerte bleiben erhalten; neue
  unabhaengige Proben ergaenzen G08/G09/G18/G19 und G04-Grenzen. Kein xfail.
- Die jetzt verfuegbaren BMF-/Dockerberichte und Originalrepros werden gelesen
  und mit Hash referenziert, nicht nachtraeglich als schon frueher gelesen ausgegeben.
- Quellmaterial liegt unter docs/blockpit-analysis im Koordinatorcheckout.
  Dieser unversionierte Nutzerordner bleibt unveraendert. Insbesondere keine
  Browserprofile oder ungeprueften Originalsnapshots ins oeffentliche Repo.
- Neue Reproausgaben nur in eigenen Ausgabeordnern, nie ueber results.json der
  Originale schreiben. Produktive DuckDB ausschliesslich explizit read-only,
  kein ensure_schema und keine neue API-Abfrage mit unbekannten Seiteneffekten.
- Decimal und Originalbelege erhalten; keine Preise/FX1/Lots erfinden.

## G04

Der physische Abgang einer belegten Gebuehrenmenge muss genau einmal im
zulaessigen FIFO-Pool erscheinen. EUR-, erworbene und hingegebene Assetgebuehr
und echtes Drittasset unterscheiden. Erwerbs-/Veraeusserungskosten und
gegebenenfalls eigener Tokenabgang duerfen keine doppelte Kostenzuordnung
erzeugen. Fehlender Preis/Bestand/Beleg bleibt explizit reviewpflichtig.
Kein Guard allein als Loesung ausgeben. Vor Implementierung konkreten
Buchungsvertrag und unabhängige Zahlenfaelle mit dem Koordinator abstimmen.
Keine Rekonstruktion/Aktivierung einer produktiven Wallet-FIFO.

## G08/G09

Bestehenden echten FX-Consumer verwenden. Quotierungsrichtung und Einheiten
explizit, positive Decimalraten, begrenzter dokumentierter vergangener
Referenztag, nie Zukunft oder implizite1. Quelle und Referenztag bleiben
gebunden. Netzwerk nur Mock-Provider in Tests; keine Tarif-/Anbieterlasttests.

## G18/G19

Identitaet nicht aus Symbolgleichheit ableiten. Bestehende Contract-/Mint-
Belege und Konfiguration zuerst untersuchen. Migration/Wrapping nur mit
ausdruecklicher belegter Zuordnung und Mengenverhaeltnis; fehlende/strittige
Zuordnung bleibt Review. Neue zentrale Contracts/Schema nur Koordinator.

## Paritaet Und CI

Legacy-DB ueber laufenden Prozess/Dateihandle/Config zweifelsfrei zuordnen,
nicht nur plausible Dateinamen. Semantisch Rohdaten, Events, Reviews, Preise,
Lots, Tax-Lines, Methoden und Archive vergleichen. Unterschiedliche Inputs
nicht als identische Rechenbasis ausgeben. Private Details nur geschuetzt.
CI muss die urspruenglichen Referenzproben getrennt von Unit-Tests ausfuehren,
damit deren strenge Isolation keine anderen Testpfade beeinflusst; jeder
echte Fehler blockiert das Gate. Keine Abschwaechung vorhandener Freigaben.

## Eigentum

- Betrieb/Paritaet: neue Audit-/Vergleichshelfer und eigene Tests, keine Taxformeln.
- Gebuehren: tax.py, gegebenenfalls tax_wallet_fifo.py nach Abstimmung, eigene
  neue Tests/Dokumentation. Keine zentralen Models/Schema/API/CI.
- FX: bestehende historische FX-/Preis-Consumer und eigene neue Tests/Doku;
  keine FIFO/zentralen Models/Schema/API/CI.
- Koordinator: Identitaet/Migration, zentrale Integration, CI, Matrix und Diff.
