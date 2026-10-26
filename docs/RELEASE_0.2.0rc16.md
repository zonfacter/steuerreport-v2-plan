# Steuerreport 0.2.0rc16

Patch vom 26.10.2026: oeffentliche Solana-Adresse ohne Signatur einrichten.

## Neuer Standardablauf

**Quellen & Wallets → Quelle hinzufuegen → Solana Wallet → Oeffentliche Adresse
speichern**. Optional Name und Adresse erfassen, Zusammenfassung pruefen und
**Adresse speichern** waehlen. Kein Connector-Passwort und keine Wallet-Verbindung
erforderlich. Der optionale kryptografische Eigentumsnachweis bleibt ein eigener,
geschuetzter Ablauf. Eine neue Phantom-Anbindung ist nicht Bestandteil dieses Patches.

Adressen liegen nur im privaten Datenvolume. Mehrere Adressen erscheinen einzeln;
erneutes Speichern behaelt denselben Eintrag und vorhandene Pruefungen. Bestehende
private Profiladressen erscheinen ebenfalls, ohne bei einem GET einen Nachweis
oder eine neue gespeicherte Verbindung zu erfinden. Quellendetails zeigen Adresse,
Bewertungsbasis und Pruefstatus; alte Import-Detailverweise bleiben erreichbar.

## Wirkung und Grenzen

Der lokale Schreibvertrag `POST /api/v1/workspace/wallets` speichert nur
`wallet_address` und optional `display_label`. Der Setup-Bearer ist fuer diesen
engen Konfigurationsschritt nicht erforderlich. Host-/Origin-Schutz bleibt bestehen,
synthetische schreibgeschuetzte Vorschauen verweigern die Speicherung.
Das Produkt hat weiterhin keine globale Benutzeranmeldung und gehoert nur in ein
geschuetztes LAN/VPN oder hinter einen geeigneten Zugriffsschutz.

- Kein Provider-Abruf, Historienimport, Wallet-Zugriff oder Neuberechnung beim Speichern.
- Keine automatische Eigentumsbestaetigung, Zuordnung zu Betriebs-/Privatvermoegen,
  Quellenregistry- oder Jahresfreigabe.
- Der vorhandene Bestandsabruf ist weiterhin auf konfigurierte Profilwallets und
  eingerichtete Datenanbieter begrenzt. Weitere Beobachtungsadressen erhalten keinen
  wirkungslosen Sync-Button; Historie ueber den vorhandenen Importablauf ergaenzen.
- Keine Aenderung von historischen Finanzdaten, Steuer-, Ledger- oder FIFO-Regeln.
- Keine Schemaaenderung: neue oeffentliche Verbindungen verwenden den bisherigen
  gespeicherten Status `configured`, ohne `verified_at` oder `source_id`.
  Die neue API stellt diesen Zustand ausdruecklich als `address_saved` dar.
- Bisherige Grenzen aus rc15 bleiben bestehen. GHCR-Sichtbarkeit ist getrennt vom
  Repository; das derzeit private Paket benoetigt ein berechtigtes Registry-Login.

## Pruefung und Inbetriebnahme

Synthetische Tests pruefen Speicherfaehigkeit, Neustart, Doppeleingaben, mehrere
Adressen, ungueltige Eingaben, gesonderte Signaturpruefung, unveraenderte Finanzzeilen,
Origin-/Host-Schutz und Demo-Sperre. Der Browserablauf nutzt das echte Frontend und
einen isolierten FastAPI-Backend-Client in vier Bildschirmbreiten.

Die tatsaechlichen CI-, Image-, Datenschutz- und Laufzeitnachweise werden als
Release-Anlagen beigefuegt; laufende Pruefungen gelten nicht als erfolgreich.
Vor dem produktiven Update das komplette private Datenvolume einschliesslich Profil,
Vault und Connector-Passwort sichern. Anleitung: [Inbetriebnahme](INBETRIEBNAHME.md).
