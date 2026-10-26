# Steuerreport 0.2.0rc18

Patch vom 26.10.2026 fuer den Solana-Bestandsabruf und dessen Fehleranzeige.

## Korrekturen

- Der vorhandene RPC-Pfad arbeitet auch ohne Alchemy-Schluessel. Vorher wurde
  trotz vorgesehener oeffentlicher Endpunkte fehlende Konfiguration gemeldet.
- Standard ist `https://api.mainnet.solana.com`. Bestehende konfigurierte RPCs
  und Rueckfallpfade bleiben erhalten. Ein gespeicherter Alchemy- oder Helius-Key
  wird serverseitig genutzt; keine Keys in Chat oder geheimnisfreie RPC-URL schreiben.
- Nur vollstaendige Antworten bestaetigen einen leeren Bestand. Fehlende oder
  fehlerhafte Teilantworten ersetzen keinen erfolgreichen historischen Snapshot.
  Bestaetigte leere RPC-Antworten loesen keinen weiteren bezahlten Fallback aus.
- **Hinweise / Abgleich** zeigt den konkreten letzten Fehler und einen
  Einrichtungseinstieg. Ohne ersten Erfolg wird kein erhaltener Erfolgsstand behauptet.
- Fehler enthalten keine Schluessel, sensitiven URL-Pfade, Querystrings oder
  vom Provider zurueckgespiegelten Freitexte; HTTP-/numerische RPC-Codes bleiben.
- Test-Fixture isoliert die durch Docker-Bootstrap gesetzten Umgebungsvariablen.
  Keine Abschwaechung des produktiven Vault-Zwangs oder der Verschluesselung.

## Bedienung und Grenzen

Bestandsabruf der zugeordneten Profilwallet unter **Quellen & Wallets** ausdruecklich
starten. Oeffentliche RPCs sind begrenzt und kein garantierter Produktivdienst;
fuer verlaessliche regelmaessige Abrufe unter **Einrichtung** passenden Anbieter
und dessen Abrufprofil hinterlegen. Beim Abruf erhaelt dieser die oeffentliche Adresse.
Der bestehende Limiter bleibt aktiv, ohne neue pauschale Hersteller-Grenzwerte.

Adressspeicherung braucht weiterhin keinen Signer oder Setup-Token und startet
keine externe Anfrage. Weitere Beobachtungsadressen erhalten keinen neuen
universellen Historien-/Synchronisationsconnector. Bestandsabruf ist kein
Historienimport und berechnet keine Steuerjahre. Keine Schemaaenderung,
keine historischen Finanz-, FIFO-, Quellenfreigabe- oder Steuerkorrekturen.

15 neue isolierte RPC-Regressionen und Browserpruefung gegen echtes isoliertes
Backend mit simulierten RPC-Antworten. Kein produktiver Wallet-Abruf als Test;
die echten aktuellen Bestaende werden durch diese Tests nicht behauptet.
Tatsaechliche Test-, Image- und Laufzeitresultate werden als Anlagen beigefuegt.

rc17 wurde nach 5 Fehlern einer bestehenden Test-Isolationsluecke im lokalen
Gesamtlauf nicht veroeffentlicht oder produktiv installiert. Der alte Tag bleibt
unveraendert. rc18 enthaelt dessen Korrekturen und die isolierte Test-Fixture.

Referenzen, geprueft am 26.10.2026:
[Solana Public RPC](https://solana.com/docs/references/clusters),
[getBalance](https://solana.com/docs/rpc/http/getbalance),
[getTokenAccountsByOwner](https://solana.com/docs/rpc/http/gettokenaccountsbyowner),
[Helius](https://www.helius.dev/docs/api-reference/rpc/http/getbalance).

Image: `ghcr.io/zonfacter/steuerreport-v2:0.2.0rc18`. Das derzeit private GHCR-Paket
benoetigt ein berechtigtes Login, unabhaengig vom oeffentlichen Repository.
Keine bewegliche Docker-`latest`-Marke und keine steuerfachliche Gesamtfreigabe.
