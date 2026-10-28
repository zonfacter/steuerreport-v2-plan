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

## Version und Updates (Entwicklungsstand nach rc32)

Die Versionsanzeige im Kopfbereich oeffnet **Einrichtung -> Version & Updates**
(`/#admin?tab=updates`). Die installierte Version kommt vom eigenen Backend,
nicht aus einem Image-Namen. Stabile Versionen und stabile Versionen mit RC
sind getrennte Kanaele. Ein RC bleibt anhand seiner Versionsnummer ein RC,
auch wenn GitHub ihn als Latest ohne Prerelease-Flag fuehrt.

Automatische Pruefungen sind anfangs ausgeschaltet. Eine Checkbox-Aenderung
erst mit **Einstellungen speichern** uebernehmen. **Jetzt pruefen** fragt nur
oeffentliche Release-Metadaten des festen Projekt-Repositories ab; es werden
keine Finanzdaten, Provider-Zugangsdaten oder KI-Anfragen uebertragen.
Automatische Pruefungen im geoeffneten Browser erfolgen hoechstens alle sechs
Stunden, manuelle Pruefungen mit mindestens einer Minute Wartefrist. Mehrere
Fenster verwenden dieselbe serverseitige Sperre und denselben Cache. Die
gespeicherte Anzeige neu laden liest nur den lokalen Cache. Demo-/Testvorschauen
erlauben keine externen Pruefungen oder Einstellungsaenderungen.

Ein gefundenes Release ist weder eine Installationsfreigabe noch ein Beleg
fuer ein oeffentlich verfuegbares Docker-Image. Quellcommit und Image-Digest
bleiben als unbekannt markiert, solange sie nicht verifiziert wurden.
**Updateauftrag fuer KI kopieren** erzeugt einen auf das ausgewaehlte Release
und dessen Metadatenhash gebundenen Text. TXT und JSON enthalten denselben
Auftrag; ein spaeter gefundenes Release ersetzt das Ziel nicht automatisch.
Ohne Browser-Zwischenablage wird der vollstaendige Text zur manuellen Auswahl
angeboten, ohne falsche Erfolgsmeldung. Fremde Versionshinweise werden als Text
angezeigt und nicht als Handlungsanweisung in den Auftrag uebernommen.

Kein Button installiert Software, startet Docker, akzeptiert eine steuerliche
Entscheidung oder korrigiert Finanzdaten. Ein Update bleibt ein separater
administrativer Auftrag mit Sicherung, geprueftem Image und Rueckweg.

## Abrufgeschwindigkeit einstellen

Unter **Einrichtung -> Abrufsteuerung** lassen sich gemeinsame IP-, Anbieter-
und Endpunktprofile konfigurieren. Fuer den offiziellen oeffentlichen Solana-RPC
steht eine ausdruecklich anzuwendende konservative Free-Voreinstellung bereit:
3 Requests/s, 30 je rollierenden 10 Sekunden und 180/min. Vorhandene individuelle
Profile werden bei Konflikten nicht still ueberschrieben. Das Standardprofil
anderer Anbieter bleibt erhalten. Auch nach dem Anwenden sind die Zahlen im
gleichen Einstellungsbereich bearbeitbar.

Speichern startet keinen Abruf, Import oder Neuberechnung. Bereits verbrauchte
Budgets und Anbieterpausen bleiben erhalten. Die Anzeige der lokalen Nutzung
ist keine gemessene Herstellerrestquote; Parallelitaet erzeugt keine weiteren
Import-Worker. [Bedienung, Profilwerte und Grenzen](SOLANA_ABRUFLIMITS.md).

## Oeffentliche Solana-Adresse hinzufuegen

1. **Quellen & Wallets → Quelle hinzufuegen → Solana Wallet** oeffnen.
2. Die vorausgewaehlte Eingabeart **Oeffentliche Adresse speichern** beibehalten.
3. Optional einen Namen und die oeffentliche Solana-Adresse eingeben.
4. **Weiter**, Zusammenfassung pruefen und **Adresse speichern** waehlen.

Keine Signatur, kein Einrichtungspasswort, kein API-Key und keine Wallet-Verbindung
sind fuer diese Adressspeicherung erforderlich. Das funktioniert auch ueber den
normalen lokalen HTTP-Zugriff. Adresse und Name werden ausschliesslich im privaten
Datenvolume gespeichert und erscheinen nach Neuladen in der Quellenliste.
Mehrere Adressen werden getrennt gefuehrt; eine erneut gespeicherte Adresse erzeugt
keinen zweiten Eintrag und setzt einen vorhandenen Pruefstatus nicht zurueck.

Speichern startet **keinen** externen Abruf, Import oder steuerliche Aktivierung.
Die Transaktionshistorie unter **Quelle → Transaktionen abrufen** starten.
Der Abruf verwendet genau diese gespeicherte Adresse, auch fuer weitere
Beobachtungswallets. CSV-/Excel-Import bleibt zusaetzlich moeglich. Der bisherige
Bestandsabruf bleibt auf konfigurierte Haupt-/weitere Wallet und eingerichtete
Datenanbieter beschraenkt; zusaetzliche Beobachtungsadressen erhalten keinen
wirkungslosen Synchronisieren-Button. Eine Signatur ist nur fuer den gesonderten
kryptografischen Eigentumsnachweis erforderlich, nicht zum Anlegen einer Adresse.
Bestehende private Profiladressen werden ebenfalls ohne erfundenen Nachweis sichtbar.

Der neue lokale Schreibvertrag `POST /api/v1/workspace/wallets` akzeptiert nur
`wallet_address` und optional `display_label`. Er setzt weder `source_id` noch
`verified_at`, aendert kein privates Profil und startet keinen Provider-Aufruf.
Er verwendet denselben lokalen Host-/Origin-Schutz wie die bestehende Einrichtung;
dies ist keine globale Benutzeranmeldung. Demo-/Testvorschauen bleiben schreibgesperrt.

## Solana-Bestandsabruf und Datenanbieter

Nach erfolgreichem Abruf unter **Quellen & Wallets → Quelle → Bestaende** die
gespeicherten Tokenmengen lesen. Sie erscheinen auch ohne Transaktionshistorie
oder EUR-Preise. Das Dashboard bietet einen direkten Einstieg. Fehlender EUR-Preis
bedeutet unbekannten Wert, nicht Nullbestand; 0 importierte Ereignisse bedeutet
nicht, dass der Bestandsabruf fehlgeschlagen ist. Eine Historie muss separat
importiert werden. Keine Anschaffungswerte aus heutigen Bestaenden ableiten.

Nach Aenderung der Profil-RPC-URL den angezeigten Neustarthinweis beachten.
Speicherung allein aendert eine bereits laufende Runtime-Konfiguration nicht.

Der Bestandsabruf der bereits zugeordneten Profilwallets nutzt den vorgesehenen
oeffentlichen beziehungsweise konfigurierten Solana-RPC auch ohne Alchemy-Key.
Ein gespeicherter Alchemy- oder Helius-Zugang wird serverseitig beruecksichtigt;
private Schluessel ausschliesslich im Provider-Key-Feld speichern. Die RPC-URL
im Profil bleibt geheimnisfrei. Oeffentliche RPCs koennen zeitweise begrenzen
oder Anfragen ablehnen; fuer regelmaessigen Betrieb einen geeigneten eigenen
Anbieter einrichten. Beim Abruf wird die oeffentliche Adresse an diesen gesendet.

**Hinweise / Abgleich** zeigt den letzten konkreten Fehler und einen Einstieg
zur Einrichtung. Ohne ersten erfolgreichen Abruf ist der Bestand unbekannt,
nicht 0,00 EUR. Unvollstaendige RPC-Antworten gelten nicht als Nullbestand.
Ein spaeterer Fehler loescht keinen zuvor erfolgreichen historischen Stand.
Abruflimits bleiben aktiv; keine Historienimporte oder Steuerneuberechnung.
Weitere Beobachtungsadressen erhalten durch diesen Patch keinen neuen Connector.

### Historienimport und Wiederholungen

Der direkte Historien-Endpunkt ist nicht derselbe Vorgang wie **Synchronisieren**.
Er importiert Transaktionen und startet die bestehende Berechnungspipeline.
Eine wiederholte oder ueberlappende Seite erzeugt keine zweite finanzielle Buchung
derselben Wallet/Signatur. Bei reiner Wiederholung wird auch nicht neu berechnet.

Eine Meldung ueber **abweichende Belege** oder **nicht vollstaendig bestaetigten
Vorimport** bedeutet: alte Daten bleiben erhalten; der Import braucht eine
manuelle Pruefung. Keine alten Batches zum blossen Umgehen dieser Meldung loeschen.
Fehlende Details brechen die ganze Seite vor dem Import ab. Den Abruf spaeter mit
demselben Cursor wiederholen, nicht den naechsten Cursor erraten.

Netzwerkgebuehren sind von SOL-Bewegungen getrennt. Tokenzufluss allein beweist
keinen Reward, und SOL-Abgang plus Tokenzufluss beweist noch keinen Swap.
Ungeklaerte Bestandsbewegungen erzeugen deshalb einen blockierenden Pruefhinweis.
Der technische Import ist keine steuerliche Freigabe. Bestehende Originalimporte
werden durch dieses Softwareupdate weder veraendert noch automatisch korrigiert.
Der neue gefuehrte Browserablauf ist in
[Automatischer Quellenimport](AUTOMATISCHER_QUELLENIMPORT.md) beschrieben.
Er sammelt Belege wiederaufnehmbar, erstellt eine isolierte Berechnung und
verlangt eine gesonderte Importfreigabe. Auch ein beendeter RPC-Scan beweist
keine vollstaendige Historie geschlossener Tokenkonten oder begrenzter Anbieter.

## Optionales Connector-Einrichtungspasswort

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

## Optionaler Wallet-Eigentumsnachweis

1. **Quellen & Wallets → Quelle hinzufuegen → Solana-Wallet** waehlen.
   Eingabeart **Optional: Eigentum per Signatur nachweisen** ausdruecklich auswaehlen.
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

## Historische EUR-Preise Ohne Altinstallation

Ab rc29 benoetigt der gefuehrte Preisablauf keinen V1-Wechselkurscache.
Nach ausdruecklichem Transaktionsimport unter Portfolio & Haltefristen ->
EUR-Preise ermitteln den Bedarf planen, Providerabruf bestaetigen und erst
nach Pruefung Preise plus Neuberechnung uebernehmen. Eigene Preiszuordnungen
werden privat gespeichert; Einrichtung verlinkt diese Zuordnung.
Details: [Historische EUR-Preise](HISTORISCHE_EUR_PREISE.md).

Ab rc31 ist **Alle erkannten Token** der normale Preiseinstieg. Er umfasst
auch Transfers und bietet Alle Jahre, Jahresuebersicht, begrenzte fortsetzbare
Abrufabschnitte sowie vollstaendige Jahresdateien und Originalbelege als ZIP.
Der komplette Ablauf ist ohne KI oder Terminal bedienbar. Bestehende steuerliche
Preisbedarfe bleiben ein eigener Modus. Preisuebernahme setzt weiterhin
Vorschau, menschliche Bestaetigung und unveraenderte Ereignisklassifikationen
voraus. Ein Preisabruf schliesst keine ungeklaerten Reward-/Trade-Zuordnungen.

Ab rc32 ergaenzt die automatische Preissuche nahe historische Zielzeitpunkte
und nur fuer belegtes natives SOL beziehungsweise native SOL-Gebuehren eine
native Referenz; keine globale SOL-/WSOL-Paritaet. Quotes bleiben am selben
UTC-Tag, nicht nach dem ersten Ereignis und hoechstens eine Stunde vom
urspruenglichen Ziel entfernt. Legacy-Mint-Zuordnungen duerfen ihre originale
Schreibweise nicht aus grossgeschriebenen Asset-Aliasen rekonstruieren.

Vor dem Start Abschnitts- und Gesamtbudget pruefen: UI-Vorgabe 200 HTTP-Starts
insgesamt, einstellbar von 1 bis 1000, maximal 50 je Abschnitt einschliesslich
alternativer Suche, Retry und FX. Bei aktivierter automatischer Fortsetzung
deckt die ausdrueckliche Zustimmung weitere ausstehende Abschnitte innerhalb
des Gesamtbudgets ab. Budgetende, Fehler oder fehlender Fortschritt stoppen
die Folge. Kein automatischer Preisimport, keine Uebernahme der Neuberechnung
oder steuerliche Entscheidung; persoenliche Freigabe bleibt separat.

Ein Update importiert keine bereits abgerufenen Transaktionen. Fertige alte
Historienvorschauen vor Importfreigabe ausdruecklich lokal erneut berechnen;
Originalbelege bleiben erhalten.
