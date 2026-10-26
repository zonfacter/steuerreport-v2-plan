# Inbetriebnahme und geschuetzte Wallet-Einrichtung

## Installation starten

```sh
docker compose -f compose.ghcr.yml pull
docker compose -f compose.ghcr.yml up -d
```

Bei einem privaten GHCR-Paket ist vorher eine eigene Registry-Anmeldung erforderlich.
Im Browser die Adresse der Installation oeffnen. Unter **Einrichtung** zuerst Profil,
privates Datenvolume und verschluesselten Vault kontrollieren. Neue Installationen
enthalten keine persoenlichen Wallets, Boersenkonten oder Originalimporte.
Ein interner Backend-Erfolg ist kein erfolgreicher Boersen-Verbindungstest.

Das Image benoetigt einen persistenten `/state`-Datentraeger. Datenbank, Profil,
private Konfigurationen und `/state/keys` muessen Neustarts und Updates ueberstehen.
Kein `docker compose down -v` verwenden. Die Anwendung besitzt weiterhin keine
globale Benutzeranmeldung; nur im vertrauenswuerdigen LAN/VPN oder hinter TLS
und einem geeigneten Authentifizierungszugang betreiben.

## Connector-Einrichtungspasswort

Dieses Passwort schuetzt die vorhandenen Connector-Administrationsfunktionen,
unter anderem Wallet-Eigentumsnachweise und die Kopplung von Mobilgeraeten.
Es ist **kein** Wallet-Passwort, Private Key, Seed oder Boersen-API-Schluessel.
Es erlaubt keine Boersen-Trades oder Auszahlungen. Nur dem Betreiber geben,
nicht an andere Nutzer, externe KI, Support-Chats oder in Screenshots weitergeben.

Bei einer **neuen Docker-Installation** wird ein zufaelliges Passwort in der
privaten Datei `/state/keys/connector-setup.token` mit Dateirechten 0600 vorbereitet.
Vorhandene Passwoerter und Vault-Schluessel werden niemals automatisch ersetzt.
Ein Update einer **bestehenden Installation** aktiviert diesen Zugang nicht still.

Status in der privaten Betreiberkonsole pruefen:

```sh
docker compose -f compose.ghcr.yml exec steuerreport python -m steuerreport_v2.connector_setup status
```

Nur wenn noch nicht eingerichtet, ausdruecklich vorbereiten:

```sh
docker compose -f compose.ghcr.yml exec steuerreport python -m steuerreport_v2.connector_setup init
```

`init` erzeugt hoechstens eine neue private Passwortdatei. Es gibt kein Passwort
aus, ersetzt keine bestehende Datei und schreibt keine Transaktionen, Steuerdaten
oder Quellenfreigaben. Anschliessend in **Einrichtung → Wallet-Eigentumsnachweis**
den Status neu pruefen. Ein Neustart ist fuer diese Aktivierung nicht erforderlich.

Passwort ausschliesslich in einer privaten interaktiven Konsole anzeigen:

```sh
docker compose -f compose.ghcr.yml exec steuerreport python -m steuerreport_v2.connector_setup show-token
```

Compose `exec` verwendet normalerweise ein interaktives Terminal. Nicht `-T`,
eine Pipe, Umleitung oder Protokollaufzeichnung verwenden. Ohne Terminal verweigert
`show-token` die Ausgabe. Das Passwort steht niemals in einer URL oder API-Antwort.
Die Weboberflaeche bietet keine unauthentifizierte Passwortausgabe oder Freischaltung.

Bei einem manuell gestarteten Container:

```sh
docker exec -it CONTAINERNAME python -m steuerreport_v2.connector_setup status
docker exec -it CONTAINERNAME python -m steuerreport_v2.connector_setup init
docker exec -it CONTAINERNAME python -m steuerreport_v2.connector_setup show-token
```

Den eigenen Containernamen verwenden. Fuer einen lokalen Compose-Build entfaellt
`-f compose.ghcr.yml`. Nativ im installierten Python-Umfeld dieselben Unterbefehle
mit `python3 -m steuerreport_v2.connector_setup` ausfuehren. Wer `initialize_state()`
bei einer neuen nativen Installation nutzt, erhaelt dieselbe sichere Vorbereitung.

## Wallet-Eigentumsnachweis

1. **Quellen & Wallets → Quelle hinzufuegen → Solana-Wallet** waehlen.
2. Die eigene oeffentliche Adresse eingeben.
   Keine Token-Mint- oder Programmadresse verwenden; diese ist kein eigener Signaturschluessel.
3. Das lokale Einrichtungspasswort in **Connector-Setup-Token** einfuegen.
4. Die Nachricht fuer den Eigentumsnachweis ausdruecklich anfordern.
5. Genau diese Nachricht mit einem vertrauenswuerdigen, kompatiblen Wallet-Signer
   als Nachricht signieren, nicht als Transaktion. Niemals Private Key oder Seed
   eingeben. Die Anwendung oeffnet derzeit kein automatisches Phantom-Signierfenster.
6. Die oeffentliche Base58-Signatur einfuegen, die Zusammenfassung pruefen und
   **Signatur pruefen und speichern** ausfuehren.

Der Token bleibt nur im aktuellen Formular und wird nach erfolgreicher Verarbeitung
verworfen. Nicht in URL, Browser-Storage oder Diagnoseexport ablegen. Ohne gueltigen
Bearer bleibt die API gesperrt; ohne gueltige Wallet-Signatur entsteht kein
bestaetigter Eigentumsnachweis. Die Challenge ist zeitlich begrenzt.

Eigentum ist weder Historienimport noch steuerliche Aktivierung. Danach weiterhin
Originalhistorie, Quellenregister, Dubletten, Preise und fachliche Freigaben pruefen.
Dateiimporte und Boersen-Zugaenge haben eigene Einrichtungsablaeufe.

## Vorhandene explizite Konfiguration und Fehler

`STEUERREPORT_V2_CONNECTOR_SETUP_TOKEN_FILE` kann weiterhin eine gesonderte private
Passwortdatei vorgeben. Ihr Inhalt wird nicht ersetzt. Ein ausdruecklich leerer
Wert deaktiviert den Setup-Zugang; ein falscher/unlesbarer Pfad faellt niemals auf
ein anderes Passwort zurueck. In Docker muss diese Variable im Container gesetzt
und die Datei fuer den Dienstbenutzer lesbar eingebunden sein.

- **Nicht vorbereitet:** `status` pruefen und gegebenenfalls lokal `init` ausfuehren.
- **401/403:** Einrichtungspasswort beziehungsweise erteilten Connector-Scope pruefen;
  kein Boersen- oder Wallet-Passwort verwenden.
- **503:** Private Datei, Umgebungskonfiguration und Dateirechte pruefen.
- **Unsichere/leere Datei:** Nicht blind loeschen oder ueberschreiben. Original sichern
  und den konkreten Konfigurations-/Dateifehler administrativ beheben.
- **Abgelaufene/ungueltige Signatur:** Neue Challenge anfordern und exakt deren
  Nachricht signieren. Es erfolgt keine automatische steuerliche Anerkennung.

Vor Updates das gesamte Volume einschliesslich **beider** privaten Dateien
`keys/vault.key` und `keys/connector-setup.token` sichern. Keine privaten Sicherungen
an GitHub-Releases anhaengen. Neue Versionen nie mit alten Zugangsdaten im Image bauen.
