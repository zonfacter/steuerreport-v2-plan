# Installation, Settings und Docker in 0.2.0rc3

## Leerer Erststart

Das Software-Image wird ohne Betreiberprofile, Walletadressen, Exchange-UIDs,
Bankverbindungen, Rohdaten und private Zugangsdaten gebaut. Die Positivliste
in `.dockerignore` begrenzt den Build-Kontext. Testprofile sind kuenstlich;
sie werden nicht in das Runtime-Image kopiert. Oeffentliche Token-Mints und
Protokollkennungen bleiben technische Konstanten, keine eigenen Konten.

## Settingsseite

Administration > Installation und Konten verwaltet die zuvor eingebauten
Wallets, Einzahlungsadressen, Transfergegenparteien, Helium-Position-Receipts,
Import-/Belegpfade, optionalen V1-Endpunkt und lokale LLM-Konfiguration.
Erwartete Nullbestaende werden nur nach ausdruecklicher Konfiguration geprueft;
fuer neue Nutzer wird kein leerer Exchange-Bestand vorausgesetzt.

Der Server liefert einen typisierten Feldkatalog mit Herkunft und
Bearbeitbarkeit. Umgebungsvariablen haben Vorrang und sind nicht heimlich
ueberschreibbar. Schreibvorgaenge sind revisionsgebunden und atomar;
parallele veraltete Formulare werden abgelehnt. Profile und private
Konfigurationsdateien werden mit Dateimodus 0600 ausserhalb des
Softwareverzeichnisses gespeichert. Auf Dateisystemen, die POSIX-Rechte
nicht abbilden, muss der Betreiber den Zugriff separat absichern.

Der erweiterte Editor verarbeitet ausschliesslich sechs benannte private
JSON-Konfigurationen. Das Quellenregister wird gegen sein Pydantic-Schema
validiert; die weiteren Belegkonfigurationen zunaechst als JSON-Objekt und
anschliessend durch den jeweiligen Fachservice. JSON-Speicherung ist kein
fachlicher Nachweis und keine steuerliche Freigabe. Es wird dabei weder
eine Pipeline gestartet noch eine bestehende Steuerberechnung geaendert.

Die bestehenden Fachservices lesen diese Konfiguration beim Prozessstart.
Nach Konto-, Pfad- oder Belegkonfigurationsaenderungen ist deshalb ein
API-/Containerneustart erforderlich. Die Seite zeigt diese ausstehende
Aktivierung an. Ein Neustart allein reimportiert oder korrigiert keine Daten.

Solscan-, Alchemy-, Jupiter- und Helius-Keys werden ueber den vorhandenen
AES-256-GCM-Vault gespeichert und nicht im Klartext zurueckgegeben. CEX-
Credentials bleiben im bestehenden Admin-Formular. Helius-Keys werden bei
RPC-Probes ausschliesslich serverseitig an die dafuer benannten HTTPS-
Helius-Hosts angefuegt; fremde URLs erhalten diesen gespeicherten Key nicht.
RPC-Fehlertexte geben keine Request-URLs mit Zugangsdaten zurueck.

## Docker und Sicherheitsgrenzen

`docker compose up -d --build` baut Frontend und API. Ein separater Node-
Buildstage erzeugt nur die statischen Frontend-Dateien. Das Runtime-Image
laeuft als UID 10001 mit einem API-Worker, schreibgeschuetztem Software-
Dateisystem und ohne Linux-Capabilities. Ein neues Datenvolume bekommt ein
leeres Profil und einen zufaelligen 32-Byte-Vault-Key. Vorhandene Profile
und Keys werden beim Neustart nicht ersetzt. Ein unlesbarer bestehender
Vault-Key blockiert den Start statt ihn still zu regenerieren.

Standardmaessig ist nur 127.0.0.1 veroeffentlicht. Die API hat weiterhin
keine globale Benutzeranmeldung. Auch auf demselben Rechner duerfen nur
vertrauenswuerdige Nutzer Zugriff haben. Fuer Fernzugriff ist ein gesondertes
Authentifizierungs-/TLS-Gateway oder VPN noetig. Zulassung von Hostnamen und
abweichenden Browser-Origins bleibt explizite Bootstrap-Konfiguration.

Backups muessen das vollstaendige private Volume samt Vault-Key umfassen.
Der Key liegt nicht im Image; Images koennen ohne Kontodaten weitergegeben
werden. Das Datenvolume und seine Sicherungen duerfen nicht weitergegeben
werden. Schluessel und verschluesselte Daten liegen im selben Volume;
dies schuetzt nicht vor einem vollstaendig kompromittierten Host.

## Pruefumfang

Die Validierung umfasst Settings-Roundtrip, veraltete Schreibrevisionen,
Umgebungsprioritaet, externe Dateispeicherung, Secret-Redaktion und
Verschluesselung, Prozessneustart, leeren Containerstart, persistentes
Volume, Browseransicht und erneute Gitleaks-/Kennungspruefung.
Die exakten Ergebnisse stehen bei den Release-Artefakten. Live-Konten,
API-Schluessel und die produktive Datenbank sind kein Teil dieser Tests.

Dokumentationsgrundlagen:
- https://docs.docker.com/build/building/multi-stage/
- https://docs.docker.com/engine/storage/volumes/
- https://www.helius.dev/docs/api-reference/authentication
