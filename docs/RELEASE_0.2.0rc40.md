# Steuerreport V2 0.2.0rc40

Releasekandidat mit einer eng begrenzten Korrektur der Bitget-CSV-Profilzuordnung.
Diese Version ist keine steuerliche Freigabe. Das Containerimage wird separat
in der GHCR-Pipeline gebaut und geprueft.

## Aenderung

- `Fee Deducted In` wird als Gebuehrenasset, nicht als Quote-Asset behandelt.
  Bei einer Zeile mit `Amount (USDT)` prueft ein synthetischer Importtest den
  USDT-Gegenwert und das separat ausgewiesene Gebuehrenasset.
- Ein synthetischer FIFO-Test prueft Vorjahreskauf, Teilverkauf, Rohbezug und
  Wiederholung anhand unabhaengiger Sollwerte. Er belegt keine Datenparitaet
  zur nativen Altinstallation.

## Grenzen

- Es werden keine bestehenden Importe, Batches oder Canonical Events automatisch
  repariert oder neu normalisiert. Eine ausdruecklich erneut gestartete
  Normalisierung eines alten Rohbatches kann die neue Profilzuordnung anwenden.
- Es erfolgt keine steuerliche Freigabe. Issue #22 bleibt offen; insbesondere
  sind separate Margin-Gebuehren und die sichere Paarung unvollstaendiger
  Trade-Beine nicht geloest.
- Ein produktives Deployment, eine Neuberechnung bestehender Daten oder ein
  Providerabruf erfolgt nicht automatisch durch dieses Release.
