# Historische EUR-Preise

Stand: 28.10.2026, Bedienablauf fuer 0.2.0rc32 (Releasekandidat).
Keine steuerliche oder rechtliche Freigabe. Lokale Ergebnisse und gesonderte
Releasebelege sind in den rc32-Releasehinweisen getrennt ausgewiesen.

## Ohne KI Bedienen

Der komplette Ablauf liegt unter **Portfolio & Haltefristen -> EUR-Preise
ermitteln**. Es sind weder Chat, Terminal noch ein privates Auswertungsskript
erforderlich. Ein noch nicht importierter Zeitraum muss zuerst unter
Quellen & Wallets importiert werden. Keine Ereignisse bedeutet nicht
vollstaendig geprueft.

1. **Alle erkannten Token** und das gewuenschte Jahr oder **Alle Jahre** waehlen.
   Dieser Modus erfasst Asset, Gegenwaehrung und Gebuehren auch bei Transfers.
   **Steuerlich angeforderte Preise** bleibt ein getrennter engerer Modus.
2. **Preisbedarf planen** liest ausschliesslich die vorhandenen Daten. Die
   Jahresuebersicht trennt erkannte Token/Tage, vorhandene Preise, abrufbare
   Preise und offene Identitaets-/Belegfragen. Die Liste ist paginiert;
   der externe Abruf ist nicht auf die sichtbare Listenseite beschraenkt.
3. Anbieter, HTTP-Budget je Abschnitt und **Gesamtes HTTP-Budget** festlegen.
   Die UI schlaegt 200 Starts insgesamt vor; einstellbar sind 1 bis 1000.
   Pro Abschnitt bleiben hoechstens 50 tatsaechliche HTTP-Starts erlaubt.
   Alternative Suchversuche, Wiederholungen und FX zaehlen mit. Unter
   Einrichtung -> Abrufsteuerung gelten weiterhin alle gemeinsamen Limits.
   Sammelabfragen koennen mehrere Tagespreise liefern; Preisanzahl ist nicht
   HTTP-Anzahl. **Ausstehende Abschnitte automatisch fortsetzen** ist in der
   UI zunaechst aktiviert und kann vor der Zustimmung ausgeschaltet werden.
4. Externe Abfrage bestaetigen und **Kurse abrufen und Vorschau berechnen**
   starten. Beobachtungen sind noch keine bestaetigten Rewards oder Trades.
5. Bei aktivierter automatischer Fortsetzung umfasst die Zustimmung weitere
   ausstehende Abschnitte bis zum gebundenen Gesamtbudget. Ohne diese Option
   jeden weiteren Abschnitt bewusst bestaetigen. Bereits belegte Preise und
   EZB-Antworten bleiben in der kombinierten Vorschau erhalten. Fehlgeschlagene
   Zeilen nur ueber **Offene Abrufe erneut versuchen** bewusst wiederholen.
   Budgetende, fehlender Fortschritt oder Fehler stoppen die automatische
   Folge; keine Endlosschleife und keine automatische Preisuebernahme.
6. Gespeicherte Vorschau, offene Gruende und Berechnungsunterschiede pruefen.
   JSON, Markdown und **Jahresdateien und Originalbelege als ZIP** herunterladen.
   ZIP enthaelt saemtliche Ergebniszeilen, nicht nur die aktuelle Seite, sowie
   unveraenderte Anbieterantworten und Dateihashes.
7. Freigebende Person eintragen und Preise sowie Neuberechnung getrennt
   bestaetigen. Erst **Preise und Neuberechnung uebernehmen** schreibt die
   abgeleiteten Werte. Auch eine Teiluebernahme schliesst offene Zeilen nicht.

Der Browser merkt sich nur die Abruf-UUID in seinem Sitzungsspeicher, keine
Finanzdaten oder Secrets. Nach einem Verbindungsabbruch zuerst den gespeicherten
Status pruefen. Ein laufender Serverabruf darf nicht durch einen neuen Klick
dupliziert werden. Nach einem abgebrochenen Serverprozess ohne fertige Vorschau
einen neuen Plan ausdruecklich starten; Originalbelege bleiben erhalten, der
unterbrochene Request wird nicht blind automatisch wiederholt. Fertige
Abschnitte sind mit neuer, gebundener Vorschau fortsetzbar. Ein Neuladen
rekonstruiert keine Zustimmung zur automatischen Fortsetzung. Ein Wechsel
der Ansicht stoppt weitere automatische Abschnitte; den bereits laufenden
Serverabschnitt gegebenenfalls ueber seine Vorgangs-ID pruefen.

## Identitaet Und Fachliche Grenzen

- Bei Solana bleibt die originale, gross-/kleinschreibungssensitive Mint-Adresse
  erhalten. Gleiches Symbol mit unterschiedlichen Mints ist ein offener
  Konflikt, kein gemeinsames Preisobjekt. Keine Rekonstruktion aus Kurzadressen.
- Nicht identifizierte Token koennen ueber ihre exakte originale Mint-Adresse
  angefragt werden. Fehlende Herkunft, unpassende Zuordnung oder Spam-Review
  blockieren den automatischen Preisabruf. Der Preis ist keine Tokenfreigabe.
- Fuer eine eigene CoinGecko-Zuordnung kann die **Originale Solana-Mint-Adresse**
  separat eingetragen werden. Ihre Gross-/Kleinschreibung bleibt gespeichert;
  sie muss zur Mint im Originalimport passen. Ein als Asset eingegebener
  exakter Mint bleibt ebenfalls separat erhalten. Alte rein grossgeschriebene
  Aliase werden nicht als rekonstruierter Identitaetsnachweis verwendet.
- Bei Legacy-Zuordnungen wird eine fehlende originale Schreibweise beim
  Lesen nicht aus dem grossgeschriebenen Asset-Alias abgeleitet. Eine bereits
  explizite Original-Mint oder die erhaltene case-sensitive Adresse einer
  exakten `solana:`-Provider-ID bleibt nutzbar. Fehlt dieser Nachweis, bleibt
  die Identitaet offen; keine Aenderung der Originalimporte.
- Nur nachgewiesen natives SOL beziehungsweise native SOL-Gebuehren koennen
  die native Referenz `coingecko:solana` als Alternative zum geplanten
  WSOL-Pfad verwenden. Keine globale WSOL-Paritaet, keine Uebertragung auf
  andere SPL-Mints oder Liquid-Staking-Token. Geplante und tatsaechlich
  erfolgreiche Anbieter-ID sowie Suchversuche bleiben unterscheidbar.
- Bestehende Preise werden nur als Tagesabdeckung gezeigt, wenn sie am selben
  UTC-Tag und nicht nach dem ersten beobachteten Ereignis liegen. Ein Kurs aus
  einem frueheren Jahr schliesst diese Beobachtungsabdeckung nicht.
- Preisvorschau und Uebernahme normalisieren keine Rohimporte und spielen
  keine Ereigniskorrekturen neu ein. Rohdaten, Canonical Events, bestehende
  Entscheidungen und Overrides muessen vor/nach der Preisberechnung exakt
  uebereinstimmen; sonst ist die Uebernahme gesperrt.
- Ein global gespeicherter Preis kann auch andere Bewertungen, Anschaffungs-
  kosten, Flows und Tax-Lines beeinflussen. Deshalb zeigt die Vorschau
  Vorher/Nachher, Lot-/Flow-Abdeckung und Tax-Line-Deltas. Unveraenderte
  Klassifikation bedeutet nicht unveraenderte EUR-Steuerbetraege.
- Jahreszuordnung verwendet die vorhandene Europe/Berlin- und
  Helium-Quellperiodenregel. UTC-Preistag und Steuerjahr sind getrennt.

## Bedienung

1. Historie zuerst abrufen, Vorschau pruefen und den Transaktionsimport selbst
   freigeben. Noch nicht importierte Historienvorschauen sind kein produktiver
   Preisbedarf. Ein leerer Preisplan beweist keine vollstaendige Historie.
2. Portfolio & Haltefristen -> EUR-Preise ermitteln oeffnen. Direktlink:
   `#portfolio?tab=prices&year=2025`. Jahr und Asset sind wiederherstellbarer
   URL-Ansichtsstatus; keine Secrets oder persoenlichen Notizen eingeben.
3. Anbieter, Abschnitts- und Gesamtbudget waehlen, Preisbedarf planen. Planung ist lokal,
   ohne externe Requests, Preisimport oder Neuberechnung. Das Jahr entspricht
   dem vorhandenen Steuerjahreskontext Europe/Berlin; Preis-/FX-Tage sind UTC.
4. Offene Zuordnungen pruefen. Unter Preisquellen zuordnen eine vorhandene
   Zuordnung laden oder eine eigene speichern. CoinGecko-ID bzw. exakte
   DefiLlama-ID verwenden, bei Solana `solana:<Mint>`. Ein gleiches Symbol
   beweist keine Tokenidentitaet. Zuordnungen liegen privat in DuckDB, nicht
   im Repository. Speichern aktiviert keine steuerliche Quelle.
5. Den externen Abruf ausdruecklich bestaetigen. Anbieterlimits und moegliche
   Tarifkosten beachten. CoinGecko-Historie kann Zugang/Tarif erfordern;
   ein Fehler oder fehlender Kurs bleibt offen, kein automatischer Tarifwechsel.
6. Kurse abrufen und Vorschau berechnen. Originalantworten und SHA256 werden
   privat gespeichert; die Pipeline rechnet nur in einer Datenbankkopie.
   In der Vorschau EUR je Token, Preiszeit, FX-Tag, offene Anforderungen,
   Review-Hinweise, Vorher/Nachher und vollstaendige Tax-Line-Deltas pruefen.
7. Originalantworten und Vorschau-JSON herunterladen. EUR-Preise und
   Neuberechnung getrennt bestaetigen und eine freigebende Person angeben.
   Erst dann erfolgt eine atomare Uebernahme mit dokumentarischer Auditspur.
   Keine Quellen-, Token-, Review- oder Jahresfreigabe wird daraus abgeleitet.
8. Die UI nutzt die automatische Strategie fuer beide Preisumfaenge.
   Ausstehende Abschnitte innerhalb der bestaetigten Suche fortsetzen;
   fruehe fehlgeschlagene Zeilen nicht immer wieder vor spaetere Bedarfe
   setzen. Der API-Standard bleibt `strategy=standard`, zehn und maximal
   50 HTTP-Starts je Abschnitt. `max_total_requests` ist im API-Standard
   nicht gesetzt; die UI bindet dagegen das gewaehlte Gesamtbudget an den
   Auftrag. Alte Vorschauen ohne Gesamtbudget werden nicht automatisch
   fortgesetzt. Ein erreichtes Gesamtbudget wird beim Fortsetzen nicht
   zurueckgesetzt; ein weiterer Suchlauf erfordert eine neue bewusste Planung.
9. Heutige Portfolio-Marktpreise separat planen/abrufen. Dieser bestehende
   Abruf kann Preise speichern und die Pipeline neu berechnen; vorherige
   Bestaetigung beachten. Er ersetzt keine fehlenden historischen Bewertungen.

Die globalen und anbieterspezifischen Limits werden unter Einrichtung ->
Abrufsteuerung eingestellt. Die Einrichtung verlinkt auch die Preiszuordnung.
Keine automatischen Anbieterabfragen beim Oeffnen oder Filtern.

## Bewertungsbasis Und Grenzen

- CoinGecko `/coins/{id}/history`: EUR-Wert direkt aus der historischen
  Antwort, nach Anbieterdefinition Referenz um 00:00 UTC. Kein Intraday-
  Ausfuehrungskurs. Anbieter-ID muss zur Antwort passen.
- DefiLlama: vorhandene exakte Token-/CoinGecko-Zuordnung, urspruengliches
  Ziel 30 Minuten vor dem ersten Tagesereignis, fruehestens UTC-Mitternacht.
  Die Antwort muss am selben UTC-Tag liegen, darf nicht nach diesem Ereignis
  liegen und hoechstens eine Stunde vom **urspruenglichen Ziel** abweichen.
  Die automatische Suche ergaenzt bei fehlendem oder zeitlich unpassendem
  Quote nahe Abfragen: minus 30, plus 15 und plus 30 Minuten relativ zum
  urspruenglichen Ziel, auf Tagesbeginn beziehungsweise vor das erste
  Ereignis begrenzt und dedupliziert. Die Alternativen erweitern das
  Zulaessigkeitsfenster nicht. Derselbe Selektor prueft auch native SOL-
  Referenzen. Konfliktbelege werden nicht durch Aliaswechsel uebergangen.
  Der tatsaechliche Quote-Zeitpunkt bleibt gespeichert; kein spaeterer
  Kurs wird zurueckdatiert. Eine Chartserie ist kein hier zugesagter
  implementierter Fallback, und Tagesreferenzen sind keine Ausfuehrungskurse.
- USD/EUR: Frankfurter v2 mit ausdruecklichem EZB-Provider, nicht der gemischte
  Standardfeed. Letzter vorhandener Geschaeftstag am oder vor dem angefragten
  Tag, hoechstens sieben Kalendertage zurueck. Kursdatum bleibt sichtbar.
  Dies ist eine Tagesreferenz, kein nachgewiesener Intraday-FX-Ausfuehrungskurs.
- Decimal-Verarbeitung; kein Float fuer Bewertung oder Umrechnung. Speichern
  nutzt die vorhandene DECIMAL(38,18)-Praezision, nicht die Anzeigerundung.
- Spaetere/heutige Ersatzpreise, negative/NaN-/Infinity-Werte, fremde IDs,
  unpassende Zeitpunkte und fehlende FX-Daten bleiben offene Nachweise.
- USDC/USDT werden nicht pauschal als 1 USD oder 1 EUR behandelt.
- Keine automatische Spamannahme oder steuerliche Kategorisierung. Ein
  bestehender Spam-Review blockiert diesen Preisabruf weiterhin.
- Bestehende historische Regeln, z.B. Qualitaetsgates oder bisherige
  Altpreisverwendung ausserhalb Solana, werden nicht still umgeschrieben.
  Eine abgearbeitete Preisliste beweist weder korrekte Tokenidentitaet noch
  vollstaendige Wallet-Historie oder eine richtige Steuererklaerung.

## Synthetische Pruefung Und Releasegrenzen

Fuer den begrenzten Native-SOL-Fallback besteht eine synthetische 20-Tage-
Regression. Ein solcher Test ersetzt weder die Pruefung eigener Originalbelege
noch einen Vollstaendigkeitsnachweis fuer alle Token oder Jahre.

Tagespreisbedarfe und fachliche Hinweise sind unterschiedliche Einheiten.
Ein gefundener Preis schliesst keine Klassifizierungsfrage oder automatische
fachliche Freigabe ein. Reale Installationszahlen und private Einzelproben
bleiben in privaten Diagnose-/Releasebelegen, ausserhalb des Repositorys.
Gemeldete lokale Regressionen und Browserergebnisse sind getrennt von den
finalen Test-/Build-, CI-, Image- und Deploymentbelegen dokumentiert; siehe
[rc32-Nachweise und Grenzen](RELEASE_0.2.0rc32.md).

## Integritaet Und Wiederholung

Abruf-UUID plus identischer Request ist idempotent. Maximal ein Preisabruf pro
lokaler Datenbank gleichzeitig; Limiter koordiniert zusaetzlich gemeinsame
Budgets. Nach Verbindungsabbruch zuerst gespeicherte Preisvorschauen ansehen,
keine unkontrollierten Doppelstarts. Unterbrochene Requests ohne fertige
Vorschau werden nicht automatisch wiederholt; ausdruecklich neu planen.

Private Dateien: neben der DuckDB unter `historical_prices/`. Originalantworten
sind hashadressiert und Vorschauen unveraenderlich angelegt. Ein Datenbank-,
Methoden-, Konfigurations- oder Belegwechsel sperrt die veraltete Uebernahme.
Dateirechte und SHA256 sind kein WORM-Speicher oder qualifizierter Zeitstempel;
der Betreiber muss Backups, Zugriffsschutz und Aufbewahrung sicherstellen.

Die `evidence_sha256`-Verweise einer Zeile identifizieren Antwortbytes, nicht
einen einzelnen Request. Bei identischem Body koennen mehrere Eintraege in
`evidence` denselben Hash haben, obwohl Provider, URL, Parameter, HTTP-Status
oder Abrufzeit abweichen. Aus dem Zeilen-Hash allein laesst sich dann nicht
eindeutig bestimmen, welcher Metadatensatz zu diesem Versuch gehoert; auch
der aus Hashes gebildete Quellenbezug schafft keine Request-Identitaet. Die
gespeicherte Vorschau enthaelt die Request-Metadaten, loest diese Mehrdeutigkeit
aber nicht in allen Faellen auf. Dies ist eine bestehende Vertragsgrenze, keine
neue Identitaets- oder Schemaaenderung.

Nach Softwarewechsel: Quellen -> Transaktionen abrufen -> Vorschau erneut
berechnen. Gespeicherte Originale werden geprueft, die alte Vorschau wird
hashgebunden archiviert; keine neuen Exchange-/RPC-Anfragen. Bestehende
Quellen-/Credentialbindungen werden weiterhin geprueft. Importfreigabe bleibt
eine eigene menschliche Aktion. Archivierte Abgabesnapshots bleiben erhalten.

## API

### Manueller Einzelbeleg

Der additive Endpunkt `POST /api/v1/prices/historical/manual-previews` startet
bei genau einer offenen Planzeile. Der Request bindet Asset/Identitaet,
UTC-Preistag, Planhash, Wert, Einheit, Belegquelle und den SHA-256 des
unveraenderten Originaldokuments. PDF, CSV, Bild- oder Textbelege werden als
Originalbytes in den privaten SHA-adressierten Belegspeicher uebernommen; die
Vorschau enthaelt Dateiname, Medientyp, Dateigroesse (je Datei maximal 2 MiB),
Erfassungszeitpunkt mit eingereichtem Zeitzonen-Offset und UTC-Normalisierung,
Fundstelle und Hash. Die Erfassungszeit ist eine manuell angegebene
Metainformation und kein bestaetigter Zeitstempel des Anbieters.

- EUR wird ausschliesslich direkt als positiver EUR-Wert je Asset eingegeben.
  Der bestehende EUR-CSV-Import und dessen Vertrag bleiben unveraendert.
- USD benoetigt im selben Request einen separaten FX-Originalbeleg und eine
  explizite FX-Beobachtung mit Referenztag, Quellwaehrung, Zielwaehrung, Rate
  und Quelle. Es werden nur USD/EUR und EUR/USD akzeptiert. Die bestehende
  `fx_reference_on_or_before_max_7_calendar_days_v1`-Policy waehlt den
  juengsten belegten Kurs am oder vor dem Preisdatum, maximal sieben
  Kalendertage zurueck; inverse Kurse werden mit Decimal umgerechnet.
- Es gibt keinen Defaultkurs und keinen EUR/USD-Paritaets-Fallback. Fehlende,
  ausschliesslich zukuenftige, veraltete oder widerspruechliche FX-Belege,
  mehrdeutige Tokenidentitaet, spaeter geaenderte Daten und geaenderte
  SHA-Dateien bleiben blockiert. Ein korrigierter Nachweis braucht eine neue
  Vorschau mit neu gebundenem Belegsatz.
- Eine manuelle Vorschau speichert private Beleg-/Vorschauartefakte und rechnet
  nur in der isolierten Datenbankkopie. Sie startet keinen Provider-, FX-,
  Exchange- oder KI-Aufruf und schreibt keine produktiven Preise oder
  abgeleiteten Finanzdaten.
- Die Uebernahme verwendet den vorhandenen Apply-Endpunkt. Akteur,
  Preisbestaetigung, Neuberechnungsbestaetigung sowie aktueller Vorschauhash
  sind erforderlich. Vor Apply prueft der Dienst erneut Datenrevision,
  Vorschau, Originalhashes und vorbereitete Berechnung; Apply ruft keine
  externen Anbieter auf. Identischer Antrag ist idempotent; abweichender Wert
  bei identischem Preis- und FX-Belegsatz ist ein Konflikt.
- JSON und Markdown weisen Quelle, Rohwert, Waehrung/Einheit, Preiszeit,
  Erfassungszeit, angewandte FX-Policy und Originalhashes aus. ZIP enthaelt die
  unveraenderten Originalbytes samt Manifest. Die Belegdownload-Route liefert
  manuelle Originale als Binaerdatei; Anbieterantworten behalten ihr bisheriges
  JSON-Verhalten.

- `POST /api/v1/prices/historical/manual-previews`: isolierte manuelle
  EUR- oder USD/FX-Vorschau fuer genau einen offenen Bedarf; keine externe
  Anfrage oder produktive Finanzdatenbank-Aenderung.

- `POST /api/v1/prices/historical/plan`: rein lokaler Bedarf mit Plan-SHA256.
- Additive Queryfelder: `scope=tax_required|all_observed`, `page` und
  `page_size` (1 bis 100). API-Default bleibt `tax_required`, UI-Default ist
  `all_observed`. Planhash und Abrufumfang sind unabhaengig von Listenseite.
- Ab rc32: `strategy=standard|automatic` (API-Default `standard`) und
  `max_total_requests` (optional, 1 bis 1000). Die UI verwendet `automatic`
  mit Gesamtbudget 200 als Voreinstellung. `max_requests` bleibt das
  Abschnittsbudget mit API-Default 10 und Maximum 50. Bei gebundenem
  Gesamtbudget verwendet jeder Folgeabschnitt nur dessen Rest; fehlende
  Budgetbindung erlaubt keine automatische UI-Fortsetzung.
- `GET/PUT /api/v1/prices/historical/mappings`: lesen / privat speichern.
- `POST /api/v1/prices/historical/previews`: bestaetigter Abruf mit
  Request-UUID und Planhash; speichert private Belege und isolierte Vorschau.
- `GET /api/v1/prices/historical/previews`: letzte 20 fertige Vorschauen.
- `GET /api/v1/prices/historical/previews/{id}`: pruefbare Vorschau.
- `GET /api/v1/prices/historical/previews/{id}/status`: rein lesender
  Abrufstatus und zuletzt gespeicherter Fortschritt; keine neue Anbieterabfrage.
- `POST /api/v1/prices/historical/previews/{id}/continue`: neue Request-UUID,
  gebundener Vorschauhash und externe Bestaetigung; die UI kann diese im
  bestaetigten automatischen Lauf innerhalb des Gesamtbudgets senden. Optional
  `retry_open=true` fuer bewusst erneut gepruefte fehlgeschlagene Zeilen.
  Vorhandene Preise werden in die neue kumulative Vorschau uebernommen,
  nicht in die produktive Finanzdatenbank.
- `GET /api/v1/prices/historical/previews/{id}/report.json`, `/report.md`,
  `/report.zip`: lesende vollstaendige Jahresauswertung mit Belegbindung.
- `GET /api/v1/prices/historical/previews/{id}/evidence/{sha}`: gebundene
  Originalantwort, keine beliebige Datei.
- `POST /api/v1/prices/historical/previews/{id}/apply`: zwei Bestaetigungen,
  Akteur und Vorschauhash; atomare Uebernahme und Auditspur, kein erneuter Abruf.
- `POST /api/v1/workspace/sources/{ref}/history/jobs/{id}/repreview`:
  ausdruecklich lokale Neuberechnung fertiger Historienbelege ohne Import.

Der bisherige `/prices/backfill/external`-Pfad bleibt als Legacy-Schnittstelle
erhalten, einschliesslich seiner expliziten V1-FX-Eingabe. Die neue gefuehrte
Oberflaeche verwendet ihn nicht. CSV-Preisbelege bleiben im Expertenmodus
verfuegbar: `asset,price_eur,priced_at,source`, Zeitpunkt mit Zeitzone.

## Anbieterquellen

Geprueft am 27.10.2026; kein Nachweis des individuellen Kontotarifs:

- [CoinGecko-Historie](https://docs.coingecko.com/reference/coins-id-history)
- [Frankfurter v2 und EZB-Provider](https://frankfurter.dev/)
- [DefiLlama-Preisendpunkte](https://api-docs.defillama.com/llms-free.txt)

Tests verwenden ausschliesslich isolierte Datenbanken, kontrollierte Uhren
und HTTP-Mocks. Browsernachweis: `scripts/check_historical_prices_browser_v2.py`.
