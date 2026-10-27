# Automatischer Historienimport pro Quelle

## Bedienung

1. Unter **Quellen & Wallets** die tatsaechlich gewuenschte Wallet oder einzelne
   Boersenverbindung oeffnen, dann **Transaktionen abrufen** waehlen.
2. Den benoetigten Zeitraum einschliesslich frueherer Anschaffungen angeben.
   Binance/Pionex benoetigen explizite Handelspaare. Keine Paare aus dem heutigen
   Bestand ableiten. Fuer Solana gibt es bewusst keinen Assetfilter, der Gebuehren
   oder Gegenbewegungen abschneiden koennte.
3. Bei Solana den Abrufmodus ausdruecklich waehlen: **Oeffentlicher RPC (Free)**
   verwendet ausschliesslich den offiziellen Mainnet-RPC ohne Provider-Keys.
   **Eigener Anbieter (Free/Premium)** erfordert die Auswahl eines eingerichteten
   Helius-, Alchemy- oder Custom-RPC. Ein Key belegt keinen Premium-Tarif;
   Anbieterlimits, moegliche Kosten und Uebermittlung der oeffentlichen Adresse
   beachten. Die Auswahl erhoeht keine Quoten und startet selbst keinen Abruf.
4. Die externe Anfrage bestaetigen und **Vorschau abrufen** starten. Der Server
   speichert Anbieterbelege, Fortsetzungscursor und Auftragsstatus privat.
   Es werden noch keine produktiven Transaktionen oder Steuerdaten veraendert.
5. Datensaetze, Duplikate, Stichprobe, Abdeckung und berechneten Vorher-/Nachherstand
   pruefen. Die Berechnung erfolgt in einer privaten Datenbankkopie.
   Die Stichprobe zeigt bis zu zehn neue normalisierte Ereignisse mit UTC-Zeit,
   Asset, exakter Menge, Gegenmenge und Gebuehren, nicht proprietaere Rohspalten.
   Originalrecords bleiben getrennt unveraendert erhalten. Reine Dubletten
   ergeben keine neuen Vorschauereignisse.
6. Freigebende Person eintragen, **Import dieser Vorschau** und **Neuberechnung**
   getrennt bestaetigen. **Importieren und neu berechnen** uebernimmt nur den
   unveraenderten Vorschauhash und die unveraenderte Datenbasis atomar.
7. Anschliessend **Hinweise pruefen**, Quellenzuordnung und das Steuerjahr
   kontrollieren. Importfreigabe ist weder Eigentumsnachweis noch steuerliche
   Quellenaktivierung oder Jahresfreigabe. Der Personenname ist eine dokumentierte
   Eigenangabe, keine technische Identitaetspruefung.

**Dateien importieren** bleibt ein zusaetzlicher Weg, insbesondere fuer von APIs
nicht lieferbare Zeitraeume/Produkte. Originalexporte sichern. Der automatische
Abruf darf eine alte Datei nicht als zweite unabhaengige Buchung anerkennen.

## Anbieterbindung, Inventar und Restzeit

Ein neuer Solana-Auftrag speichert seine explizite Anbieterwahl und bindet
sich an die zugehoerige Key-/URL-Konfiguration. **Fortsetzen** verwendet diese
Bindung, nicht die inzwischen geaenderte Auswahl im Startformular. Bei
geaendertem Key oder Endpunkt wird nicht still mit der neuen Einrichtung
weitergemacht. Ein Anbieterwechsel erfordert einen neuen Auftrag; Fehler
fuehren zu keinem automatischen Ersatzanbieter. Fuer aeltere Auftraege ohne
gespeicherte explizite Bindung wird keine nachtraegliche Anbieterbindung behauptet.

Der neue Solana-Abruf hat zwei Phasen:

1. **Signaturliste ermitteln:** Verfuegbare finalisierte Referenzen der Wallet
   und nachgewiesener aktueller Tokenkonten sammeln. Bis zum Inventarabschluss
   bleiben eindeutige Gesamtzahl, Gesamtprozentsatz und Restzeit unbekannt.
   Gefundene Referenzen sind noch keine abgerufenen Transaktionsdetails.
2. **Transaktionsdetails abrufen:** Die eindeutigen Signaturen des abgeschlossenen
   Inventars abarbeiten. Mehrfachfunde ueber verschiedene Adressen werden nicht
   als mehrere Transaktionen gezaehlt. Fehlende oder unvollstaendige Details
   werden nicht als erfolgreich erledigt uebersprungen.

Eine Restzeitschaetzung setzt ein abgeschlossenes Inventar, mindestens fuenf
erfolgreich gemessene Detailabrufe, frische Messdaten und lesbare wirksame
Limitdaten voraus. Die geglaettete gemessene Detailrate wird durch die effektiven
gemeinsamen Budgets begrenzt. Messungen erfolgreich gespeicherter Detailseiten
schliessen dort anfallende Warte-/Retryzeiten ein. Die Anzeige ist keine
garantierte Geschwindigkeit und keine Schaetzung fuer die gesamte Bearbeitung.

Discovery, Pause, Abbruch, Fehler oder fehlende/veraltete Messdaten liefern
keinen laufenden Countdown. Bei Anbieterpausen oder fehlgeschlagener
Statusaktualisierung wird keine verlaessliche laufende ETA behauptet.
**Abruf beendet** bedeutet nur, dass die verfuegbaren Details abgearbeitet sind.
Die anschliessende **Vorschauberechnung** hat keine ETA und bleibt von der
gesonderten Importfreigabe getrennt. Auch 100 Prozent der verfuegbaren Details
sind kein Vollstaendigkeitsbeweis fuer die Wallet-Historie.

Die Detailanfragen bleiben sequenziell. Hoehere Tarif- oder Parallelitaetswerte
erzeugen keine zusaetzlichen Detailworker. RPC-Retention und heute nicht mehr
nachweisbare geschlossene Tokenkonten koennen weiterhin Belege fehlen lassen.

## Abdeckung

| Quelle | Automatisch | Wichtige Grenze |
| --- | --- | --- |
| Solana-Adresse | Finalisierte Signaturen/Transaktionsdetails der Adresse und heute nachweisbar zugehoeriger SPL-/Token-2022-Konten | Geschlossene Tokenkonten, historische Eigentumswechsel und RPC-Retention bleiben offen. Zufluss ist nicht automatisch Reward; gegenlaeufige Bewegungen nicht automatisch Swap. |
| Binance | Spot-Fills fuer angegebene Paare, Capital-Ein-/Auszahlungsbelege | Keine automatische Abdeckung aller Earn-, Convert-, Fiat-, Margin- oder Futures-Produkte; lange Zeitraeume brauchen viele Tagesabfragen je Paar. |
| Bitget Classic | Spot-Fills und Wallet-Ein-/Auszahlungsbelege | Fill-API ist auf die letzten 90 Tage begrenzt; aeltere Fills, UTA und andere Produkte mit Originalexporten ergaenzen. |
| Pionex | Spot-Fills fuer angegebene Paare | Keine allgemeine Funding-/Derivatehistorie; Botkontext nicht aus Fills erfinden. |
| Coinbase Advanced | Advanced-Spot-Fills | Keine pauschale Simple-Buy-, Funding-, Reward- oder vollstaendige Coinbase-Historie. |

Die geprueften offiziellen CEX-Vertraege mit Abrufdatum stehen in
[Provider-Referenzen](HISTORY_CEX_PROVIDER_REFERENCES.md). Ein abgeschlossenes
Paging ist **kein** Vollstaendigkeitsbeweis. Die UI bestaetigt dies nicht.
Erfolgreiche, aber mengen-/gebuehrenseitig uneindeutige CEX-Auszahlungen bleiben
mit Originalbeleg als unbekanntes Null-Ereignis und blockierendem Review erfasst.
Es wird weder ein Nullsaldo noch eine Gebuehr oder steuerliche Einordnung behauptet.

## Wiederaufnahme und Fehler

Die Abrufgeschwindigkeit wird zentral unter **Einrichtung -> Abrufsteuerung**
eingestellt, nicht durch einen weiteren Importbutton. Fuer den offiziellen
Solana-Public-RPC gibt es eine konservative Free-Voreinstellung und editierbare
IP-/Anbieter-/Methodenprofile. [Profilwerte und Grenzen](SOLANA_ABRUFLIMITS.md).
Ein strengeres gemeinsames Budget begrenzt alle betroffenen Auftraege weiterhin.
Speichern startet keinen Auftrag und setzt verbrauchte Kontingente nicht zurueck.
Die Ansicht zeigt wirksame gemeinsame Limits, Engpaesse und bekannte Wartegruende;
ein eigener Key ist weder ein Tarifnachweis noch eine automatische Quotenerhoehung.

- Der Browser darf nach Start geschlossen werden. Der Server fuehrt den
  gestarteten Auftrag in begrenzten Abschnitten fort; alle Requests nutzen den
  vorhandenen gemeinsamen Limiter. Ein Seitenwechsel startet keinen neuen Job.
- **Pausieren** stoppt Folgeanfragen. **Fortsetzen** benoetigt erneute externe
  Bestaetigung. Nach einem Server-/Workerneustart kein stiller Wiederanlauf.
- **Abbrechen** verhindert weitere Abschnitte und Importfreigabe, entfernt aber
  bereits gesicherte Originalbelege nicht. Laufende HTTP-Aufrufe koennen bis zu
  ihrem begrenzten Timeout benoetigen; das ist kein erfolgreicher Import.
- Fehlende Details oder fehlerhafte Seiten verschieben den Cursor nicht.
  Vorher erfolgreich gesicherte Seiten bleiben erhalten.
- Das Datensatzlimit stoppt vor Ueberschreitung. Zum Fortsetzen bei Bedarf erhoehen.
  Es gibt hoechstens zwei aktive Abrufe und 100 gespeicherte Auftraege pro
  Installation. Keine automatische Loeschung alter Auditbelege.
- Bei geaenderten Zugangsdaten, Konto-/Walletzuordnung oder Software wird die
  alte Quellbindung nicht still uebernommen. Bestehenden Auftrag abbrechen und
  fuer die neue Konfiguration neu starten.
- Daten-/Preis-/Methodenaenderungen nach Vorschauerstellung sperren die Uebernahme.
  Vorschau erneut erzeugen und neu bestaetigen, nicht den Hash manipulieren.
- Ueberlappende aeltere CEX-Dateidaten ohne belegte API-Identitaet blockieren den
  Import, auch bei bereits zugeordnetem Konto. Erst Belegidentitaet/Zuordnung
  fachlich klaeren; keine alten Batches zum Umgehen loeschen.

## Nachvollziehbarkeit und Speicherung

Jobmetadaten liegen in vorhandenen privaten `admin_settings` unter `history.job.*`.
Unveraenderliche, SHA-256-adressierte Anbieterrecords liegen neben der Datenbank
in `source_history_previews/<Auftrags-ID>/records/`. Diese Verzeichnisse sind
**privat und Teil der Sicherung**, keine oeffentlichen Web-Artefakte.
Der neue Solana-Inventarpfad sichert Owner-/Signaturseiten und Detailreferenzen
zusaetzlich unter `source_history_previews/<Auftrags-ID>/inventory/` mit
SHA-256-Bezug. Ein Datei-Append allein schreibt den gespeicherten Jobcursor
nicht fort; nach Unterbrechung ist nur der bestaetigte Cursor der Fortsetzungspunkt.
Berechnungskopien haben die Endung `.prepared`; nach erfolgreicher Uebernahme
wird nur diese entbehrliche Kopie entfernt. Urspruengliche Dateien und bereits
importierte Rohobjekte werden niemals ueberschrieben.

Stabile Konto-/Walletidentitaet plus Anbieterrecord und finanzieller Digest
verhindern Wiederholungen. Gleiche Identitaet mit widerspruechlichem Inhalt
blockiert statt still zu aktualisieren. Veraenderliche Paging-/Discoverydaten
allein ergeben keine neue finanzielle Buchung.

## API und Wirkungen

Basispfad: `/api/v1/workspace/sources/{ref}/history`.

| Methode/Pfad | Wirkung |
| --- | --- |
| GET Basis, `/jobs/{id}`, `/jobs/{id}/audit.json` | Gespeicherten Zustand lesen; keine Anbieteranfrage oder Berechnung starten. |
| POST `/jobs` | Mit stabiler `request_id` und `confirm_external_request=true` genau eine quellengebundene Sammlung/Vorschau starten. |
| POST `/jobs/{id}/pause`, `/cancel` | Dauerhafte Steuerungsabsicht speichern; kein Import. |
| POST `/jobs/{id}/resume` | Mit ausdruecklicher Bestaetigung am gespeicherten Cursor fortsetzen. |
| POST `/jobs/{id}/import` | Vorschauhash, Person, Import- und Berechnungsbestaetigung pruefen; atomare Uebernahme plus Auditentscheidung. |

Antworten enthalten keine API-Key-/Secretwerte, privaten Dateipfade oder
internen Cursor. Der private Auditabruf enthaelt bewusst die ausgewaehlte
oeffentliche Wallet-/Kontoreferenz und Anfrageparameter. Nicht ungeschwaerzt
oeffentlich weitergeben. Die Installation besitzt keine globale Benutzeranmeldung;
Zugriffsschutz bleibt gemaess Inbetriebnahmeanleitung Aufgabe des Betreibers.

## Offizielle RPC-Quellen

Geprueft am **27.10.2026**: [Solana: Clusters and Public RPC
Endpoints](https://solana.com/docs/references/clusters) und [Helius: Rate
Limits](https://www.helius.dev/docs/billing/rate-limits). Diese Referenzen sind
kein Nachweis des eigenen Tarifs oder einer vollstaendigen historischen Abdeckung.
Lokale Grenzen und Bedienung stehen unter [Solana-Abruflimits](SOLANA_ABRUFLIMITS.md).
