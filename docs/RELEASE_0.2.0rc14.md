# Steuerreport 0.2.0rc14

Vorabversion vom 26.10.2026. Neuer unveränderlicher Tag: `v0.2.0rc14`.
Die geprüfte UX-/API-Umsetzung aus `b01f9b7` ist Bestandteil dieser Version.

## Änderungen

- Datenorientiertes Bedienkonzept mit Quellen-, Transaktions- und Aufgabenlisten,
  Detailpanels, wiederherstellbaren Filtern und getrennten Jahresfreigaben.
- Quellenhinweise und Review-Aufgaben konsistent zugeordnet; direkter Sprung
  zur betroffenen Ledgerposition mit Rückweg. Laden ist kein Nicht-gefunden-Zustand.
- EUR-Referenzwert statt technischem Epochendatum; kompakte Mengen mit exaktem Wert.
- Einrichtung nach Installation, Datenanbietern, eigenen Kontoverbindungen,
  Abrufsteuerung und KI getrennt. „Backend erreichbar“ ist kein Anbieter-Test.
- Mehrere Börsenkonten mit stabilen IDs und getrennten Bestands-Snapshots.
  Test und Bestandsabruf müssen ausdrücklich bestätigt werden; kein automatischer Import.
- Maskierte Secret-Felder und verschlüsselte Speicherung mit Vault-Pflicht,
  auch für ältere Admin-Schreibwege. Keine automatische Legacy-Migration.
- Gemeinsame serverseitige Sekunden-/Minutenbudgets, lokale Endpunktkosten,
  Parallelität, Retry-Pausen und Gesamtdeadlines. Mehrere hostlokale Prozesse
  teilen die Budgets; Konfigurationswechsel und Neustart setzen sie nicht zurück.
- Anbieterreferenzen werden in Image und Software-ZIP mitgeliefert und beim
  leeren Containerstart geprüft. Keine Betreiberkonten oder Zugangsdaten im Image.

## Grenzen

Diese Vorabversion ist keine vollständige steuerfachliche oder medizinische
Freigabe. Steuer-, FIFO-, Ownership- und Freigaberegeln werden nicht abgeschwächt.
Bestehende historische Finanzdaten werden durch das Update nicht korrigiert.

- Noch kein automatischer Sync-Zeitplan oder Tages-/Monatsabrechnungsbudget.
- Kein eigener persistierter Jobstatus „pausiert nach Anbieterlimit“;
  Budgetpause und Warteschlange sind in der Abrufsteuerung sichtbar.
- Koordination auf einem Host, keine verteilte Mehrhostfreigabe.
- Kein neuer vollständiger Historienimport für jede neue Kontoverbindung.
- Unbekannte Herstellerlimits bleiben unbekannt. Konservative lokale Profile
  ersetzen keinen passenden Tarif-/Endpunktabgleich.
- Nach Workerabsturz ist gegebenenfalls eine geprüfte administrative
  Wiederherstellung notwendig; keine automatische Leasefreigabe oder Budgetlöschung.
- Die bestehende Vite-Warnung zum großen Haupt-Chunk bleibt offen.

## Docker

```sh
docker pull ghcr.io/zonfacter/steuerreport-v2:0.2.0rc14
docker compose -f compose.ghcr.yml up -d
```

Ein privates GHCR-Paket erfordert zuvor `docker login ghcr.io` mit Leseberechtigung.
Die Paket-Sichtbarkeit wird bei GitHub getrennt vom öffentlichen Repository verwaltet.
Alternativ aus dem unveränderten Tag lokal bauen. Vorabversionen erhalten kein `latest`.
Unterstützte Imageplattform: `linux/amd64`.

Vor einem Update das vorhandene Datenvolume einschließlich Profil, Quellenkonfiguration,
Datenbank und `keys/vault.key` sichern. Dasselbe Volume und denselben Projektnamen
weiterverwenden; kein `down -v`. Der vorherige Container bleibt bis zur erfolgreichen
Prüfung als Rollback erhalten. Schlüssel und bestehende Zugangsdaten nicht ersetzen.

Die Anwendung hat keine globale Benutzeranmeldung. Nur im vertrauenswürdigen LAN/VPN
oder hinter TLS und einem geeigneten Authentifizierungszugang betreiben.

## Prüfnachweise

Die Ausgangsumsetzung wurde vollständig mit **1.381 bestandenen und vier übersprungenen
Tests** sowie synthetischen Browserabläufen in vier Bildschirmbreiten geprüft.
Die Release-Vorbereitung ergänzt einen Regressionstest zur Paketaufnahme der
Anbieterreferenzen und prüft Versionskonsistenz, Paketfilter und OpenAPI erneut.

Die verbindlichen Ergebnisse der Release-CI und des frisch gezogenen Images stehen
in den GitHub-Actions-Läufen des Tags; ein gestarteter Lauf ist noch kein Erfolg.
Bereinigte Veröffentlichungs- und Laufzeitnachweise werden als Release-Anlagen ergänzt.

- [Changelog](../CHANGELOG.md)
- [Bedienkonzept und A01–A24](UX_BEDIENKONZEPT_2026-10-26.md)
- [API-Einrichtung und Grenzen](API_EINRICHTUNG_ABRUFLIMITS_2026-10-26.md)
- [14-Punkte-Testmatrix und synthetische Browsernachweise](api-setup/2026-10-26/README.md)
