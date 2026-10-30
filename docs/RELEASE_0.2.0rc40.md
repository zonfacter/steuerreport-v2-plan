# Steuerreport V2 0.2.0rc40

Releasekandidat mit einer eng begrenzten Korrektur der Bitget-CSV-Profilzuordnung.
Diese Vorbereitung ist keine steuerliche Freigabe und baut oder veroeffentlicht
kein Containerimage.

## Aenderung

- `Fee Deducted In` wird als Gebuehrenasset, nicht als Quote-Asset behandelt.
  Bei einer Zeile mit `Amount (USDT)` prueft ein synthetischer Importtest den
  USDT-Gegenwert und das separat ausgewiesene Gebuehrenasset.

## Grenzen

- Es werden keine bestehenden Importe, Batches oder Canonical Events automatisch
  repariert oder neu normalisiert. Eine ausdruecklich erneut gestartete
  Normalisierung eines alten Rohbatches kann die neue Profilzuordnung anwenden.
- Es erfolgt keine steuerliche Freigabe. Issue #22 bleibt offen; insbesondere
  sind separate Margin-Gebuehren und die sichere Paarung unvollstaendiger
  Trade-Beine nicht geloest.
- Kein Docker-Build, Deployment, Zugriff auf produktive Datenbanken oder
  Providerabruf ist Teil dieser Vorbereitung.
