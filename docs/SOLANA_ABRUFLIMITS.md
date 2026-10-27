# Solana-Abruflimits einstellen

## Einrichtung

Die Einstellungen liegen unter **Einrichtung -> Abrufsteuerung**, zusammen
mit den vorhandenen API-, Konto- und Verbindungseinstellungen.

1. Den gespeicherten Stand und die lokale Budgetauslastung laden.
2. Das Profil **Solana Public RPC - Free** pruefen. Die Anwendung nennt Quelle,
   Pruefdatum, betroffene gemeinsame Gruppen und vorhandene Konflikte.
3. Die Aenderung ausdruecklich bestaetigen und das Profil anwenden. Dabei
   werden ausschliesslich lokale Abruflimits gespeichert. Es startet weder
   ein Anbieterabruf noch ein Import oder eine Neuberechnung.
4. Fuer eigene Werte das betreffende **Limitprofil** auswaehlen und bearbeiten.
   Sekunden-, 10-Sekunden- und Minutenfenster gelten gleichzeitig. Ein leeres
   optionales 10-Sekunden-Feld fuegt keine weitere lokale 10-Sekunden-Grenze
   hinzu; die anderen Fenster bleiben aktiv. Null ist kein gueltiges Limit.
5. Endpunktprofile koennen einzelne RPC-Methoden zusaetzlich einschraenken.
   Ein hoeheres Endpunktlimit hebt die gemeinsame Anbieter- oder IP-Grenze
   nicht auf. KI-Limits bleiben getrennt.

Ein bereits individuell abweichend konfiguriertes Profil wird durch die
Voreinstellung nicht still ueberschrieben. Die betroffenen Profile zuerst
pruefen und gegebenenfalls gezielt im Editor anpassen. Bei zwischenzeitlicher
Aenderung durch einen anderen Browser zuerst neu laden.

Auch ein begonnener Tarifentwurf bleibt an seinen urspruenglichen
Konfigurationsstand gebunden. Nach einer konkurrierenden Aenderung wird seine
Bestaetigung ungueltig; alte Eingaben duerfen keine neuere Tarifgrenze ersetzen.
Den aktuellen Stand ausdruecklich in das Formular laden und erneut pruefen.

## Anbieter fuer einen Historienauftrag waehlen

Unter **Quellen & Wallets -> Transaktionen abrufen** ist die Anbieterwahl
vom Limitprofil getrennt: **Oeffentlicher RPC (Free)** verwendet den offiziellen
Mainnet-RPC ohne Key. **Eigener Anbieter (Free/Premium)** verlangt einen
eingerichteten Helius-, Alchemy- oder Custom-RPC. Ein eigener API-Key weist
keinen bezahlten Tarif nach und hebt keine Quote automatisch an.

Neue Auftraege bleiben an die gewaehlte Anbietereinrichtung gebunden.
Fortsetzen behaelt die gespeicherte Bindung; eine neue Auswahl im Startformular
aendert den alten Auftrag nicht. Bei Key-/URL-Aenderung gibt es keinen stillen
Wechsel und bei Fehlern keinen automatischen Ersatzanbieter. Fuer einen
Anbieterwechsel einen neuen Auftrag anlegen. Bei Legacy-Auftraegen ohne
explizit gespeicherten Pin bleibt die eindeutige Anbieterbindung unbestaetigt.

Die angezeigten effektiven Limits beruecksichtigen die gemeinsam passenden
IP-, Anbieter-, Endpunkt- und weiteren konfigurierten Budgets. Auch ein hoher
Anbietertarif kann am niedrigeren gemeinsamen IP-Budget begrenzt bleiben.
Lesen dieser Statusdaten startet keine Anbieteranfrage und erhoeht keine Limits.
Nicht lesbare Limitdaten sind unbekannt, nicht unbegrenzt.

## Konservative Voreinstellung

| Budget | Sekunde | 10 Sekunden | Minute | Burst | Parallelitaet |
| --- | ---: | ---: | ---: | ---: | ---: |
| Gemeinsames IP-Budget `ip:global` | 3 | 30 | 180 | 1 | 1 |
| Anbieter `provider:solana_rpc` | 3 | 30 | 180 | 1 | 1 |
| Historien-RPC-Methode | 4 | 40 | 240 | 1 | 1 |

Die Methodenprofile gelten fuer `getTransaction`, `getSignaturesForAddress`
und `getTokenAccountsByOwner`. Alle passenden Budgets werden vor jedem
tatsaechlichen Request-Start gemeinsam geprueft, auch bei Wiederholungen und
weiteren Historienseiten. Eine zweite Wallet erhaelt kein zweites IP-Budget.
Die strengste gleichzeitig geltende Grenze entscheidet.

Die lokalen Fenster sind rollierend: `(jetzt - Fenster, jetzt]`. Ein
Zeitfensterwechsel erlaubt keinen zusaetzlichen Doppelburst. Burst ist eine
zusaetzliche Token-Bucket-Grenze, keine Erlaubnis, ein Zeitfenster zu umgehen.
Parallelitaet begrenzt laufende HTTP-Aufrufe und erzeugt keine zusaetzlichen
Worker. Der Historien-Detailabruf bleibt sequenziell.

## Quelle und Grenzen

Geprueft am **27.10.2026**:
[Solana: Clusters and Public RPC Endpoints](https://solana.com/docs/references/clusters).
Fuer das oeffentliche Mainnet nennt die Dokumentation pro IP:

- 100 Requests je 10 Sekunden insgesamt;
- 40 Requests je 10 Sekunden fuer dieselbe RPC-Methode;
- 40 gleichzeitige Verbindungen;
- 40 neu aufgebaute Verbindungen je 10 Sekunden;
- 100 MB Daten je 30 Sekunden.

Diese Angaben koennen sich ohne Vorankuendigung aendern und sind keine
vertraglich garantierte Rate. Der bestehende RPC-Helfer baut fuer einzelne
Aufrufe HTTP-Clients auf. Daher ist die lokale Startvorgabe von 3/s bewusst
vorsichtiger als das reine Gesamtrequestlimit. Andere Anwendungen hinter
derselben oeffentlichen IP koennen das Anbieterbudget ebenfalls verbrauchen;
sie werden durch diesen host-lokalen Koordinator nicht erfasst.

**Das Datenvolumen von 100 MB/30 s ist kein implementiertes oder gemessenes
Bytebudget.** Es wird keine verbleibende Herstellerquote erfunden. Bei grossen
Antworten oder gemeinsam genutzter IP niedrigere Betreiberwerte setzen.
Eigene RPC-Dienste, Helius und Alchemy benoetigen jeweils passende eigene
Tarifprofile; der Solana-Public-Wert bestaetigt deren Kontingente nicht.

Ebenfalls geprueft am **27.10.2026**: [Helius: Rate
Limits](https://www.helius.dev/docs/billing/rate-limits). Dort werden Tarif- und
Produktlimits unterschieden. Ein gespeicherter Helius-Key verraet nicht den
gebuchten Tarif; dessen Werte muessen beim Anbieter geprueft und bewusst als
passende lokale Profile gepflegt werden. Hier werden keine neuen Herstellerzahlen
oder automatisch hoehere Quoten uebernommen.

## Fortschritt und Restzeit

Bei neuen Solana-Auftraegen wird zuerst die verfuegbare Signaturliste
inventarisiert. Solange das Inventar nicht abgeschlossen ist, bleiben
eindeutige Gesamtzahl, Gesamtprozentsatz und ETA unbekannt. Erst danach kann
die Restzeit fuer **verbleibende verfuegbare RPC-Transaktionsdetails** geschaetzt
werden: mindestens fuenf erfolgreich gemessene Detailabrufe, frische Messungen
und verfuegbare effektive Limitdaten sind erforderlich. Die geglaettete Messrate
wird auf die wirksame gemeinsame Obergrenze begrenzt; bekannte Kontingentwartezeit
geht in die Berechnung ein. Messzeiten erfolgreich gespeicherter Detailseiten
enthalten dort anfallende Warte-/Retryzeiten.

Pausierte, abgebrochene oder fehlerhafte Auftraege erhalten keinen Countdown.
Fehlende/veraltete Messdaten, Anbieterpausen oder nicht aktualisierbarer Status
sind keine Grundlage fuer eine verlaessliche laufende Restzeitanzeige.
Die **Vorschauberechnung hat keine ETA**; ihr Aufwand ist in der Detailabruf-
Schaetzung nicht enthalten. Ein beendeter Abruf ist noch keine Importfreigabe.

Der Detailabruf bleibt sequenziell. Ein hoeheres lokales Parallelitaetslimit
nutzt einen Premium-Tarif daher nicht automatisch voll aus. RPC-Latenz und
Belegsicherung begrenzen die tatsaechliche Rate zusaetzlich. Anbieter-Retention,
geschlossene Tokenkonten und historische Eigentumswechsel bleiben Grenzen:
auch eine abgearbeitete Liste beweist keine vollstaendige Historie.

## Geschwindigkeit und Fehler

Die vorherige lokale Standardbegrenzung von 30/min bleibt fuer nicht separat
konfigurierte Anbieter erhalten. Die Solana-Voreinstellung hebt nur die
ausdruecklich genannten Gruppen an. Ein langsameres gemeinsames Profil kann
den Solana-Abruf weiterhin begrenzen; dessen Wartegrund steht in der
Budgetauslastung. Hoehere Zahlen allein garantieren keine Transaktionsrate:
RPC-Latenz, Originalbelegsicherung und Berechnung benoetigen ebenfalls Zeit.

Eine Konfigurationsaenderung behaelt vorhandene Startbuchungen, Pausen und
laufende Reservierungen bei. Sie setzt kein Kontingent zurueck. Ein aktiver
Abruf beruecksichtigt die wirksamen Werte beim naechsten Request-Start.
Abgebrochene oder pausierte Auftraege werden durch Speichern nicht gestartet.
Nach Software-/Quellwechsel kann ein neuer quellengebundener Auftrag notwendig
sein; alte Originalbelege bleiben erhalten.

HTTP 429 mit `Retry-After` wird nach vorhandener Retry-Regel behandelt, nicht
durch sofortige Wiederholung umgangen. Anbieter- und lokale Wartezeiten
bleiben unterscheidbar. IP-/Key-Wechsel zur Limitumgehung gibt es nicht.

Die Aenderung betrifft nur den Transport. Mengen, Originaldaten, FIFO-, Steuer-,
Review-, Eigentums- und Importfreigaberegeln werden nicht angepasst.

Wuerde eine neue oder engere Parallelitaetsbindung bereits reservierte Requests
gegenseitig blockieren, lehnt die API das Speichern mit HTTP 409 ab. Es erfolgt
keine Teilaenderung. Bestehende Anfragen zuerst beenden lassen und danach den
aktuellen Stand erneut pruefen; keine Reservierungen manuell loeschen.

## Installation und Rueckkehr zu einer alten Version

Bestehende Konfigurationen ohne die neuen optionalen Felder werden gelesen;
Standardwerte und vorhandene Budgets bleiben erhalten. Die neuen Felder werden
mit dem privaten Koordinatorzustand dauerhaft gespeichert, nicht im Quellcode.
Vor einem Update Datenvolume, Profile, Schluessel und Koordinator gemeinsam
sichern. Alte Software kann die erweiterten strikt validierten Zustandsfelder
nicht notwendigerweise lesen. Eine Rueckkehr benoetigt daher das passende
Zustandsbackup und nachweislich beendete alte Worker/HTTP-Aufrufe; nur ein
Imagewechsel genuegt nicht. Niemals den Koordinator loeschen oder waehrend
laufender Requests auf einen frueheren Zaehlerstand zuruecksetzen.
