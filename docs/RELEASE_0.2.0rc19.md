# Steuerreport 0.2.0rc19

Patch vom 26.10.2026: Wallet-Positionen ohne Historie oder EUR-Preis anzeigen.

## Ursache und Korrektur

Erfolgreich abgerufene RPC-Positionen waren gespeichert, aber ohne EUR-Preise und
importierte Historie nicht in der Quellenansicht sichtbar. Eine unvollstaendige
Live-Bewertung konnte irrefuehrend als 0,00 EUR erscheinen.

- **Quellen & Wallets → Quelle → Bestaende** zeigt gespeicherte Tokenmengen,
  Datenstand und Abrufbezug auch ohne Preis oder Transaktionshistorie.
- Quellenliste nennt Bestandspositionen und fehlende Bewertungen getrennt von
  importierten Ereignissen. Dashboard fuehrt direkt zum passenden Bestandstab.
- Fehlende Bewertungen bleiben unbekannt, statt 0 EUR oder eine Teilsumme als
  vollstaendigen Walletwert auszugeben. Bestaetigter Leerbestand bleibt echte Null.
- Fehlgeschlagene Folgeabrufe loeschen keinen erfolgreichen historischen Stand.
- Nur explizit zugeordnete Profilwallets verwenden den jeweiligen Connector-Snapshot.
  Andere Beobachtungsadressen erben weder dessen Positionen noch Bewertung.

Additiver lesender Vertrag: `WorkspaceSource.live_assets_count`,
`live_unpriced_assets_count`, `live_value_eur`, `live_balance_status` und
`WorkspaceSourceDetail.live_balance`. Bestehende Quellenbewertung bleibt separat.
Keine Aenderung der Portfolio-/FIFO-Fachlogik, Preise oder historischen Finanzdaten.

## Grenzen und Pruefung

Ansicht aktualisieren liest gespeicherte Daten, ohne externen Abruf oder
Neuberechnung. Snapshots sind keine Historie, kein Anschaffungsnachweis und keine
Eigentums- oder Steuerfreigabe. Weitere Beobachtungsadressen erhalten keinen neuen
universellen Historienconnector. Fehlende Historie ueber vorhandene Importe ergaenzen.

Nach Aenderung einer Profil-RPC-URL den Neustarthinweis beachten: gespeicherte
und aktive Konfiguration unterscheiden sich. Provider-Keys nur in verschluesselten
Key-Feldern speichern, nicht in Chat, URLs oder oeffentlichen Screenshots.

Sechs neue Backend-Regressionen und Browserpruefung mit 18 unbewerteten Positionen
ohne Transaktionen in vier Bildschirmbreiten. Tatsaechliche CI-, Image-, Datenschutz-
und Laufzeitresultate als Release-Anlagen. Kein weiterer produktiver RPC-Abruf als
Test, keine steuerfachliche Gesamtfreigabe durch diesen Anzeigepatch.

Image: `ghcr.io/zonfacter/steuerreport-v2:0.2.0rc19`. GHCR-Paket weiterhin privat,
berechtigtes Login erforderlich; keine bewegliche Docker-`latest`-Marke.
