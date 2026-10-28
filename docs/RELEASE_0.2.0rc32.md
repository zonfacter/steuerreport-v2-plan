# Steuerreport V2 0.2.0rc32

Releasekandidat vom 28.10.2026. Keine Aussage ueber eine bereits erfolgte
Image-Veroeffentlichung oder ein produktives Update. Lokale Pruefergebnisse
stehen unten; finale Build-, CI-, Image- und Deploymentbelege werden getrennt
am Release hinterlegt, sobald sie tatsaechlich vorliegen.

## Historische Preise Automatisch Suchen

Portfolio & Haltefristen -> EUR-Preise ermitteln -> Umfang und Jahr waehlen ->
Preisbedarf planen -> Abschnitts- und Gesamtbudget pruefen -> externen Abruf
bestaetigen -> kumulative Vorschau und offene Gruende pruefen.

Die automatische DefiLlama-Strategie fragt zunaechst den urspruenglichen
Zielzeitpunkt ab. Fehlt ein passender Quote, folgen begrenzte nahe Zeitpunkte.
Nur fuer nachgewiesen natives SOL beziehungsweise native SOL-Gebuehren ist
zusaetzlich `coingecko:solana` als native Preisreferenz zulaessig. Der
urspruengliche Provider und die tatsaechlich erfolgreiche Referenz bleiben
unterscheidbar. Das ist keine allgemeine Gleichsetzung von SOL und WSOL;
originale SPL-Mints, andere Token und Liquid-Staking-Token erhalten daraus
keinen Alias. Identitaetskonflikte und Spam-Sperren bleiben wirksam.

Fuer jede Alternative gelten dieselben Regeln: Quote am selben UTC-Tag,
nicht nach dem ersten Ereignis und maximal 3600 Sekunden vom urspruenglichen
Zielzeitpunkt entfernt. Dieser Zielzeitpunkt liegt 30 Minuten vor dem ersten
Ereignis, fruehestens um UTC-Mitternacht. Nahe Abfragen verschieben nicht das
Zulaessigkeitsfenster. Gespeichert wird der tatsaechliche Quote-Zeitpunkt,
kein zurueckdatierter spaeterer Kurs. Historische EZB-USD/EUR-Tagesreferenzen
duerfen weiterhin hoechstens sieben Kalendertage zurueckliegen.

## Begrenzte Abschnitte Und Freigabe

Die UI schlaegt 200 tatsaechliche HTTP-Starts als Gesamtbudget vor; einstellbar
sind 1 bis 1000. Ein Abschnitt bleibt auf hoechstens 50 Starts begrenzt.
Alternative Suchversuche, HTTP-Wiederholungen und Wechselkurse zaehlen mit.
Gemeinsame IP-/Anbieterlimits bleiben wirksam; das Budget ist keine Quote
des Anbieters und keine Zusage einer bestimmten Anzahl gefundener Preise.

Bei aktivierter automatischer Fortsetzung gilt die ausdrueckliche Zustimmung
fuer weitere ausstehende Abschnitte innerhalb des gebundenen Gesamtbudgets.
Erreichtes Budget, fehlender Fortschritt, Fehler oder geaenderte Ansicht
stoppen die automatische Folge. Gespeicherte IDs oder ein Seitenneuladen
stellen die Einwilligung nicht wieder her. Offene fehlgeschlagene Zeilen
erfordern einen bewusst gestarteten erneuten Versuch; kein Endlos-Retry.

Sammlung und isolierte Neuberechnung sind kein produktiver Preisimport.
Erst gepruefte Vorschau, benannte Person und getrennte Bestaetigungen fuer
Preise und Neuberechnung erlauben die atomare Uebernahme. Keine automatische
Quellen-, Token-, Einkommens-, FIFO-, Review- oder Jahresentscheidung.

## Gespeicherte Mint-Zuordnungen

Bei alten Zuordnungen konnte der normalisierte grossgeschriebene Asset-Alias
irrtuemlich als originale Mint-Schreibweise behandelt werden. Beim Lesen
gespeicherter Zuordnungen wird diese verlorene Schreibweise nicht geraten.
Eine bereits explizite Original-Mint beziehungsweise eine erhaltene exakte
`solana:`-Provider-ID liefert weiterhin die case-sensitive Identitaet.
Reine Grossbuchstaben-Aliase oder CoinGecko-Symbole allein ersetzen diesen
Nachweis nicht. Keine Umschreibung von Originalimporten oder pauschale
Freigabe alter Zuordnungen.

## Synthetische Pruefung Und Fachliche Grenzen

Eine synthetische 20-Tage-Regression prueft den begrenzten Native-SOL-
Fallback. Synthetische Fixtures enthalten keine persoenlichen Transaktionen
oder Wallets. Fokussierte Ergebnisse und offene Releasepruefungen werden
unten getrennt ausgewiesen; keine pauschale Vollstaendigkeitszusage.

Preisbedarfe und fachliche Hinweise sind unterschiedliche Einheiten.
Gefundene Tagespreise schliessen keine Klassifizierungsfragen und belegen
weder eine neue Reward-/Trade-Zuordnung noch eine vollstaendige Historie.
Ein gefundener Referenzpreis ist keine automatische produktive
Preisuebernahme. Reale Installationszahlen, finanzielle Aggregate und
Native-/WSOL-Einzelproben bleiben ausschliesslich in privaten Diagnose-
beziehungsweise Release-/Runtime-Belegen. Private Wallets, Originalantworten,
Belegpfade und Fallartefakte gehoeren nicht ins Repository oder Image.

## Pruefstatus

Verifizierter lokaler Stand vom 28.10.2026:

- 231 Preis-/Workflow-/Mappingregressionen bestanden.
- 59 automatische Preisfaelle nach der Native-SOL-Originalziel-Ergaenzung
  bestanden; die alternative native Referenz fragt auch das Originalziel ab.
- 229 Impact-Regressionen bestanden.
- Abschliessender Browserlauf mit 12 Screens bei 390/768/1280/1440 Pixeln
  bestanden, keine Browserfehler oder externen Requests. Frontend-Build
  erfolgreich; bestehende Warnung zum grossen Haupt-JavaScript-Bundle bleibt.
- rc32-PDFs mit 16, 10 und 9 Seiten erzeugt und Versionsangabe geprueft.

Die Angaben beziehen sich auf getrennte Laeufe. Testausgaben, Screenshots und Buildartefakte sind die
konkreten Pruefbelege; lokale Erfolge sind keine pauschale CI-Freigabe.

## Getrennte Releasebelege

Die finalen Test-/Browser-/Buildausgaben sowie Softwarepaket-, Privacy-/
Secret-, CI-, Image-, Pull- und Container-Smoke-Nachweise werden nach
tatsaechlicher Ausfuehrung als separate Releasebelege hinzugefuegt, auch
nach der Tag-Erstellung. Ihr Erfolg wird nicht aus lokalen Teilergebnissen
abgeleitet. Der Deploymentbeleg dokumentiert gesondert die Sicherung und
Rollbackmoeglichkeit vor dem Containerwechsel sowie Daten-/Konfigurationserhalt
und Runtime-Smoke-Test danach. Private Diagnose- und Finanzdaten bleiben
in privaten Belegen, nicht in oeffentlichen Release-Anhaengen.

Die Dokumentations-Allowlist enthaelt die neue Release-Datei zusaetzlich zu
den unveraenderten alten Releases. Alte Release-Dateien und Tags bleiben
unveraendert. Keine automatischen Anbieterabrufe oder Preisfreigaben durch
Versionswechsel.

Details: [Historische EUR-Preise](HISTORISCHE_EUR_PREISE.md).
