# Steuerreport 0.2.0rc17

Patch vom 26.10.2026 fuer den Solana-Bestandsabruf nach rc16.

## Ursache und Korrektur

Der vorhandene Solana-RPC-Pfad wurde nur bei vorhandenem Alchemy-Schluessel
versucht. Ohne eingerichteten Anbieter meldete der Abruf deshalb fehlende
Konfiguration, obwohl bereits oeffentliche RPC-Endpunkte vorgesehen waren.
Die Quellenansicht zeigte dazu nur einen pauschalen Fehler und behauptete
auch ohne ersten erfolgreichen Abruf, ein Erfolgsstand sei erhalten geblieben.

- Der RPC-Pfad ist jetzt auch ohne Alchemy-Schluessel nutzbar.
- Standard ist der aktuell dokumentierte Mainnet-Endpunkt `https://api.mainnet.solana.com`;
  bestehende konfigurierte Endpunkte und Rueckfallpfade bleiben erhalten.
- Ein im Secret-Store gespeicherter Helius-Schluessel wird fuer dessen RPC genutzt.
- Vollstaendig bestaetigter leerer RPC-Bestand loest keinen weiteren kostenpflichtigen
  Fallback aus. Fehlerhafte Teilantworten gelten nicht als Nullbestand.
- Quellen zeigen unter **Hinweise / Abgleich** den letzten konkreten Fehler
  und **Datenanbieter und RPC einrichten**. Die Abrufmeldung unterscheidet
  ersten Fehler und Fehler bei vorhandenem erfolgreichen Stand.
- RPC-Fehlerdetails enthalten nur bereinigte Anbieterkennung, HTTP-Status
  beziehungsweise numerischen Fehlercode. Keine Schluessel, sensitiven Pfade,
  Querystrings oder vom Anbieter zurueckgespiegelten Freitexte.

## Bedienung und Grenzen

Bei bereits zugeordneter Profilwallet unter **Quellen & Wallets** den Bestandsabruf
ausdruecklich starten. Zum Speichern einer Beobachtungsadresse ist weiterhin kein
Signer oder Einrichtungspasswort erforderlich. Weitere Beobachtungsadressen erhalten
keinen neuen universellen Historien-/Synchronisationsconnector; rc16-Grenzen bleiben.

Oeffentliche RPCs sind begrenzt und koennen Anfragen ablehnen; kein garantierter
Produktivdienst. Fuer verlaessliche regelmaessige Abrufe unter **Einrichtung** einen
geeigneten RPC beziehungsweise Alchemy-/Helius-Zugang hinterlegen und das Abrufprofil
pruefen. Schluessel niemals in Chat oder geheimnisfreie RPC-URL-Konfiguration schreiben.
Beim ausdruecklichen Abruf erhaelt der jeweilige Anbieter die oeffentliche Adresse.
Der bestehende Limiter bleibt aktiv; keine neuen Hersteller-Grenzwerte oder Zusagen.

Speichern einer Adresse startet keine externe Anfrage. Bestandsabruf speichert
Snapshots und Protokolle, importiert keine Historie und berechnet keine Steuerjahre.
Fehlende Preise werden nicht durch Kursannahmen ersetzt. Keine Schemaaenderung oder
Aenderung historischer Finanzdaten, fachlicher Freigaben, Steuer- oder FIFO-Regeln.

## Nachweise

Isolierte Tests fuer Public-/Alchemy-/Helius-RPC, echte Null, unvollstaendige
Antworten, Fehlerredaktion, fehlende Wallet und historischen Snapshot-Erhalt.
Browserregression gegen echtes isoliertes Backend fuer Fehler, Wiederholung und
erneuten Fehler. Tatsaechliche Resultate und Build-/Imagebelege liegen dem Release
bei; simulierte Antworten sind kein Nachweis eines erfolgreichen Live-Abrufs.

Offizielle Referenzen, geprueft am 26.10.2026:
[Solana Public RPC](https://solana.com/docs/references/clusters),
[getBalance](https://solana.com/docs/rpc/http/getbalance),
[getTokenAccountsByOwner](https://solana.com/docs/rpc/http/gettokenaccountsbyowner),
[Helius](https://www.helius.dev/docs/api-reference/rpc/http/getbalance).

Image: `ghcr.io/zonfacter/steuerreport-v2:0.2.0rc17`. Das derzeit private GHCR-Paket
benoetigt ein berechtigtes Login, unabhaengig vom oeffentlichen Repository.
Keine bewegliche Docker-`latest`-Marke und keine steuerfachliche Gesamtfreigabe.
