# Aktuelle Portfolio-Preisauswahl: begrenztes Teilpaket zu Issue 37

Der aktuelle Portfolio-Snapshot und sein Bewertungs-Audit waehlen aus dem
vorhandenen Preisledger. Es gibt keinen Anbieterabruf und keine Schreibaktion.
Die Auswahl verwirft Preise nach dem Bewertungszeitpunkt, nichtpositive Preise
und Quellen mit dem Praefix `derived:event_quote` (ohne Beachtung von
Gross-/Kleinschreibung und fuehrendem oder abschliessendem Whitespace). Ein
vorheriger geeigneter Preis bleibt verwendbar, auch wenn er veraltet ist.

Die Reihenfolge ist: juengster Preiszeitpunkt, hoechste gespeicherte
Confidence, normalisierter Quellenname, Originalquellenname, Preis und
Preis-ID. Diese reproduzierbare Gleichstandsregel ist keine fachliche
Zertifizierung der Quelle oder der Confidence. Ableitungen mit anderen Praefixen
werden durch dieses enge Teilpaket nicht neu klassifiziert.

## Bewertungsabdeckung und Frische

Der Snapshot behaelt `total_value_eur` als Summe bewerteter Positionen. Bei
fehlenden Preisen fuer enthaltene Positionen ist sie nur ein Teilwert:
`valuation_coverage_status` ist `partial`, `total_value_semantics` erklaert
die Summe, Positionen behalten `null` als Preis und Wert, und
`missing_price_assets` nennt die Assets einschliesslich ausgeschlossener Konten.
Der Abdeckungsstatus bezieht sich nur auf enthaltene Positionen. Die Kontosummen
weisen `unpriced_position_count` aus. `price_selection_diagnostics` zaehlt je
enthaltenem oder ausgeschlossenem Snapshot-Asset Kandidaten und Ablehnungen;
die Ablehnungszaehler koennen sich ueberschneiden. Eine leere Bestandsliste
wird als `empty` ausgewiesen.

`valuation_coverage_status=complete` bedeutet nur, dass fuer alle enthaltenen
Positionen ein nicht ausgeschlossener Preis verwendet wurde. Dies ist weder
Frische noch eine Freigabe als aktueller Marktwert: Auch ein jahrealter Preis
kann die Abdeckung vervollstaendigen. Der vorhandene `asset_summary.price_status`
kennzeichnet das Preisalter separat als `fresh`, `stale` oder `outdated`;
EUR hat den Status `fiat`, nicht bewertete Positionen `missing`. Die bestehende
Altersschwelle und die separate UI-Auswertung werden hier nicht veraendert.
Da der aktuelle Abruf Anbieter-Kurszeit und Abrufzeit bisher nicht trennt,
belegt selbst `fresh` keine echte Anbieter-Kursfrische.

## Auswirkungen und Mengenbasis

- Der Snapshot nutzt Balance-Ledger-Positionen mit den bestehenden Live-Ankern
  fuer die betreffenden Wallets und Boersen. Er ist weder ein reines Ledger-
  Stichtagsbild noch ein vollstaendiger, synchroner Live-Bestandsnachweis.
  Konten- und Anchor-Ausschluesse bleiben unveraendert.
- Das Bewertungs-Audit nutzt die gefilterte Snapshot-Auswahl auch fuer den
  vorherigen Kurs und uebernimmt Abdeckungsstatus und Summenbedeutung.
  Aggregierte Preiswertdeltas werden nur bei vollstaendigem Vergleich angegeben.
  Die eingebettete virtuelle Wallet verwendet dieselbe
  Preisauswahl, aber ihre eigene bestehende FIFO-Lot-Mengenbasis.
- Die Token-Risikoauswertung und der Portfolio-Paritaetsvergleich konsumieren
  den Snapshot und koennen deshalb andere Wert- oder Fehlpreisangaben liefern.
  Der Paritaetsvergleich uebernimmt den numerischen Snapshot-Teilwert bisher
  ohne das neue Abdeckungsfeld; er ist keine Vollstaendigkeitsfreigabe.
- Die aktuelle Mengenprojektion im Steuerdienst und die Quellenregistrierung
  lesen Snapshot-Positionen. Diese Aenderung ersetzt weder ihre Mengenregeln noch
  die historischen Ledger-Stichtags- oder Steuer-/FIFO-Preisregeln.

## Grenzen

- Die bestehende historische Same-Day-Preisregel, Steuer-/FIFO-Methodik,
  Preisledger-Imports und `GET /api/v1/prices/latest` bleiben unveraendert.
- Andere Read-Models, etwa der eigenstaendige Trennungsbericht und Dienste,
  die weiterhin `latest_price_points` verwenden, sind nicht durch diese
  Snapshot-Aenderung abgesichert. Ihre Werte duerfen nicht als Nachweis
  einheitlich gepruefter aktueller Marktpreise verstanden werden.
- Der bestehende Live-Anchor kann bisher unbekannte Assets ohne irgendeinen
  Ledgerpreis ausblenden. Mengenbasis und dessen Methodik wurden hier nicht
  veraendert; die Diagnose erfasst nur tatsaechlich im Snapshot enthaltene
  Assets. Das bleibt eine eigenstaendige offene Aufgabe aus Issue 37.
- Weder Kurszeit versus Abrufzeit noch FX-Alter, Quellenzuverlaessigkeit,
  Contract-/Mint-Identitaet oder die Frontend-Anzeige sind hier repariert.
  Ein vorhandener und nicht ausgeschlossener Preis ist daher nicht automatisch
  ein frischer oder unabhaengig belegter Marktpreis.
- Die historischen API-Felder bleiben erhalten; die neuen Diagnose- und
  Vollstaendigkeitsfelder sind additive Vertragserweiterungen. Bestehende
  Clients muessen sie auswerten, um Teilwerte als solche darzustellen.
