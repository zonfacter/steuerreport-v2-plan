# Steuerreport 0.2.0rc15

Geschuetzte Wallet-Inbetriebnahme vom 26.10.2026. Tag `v0.2.0rc15`.

## Aenderungen

- Eigener Bereich **Einrichtung → Wallet-Eigentumsnachweis** mit Status und
  konkreten lokalen Inbetriebnahmebefehlen statt einer pauschalen Fehlermeldung.
- Neue Docker-Installationen erhalten ein zufaelliges privates Einrichtungspasswort.
  Updates bestehender Installationen schalten den Zugang nicht still frei.
- Lokales `python -m steuerreport_v2.connector_setup init` erzeugt eine private
  Datei und behaelt vorhandene Passwoerter. `status` gibt keine Secret-Werte aus.
  `show-token` ist nur in einer interaktiven privaten Konsole zulaessig.
- Kein unauthentifizierter Web-Endpunkt zur Freischaltung oder Passwortausgabe.
  Das Passwort bleibt aus URL, Browser-Storage, Exporten und API-Antworten heraus.
- Wallet-Eingabe verlangt den geschuetzten Zugang schon vor der Challenge;
  fehlende/ungueltige Authentifizierung und abgelaufene Pruefungen werden erklaert.
- Strikte Schluesselpruefung und Ed25519-Verifikation mit **PyNaCl 1.6.2/libsodium**.
  Ungueltige und schwache Punkte werden bereits vor einer neuen Challenge sowie
  bei der Verifikation bestehender Challenges abgewiesen. Keine eigene Kryptomathematik.

## Ablauf und Grenzen

Das Einrichtungspasswort schuetzt Connector-Administration, unter anderem
Wallet-Nachweise und Geraetekopplung. Es ist kein Wallet-Private-Key und kein
Boersen-API-Schluessel. Es darf nicht an andere Personen oder externe KI gegeben werden.
Es erweitert keine Handels- oder Auszahlungsrechte bei Boersen.

Unter **Quellen & Wallets → Quelle hinzufuegen → Solana-Wallet** Adresse und
Einrichtungspasswort eingeben, Nachricht anfordern und mit einem geeigneten
Wallet-Signer signieren. Ein automatisches Phantom-Signierfenster ist nicht enthalten.
Signaturpruefung, Quellenregister und steuerliche Aktivierung bleiben getrennt.
Historische Finanzdaten und bestehende Steuer-/FIFO-Regeln werden nicht veraendert.

Die Anwendung hat weiterhin keine globale Benutzeranmeldung und ist nicht ohne
geeigneten Netz-/TLS-/Authentifizierungsschutz fuer das Internet freigegeben.
Die bekannten Grenzen aus rc14, darunter fehlende periodische Sync-Zeitplaene,
Tages-/Monatsbudgets und Mehrhost-Koordination, bleiben bestehen.

## Inbetriebnahme

[Vollstaendiger Inbetriebnahmeleitfaden](INBETRIEBNAHME.md) mit Docker-Compose-,
manuellem Container- und nativem Ablauf sowie Fehlerhilfe. Der HTML-/PDF-
Benutzerleitfaden wurde entsprechend aktualisiert.

```sh
docker compose -f compose.ghcr.yml exec steuerreport python -m steuerreport_v2.connector_setup status
docker compose -f compose.ghcr.yml exec steuerreport python -m steuerreport_v2.connector_setup init
docker compose -f compose.ghcr.yml exec steuerreport python -m steuerreport_v2.connector_setup show-token
```

`init` bei bestehenden Installationen nur ausdruecklich aufrufen. Fuer die letzte
Zeile ein interaktives Terminal verwenden. Nie in CI, Chat oder Diagnoseprotokollen
anzeigen. Vor Updates das komplette Volume einschliesslich Vault und gegebenenfalls
Connector-Passwort sichern. Alte Dateien nicht ersetzen oder in das Image kopieren.

## Pruefung

Gezielte Negativ-/Positivtests pruefen Dateirechte, Idempotenz, frische Installation
gegen Update, explizite Deaktivierung, fehlende/falsche Bearer, ungueltige Schluessel,
ungueltige Signaturen und Neustart. Ein Browserlauf verwendet das echte Frontend
mit FastAPI-TestClient, eine rein synthetische Wallet und eine tatsaechliche
Ed25519-Signatur; es entstehen keine Finanzereignisse oder Steuerfreigaben.

Verbindliche Ergebnisse und bereinigte Image-/Laufzeitnachweise werden als
Release-Anlagen veroeffentlicht. Laufende CI gilt nicht als bestandene Pruefung.

Primaerquellen zur Bibliotheksauswahl:
[PyNaCl 1.6.2](https://pynacl.readthedocs.io/en/latest/changelog/),
[libsodium-Punktvalidierung](https://libsodium.gitbook.io/doc/advanced/point-arithmetic).
