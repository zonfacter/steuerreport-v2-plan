# API Contracts V2

## Quellengebundener Historienjob mit Vorschau

`/api/v1/workspace/sources/{ref}/history` ist der neue, gefuehrte Importpfad.
`ref` bindet genau eine gespeicherte Solana-Adresse oder CEX-Verbindung;
`connection_id` im lesenden Quellvertrag bezeichnet die einzelne Verbindung.
Es gibt keinen Clientparameter zum Ueberschreiben der Wallet oder des Kontos.

- GET Basis, `/jobs/{id}` und `/jobs/{id}/audit.json` lesen ausschliesslich.
- POST `/jobs` verlangt UUID-`request_id`, ausdrueckliches Boolean
  `confirm_external_request=true`, UTC-Datumsfenster und optional Symbole,
  `public_rpc_only`, `max_records`. Wiederholung derselben ID/Parameter
  liefert denselben Job; veraenderte Parameter fuer dieselbe ID ergeben 409.
- POST `/pause`, `/cancel` am Job speichert die Steuerungsabsicht; POST
  `/resume` verlangt erneute externe Bestaetigung und optional ein neues Limit.
- POST `/import` verlangt `preview_sha256`, benannte `actor`-Person sowie
  exakt `confirm_import=true` und `confirm_recalculation=true`. Geaenderte
  Quellen-, Daten-, Software- oder Methodenbindung sperrt die Uebernahme.

Status: `queued`, `running`, `paused`, `ready`, `succeeded`, `failed`,
`cancelled`; `importing` ist fuer Clients mitmodelliert. `ready` bedeutet
Vorschau, keinen Finanzimport. Erst Importfreigabe uebernimmt Rohobjekte,
kanonische Ereignisse und bestehende Ableitungen in einer Transaktion.
`can_resume` unterscheidet unterbrochene von nicht sicher fortsetzbaren Jobs.
`sample_rows` eines bereiten Jobs enthaelt ab rc23 bis zu zehn neue normalisierte
Ereignisse aus derselben vorbereiteten Datenbank, einschliesslich UTC-Zeit,
Asset/Menge, Gegenmenge und Gebuehren. Die Stichprobe ist hashgebunden; Rohspalten
werden nicht als kanonische Felder ausgegeben. Bei reinen Dubletten ist sie leer.
`requests` zaehlt Anfragen erfolgreich gespeicherter Seiten, keine garantierte
Gesamtzahl aller fehlgeschlagenen Versuche oder Anbieter-Credits.

Private Rohbelege sind SHA-256-adressiert; Konflikte werden nicht ueberschrieben.
Keine Secretwerte oder internen Dateipfade in Antworten. Audit enthaelt bewusst
die private Konten-/oeffentliche Walletreferenz und UTC-Anfragegrenzen.
Vollstaendigkeit bleibt unbestaetigt; Konto-/Quellen-/Jahresfreigaben bleiben
getrennt. Ausfuehrliche Wirkungen und Limits:
[Automatischer Quellenimport](AUTOMATISCHER_QUELLENIMPORT.md).

## Direkter Solana-Historienimport: Idempotenz und Grenzen

`POST /api/v1/portfolio/jup-wallet/import-history` bleibt eine ausdruecklich
schreibende Aktion mit externen RPC-Aufrufen. Neue Zeilen werden importiert und
die bestehende Pipeline wird neu berechnet. Quellen-Synchronisieren bleibt davon
getrennt: es liest Bestaende, nicht diese Historie. Der neue gefuehrte UI-Ablauf
verwendet den oben beschriebenen Jobvertrag statt dieses direkten Legacy-Aufrufs.

- Eindeutigkeit: Quelle `solana_rpc`, exakte Wallet und Transaktionssignatur.
  Die gesamte Transaktion wird mit ihren gespeicherten Rohzeilen verglichen;
  eine groessere/ueberlappende Seite erhoeht alte Bestaende nicht erneut.
- Reine Wiederholung: `duplicate_batch=true`, `normalized_events=0`,
  `pipeline={"skipped":true,"reason":"no_new_transactions"}`. `batch_id` verweist
  auf einen bestehenden Belegbatch, nicht auf einen neuen Batch fuer die Seite.
  `fetched_rows` beschreibt weiterhin gelesene Zeilen, nicht neue Transaktionen.
- Teilueberlappung: nur neue Transaktionen gehen in den neuen Batch ein;
  `warnings` enthaelt `solana_history_duplicate_transactions` mit Anzahl.
- HTTP 409: abweichende vorhandene Rohzeilen, alter/unvollstaendiger Import ohne
  erfolgreich abgeschlossene Berechnung oder laufender paralleler Import.
  Kein automatisches Ersetzen alter Belege. HTTP 422 bei fehlender Wallet.
- HTTP 502: eine Transaktion fehlt, ist nicht eindeutig auswertbar oder konnte
  nicht gelesen werden. Kein erfolgreicher Teilimport und kein neuer Cursor.
  Erneut mit demselben Eingabecursor versuchen. Dies ist noch kein persistenter Job.

Mapper-Version `2` speichert pro erzeugter Zeile die urspruengliche RPC-Antwort
als deterministisches JSON `raw_transaction`, Wallet, Signatur und bei Tokenzeilen
den unveraenderten Mint. Netzwerkgebuehren stehen als `network_fee` neben den
gebuehrenbereinigten SOL-Bewegungen. Nur Account 0 zahlt die Transaktionsgebuehr;
fehlgeschlagene Transaktionen tragen hoechstens dessen Gebuehr bei. Fehlende
Zeit-/Bestands-/Eigentumsdaten werden nicht durch Annahmen ergaenzt.

Bekannte Mints werden ausschliesslich ueber exakte `solana:`-IDs in der bestehenden
Assetkonfiguration zugeordnet. Unbekannte Mints erhalten `SOLANA_` plus SHA256 des
exakten Mintstrings; Gross-/Kleinschreibung bleibt dadurch identitaetswirksam.
Originalmint und Originalmenge bleiben im Beleg erhalten. Keine automatische
Preisannahme oder Assetfreigabe fuer unbekannte Token.

Nettoveraenderungen allein beweisen weder Swap noch Reward. Solche Bewegungen
bleiben zunaechst Transfers mit dem blockierenden Hinweis
`solana_history_classification_required`. Dieser Patch fuehrt keinen neuen
Freigabeautomatismus ein. Fachliche Klassifizierung, Belegpruefung und bestehende
Korrekturablaeufe bleiben erforderlich; eine dokumentarische Markierung ersetzt
keine fachliche Klaerung. Alte CSV-/Referenznormalisierungen bleiben unveraendert.

Die Importsperre liegt neben der Datenbank (`.solana-history.lock`), enthaelt
keine Zugangsdaten und gilt ueber Store-Instanzen und Prozesse hinweg. Linux/
POSIX-Dateisperren sind erforderlich; ohne Sperre wird nicht ungeschuetzt importiert.
Sie ersetzt keinen allgemeinen Mehrprozess-Schreibbetrieb fuer DuckDB. Ein nach
Pipelinefehler als `loaded` verbliebener Batch wird nicht als Erfolg bestaetigt.
Es erfolgt keine automatische Datenbereinigung oder steuerliche Rueckkorrektur.

## Gespeicherter Wallet-Bestand ohne Historie

`GET /api/v1/workspace/sources` liefert bei explizit zugeordneten Profilwallets
optional `live_assets_count`, `live_unpriced_assets_count`, `live_value_eur` und
`live_balance_status`. Ein fehlender EUR-Wert ist `null`, nicht 0 oder eine
unvollstaendige Teilsumme. Fehlender Abruf hat keine Live-Zusammenfassung.

`GET /api/v1/workspace/sources/{ref}` ergaenzt `live_balance` mit `fetched_at`,
`status` (`available` oder `confirmed_empty`), `assets`, `unpriced_assets_count`,
`value_eur` und `sources`. Asset-Zeilen enthalten Menge, optionalen EUR-Preis/-Wert,
Preisquelle, Kurszeitpunkt und Preisstatus. Mengen und Werte bleiben Decimal-Strings.
`confirmed_empty` ist eine erfolgreiche ausdrueckliche Leerbestaetigung; bei
Fehlern wird der letzte erfolgreiche Snapshot mit separatem `last_attempt` gelesen.

Dieser rein lesende Vertrag uebernimmt keine Tokenmengen in Canonical Events,
Ledger oder Tax Lines. Bestehende `valuation` bleibt getrennt erreichbar. Andere
Beobachtungsadressen erben keine profilgebundenen Connector-Snapshots. Kein RPC-,
Kursanbieter-, Historienimport- oder Neuberechnungsaufruf beim Oeffnen.

## Vollstaendige Endpoint-Referenz

Dieses Dokument beschreibt wichtige API-Contracts fachlich. Die vollstaendige
aus dem Code generierte Endpoint-Liste steht hier:

- `docs/626_API_ENDPOINT_REFERENZ_VOLLSTAENDIG_2026-07-05.md`
- `docs/openapi/steuerreport-v2-openapi.json` fuer Request-/Response-Schemas,
  Parameter, Tags und SDK-Generierung.
- `docs/007_MOBILE_APP_API_INTEGRATION_2026-08-26.md` fuer Android-/iOS-
  Transport, Sicherheit, Caching und Fehlerbehandlung.

Zur Laufzeit stehen dieselben Vertraege unter `/docs`, `/redoc` und
`/openapi.json`. `GET /api/v1/meta/capabilities` liefert die von Mobile-Clients
zuerst zu pruefenden Transport- und Sicherheitsmerkmale.

## Allgemein

Alle Endpunkte antworten im Standardformat:

```json
{
  "trace_id": "uuid",
  "status": "ok",
  "data": {},
  "errors": [],
  "warnings": []
}
```

Ausnahmen sind explizite Datei-/HTML-Downloads. Clients muessen deshalb den
HTTP-Header `Content-Type` auswerten und duerfen Downloads nicht als
`ApiResponse` dekodieren.

Verbindliche Transportregeln:

- Decimal-Felder werden verlustfrei als JSON-Strings uebertragen. Mobile-
  Clients duerfen sie nicht zuerst in binaere `Double`-/`Float`-Werte parsen.
- Zeitstempel sind ISO-8601 in UTC. Steuerliche Tagesgrenzen werden
  serverseitig mit `Europe/Berlin` bestimmt.
- EUR-Anzeige erfolgt im Client mit zwei Nachkommastellen; Berechnungen bleiben
  auf dem Server in voller Decimal-Genauigkeit.
- Der HTTP-Status und zusaetzlich `status`, `errors` und `warnings` im Envelope
  sind auszuwerten. Ein fachlicher Fehler kann bewusst in einem gueltigen
  HTTP-Response stehen.
- `trace_id` gehoert in Client-Logs und Supportmeldungen, aber nicht in
  fachliche Berechnungen.

## Sicherheitsgrenze

Die V2-API besitzt aktuell keine allgemeine Benutzeranmeldung und verwendet
offenes CORS fuer das lokale Web-Frontend. Mobile Connector-Schreibzugriffe
verwenden gescopte, widerrufbare Sitzungen; deren einmalige Kopplung und
Administration bleibt mit einem separaten lokalen Setup-Bearer geschuetzt. Die
API ist deshalb weiterhin nur im vertrauenswuerdigen LAN oder VPN sicher. Vor
Internetzugriff oder App-Store-Verteilung sind mindestens TLS,
Authentifizierung/Autorisierung, restriktives CORS, Rate-Limits und getrennte
Benutzer-/Datenbereiche vorzuschalten. Schreibende Admin-, Import-, Decision-,
Refresh- und Rebuild-Endpunkte sind bis dahin keine oeffentliche Mobile-
Oberflaeche.

## Connector-Katalog und Wallet-Eigentum

### `POST /api/v1/workspace/wallets`

Lokale Adresskonfiguration mit `wallet_address` und optional `display_label`.
Ohne Setup-Bearer oder Signatur; bestehender Host-/Origin-Schutz bleibt wirksam,
synthetische schreibgeschuetzte Vorschauen verweigern die Aktion. Keine allgemeine
Internet-Authentifizierung. Antwort: `connection`, `created`, `message`.
Der neue unbestaetigte Zustand heisst `address_saved`, `verified_at` und `source_id`
bleiben leer, `tax_activation` bleibt `review_required`. Kein Provider-Aufruf,
Import, Eigentumsnachweis oder Steuerlauf. Doppeleingaben erhalten denselben
Eintrag und bestehenden Pruefstatus, widerrufene Verbindungen werden nicht reaktiviert.
Quellen-Readmodelle enthalten optional `wallet_address`; dies gehoert nicht in URLs.

`GET /api/v1/connectors/catalog`

Liefert den serverseitigen Connector-Katalog fuer Wallets, CEX, Datenanbieter,
Bank-/Zahlungsabgleich und Dokumente. Die Antwort nennt Auth-Modell,
Verfuegbarkeit, Faehigkeiten, letzten Abruf, Secret-Vault-Status und bekannte
Verbindungen, aber niemals API-Keys oder Setup-Token.

`GET /api/v1/connectors/connections`

Liefert gespeicherte oeffentliche und signierte Wallet-Verbindungen einschliesslich vollstaendiger Adresse
fuer den Drilldown. Clients muessen Wallets in Listen kuerzen und die
vollstaendige Adresse nur im Detail anzeigen.

`POST /api/v1/connectors/mobile/pairings`

Erzeugt nach Autorisierung mit dem lokalen Setup-Bearer einen einmaligen,
zehn Minuten gueltigen Kopplungscode. Der Code wird nur in dieser Antwort
ausgegeben und serverseitig ausschliesslich als SHA-256-Hash gespeichert.

`POST /api/v1/connectors/mobile/sessions`

Tauscht Kopplungs-ID und Einmalcode genau einmal gegen einen zufaelligen
Mobile-Bearer. Der Bearer wird nur einmal ausgegeben; gespeichert werden nur
Hash, Geraet, Plattform, Scopes, Ablauf- und Auditzeitpunkte.

`GET /api/v1/connectors/mobile/session`

Prueft die aktuelle Mobile-Sitzung und liefert Scopes, Ablauf und letzten
Zugriff. `GET /api/v1/connectors/mobile/sessions` und
`DELETE /api/v1/connectors/mobile/sessions/{session_id}` sind ausschliesslich
mit dem lokalen Setup-Bearer fuer Inventar und Widerruf zugaenglich.
Das OpenAPI-Schema beschreibt diese Grenzen mit den Security-Schemes
`ConnectorSetupBearer` und `MobileConnectorBearer`; beim Wallet-Nachweis sind
beide als alternative Autorisierung dokumentiert.

`POST /api/v1/connectors/mobile/documents`

Nimmt genau eine PDF-, JPEG- oder PNG-Datei als `multipart/form-data` an. Der
Aufruf verlangt den lokalen Setup-Bearer oder eine aktive Mobile-Sitzung mit
Scope `document:upload`. Zulaessige Formfelder sind `document_kind`,
`source_hint`, `note` und `captured_at`. Maximalgroesse: 25 MiB. Dateiendung,
gemeldeter Medientyp und Magic Bytes werden gegengeprueft. Der Inhalt wird
unter seinem SHA-256 content-addressed abgelegt; ein identischer erneuter
Upload erhoeht nur den Uploadzaehler und erzeugt kein zweites Dokument.

`GET /api/v1/connectors/mobile/documents`

Liefert die private Review-Inbox mit Metadaten und Hashbindungen. Die Route ist
ausschliesslich mit dem lokalen Setup-Bearer erreichbar. Der ungeschuetzte
Connector-Katalog enthaelt nur aggregierte Zaehler, niemals Dateinamen, Hashes,
Notizen oder Inhalte.

`GET /api/v1/connectors/mobile/documents/{document_id}/content`

Liefert das zuvor erneut SHA-256-gepruefte Original ausschliesslich mit dem
lokalen Setup-Bearer. Upload-, Inventar- und Downloadantworten verwenden
`Cache-Control: no-store` und `X-Content-Type-Options: nosniff`; der Download
liefert zusaetzlich den Inhalts-Hash im Header.

Jeder neue Upload bleibt `pending_review` und hat
`tax_effect=none_pending_review`. Die Inbox schreibt keine Canonical Events,
Ledgerzeilen, FIFO-Lots, Steuerzeilen oder fachlichen Review-Freigaben. OCR und
Weiterleitung an Erbnachweis-, Bank-, Exchange- oder Kaufbelegpfade sind
separate, spaetere Review-Aktionen. Ein ungepruefter Inbox-Beleg blockiert das
bestehende Export-Gate daher nicht automatisch.

`POST /api/v1/connectors/wallet/challenges`

Erzeugt eine einmalige, fuenf Minuten gueltige Solana-`signMessage`-Challenge.
Die Route akzeptiert den lokalen Setup-Bearer oder eine aktive Mobile-Sitzung
mit Scope `wallet:verify`.

`POST /api/v1/connectors/wallet/verifications`

Prueft eine Base58-kodierte Ed25519-Signatur. Eine neue Wallet erhaelt nur
`ownership_verified_pending_registry` und `review_required`. Erst ein bereits
vorhandener expliziter Eintrag in `configs/source_registry.json` fuehrt zu
`registered` und `registry_active`. Die Challenge-Pipeline schreibt keine
Canonical Events, Ledgerzeilen, FIFO-Lots oder Steuerwerte.

## Health

`GET /api/v1/health`

Rueckgabe:

- App-Version
- Datenbanktyp `duckdb`
- Datenbankstatus
- Schema-Version

## Import

`POST /api/v1/import/batches`

Erzeugt einen Import-Batch fuer Browser-Dateiuploads oder API-Importe.

`GET /api/v1/import/batches/{batch_id}`

Liefert Status, erkannte Quelle, Dateihash, Rohobjekt-Anzahl und Warnungen.

`POST /api/v1/import/batches/{batch_id}/normalize`

Startet Normalisierung zu Canonical Events.

`POST /api/v1/import/batches/{batch_id}/run`

Fuehrt nach einem Raw-Import den kompletten Importlauf aus: Normalisierung,
Balance-Ledger, Flow-Ledger, FIFO-Steuerlauf und Review-Gates. Die Antwort
enthaelt importierte Rohzeilen, erzeugte Canonical Events, uebersprungene
Rohzeilen und den Pipeline-Status. Uebersprungene Rohzeilen erzeugen
`status=warning`.

`DELETE /api/v1/import/batches/{batch_id}`

Entfernt einen Import-Batch mit Raw Objects und Canonical Events und baut die
Pipeline danach neu auf. So koennen falsche Imports rueckstandsfrei entfernt
werden. Wenn der Batch nicht existiert, kommt `status=warning`.

`GET /api/v1/import/profiles`

Listet deterministische Importprofile fuer `manual-csv`, `pionex`, `binance`
und `helium`. Die Profile enthalten Spaltenalias-Gruppen fuer Zeit, Asset,
Menge, Typ und Handelspaar. Bei Paaren wie `MXC_USDT` wird das Base-Asset als
Asset und das Quote-Asset als Gegenwaehrung abgeleitet; `SELL`-Trades werden
als negative Asset-Menge normalisiert. Diese Regeln sind Teil des
nachvollziehbaren Import-Audits und werden nicht durch KI geschaetzt.
`bitget` ist ebenfalls ein Profil fuer die primären Spot-/Futures-Ledger-
Exports; Futures-Cashflows werden als `event_type=derivative` normalisiert.
`blockpit` und `blockpit-solana` lesen Blockpit-CSV-Exports mit Incoming-,
Outgoing- und Fee-Spalten. Die Normalisierung bildet daraus steuerlich
nachvollziehbare Canonical Events; fuer Live-Ergaenzungen sollte eine einzelne
Integration gefiltert importiert und vorab auf einer Datenbankkopie validiert
werden.
Das mitgelieferte Blockpit-Supplement-Skript macht diese Vorabvalidierung bei
`--execute` automatisch: zuerst wird eine Staging-Kopie importiert, Review und
V1-Paritaet werden als Vorher-/Nachher-Snapshot ausgegeben, und die Ziel-DB
wird ohne `--force` nur veraendert, wenn `allow_export=true` bleibt.
Mit `--analyze-classes` und `--class-matrix` kann derselbe Bestand vorab in
fachliche Klassen zerlegt werden. Jede Klasse wird auf einer separaten
DuckDB-Kopie mit Review- und Paritaetsdelta bewertet; die Ziel-DB bleibt dabei
unveraendert.
`--readiness-report` ist die schnelle Vorstufe ohne Import: sie erstellt zuerst
eine DuckDB-Snapshot-Kopie, damit die laufende Backend-Datenbank keinen
Analyse-Lock-Konflikt bekommt. Danach berechnet sie je Klasse fehlende aktuelle
Preisabdeckung und den minimal benoetigten Startbestand pro Asset auf dem
Solana-Konto.

`GET /api/v1/import/blockpit-solana/preflight`

Liefert dieselbe schnelle Price-/Bestands-Vorstufe als Backend-Schnittstelle,
ohne eine Staging-DB zu importieren und ohne die Ziel-Datenbank zu veraendern.
Die Antwort gruppiert die Blockpit-Solana-Zeilen nach fachlicher Klasse, nennt
pro Klasse fehlende aktuelle Preise, benoetigte Vorbestaende,
Brutto-Bewegungen und einen Status `importable` oder `blocked`.
Zusaetzlich enthaelt `combined_readiness` die zeitlich zusammengefuehrte
Bestandspruefung ueber alle gefilterten Solana-Zeilen. Dieser Block ist fuer
die reale Importfreigabe massgeblich, weil positive Bewegungen aus einer Klasse
spaetere negative Bewegungen einer anderen Klasse decken koennen. Die
Klassenblocker bleiben Diagnosewerte und duerfen nicht als additiver
Startbestand interpretiert werden.
Jeder chronologische Startbestands-Incident kann `evidence_candidates`
enthalten. Diese Kandidaten stammen aus bereits importierten Canonical Events
mit gleichem Asset und frueherem Zeitpunkt; sie sind nur Beleg-/Herkunfts-
Hinweise und loesen keinen Import oder Review-Decision automatisch aus.
Diese Schnittstelle ist fuer die Browser-/Admin-Pruefung gedacht; die schwere
`--class-matrix` bleibt der belastbare Vorher-/Nachher-Test fuer Review- und
Paritaetsdelta.

`POST /api/v1/import/blockpit-solana/price-probe`

Prueft die aus `GET /api/v1/import/blockpit-solana/preflight` abgeleiteten
historischen Preisjobs gegen externe Provider. Standard ist `dry_run=true`;
damit werden keine Preise gespeichert und die Pipeline wird nicht neu
berechnet. Mit `dry_run=false` werden nur Jobs mit Status `available` als
Price-Ledger-Eintraege importiert und danach wird die Pipeline neu berechnet.
Der Probe nutzt dieselbe Providerlogik wie
`/api/v1/prices/backfill/external`, kombiniert `Asset/USD` mit `USD/EUR` aus
dem V1-`fx_cache` und liefert je Job `available`, `failed` oder `skipped`.
Damit kann vor einem Blockpit-Liveimport geprueft werden, ob die benoetigten
Tagespreise belegbar sind. `target_changed=true` ist nur bei ausdruecklichem
Preisimport moeglich; Rohdaten/Blockpit-Events werden von diesem Endpoint nie
importiert.

`GET /api/v1/import/solscan/token-preflight`

Vergleicht eine Solscan-CSV fuer ein Token/Wallet-Paar gegen die
Blockpit-Solana-Datei. Standard ist die IOT-Auswertung fuer
`6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP`. Die Schnittstelle aggregiert
Solscan-Transfers und Blockpit-Bewegungen je Signatur, vergleicht die Mengen
und liefert:

- Solscan-/Blockpit-Mengensummen,
- Anzahl gematchter Signaturen,
- Blockpit-Signaturen ohne Treffer in der aktuellen Solscan-Datei,
- Solscan-Signaturen ohne Blockpit-Treffer,
- Coverage-Checkpoints an den relevanten IOT-Defizitzeitpunkten.
- `rpc_evidence` aus dem kombinierten RPC-Audit-Artefakt, falls vorhanden.

Der Endpoint ist reine Preflight-/Beleganalyse. Er importiert keine Solscan-
Rohdaten und schreibt keine Review-Entscheidung.

`POST /api/v1/import/solscan/rpc-probe`

Prueft Blockpit-Signaturen, die in der vorhandenen Solscan-CSV fehlen, direkt
gegen einen Solana-RPC-Endpunkt via `getTransaction`. Die Antwort vergleicht
das Token-Wallet-Delta aus `preTokenBalances`/`postTokenBalances` mit der
Blockpit-Menge. Statuswerte sind unter anderem `verified`,
`quantity_mismatch`, `not_found`, `failed` und `rate_limited`.

Der Endpoint ist bewusst gedrosselt nutzbar:

- `max_requests` begrenzt die Anzahl der Signaturen je Lauf.
- `delay_seconds` setzt eine Pause zwischen RPC-Requests.
- `rpc_url` kann auf einen stabileren eigenen oder bezahlten RPC-Endpunkt
  gesetzt werden.

Auch dieser Endpoint importiert nichts und veraendert keine Review-Decision.

`GET /api/v1/import/solscan/evidence-trace`

Buendelt Solscan-Coverage, Blockpit-Referenzexport und vorhandenes
RPC-Evidence-Artefakt zu einer read-only Belegspur. Die Antwort enthaelt:

- `status`, zum Beispiel `covered`, `rpc_verified`, `partial` oder
  `missing_rpc_evidence`,
- `missing_signatures`, `verified_signatures` und `quantity_delta_sum`,
- den eingebetteten `preflight`,
- `trace_steps` mit Belegquelle, Status, Importeffekt und Notiz,
- `evidence_refs` fuer Finanzamt-/Review-Nachvollziehbarkeit,
- `review_scope` und optional `review_suggestion_id`.

Der Endpoint schreibt keine Raw-Objects, Canonical Events, Tax-Lines,
Review-Entscheidungen oder Portfolio-Bestaende. `import_effect` bleibt `none`.

`GET /api/v1/import/wallet-monthly/preflight`

Wertet die Datei `Wallet.6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP-month.csv`
als Monats-/Gateway-Beleg aus. Standard ist die IOT-Pruefung gegen den
Blockpit/Solana-Defizitzeitpunkt `2024-02-23T21:01:15` und den aktuell
erforderlichen Startbestand `339834.071782 IOT`.

Die Antwort liefert Monatssummen, Gateway-Anzahl, Gesamtmenge bis Stichtag,
Deckungsfaktor und `covers_required_quantity`. Der Endpoint ist ein
Beleg-/Preflight-Endpunkt; er importiert die Reward-Monatsdaten nicht direkt
als steuerliche Realereignisse.

`POST /api/v1/import/csv/preview`

Prueft eine CSV vor dem Speichern gegen das ausgewaehlte Importprofil. Die
Antwort enthaelt Spalten, gematchte Pflichtgruppen, fehlende Pflichtgruppen,
Beispielzeilen und `can_import`. Der Endpunkt persistiert keine Daten.
Wurde dieselbe Datei fuer dieselbe Quelle bereits importiert, enthaelt die
Antwort `duplicate_batch_id` und eine `duplicate_import`-Warnung.

`POST /api/v1/import/csv/raw`

Importiert CSV-Text nur, wenn dieselbe Preview-Validierung keine fehlenden
Pflichtgruppen und keine leere Datei meldet. Ungueltige Rohimporte liefern
`status=error` und persistieren keine Raw Objects. Bei identischem Import wird
der vorhandene Batch mit `duplicate_import`-Warnung zurueckgegeben.

`POST /api/v1/import/file/preview`

Prueft eine CSV-, XLSX- oder XLS-Datei als Base64-Payload vor dem Speichern.
Excel-Dateien werden serverseitig ueber Pandas gelesen. Die Antwort enthaelt
`sheet_names`; ueber `sheet_name` kann ein bestimmtes Tabellenblatt fuer Preview
und Import ausgewaehlt werden. Ohne Auswahl wird das erste Tabellenblatt
verwendet. Der Endpunkt persistiert keine Daten.
Die Deduplizierung nutzt Quelle, Dateihash und bei Excel das Tabellenblatt.

`POST /api/v1/import/assistant/preview`

Gefuehrte Import-Preview fuer Dateiimporte. Die Antwort buendelt CSV-/Excel-
Preview, Preisbedarf und Steuerwirkungs-Schaetzung. Sie persistiert keine
Daten und fuehrt keinen Pipeline-Rebuild aus.

Zusaetzliche Wirkungsfelder:

- `current_state`: aktuelle Zaehler fuer Import-Batches, Raw Objects,
  Canonical Events, Balance-Ledger, Tax-Lines, Derivate, Review-Issues und
  Exportfreigabe vor dem Import
- `estimated_state`: konservative Voransicht nach einem moeglichen Execute;
  echte Canonical-/FIFO-Zahlen werden erst nach bestaetigtem Import und
  Pipeline-Rebuild erzeugt
- `execution_plan`: ob Execute Daten schreibt, ob ein Batch erzeugt und
  normalisiert wird, ob die Pipeline rebuildet wird, betroffene Tabellen und
  Trace-JSON-Pfadtemplate
- `linked_preflights`: konkrete weiterfuehrende Preflight-Endpunkte fuer
  API-, Onchain- oder V1-Cache-Importarten, inklusive Schreibstatus,
  externem Request-Hinweis, Zweck und naechstem Schritt

`POST /api/v1/import/assistant/execute`

Schreibt erst nach bestandener Assistant-Preview. Execute legt den Raw-Batch
an, normalisiert diesen Batch, fuehrt den Pipeline-Rebuild aus und liefert den
konkreten Batch-/Run-Status zurueck. Der Import-Trace ist danach ueber
`/api/v1/import/batches/{batch_id}/trace.json` belegbar.

API-/Onchain-Modi im Assistenten sind bewusst Preview-only. Sie verweisen auf
die spezialisierten Preflight-Pfade, z.B. Binance Earn History API Preview,
Solscan Token Coverage oder Solana RPC Signature Probe. Dadurch wird beim
Oeffnen des Assistenten kein externer Connector automatisch abgefragt.

`GET /api/v1/import/coverage`

Scannt vorhandene CSV-/Excel-Dateien im Usertransfer-Verzeichnis fuer die
Import-Coverage. Der Scan ist budgetiert (`limit`, `max_seconds`) und liefert
`files_total`, `files_scanned`, `scan_truncated` und `scan_seconds`, damit die
Browser-Importseite nicht durch grosse Altbestände timeoutet. Ein gekuerzter
Scan ist ein UI-/Arbeitsstatus, keine fachliche Importentscheidung.

`GET /api/v1/import/policy/audit`

Klassifiziert alle unterstuetzten CSV-/XLS-/XLSX-Dateien im
Usertransfer-Verzeichnis nach Import-Policy. Die Antwort enthaelt
`files_total`, `classified`, `unclassified`, `curated_primary`,
`staging_required`, `parser_needed`, `reference_only` und eine Entscheidung je
Datei. `curated_primary` ist die einzige Kategorie, die in den kuratierten
Realimport darf. `staging_required`, `parser_needed` und `reference_only`
bleiben blockiert, bis ein eigener Parser, Staging-Preflight oder
Plausibilitaets-/Belegpfad umgesetzt ist.

`GET /api/v1/import/parser-preflight`

`GET /api/v1/import/jup-perps/preview`

Staging-Preview fuer die Jupiter-Perps-Datei. Die Schnittstelle trennt
realisierten USD-PnL, Handelsgebuehren, Liquidationsgebuehren und
Collateral-Flows. Sie erzeugt keine steuerwirksamen Canonical Events und ist
kein kuratierter Realimport.

Prueft alle Dateien aus der Import-Policy-Kategorie `parser_needed`, ohne
Rohdaten zu importieren oder Canonical Events zu erzeugen. Die Antwort nennt
pro Datei Parser-Art, Dateiformat, Sheet-Informationen, erkannte Spalten,
Zeilenanzahl, Beispielzeilen und Warnungen. `can_realimport` bleibt fuer diese
Dateien immer `false`, bis ein dedizierter Parser implementiert und getestet
ist.

`POST /api/v1/import/file/raw`

Importiert CSV-, XLSX- oder XLS-Dateien als Base64-Payload in Raw Objects.
Bei Excel-Dateien kann `sheet_name` gesetzt werden. Auch dieser Endpunkt nutzt
die Preview-Validierung als Persistenz-Gate. Danach laufen
Normalisierung, Ledger und Review ueber dieselbe Pipeline wie bei
CSV-Textimporten.
Bei identischem Import wird der vorhandene Batch zurueckgegeben und keine
zweite Rohdatenkopie erzeugt.

`GET /api/v1/raw/objects`

Listet gespeicherte Rohzeilen, optional gefiltert mit `batch_id`.

`GET /api/v1/events/canonical`

Listet normalisierte Canonical Events, optional gefiltert mit `batch_id`.

`GET /api/v1/import/batches/{batch_id}/trace.json`

Laedt einen nachvollziehbaren Batch-Trace als JSON herunter. Enthalten sind der
Import-Batch, alle Raw Objects des Batches und alle daraus erzeugten Canonical
Events.

## Ledger

`POST /api/v1/ledger/rebuild`

Startet reproduzierbare Ledger-Neuberechnung.

`GET /api/v1/ledger/balances`

Liefert Bestaende aus dem Balance-Ledger.

`GET /api/v1/transfers/candidates`

Berechnet moegliche Eigen-Transfer-Kandidaten aus Canonical Events mit
`event_type=transfer`. Bewertet werden Mengennaehe, Zeitrichtung, Zeitfenster,
Konto-/Quellen-Unterschiede und TX-ID. Die Antwort enthaelt Score, Status,
Gruende und Warnungen. Kandidaten sind keine automatische
Transferentscheidung und veraendern keine Steuerdaten.

`GET /api/v1/ledger/flows`

Liefert Netto-Euro-Fluesse fuer Sankey.

## Cockpit

`GET /api/v1/cockpit/summary`

Liefert die Startseiten-Aggregation aus Portfolio, Quellen, Review-Gate,
Preisdeckung und gespeicherten Live-Snapshot-Ankern. Der Endpunkt ist lesend
und ruft beim Laden keine externen Connectoren ab.

`top_sources` enthaelt neben Anzeige- und Ledgerwerten auch:

- `live_anchor_source`: technische Quelle des gespeicherten Live-Snapshots
- `display_warning`: Hinweis, wenn API-Livewert und steuerlicher Ledger nicht
  als abgeglichen gelten

Live-Werte sind damit ein Anzeigeanker, keine automatische FIFO- oder
Ledger-Korrektur.

## Quellen

`GET /api/v1/sources/overview`

Liefert lesbare Quellen mit Anzeige-Wert, Ledger-Wert, API-Livewert, Delta,
letztem Live-Stand und Import-/Review-Kontext. Nur wenn ein gespeicherter
Live-Snapshot frisch ist, kann `value_eur` der API-Anzeigewert sein;
`ledger_value_eur`, `delta_value_eur`, `live_anchor_source` und
`display_warning` bleiben zur steuerlichen Einordnung sichtbar.

Bei einer `expected_zero`-Quelle ohne frischen Live-Anker ist `value_eur=0`,
`value_basis=expected_zero_policy_no_current_live` und `delta_value_eur=null`.
Der Ledger-Restbestand bleibt separat erhalten und wird nicht als heutiges
Vermoegen oder beobachtetes Live-Delta dargestellt.

`GET /api/v1/sources/connector-diagnostics`

Liefert Credential-Metadaten, Snapshot-Frische und den letzten persistierten
Connectorversuch, ohne Secretwerte auszugeben oder eine externe Abfrage zu
starten. `diagnostics[].last_attempt` enthaelt Connector, UTC-Zeitpunkt,
Status, Snapshotzahl, technische Quelle und die bereinigte Provider-
Fehlermeldung. `failed_latest_attempts` zaehlt die letzten fehlgeschlagenen
Abrufe. Ist ein `connector_error` neuer als der letzte erfolgreiche Snapshot,
bleibt er sichtbar und wird nicht durch den alten Snapshotstatus verdeckt.
Bekannte Authentifizierungsfehler wie `APIKEY_EXPIRED` liefern direkt die
Aktion, den Key im V2 Secret Store zu erneuern.

`GET /api/v1/sources/registry/config`

Liefert die versionierte Registry aus `configs/source_registry.json`. Jeder
Eintrag enthaelt Eigentum, Rolle, Portfolio- und FIFO-Policy,
Gueltigkeitszeitraum, Abdeckungsstatus, Identifier und Belegreferenzen. Die
optionale `coverage_limitation` klassifiziert eine partielle Abdeckung als
`provider_api_history_boundary`, `provider_export_field_gap`,
`missing_original_account_history` oder einen bestimmungsgemaessen
`documented_transfer_route_only`. `additional_user_evidence_required` darf nur
bei einer echten fehlenden Account-History gesetzt sein. Secrets sind nicht
Teil dieser Datei.

`POST /api/v1/sources/registry/runs`

Erzeugt einen read-only Registry-Lauf. Canonical Source-/Account-Gruppen werden
mit Vorrang fuer exakte Account-/Wallet-Identifier zugeordnet. Fuer aktuelle
eigene Portfolioquellen wird der historische Ledger-Bestand gegen den live
verankerten Snapshot verglichen. Unregistrierte Gruppen, sichtbare Legacy- oder
Infrastrukturkonten, echte fehlende Account-Historien, dokumentierte
Provider-Grenzen und materielle Mengendeltas verhindern `strict_ready`.

`coverage_gate_status` trennt `provider_gap` von `missing_evidence`. Ein
ausgeschlossener historischer Staking-/Servicepfad darf dagegen
`documented_route` und fuer seinen engen Transferzweck `strict_ready=true`
sein. Eine solche Serviceadresse ist keine eigene aktuelle Portfolio-Wallet.
Der Run zaehlt diese Kategorien separat in
`provider_coverage_gap_entries_count`, `user_evidence_gap_entries_count` und
`documented_route_entries_count`. Bereits vollstaendig gelieferte
Providerpakete werden nicht erneut vom Nutzer angefordert.

Jeder Entry trennt dabei explizit:

- `live_snapshot_status`: `current`, `stale`, `missing` oder
  `not_applicable`,
- `latest_live_snapshot_at`: UTC-Zeit des letzten gespeicherten API-/RPC-
  Snapshots,
- `live_balance_basis`: `current_live_snapshot`, `ledger_fallback` oder
  `not_applicable`,
- `last_connector_attempt`: letzter persistierter Abruf mit Status und
  Fehlermeldung, auch wenn kein neuer Snapshot erzeugt wurde.

Bei `stale` oder `missing` darf der angezeigte Ledger-Fallback nicht als
aktueller Plattformbestand und `current_value_delta_eur` nicht als belastbarer
Live-Abgleich ausgelegt werden. Die UI zeigt in diesem Fall `nicht aktuell`
beziehungsweise `nicht belastbar`.

`GET /api/v1/sources/registry/runs/latest`

Liefert das letzte versionierte Artefakt aus
`var/source_registry/latest_source_registry.json` inklusive semantischem Hash,
Entry-Status, Mengenabweichungen, Findings und naechsten Aktionen.

`GET /api/v1/sources/{source_id}`

Liefert dieselben Felder fuer eine Quelle plus Konten, Assets, aktuelle
Transaktionen, Reconciliation-Status und `full_accounts`. Wallet-Adressen
duerfen im UI gekuerzt werden, bleiben im Detail aber vollstaendig vorhanden.

`GET /api/v1/sources/{source_id}/reconciliation`

Liefert den Asset-Level-Drilldown fuer eine Quelle. Die Antwort enthaelt je
Asset Ledger-Menge/-Wert, API-Live-Menge/-Wert, Delta, Preisquelle,
Live-Komponenten, Live-Account-Typen und die fachliche Naechste-Aktion.
Zusaetzlich enthaelt `live_components` die einzelnen Komponenten des
gespeicherten Live-Snapshots mit Asset, Menge, EUR-Wert, Account-Typ,
Produkt-ID, Position-ID, Event-Typ und Preisquelle.
Der Endpunkt ist lesend; Deltas erzeugen keine FIFO-, Ledger- oder
Steuerkorrektur.

`GET /api/v1/sources/binance/reconciliation/evidence`

Liefert einen read-only Binance-Evidence-Report fuer den Live-vs-Ledger-
Abgleich, standardmaessig seit `2025-01-01` fuer `JUP,SOL,EUR`.
Optionale Query-Parameter:

- `since`: ISO-Datum/-Zeit, z.B. `2025-01-01`
- `assets`: kommaseparierte Asset-Liste, z.B. `JUP,SOL,EUR`

Die Antwort enthaelt:

- Gesamt-Ledger, API-Livewert, Delta und letzten Live-Stand
- vorhandene Binance-Import-Batches
- `history_requirements` fuer fehlende Produkt-/Fiat-Historien wie Flexible
  Earn, Locked Earn oder Fiat Spend/Buy
- je Asset Ledger-/Live-Mengen, Delta, Live-Komponenten
- Canonical-Event-Aggregate nach Jahr, Asset, Event-Typ und Account
- `suspected_gap` und `next_action`

Der Report dient der Nachverfolgung der fehlenden Historie bzw.
Produkt-Mappings. Er schreibt keine Preis-, FIFO-, Ledger- oder
Canonical-Event-Daten.

`GET /api/v1/sources/binance/earn-history-preflight`

Liefert einen read-only Preflight der aktuellen Binance Simple-Earn-
Liveprodukte. Die Antwort enthaelt je Produkt:

- Asset, Account-Typ, Product-ID und Position-ID
- Live-Menge und Live-EUR-Wert
- erkannte Live-Event-Typen
- benoetigte Bewegungen wie Subscription, Redemption, Reward,
  Early-Redemption oder Accrued-Reward-Snapshot
- Importstatus und Evidence-Dateien
- `api_probe_payload` fuer einen spaeteren gefuehrten API-History-Abruf

Der Endpunkt plant History-Abdeckung fuer Earn-Produkte, fuehrt aber keinen
Import aus und schreibt keine Canonical Events.

`GET /api/v1/sources/binance/earn-history-api-preview`

Fuehrt einen signierten, read-only Binance Simple-Earn-History-Abruf aus.
Credentials werden aus dem V1/V2-Secret-Store (`secret.cex.binance.api_key`
und `secret.cex.binance.api_secret`, Fallback `secret.binance.*`) oder aus
`BINANCE_API_KEY` und `BINANCE_SECRET_KEY`/`BINANCE_API_SECRET` gelesen.

Optionale Query-Parameter:

- `since`: ISO-Datum/-Zeit, Default `2021-01-01`
- `until`: ISO-Datum/-Zeit, Default jetzt
- `assets`: kommaseparierte Asset-Liste, z.B. `JUP,SOL`
- `max_pages`: pro Endpoint, gekappt auf `200`
- `max_records`: gesamt, gekappt auf `50000`

Abgefragt werden fuer aktuelle Live-Earn-Produkte:

- Flexible Subscription/Redemption/Rewards
- Locked Subscription/Redemption/Rewards

Bei Locked-Earn-Produkten werden Position-IDs aus gefundenen Subscription-
Records fuer weitere Redemption-Abfragen genutzt. So koennen auch alte
Positionen belegt werden, die nicht mehr als aktuelle Live-Position erscheinen,
aber fuer den FIFO-/Ledger-Abgleich relevant sind.

Die Antwort enthaelt Request-Status pro Binance-Endpunkt und die geladenen
Records als Rohpayload. Der Endpunkt importiert nichts und schreibt keine
Raw Objects, Canonical Events, FIFO-Lots oder Ledgerbuchungen.

`POST /api/v1/sources/binance/earn-history-harvest/import`

Importiert einen zuvor lokal gespeicherten Binance Simple-Earn-Harvest als
kuratierten Raw-Batch `binance_simple_earn_api`. Der Request erwartet:

```json
{
  "harvest_path": "var/binance_simple_earn_history/20260531T095848Z",
  "execute": false
}
```

Mit `execute=false` wird nur die Importfaehigkeit geprueft. Die Preview nennt
Record-Anzahl, vorbereitete Zeilen, Assets, Record-Typen, Warnungen und einen
moeglichen Duplicate-Batch. Mit `execute=true` wird der Batch importiert und
die Pipeline danach neu aufgebaut.
Bereits importierte Simple-Earn-Records werden vor dem Import ueber
`source_ref` sowie, wo vorhanden, `purchase_id`/`redeem_id` erkannt und
uebersprungen. Damit kann ein erweiterter Harvest als Supplemental-Import
genutzt werden, ohne alte Subscriptions, Rewards oder Redemptions doppelt zu
buchen.

Die Normalisierung bildet Simple-Earn-Records wie folgt ab:

- Subscriptions: `transfer`, positive Menge auf dem Earn-Produktkonto
- Redemptions: `transfer`, negative Menge auf dem Earn-Produktkonto
- Flexible Rewards: `reward`, positive Menge auf dem Earn-Produktkonto
- Locked Rewards: `reward`, positive Menge auf `Spot`, entsprechend dem
  Binance-Account-Ledger und Asset-Dividend-Beleg
- `lossAmount` einer vorzeitigen Locked-Redemption:
  `fee`, negative Menge auf dem Earn-Produktkonto mit Provider-Referenz,
  `originalAmount`, `rewardAmt` und `redeemId`; globale FIFO und Wallet-FIFO
  fuehren dies nur bei einer exakten Reward-Kette als Provider-Clawback ohne
  Verkaufserloes. Zugeordnet werden ausschliesslich Reward-Lots derselben
  Binance-Position oder eine betragsgenau geschlossene Locked-Reward-Kette
  zwischen Subscription und Redemption. Ohne exakte Deckung entsteht ein
  sichtbarer Unmatched-Fall; es werden keine beliebigen FIFO-Lots entfernt.
  Die steuerliche Abzugsfaehigkeit bleibt getrennt pruefpflichtig
- Locked-Subscriptions mit `type=AUTO`: belegtes Transfer-Event mit Menge `0`,
  weil dies eine Auto-Renewal-/Rollover-Buchung derselben Position ist und den
  Bestand nicht erneut erhoehen darf

Der Endpoint ist kein Live-Balance-Fix. Er erzeugt belegbare Historienereignisse
aus Binance-API-Rohdaten; verbleibende Live-vs-Ledger-Deltas bleiben im
Reconciliation-Drilldown sichtbar und duerfen nicht automatisch als FIFO-Trade
oder Ledger-Korrektur gebucht werden.

`POST /api/v1/sources/binance/earn-history-api/import`

Fuehrt denselben signierten Simple-Earn-Abruf wie der Preview-Endpunkt aus und
importiert bei `execute=true` ausschliesslich noch nicht vorhandene Records.
Der Request akzeptiert `since`, `until`, `assets`, `max_pages`, `max_records`
und `execute`. Die Antwort enthaelt API-Preview, Import-Preview, optionalen
Batch und den Pipeline-Lauf. Vor dem Schreiben wird ueber stabile
Source-Referenzen dedupliziert.

`GET /api/v1/sources/binance/asset-dividend-api-preview`

Fuehrt einen signierten, read-only Abruf von
`GET /sapi/v1/asset/assetDividend` aus. Query-Parameter sind `since`, `until`,
`assets` und `max_records`; ohne Asset-Angabe wird konservativ nur `SOL`
abgefragt. Die offiziell erlaubten maximal 180 Tage pro Anfrage werden durch
179-Tage-Fenster eingehalten. Antworten mit mehr als 500 Treffern werden durch
kleinere Zeitfenster erneut abgefragt. Der Preview schreibt keine Daten.

`POST /api/v1/sources/binance/asset-dividend-api/import`

Importiert bei `execute=true` neue Provider-Belege als Raw-Batch
`binance_asset_dividend_api`. Locked-Rewards werden ueber Asset, exakte Menge
und UTC-Kalendertag gegen vorhandene Binance-Ledger- und Simple-Earn-Records
gezaehlt dedupliziert. Unterschiedliche Credit-/Accrual-Uhrzeiten desselben
Tages erzeugen dadurch keine doppelten Reward-Einnahmen. Positive Locked-
Dividenden werden als `reward` auf `Spot` normalisiert; Provider-ID, `tranId`,
`divTime`, `direction` und `enInfo` bleiben im Raw-Beleg erhalten.

Die Asset-Dividend-Historie ist ein Reward-/Distribution-Beleg und kein
Live-Balance-Fix. Der Import schreibt keine synthetische Ausgleichsbuchung.

`GET /api/v1/sources/binance/withdraw-history-api-preview`

Liest die Binance Capital Withdraw History in begrenzten Zeitfenstern. Optional
werden `since`, `until`, `assets` und `max_records` gesetzt. Die Rohbelege
enthalten insbesondere Nettomenge, Gebuehr, Zieladresse, Netzwerk, Abschlusszeit
und TxID. Der Preview schreibt keine Daten.

`POST /api/v1/sources/binance/withdraw-history-api/import`

Importiert bei `execute=true` neue Withdrawal-Belege dedupliziert als
Evidence-Events mit Menge `0`. Diese Events veraendern den Bestand nicht. Die
Wallet-FIFO-Methode kann sie jedoch ueber exakte TxID, eigene Zielwallet,
Nettomenge und Gebuehr mit dem On-chain-Zufluss verbinden und die vorhandenen
Binance-Lots samt Anschaffungszeit und Kostenbasis fortfuehren.

`GET /api/v1/sources/bitget/withdraw-history-api-preview`

Liest die Bitget Withdrawal Records in 29-Tage-Fenstern. Der Endpunkt liefert
pro Anfrage Status und Anzahl sowie, soweit von Bitget vorhanden, Coin, Menge,
Fee, Zieladresse, Chain, TxID und Zeitstempel. Ein leeres Ergebnis ist kein
Vollstaendigkeitsbeleg fuer historische Bitget-Produktklassen.

`POST /api/v1/sources/bitget/withdraw-history-api/import`

Importiert nur neue Bitget-Withdrawal-Belege und baut danach die Pipeline neu.
`execute=false` ist der sichere Preview-Modus. Bereits vorhandene Source-Refs
und TxIDs werden uebersprungen.

## Portfolio

`GET /api/v1/portfolio/snapshot`

Berechnet Portfolio aus Balance-Ledger und Price-Ledger.
Gekuerzte Account-Labels mit `...` werden nur dann mit einer vollen Wallet
zusammengefuehrt, wenn Prefix und Suffix eindeutig genau eine volle Adresse
treffen. Als Quellen gelten Canonical Accounts und volle Account-/Wallet-/
Address-Werte aus Raw-Transferdaten; TXIDs und Hashfelder werden nicht als
Wallet-Quelle verwendet. Die Antwort enthaelt `resolved_account_aliases` und
`unresolved_truncated_accounts`; nicht aufloesbare gekuerzte Accounts werden
zusaetzlich im Review-Gate blockierend gemeldet.

Die Antwort enthaelt zusaetzlich `separation_virtual_wallet`. Diese virtuelle
Wallet zeigt offene FIFO-Restmengen aus echten EUR-zu-Token-Kaeufen seit
`2025-06-13T00:00:00Z`. Gezaehlt werden nur Canonical Events mit
`event_type=trade`, positiver Token-Menge und `quote_asset=EUR`. Staking,
Rewards, Mining, Zinsen, Deposits, Transfers, Redeems und reine
Bestandszunahmen werden nicht als Investment-Neubestand gefuehrt. EUR-Cash
bleibt im normalen Portfolio sichtbar.
Sie ist nur eine Portfolio-Auswertung und erzeugt keine Canonical Events,
keine Ledger-Buchungen und keine Steuerzeilen.

`GET /api/v1/portfolio/as-of?as_of=YYYY-MM-DD`

Berechnet den Besitz zu einem frei waehlbaren Stichtag. Datumseingaben ohne
Uhrzeit werden als Tagesende UTC interpretiert, z.B. `2024-12-31` als
`2024-12-31T23:59:59.999999Z`. Die Mengen kommen aus allen Balance-Ledger-
Deltas bis einschliesslich Stichtag. Die EUR-Bewertung nutzt pro Asset den
letzten belegten Preis am oder vor dem Stichtag; fehlende historische Preise
werden in `missing_price_assets` ausgewiesen und nicht geschaetzt.

Die Antwort enthaelt:

- `positions`: Asset-/Account-Positionen zum Stichtag
- `asset_summary`: aggregierter Besitz nach Asset
- `account_summary`: aggregierter Besitz nach Konto/Wallet/Plattform
- `total_value_eur`: bewerteter Gesamtwert ohne fehlende Preispositionen
- `missing_price_assets`: Assets ohne belegten historischen Preis
- `methodology`: menschenlesbare Bewertungslogik

`GET /api/v1/portfolio/separation-report`

Liefert den internen Darstellungsbericht fuer den Neubestand seit Trennung:
`trend` fuer den Wertverlauf, `investment_locations` fuer die aktuelle
Account-/Asset-Auflistung und `virtual_wallet` fuer die aggregierte
Stichtags-Wallet. Zusaetzlich enthaelt die Antwort `unrealized_lots` mit
Anschaffungsdatum, Restmenge, anteiligen Anschaffungskosten, aktuellem Wert,
unrealisiertem Gewinn/Verlust und Preisqualitaet pro FIFO-Lot seit Stichtag.
Diese Lots sind auf echte EUR-Kaeufe ab Stichtag begrenzt; Rewards,
Staking-/Mining-Ertraege und Transfer- oder Redeem-Buchungen erscheinen dort
nicht als neue Investments.
`price_quality` markiert fehlende, alte oder nur aus Transaktions-Quotes
abgeleitete Preise. `unmatched_lot_assets` markiert Assets, deren positiver
Stichtags-Neubestand nicht vollstaendig mit FIFO-Anschaffungslots seit dem
Stichtag belegbar ist. Fiat-EUR ist aus Trend und Investment-Orten
ausgeschlossen. Der Endpunkt ist nur lesend.

## Stichtag und Zugewinn

`GET /api/v1/divorce/equalization-summary`

Erzeugt eine read-only Vergleichsrechnung fuer Trennungs- und
Endvermoegensstichtag. Bevorzugte Query-Parameter sind `separation_date`,
`end_asset_date` und `materiality_threshold_eur`; kompatibel bleiben die
expliziten UTC-Parameter `cutoff_at` und `valuation_at`. Ohne Parameter gelten
der 13.06.2025 und der 24.07.2026. Reine Datumswerte werden als Tagesende in
`Europe/Berlin` inklusive Sommer-/Winterzeit auf UTC normalisiert. Fuer diese
beiden Sommerdaten ist die persistierte Grenze jeweils `21:59:59.999999 UTC`.
Mengen und Marktwerte werden an beiden Zeitpunkten historisch rekonstruiert;
ein aktueller Live-Snapshot wird nicht als historischer Endwert umbeschriftet.

Die Antwort enthaelt getrennte Wallet-/Exchange-Konten, vollstaendige
Quellkonten, bestaetigte Fiat-Einzahlungen, mit der SHA-256-gebundenen Trade
History, Sparkassen-CAMT-Primaerbelegen und On-chain-Eingaengen gematchte
MoonPay-/Apple-Pay-Bruttozahlbetraege,
gegebenenfalls verbleibende vorlaeufige Onramps sowie eine vorlaeufige
flussbereinigte Wertveraenderung und je Stichtag ein Preis-Gate. Das zusaetzliche
`capital_flow_gate` klassifiziert jeden negativen Transfer als belegten internen
Transfer, interne Produktumbuchung, technische Gebuehr, Trade-/Service-Route,
belegte interne Serviceposition mit vollstaendiger Liquidation, operative
Korrektur oder externe Auszahlung. Nur explizit bestaetigte externe
Auszahlungen werden der Flussrechnung zugeschlagen; offene materielle Abfluesse
werden lediglich in einem getrennten Szenario gerechnet. `strict_ready=false`
bleibt bestehen, wenn eine materielle Position keinen Same-Day-Preis besitzt,
ein Token-Risikoflag traegt, die Kapitalherkunft nicht belegt ist oder ein
materieller Abfluss ungeklart bleibt. `stichtage` dokumentiert deutsche
Kalendertage, UTC-Grenzen, Zeitzone,
§ 1384 BGB als Rechtsgrundlage und den Status des Gerichts-/Zustellungsbelegs.
Ein optionales `court_evidence_reference` bindet eine vorhandene Belegreferenz
an Summary und Dossier; ohne Referenz bleibt das Dossier blockiert.

Die Klassifikation `internal_service_position_loss` ist ausschliesslich fuer
einen SHA-geprueften Servicepositions-Lebenszyklus vorgesehen. Das Collateral
wurde aus einer registrierten eigenen Wallet in ein programmverwaltetes Konto
uebertragen, die Position vor dem Endvermoegensstichtag vollstaendig liquidiert
und danach bis zum Stichtag nicht mehr erfolgreich veraendert. Der belegte
Wertverlust bleibt Teil der Portfolioveraenderung und wird nicht als externe
Auszahlung addiert. Diese familienrechtliche Flussklassifikation aendert keine
steuerliche Einordnung, Imports, Canonical Events, Ledger, FIFO-Lots oder
Tax-Lines.

Die gleichen Parameter gelten fuer:

- `GET /api/v1/divorce/equalization-summary/accounts.csv`
- `GET /api/v1/divorce/equalization-summary/capital-flows.csv`
- `GET /api/v1/divorce/equalization-summary/valuation-tokens.csv`
- `GET /api/v1/divorce/equalization-summary/live-reconciliation.csv`
- `GET /api/v1/divorce/equalization-summary/evidence-package.zip`

Der Token-CSV enthaelt beide Snapshots, Preisquelle, Preiszeitpunkt, Preisalter
und Preisstatus. Der Kapitalfluss-CSV enthaelt Zuflussgruppen mit Mittelherkunft
sowie alle negativen Transferereignisse mit Klassifikation, Belegstatus, TXID,
Raw-Referenz und Auswirkung auf die Rechnung. Das ZIP berechnet die
Zusammenfassung nur einmal und enthaelt zusaetzlich beide Preis-Gates sowie den
Kapitalfluss-Abgleich als JSON und CSV. Eine zusaetzliche Datei
`02_Token/stichtag-token-valuation-decisions.csv` dokumentiert alle fuer die
beiden Stichtage angenommenen Risikotoken-Bewertungen mit exaktem Mint,
Preisquelle, EUR-Preis, Decision-ID und Belegreferenz. Sobald MoonPay-Onramps im Zeitraum
vorhanden sind, werden auch `moonpay_receipt_reconciliation.json` und der
SHA-256-gepruefte Primaerexport `moonpay_trade_history.csv` versioniert. Die
privaten CAMT-Dateien selbst werden nicht kopiert; der JSON-Abgleich bindet sie
ueber den semantischen CAMT-Hash und gehashte Einzelreferenzen.

`POST /api/v1/divorce/valuation-runs`

Erzeugt ein versioniertes Stichtags-/Zugewinndossier. Der Request akzeptiert
`separation_date`, `end_asset_date`, optional `court_evidence_reference`,
`materiality_threshold_eur` und `material_delta_threshold_eur`. Die alten
Felder `cutoff_at` und `valuation_at` bleiben fuer explizite UTC-Zeitpunkte
kompatibel. Neben der Stichtagsbewertung werden zwei separate
Wallet-/Depot-FIFO-Replays exakt bis zum Trennungs- und
Endvermoegenszeitpunkt ausgefuehrt. Der Lauf schreibt ausschliesslich Belege unter
`var/valuation_runs/` und `var/wallet_fifo_runs/`; produktive Imports, Preise,
Ledger, Tax-Lots und Tax-Lines bleiben unveraendert.

Bereits vorhandene FIFO-Beleglaeufe werden fuer das Dossier wiederverwendet,
wenn Stichtag, Jahre, Materialitaetsschwellwert, FIFO-Methodenversion und der
semantische Eingabefingerprint exakt uebereinstimmen. Vor der Wiederverwendung
werden Groesse und SHA-256 aller gebundenen Belegdateien geprueft. Das Feld
`fifo_checkpoints[].reused_existing_run` macht die Laufbasis explizit. Sobald
sich Events, Preise, relevante Reviews, Settings, Raw-Objekte oder die
Methodenversion aendern, wird kein alter Lauf verwendet und der FIFO-Stichtag
neu berechnet.

Die Quellenlage wird im Dossier nicht mehr als ein einziger Sammelblocker
ausgegeben. `source_provider_coverage_gap_count` zaehlt dokumentierte Grenzen
der Anbieter-API oder des Anbieterexports, fuer die identische Nutzerexporte
nicht erneut angefordert werden duerfen. `source_user_evidence_gap_count`
zaehlt dagegen Quellen, fuer die tatsaechlich noch eine originale
Account-History oder ein gleichwertiger eigener Primaerbeleg fehlt.
`source_quantity_blocker_count` weist materielle Live-vs-Ledger-
Mengendifferenzen separat aus.

Jeder Eintrag in `fifo_checkpoints` trennt zudem die Methodendifferenz in
`provider_basis_event_set_gap_groups_count`,
`provider_basis_quantity_gap_groups_count` und
`unexplained_method_gap_groups_count`. Die Klassifikation darf nur verwendet
werden, wenn `method_gap_classification_complete=true`. Eine vollstaendig
providergebundene Ereignisabweichung bleibt bis zur fachlichen Behandlung der
Kostenbasis blockierend, ist aber keine unbekannte Wallet-Transaktion und kein
fehlender Nutzerexport.

- `GET /api/v1/divorce/valuation-runs/latest` liefert den letzten Lauf.
- `GET /api/v1/divorce/valuation-runs/{run_id}` liefert einen bestimmten Lauf.
- `GET /api/v1/divorce/valuation-runs/{run_id}/evidence/{filename}` laedt eine
  im Run freigegebene JSON-, CSV- oder ZIP-Belegdatei.

Der Status ist nur dann `strict_ready`, wenn der Gerichtsbeleg referenziert,
beide Preis-Gates, das Vermoegensfluss-Gate, die Quellenregistry und beide
FIFO-Stichtage streng freigegeben sind. Offene Herkunft, Mengendifferenzen,
Kaufbelege oder veraltete Preise bleiben sichtbar und blockieren bzw. erzeugen
Review statt automatisch korrigiert zu werden.

`POST /api/v1/divorce/service-route-evidence/refresh`

Prueft eine konkrete Solana-TXID per freier Public RPC und schreibt kleine,
komprimierte Primaerbelege unter `var/divorce_service_route_evidence/`. Fuer
Jupiter Perps verlangt die Decision Layer gemeinsam:

- ein kanonisches negatives SOL-Ereignis,
- eine zum Ereigniszeitpunkt als `owned` registrierte Wallet,
- erfolgreichen, zeitgleichen und von dieser Wallet signierten Positionsaufbau,
- exakte Lamport-Gleichung aus Collateral, Netzwerkgebuehr, Position-Rent und
  Rueckzahlung des Wrapped-SOL-Konto-Rents,
- Jupiter-Perps-Programm und `InstantIncreasePosition`,
- exakten WSOL-Collateraltransfer und mit dem On-chain-Preis reconcilierten
  USD-Collateralwert,
- dasselbe programmverwaltete Positionskonto im weiteren Lebenszyklus,
- `LiquidateFullPosition4` vor dem angeforderten Endstichtag,
- keine spaetere erfolgreiche Aktivitaet bis zu diesem Stichtag,
- mit einem Same-Day-SOL-Preis bewertetes Rest-Rent unter der angeforderten
  EUR-Materialitaet.

Die Antwort ist erst bei allen Flags `strict_ready=true`. RPC-Rohantworten
werden gzip-komprimiert und einzeln mit SHA-256 gebunden.

`GET /api/v1/divorce/service-route-evidence/{tx_id}`

Liefert den letzten semantisch validen Evidence-Report fuer die TXID. Ein
veralteter oder manipulierter Report wird nicht zurueckgegeben.

`POST /api/v1/divorce/service-route-evidence/decisions`

Akzeptiert nur einen `strict_ready`-Report mit exakt passendem
`semantic_sha256`. Die idempotente Decision hat den Typ
`divorce_service_route`, den Status
`internal_service_position_loss_confirmed` und die Wirkung
`divorce_capital_flow_only`. Import-, Ledger-, FIFO- und
Steuerklassifikationswirkung sind jeweils `none`.

`GET /api/v1/divorce/service-route-evidence/{tx_id}/artifacts/{filename}`

Liefert ausschliesslich eine im validierten Report gelistete gzip-Datei, wenn
Dateipfad und SHA-256 unveraendert sind. Freie Dateipfade sind nicht erlaubt.
Akzeptierte Reports werden als `service_route_evidence.json` in das direkte und
das versionierte Stichtagsdossier aufgenommen. Die Datei bindet neben dem
On-chain-Report auch die akzeptierte Reviewentscheidung mit Decision-ID,
Zeitpunkt, Akteur, Belegreferenz und demselben semantischen Evidence-Hash ein.

## Preise

`GET /api/v1/prices/as-of-gate?as_of_date=YYYY-MM-DD&materiality_threshold_eur=1`

Prueft alle materiellen Portfolio-Positionen an einem historischen Stichtag.
Same-Day-Preis, Preisalter, Preisquelle, Provider-Konfiguration und Tokenrisiko
werden getrennt ausgewiesen. Die Tokenidentitaet wird mintgenau aus dem lokalen
Jupiter-Metadatenbeleg bestimmt; ein vorangestelltes `$` im Symbol wird dabei
normalisiert. `fetchable` bedeutet, dass ein historischer Provider-Identifier
vorhanden ist; es ist noch kein Schreibvorgang. `review_only` bedeutet, dass
bereits ein Same-Day-Preis vorliegt, aber ein unverified Token mit
`spam_review`- oder `review`-Flag noch keine stichtagsbezogene Entscheidung
besitzt. Verifizierte Token werden nicht allein wegen ihres Symbols blockiert.

`POST /api/v1/prices/as-of-gate/backfill`

Der Request enthaelt bevorzugt `as_of_date`, alternativ einen expliziten
`as_of`-UTC-Zeitpunkt, sowie Materialitaet, optionale Assets, Request-Limit,
Provider, Confidence und `dry_run`. `as_of_date` wird als deutsches Tagesende
nach UTC normalisiert. Standard ist `dry_run=true`. Fuer alte
Stichtage nutzt der produktive Pfad DefiLlama fuer den USD-Preis und den
vorhandenen V1-FX-Cache fuer den belegten USD/EUR-Tageskurs. Apply schreibt nur
neue Price-Ledger-Punkte. Es startet bewusst keinen automatischen Ledger- oder
Steuer-FIFO-Rebuild. Ein unverified Risikotoken bleibt trotz Preis blockiert,
bis der nachfolgende Review-Endpunkt fuer genau Datum, Asset und Mint eine
Entscheidung speichert.

`POST /api/v1/prices/as-of-gate/token-review-decisions`

Akzeptiert fuer einen materiellen Risikotoken den bereits vorhandenen,
positiven Same-Day-EUR-Preis fuer genau einen Stichtag. Der Request enthaelt:

- `as_of_date`: deutscher Bewertungsstichtag,
- `asset`: normalisiertes Assetsymbol,
- `materiality_threshold_eur`: dieselbe Schwelle wie im Preis-Gate,
- optional `rationale` und `actor`.

Die Entscheidung ist durch Datum, normalisiertes Asset und exakten Mint
eindeutig gescoped und idempotent. Ohne materiellen Kandidaten, Risikoflag oder
positiven Same-Day-Preis antwortet die API mit `422`. Der gespeicherte Payload
bindet EUR-Preis, Preisquelle und Belegreferenz. Die Wirkung ist ausschliesslich
`include_existing_position_with_same_day_price`: Import, Bestand, Ledger, FIFO
und Steuerzeilen bleiben unveraendert. Ein spaeterer anderer Stichtag oder ein
anderer Mint benoetigt eine eigene Entscheidung.

`GET /api/v1/prices/as-of-gate/token-review-decisions.csv`

Liefert die stichtagsbezogenen Entscheidungen als Beleg-CSV. Optionale Query-
Parameter sind `separation_date` und `end_asset_date`; ohne Parameter gelten
der 13.06.2025 und der 24.07.2026. Die CSV wird auch in neue versionierte
Stichtagsdossiers aufgenommen.

`POST /api/v1/prices`

Speichert einen EUR-Preis fuer ein Asset im Price-Ledger.

`POST /api/v1/prices/import/csv/preview`

Prueft einen historischen Preis-CSV-Import ohne Persistenz. Pflichtspalten sind
`asset`, `price_eur` und `priced_at`; optional sind `source` und `confidence`.
Datumswerte im Format `YYYY-MM-DD` werden als Tagespreis um `00:00:00 UTC`
interpretiert.

`POST /api/v1/prices/import/csv`

Importiert einen validierten Preis-CSV in das Price-Ledger und berechnet die
Pipeline neu. Ungueltige Zeilen verhindern den gesamten Import. Der Endpunkt
ist fuer belegte historische Preisquellen gedacht und schaetzt keine Preise.

`POST /api/v1/prices/import/v1-fx-cache/preview`

Prueft, welche offenen V2-Preisbedarfe aus dem V1-`fx_cache` belegt werden
koennen. V1 speichert Asset/USD und USD/EUR getrennt; V2 importiert daraus nur
dann einen EUR-Preis, wenn fuer den konkreten Asset-Tag ein Asset/USD-Kurs und
ein USD/EUR-Kurs am selben Tag oder davor vorhanden ist.

`POST /api/v1/prices/import/v1-fx-cache`

Importiert die aus V1 belegbaren historischen Preise in das V2-Price-Ledger
und berechnet die Pipeline neu. Der Standardpfad ist
`/root/.local/share/steuerreport/steuerreport.db`. Nicht im V1-Cache
vorhandene Preisbedarfe bleiben offen.

`POST /api/v1/prices/backfill/external`

Migriert die V1-Providerlogik fuer historische Kryptopreise nach V2. Der
Endpunkt baut aus den offenen V2-Preisbedarfen eine Jobliste, nutzt das
Asset-Mapping aus `configs/crypto_price_sources.json`, fragt je nach Provider
CoinGecko und/oder DefiLlama fuer `Asset/USD` ab und kombiniert den Wert mit
`USD/EUR` aus dem V1-`fx_cache`. Mit `dry_run=true` wird nur geplant; mit
`dry_run=false` werden belegte EUR-Preise in das V2-Price-Ledger geschrieben
und die Pipeline neu berechnet. `max_requests` begrenzt externe Abrufe.
Optional kann `assets` als Liste von Asset-Symbolen gesetzt werden, damit
problematische Quellen getrennt von anderen Preisbedarfen verarbeitet werden,
zum Beispiel `["BTTC", "VTHO", "NFT"]`.
Die Konfiguration enthaelt auch die Solana-Sonderassets aus dem
Blockpit-Preflight, unter anderem `IOT`, `ZEUS`, `JUPSOL`, `MANEKI`, `POPCAT`,
`WBTC` und `CBDC`. Eine konfigurierte Quelle bedeutet nur, dass ein externer
Provider technisch bekannt ist; ein steuerlicher Preis gilt erst nach
konkretem historischen Backfill oder manuellem Beleg im Price-Ledger.

`POST /api/v1/prices/backfill/current-portfolio`

Laedt aktuelle EUR-Marktpreise fuer positive Portfolio-Assets. Der Endpoint
nutzt dasselbe Asset-Mapping aus `configs/crypto_price_sources.json`, kann per
`assets` auf einzelne Assets wie `["HNT"]` begrenzt werden und schreibt bei
`dry_run=false` neue Price-Ledger-Eintraege mit Quelle
`coingecko:simple-price:eur`. Solana-Mint-Quellen werden, wenn im Mapping als
`solana:<mint>` hinterlegt, ueber DefiLlama in USD und den aktuellen
USD/EUR-Referenzkurs bewertet. Diese aktuellen Preise gewinnen im
Portfolio-Snapshot gegen alte `derived:event_quote`-Preise, ohne historische
Steuerbewertungen rueckwirkend zu ersetzen.

`GET /api/v1/prices`

Listet Preis-Ledger-Eintraege absteigend nach Bewertungszeitpunkt. Diese
Preise sind die Grundlage fuer Portfolio-, Flow- und Tax-Bewertungen, sofern
kein EUR-Wert direkt aus dem Event kommt.

`GET /api/v1/prices/latest`

Listet pro Asset genau den aktuell wirksamen Preis. Diese Sicht entspricht der
Preisgrundlage, die Portfolio, Flow-Ledger und FIFO-Steuerlauf verwenden.

`GET /api/v1/prices/coverage`

Liefert steuerrelevante Canonical Events, fuer die zum Event-Zeitpunkt keine
historische EUR-Bewertung gefunden wurde. Gruppiert wird nach Asset, Jahr,
Quelle, Event-Typ und Rolle (`asset`, `quote_asset`, `fee_asset`). Diese
Sicht verhindert, dass fehlende Bewertungen nur als `0 EUR` in FIFO- oder
Exportdaten sichtbar werden. Jede Gruppe enthaelt einen stabilen `scope` und
einen `decision_status`; ohne Bearbeitung ist der Status `unreviewed`.

`GET /api/v1/prices/requirements`

Liefert die datumsgenaue Arbeitsliste fuer fehlende historische Preise.
Gruppiert wird nach Asset, Kalendertag, Quelle, Event-Typ und Rolle. Jede
Zeile enthaelt Event-Anzahl, Zeitfenster, Bruttomenge und Beispiel-Event-IDs.
Die Liste ist fuer Preisrecherche und belegte Preisimporte gedacht; sie
erzeugt keine Preise.

`POST /api/v1/prices/coverage/decisions`

Speichert einen Bearbeitungsstatus fuer eine Preis-Luecke als Review Decision
mit `decision_type=price_gap`. Moegliche Statuswerte sind
`price_source_needed`, `manual_price_required`, `parser_data_needed`,
`not_tax_relevant` und `price_added`. Diese Entscheidung ersetzt keinen Preis
und hebt das Export-Gate nicht auf.

`GET /api/v1/export/price-gaps.csv`

Download der offenen Preis-Luecken als CSV-Arbeitsliste. Enthalten sind Scope,
Bearbeitungsstatus, Asset, Jahr, Quelle, Event-Typ, Rolle, Event-Anzahl,
Zeitfenster, Bruttomenge und Beispiel-Event-IDs. Die Datei ist fuer manuelle
Preisrecherche und KI-/Worker-Auftraege gedacht; sie ist kein Preisimport.

`GET /api/v1/export/price-requirements.csv`

Download der datumsgenauen Preis-Anforderungsliste als CSV. Diese Datei ist
die bevorzugte Grundlage fuer manuelle Preisrecherche, weil sie konkrete
Preis-Tage statt nur grobe Jahres-/Quellgruppen ausweist.

`DELETE /api/v1/prices/{price_id}`

Loescht einen einzelnen Preis-Ledger-Eintrag und berechnet die Pipeline neu.
Damit werden nach einer Preiskorrektur Portfolio, Flow-Ledger, FIFO-Steuerlauf
und Review-Gates wieder aus derselben Datenbasis erzeugt.

## Geldfluesse

`POST /api/v1/flows/rebuild`

Erzeugt den Flow-Ledger neu. Erfasst werden Nettofluesse aus Transfer,
Income, Reward, Staking und Mining. Trades bleiben draussen, damit
Handelsvolumen nicht als Geldfluss erscheint.

`GET /api/v1/flows/net`

Liefert aggregierte Kanten fuer Sankey. Fehlende Preise werden separat als
`missing_price_assets` gemeldet und nicht still geschaetzt.
Das Frontend rendert daraus eine Sankey-Ansicht fuer Netto-Euro-Fluesse; die
Tabelle bleibt als pruefbare Datenbasis sichtbar.
Optional kann `year=YYYY` gesetzt werden, um die Kanten auf ein Kalenderjahr zu
begrenzen. Die Antwort enthaelt immer `available_years`, damit die UI die
verfuegbaren Steuerjahre aus dem Flow-Ledger anzeigen kann.

## Review

`GET /api/v1/review/issues`

Listet offene und historische Issues.

`GET /api/v1/review/gates`

Entscheidet, ob Export erlaubt ist. Die Antwort enthaelt offene Issues,
Severity-Zaehler und `blocking_issues_open`, damit UI und Exporte dieselben
Freigabedaten verwenden. High-Issues blockieren.

`POST /api/v1/review/decisions`

Speichert menschliche Entscheidungen mit Begruendung.

`GET /api/v1/review/decisions`

Listet gespeicherte Review-Entscheidungen absteigend nach Erstellung. Diese
Entscheidungen sind Nachweis- und Auditdaten. Sie veraendern die Review-Gates
nicht automatisch; steuerwirksame Aenderungen muessen weiterhin ueber
nachvollziehbare Imports, Preise oder Opening-Balance-Adjustments laufen.
Entscheidungen enthalten `actor`, `source`, `affected_ids`, `evidence_ref` und
freies `payload`, damit manuelle Eingriffe spaeter auditierbar bleiben.

`GET /api/v1/review/decision-suggestions`

Erzeugt nicht-persistente Review-Entscheidungsvorschlaege aus belegten
Preflights. Aktuell werden unter anderem vorgeschlagen:

- IOT-Startbestand durch Wallet-Monatsdaten gedeckt,
- Solscan-IOT-Signaturen per Solana-RPC verifiziert.

Die Antwort nutzt dasselbe Grundschema wie Review-Entscheidungen, ergaenzt um
`suggestion_id`, `confidence` und `auto_persist=false`. Der Endpoint schreibt
nichts in die Datenbank und erzeugt keine Buchung.

`POST /api/v1/review/decision-suggestions/{suggestion_id}/accept`

Speichert einen konkreten Vorschlag bewusst als Review-Decision. Die erzeugte
Decision enthaelt `suggestion_id`, `confidence`, `auto_persist` und
`import_effect` im Payload. Der Endpoint ist idempotent: wurde derselbe
Vorschlag bereits uebernommen, wird die bestehende Decision mit
`status=warning` zurueckgegeben statt ein Duplikat zu erzeugen.

## Steuerlauf

`GET /api/v1/tax-methodology/bmf-compliance-matrix`

Liefert die strenge, read-only BMF-Anforderungsmatrix. Sie trennt
`implementation_status`, `evidence_status` und `strict_ready` je Anforderung
und verweist auf die einschlaegigen Randnummern des BMF-Schreibens vom
6. Maerz 2025. Ein freies Export-Gate oder eine konservative Jahresbeilage
setzen `strict_bmf_ready` nicht automatisch auf `true`.

Harte Matrixbereiche sind insbesondere Quellenvollstaendigkeit,
Einzeltransaktionsspur, walletbezogene Verbrauchsfolge, Transfer-Provenance,
Kurskonsistenz, Reward-/Mining-Dokumentation, Korrekturaudit und
Stichtagsbestaende.

`GET /api/v1/tax-methodology/time-precision-audit`

Liefert den read-only Zeitzonen- und Jahresgrenzen-Audit. Zeitpunkte bleiben
in UTC gespeichert; deutsche Steuerjahre werden mit der IANA-Zeitzone
`Europe/Berlin` inklusive CET/CEST bestimmt. Der Audit listet alle Ereignisse,
deren UTC-Jahr vom Berichtsjahr abweicht, die betroffenen FIFO-Steuerzeilen
und Reward-Anschaffungswerte. Helium-Monatsaggregate mit belegtem
`Period Start (UTC)` werden separat ausgewiesen und verbleiben im
Quellperiodenjahr. `reporting_policy_applied=true` belegt, dass die Regel in
den Jahresreports aktiv ist.

`GET /api/v1/tax/wallet-fifo-preview`

Liefert die read-only Wallet-/Depot-FIFO-Vorschau. Die optionalen Query-
Parameter `year` und `as_of` begrenzen Ergebnis und Ereignismenge; `as_of`
wird als ISO-8601-Zeitpunkt verarbeitet. Versionierte Parallel-Runs waermen
die fingerprintgebundenen Jahres- und Gesamt-Caches dauerhaft vor, damit ein
API-Neustart keinen erneuten Voll-Replay fuer denselben Stichtag erzwingt.

`GET /api/v1/tax/wallet-fifo-internal-transfer-carry`

Liefert den kompakten Drilldown fuer interne Exchange-Umbuchungen und deren
Kostenbasisfortfuehrung. Binance Spot, Simple Earn, Staking und Auto-Invest
bleiben im selben wirtschaftlichen Eigentumspool; echte Bitget-Unterkonten-
Transfers fuehren Lots zwischen den belegten Pools fort. `basis_pending`
bleibt sichtbar, wenn zum Ereigniszeitpunkt keine vollstaendige Vorlotmenge
vorliegt. Der Endpunkt schreibt keine Steuer- oder Ledgerdaten.

`POST /api/v1/tax/wallet-fifo-runs`

Erzeugt einen versionierten, read-only Wallet-/Depot-FIFO-Parallel-Run. Der
Request enthaelt `years`, optional `as_of` und die materielle Delta-Schwelle
`material_delta_threshold_eur`. Ohne `as_of` wird fuer abgeschlossene Jahre
das Ende des hoechsten angeforderten Jahres verwendet. Canonical Events und
globale Vergleichszeilen werden beide bis zu diesem UTC-Zeitpunkt begrenzt.

Der Lauf schreibt keine produktiven `tax_lots`, `tax_lines`, Ledger- oder
Importdaten. Er erzeugt unter `var/wallet_fifo_runs/` stattdessen ein
versioniertes JSON-Manifest sowie gzip-komprimierte CSV-Belege fuer Tax-Lines,
alle erzeugten Lots, offene Lots, Transferketten, unmatched Abgaenge,
Jahres-/Asset-Deltas und die vollstaendige Ereigniszerlegung der globalen-/
Wallet-FIFO-Differenz. `wallet_fifo_all_lots.csv.gz` enthaelt auch vollstaendig
verbrauchte und transferfortgefuehrte Lots und ist damit die vollstaendige
Quelle fuer eine kontrollierte Zieltabellenmigration. Jede neue Wallet-FIFO-
Tax-Line fuehrt neben `lot_id` auch
`acquisition_source_event_id` und `origin_lot_id`, damit der verbrauchte
Anschaffungsvorgang und eine Transferfortfuehrung belegbar bleiben.
`strict_ready` bleibt auch nach der rechnerischen Delta-Erklaerung bis zur
expliziten Methodenabnahme `false`. Die Methode
`wallet_asset_preview_v45_binance_withdrawal_evidence_lot_carry` gruppiert die
Ergebnisse nach deutschem Kalenderjahr, ohne den exakten UTC-Stichtag zu
veraendern. Dokumentierte konservative Mindestbestands-Reconciliations erhalten
einen eigenen Trace-Status und werden nicht als Reward oder externer Deposit
umgedeutet. Dokumentierte Staking-Ruecklaeufe fuehren den Principal-Lot fort;
nur die belegte Mehrmenge erzeugt einen neuen Reward-Lot.
Binance-Withdrawal-Evidence mit Menge `0` wird nur dann als steuerneutraler
Lot-Transfer verarbeitet, wenn TxID, eigene Zieladresse, Asset und On-chain-
Nettomenge exakt passen. Die Binance-Gebuehr wird getrennt aus den Quelllots
verbraucht; der Transfer selbst erzeugt weder Ertrag noch Veraeusserung.

Jeder neue Run erzeugt zusaetzlich
`bitget_strategy_fifo_gap_report.json` und
`bitget_strategy_fifo_gap_disposals.csv.gz`. Diese Belege gruppieren
Bitget-Abgaenge ohne passendes Wallet-Lot nach der belegten vorherigen
`STRATEGY_TRANSFER_IN`-Abrechnung. Ein mit vorhandenen Lots belegter
`STRATEGY_TRANSFER_OUT`-Principal wird von der offenen Strategy-Menge
abgezogen. `quantity_reconciled_basis_pending` bedeutet ausschliesslich:
Settlement-Menge, spaetere Abgangsluecke und Rundungsrest sind geschlossen.
Das vollstaendig gelieferte Bitget-Supportpaket wird mit allen sechs Dateien,
Spalten, Zeilenanzahlen und SHA-256-Werten im Feld `support_package`
ausgewiesen. `Strategy.csv` bindet die vier relevanten Strategien innerhalb
von drei Sekunden an ihre Settlements. Der Anbieterexport enthaelt jedoch
keine Bot-Einzelfills mit Strategy-ID. Anschaffungszeitpunkte und Kostenbasis
bleiben deshalb als Anbieter-Feldluecke offen und sperren weiterhin die
strikte Wallet-FIFO. Weder der Bitget-Wert in
`Amount (USDT)` noch eine Blockpit-Referenzzeile setzt automatisch eine
historische Kostenbasis.

`GET /api/v1/tax/wallet-fifo/bitget-strategy-gaps`

Liefert den Bitget-Strategy-FIFO-Nachweis des neuesten versionierten Runs.
Optional waehlt `run_id` einen bestimmten Lauf. Der Report bindet jede
Settlement- und Abgangszeile an Raw-Object, Import-Batch, Dateihash,
Zeilennummer und Payload-SHA-256. `linked_unmatched_disposals_count` und
`unallocated_unmatched_disposals_count` trennen erklaerte von weiterhin
offenen Mengen. Mengen werden nie ueber verschiedene Assets addiert;
`asset_totals` weist BTC, HNT und SOL getrennt aus.

Eine Blockpit-Bezeichnung `Mining` oder `Reward` fuer eine durch die
Bitget-Originalzeile belegte `STRATEGY_TRANSFER_IN`-Abrechnung wird als
`classification_conflict=true` ausgewiesen. Fuer diese Fremdklassifizierung
bleiben `reward_classification_effect=none` und `tax_line_effect=none`.
Canonical Events, Lots, Tax-Lines, Ledger und Preise werden nicht veraendert.

Die offizielle Bitget-Spot-History ist auf die letzten 90 Tage begrenzt. Fuer
2024 nennt der Report deshalb
`support_package_already_supplied_provider_fill_fields_absent`: Das vom Support
bereitgestellte Paket ist bereits vollstaendig vorhanden, ein heutiger
API-Aufruf kann die darin nicht enthaltenen Bot-Fills aber nicht nachliefern.
`additional_user_export_required=false` verhindert eine weitere falsche
Nachforderung beim Nutzer:

- https://www.bitget.com/api-doc/classic/spot/trade/Get-History-Orders
- https://www.bitget.com/api-doc/uta/trade/Get-Order-History

`GET /api/v1/tax/wallet-fifo/bitget-strategy-gaps.csv`

Liefert dieselben zugeordneten Abgaenge als normale UTF-8-CSV. Optional kann
derselbe `run_id` wie beim JSON-Endpunkt angegeben werden. Die CSV ist fuer
Tabellenpruefung und Weitergabe vorgesehen; der unveraenderliche gzip-Beleg
bleibt zusaetzlich im Run-Manifest erhalten.

`GET /api/v1/tax/wallet-fifo/bitget-strategy-reconstruction`

Liefert die an denselben Wallet-FIFO-Run gebundene konservative
Rekonstruktionsakte fuer die vom Anbieter nicht exportierten Bot-Einzelfills.
Je Strategy-Gruppe werden das durch `Strategy.csv` belegte Erwerbszeitfenster,
die mengenmaessig zugeordneten Abgaenge, anteilige Verkaufserloese in EUR und
die technische Haltefristspanne ausgewiesen. Historische Quote-Preise enthalten
Quelle, Zeitpunkt, Alter und Confidence.

`documented_cost_basis_floor_eur=0` ist nur die konservative
Nullbasis-Sensitivitaet. `documented_cost_basis_ceiling_eur=null` zeigt, dass
aus den gelieferten Feldern keine belastbare Obergrenze abgeleitet werden kann.
Der anteilige Settlement-Zeitwert und das daraus berechnete G/V sind
Plausibilitaetsvergleiche mit
`tax_basis_use=sensitivity_only_not_fifo_cost_basis`. Der Report besitzt immer
`productive_tax_effect=none`, solange eine Strategy-Luecke besteht, und
veraendert weder Lots noch Tax-Lines oder Steuerjahreswerte. Optional bindet
`run_id` einen bestimmten versionierten Lauf.

`GET /api/v1/tax/wallet-fifo/bitget-strategy-basis-decision`

Liefert die hashgebundene Readiness fuer eine ausdrueckliche Behandlung der
Bitget-Provider-Feldluecke. Der Contract prueft Wallet-FIFO-Input-Fingerprint,
Run-/Gap-/Rekonstruktionsbindung, alle sechs Supportdateien, vollstaendigen
Mengenabgleich, EUR-Referenzpreise, Verkaufserloese und eindeutige
Haltedauerbaender. `decision_ready=true` bedeutet nur, dass eine fachliche
Entscheidung dokumentiert werden kann; `strict_ready` bleibt bei einer
Schaetzung immer `false`.

`POST /api/v1/tax/wallet-fifo/bitget-strategy-basis-decision/{run_id}`

Speichert eine Review Decision, die an Run-ID, Input-Fingerprint, Gap-Hash und
Rekonstruktions-Hash gebunden ist. Erlaubte Entscheidungen sind:

- `retain_provider_gap_pending_professional_review`,
- `approve_zero_basis_estimate_for_staging`,
- `approve_settlement_value_proxy_estimate_for_staging`,
- `rejected_requires_rework`.

```json
{
  "decision": "retain_provider_gap_pending_professional_review",
  "rationale": "Die Providerakte ist vollstaendig; bis zur Fachpruefung bleibt die Basis offen.",
  "actor": "user",
  "acknowledge_provider_fill_data_missing": true,
  "acknowledge_estimate_not_observed_transaction": true,
  "acknowledge_consistent_application": true,
  "acknowledge_no_automatic_tax_effect": true,
  "acknowledge_professional_review_before_filing": true
}
```

Die beiden Schaetzmethoden werden ausschliesslich fuer ein spaeteres Staging
markiert. Der POST schreibt weder Canonical Events noch Preise, Lots,
Tax-Lines oder Ledgerdaten und aktiviert keine FIFO-Migration. Identische
Entscheidungen sind idempotent. Ein solcher Review-Entscheid wird wegen seiner
fehlenden Produktivwirkung nicht in den Wallet-FIFO-Input-Fingerprint
eingerechnet; der gebundene Prueflauf bleibt deshalb reproduzierbar. Die aus
den Strategy-Gruppen abgeleiteten Steuerjahre werden im Decision-Payload
gespeichert, damit der Nachweis automatisch im jeweiligen Jahrespaket erscheint.

`GET /api/v1/tax/wallet-fifo/bitget-strategy-reconstruction.csv`

Liefert jede zugeordnete Disposal-Zeile mit Erwerbszeitfenster,
Mindest-/Hoechsthaltedauer, anteiligem Verkaufserloes, Nullbasis-Sensitivitaet
und Settlement-Proxy als UTF-8-CSV. Die gleiche CSV liegt gzip-komprimiert und
SHA-256-gebunden im Wallet-FIFO-Run; das Stichtags-/Zugewinndossier nimmt JSON
und CSV fuer beide FIFO-Stichtage auf.

`GET /api/v1/tax/wallet-fifo/bitget-strategy-review.html`

Oeffnet eine druckbare, menschenlesbare Fachakte statt einer JSON-Antwort.
Sie trennt belegte Mengen, Erwerbszeitfenster, Abgaenge und Erloese klar von
der weiterhin fehlenden exakten Bot-Fill-Kostenbasis. Run-ID, Input-Fingerprint,
Gap-Hash und Rekonstruktions-Hash sind direkt in der Akte sichtbar. Nullbasis
und Settlement-Zeitwert sind ausdruecklich nur Sensitivitaeten ohne produktive
Steuerwirkung. Die Akte zeigt zusaetzlich den aktuellen Status der
Bitget-Basismethodenentscheidung. Optional bindet `run_id` einen bestimmten
Lauf.

`GET /api/v1/tax/wallet-fifo/bitget-strategy-review-package.zip`

Liefert die Fachakte als abgeschlossenes Pruefpaket. Enthalten sind die
druckbare HTML-Datei, Gap- und Rekonstruktions-JSON, die Disposal-CSV, das
vollstaendige Bitget-Supportpaket als verschachteltes ZIP und ein
`manifest.json`. Das Manifest bindet jede Datei mit Groesse und SHA-256 an den
Wallet-FIFO-Run. Bei fehlenden oder veraenderten Supportdateien antwortet die
API mit HTTP 409; es werden keine Steuer- oder Ledgerdaten geschrieben.

`POST /api/v1/tax/wallet-fifo/bitget-strategy-reconstruction/reference-price-backfill`

Prueft ausschliesslich die in der gebundenen Rekonstruktionsakte als fehlend,
abgeleitet oder veraltet markierten USDT/EUR-Tage. Der Default
`execute=false` ist ein Dry-Run. Mit `execute=true` werden additive
`price_ledger`-Zeilen aus dem Frankfurter-v2-Endpoint mit Provider ECB
gespeichert. Vollstaendige Request-URL, Provider-Referenztag, HTTP-Payload und
Response-SHA-256 werden versioniert archiviert. Der Lauf startet keinen
Pipeline-, Steuer- oder FIFO-Rebuild und vergleicht vor und nach dem Import den
Hash von `tax_lots` und `tax_lines`.

```json
{
  "execute": false,
  "timeout_seconds": 20,
  "run_id": "wallet-fifo-..."
}
```

`GET /api/v1/tax/wallet-fifo/bitget-strategy-reconstruction/reference-price-backfill/latest`

Liefert den letzten Dry-Run oder Apply-Beleg inklusive Jobstatus,
Tax-Komponenten-Hash, Evidence-SHA-256 und naechster erforderlicher
Run-Neubindung.

`GET /api/v1/tax/wallet-fifo/bitget-support-package.zip`

Liefert das vollstaendige Bitget-Supportpaket mit den sechs unveraenderten
Original-CSV-Dateien und `bitget_support_manifest.json`. Das Manifest enthaelt
Dateigroesse, Zeilenanzahl, Spalten, Evidence-Rolle und SHA-256. Vor dem
Download werden alle Dateien erneut gegen die gebundenen Hashes geprueft; bei
einer Abweichung antwortet die API mit HTTP 409. Optional waehlt `run_id` den
zugehoerigen versionierten Wallet-FIFO-Lauf.

`GET /api/v1/tax-years/{year}/wallet-fifo-solana-program-settlement-evidence`

Liefert den versionierten, read-only Nachweis fuer native SOL-Rueckfluesse aus
von der eigenen Wallet signierten Programmkonto-Schliessungen. Eine Zeile wird
nur als `owned_program_account_close_rent_return` in Wallet-FIFO aufgeloest,
wenn Event-ID, TXID, Wallet, Asset, Menge und alle Lamport-Summen exakt mit dem
Canonical Event uebereinstimmen. `artifact_integrity_valid` prueft den
semantischen SHA-256 des JSON-Artefakts; `database_binding_valid` prueft die
Bindung an die aktuelle Datenbank. Nur beide gemeinsam koennen
`strict_ready=true` ergeben. Der Nachweis schreibt keine Import-, Ledger-, Lot-
oder Steuerdaten und wird in das Jahresbelegpaket aufgenommen.

`GET /api/v1/tax-years/{year}/wallet-fifo-solana-service-swap-evidence`

Liefert den versionierten, read-only Nachweis fuer eine servicevermittelte
Jupiter-Route von einem eigenen Wallet-Abgang bis zu einer dokumentierten
CEX-Einzahlung. Der Beleg bindet Input-Transfer, SOL-Funding, Route-Signer,
Jupiter-Programm, Swap-Input/-Output, CEX-Deposit-Adresse und Zielmenge an die
Canonical Events. Die Route-Adresse wird dabei ausdruecklich nicht als
Eigenwallet klassifiziert. `evidence_ready=true` bestaetigt die vollstaendige
On-chain-/CEX-Kette. Ob Input-Veraeusserung, Output-Anschaffung und direkte
Servicekosten steuerlich abgebildet sind, zeigt separat `tax_mapping_ready`.
Das Artefakt veraendert keine Imports, Lots, Tax-Lines oder Ledgerdaten und
liegt im Jahresbelegpaket.

`GET /api/v1/tax/service-swap-mappings`

Liefert die SHA- und Event-ID-gebundene Steuerabbildung fuer freigegebene
servicevermittelte Swaps. Der Report trennt den steuerbaren Krypto-zu-Krypto-
Tausch, die Anschaffung des erhaltenen Assets und direkt aus dem eigenen Wallet
bezahlte Kosten. Nur wenn alle Entscheidungsflags wahr sind, wird
`tax_mapping_ready=true`; die Serviceadresse wird dadurch nicht zur Eigenwallet.

`GET /api/v1/tax/pionex-hnt-reconciliation`

Liefert den Pionex-HNT-Bestandsnachweis fuer 2022. Die Pruefung bindet die
Originalexporte per SHA-256, gleicht Detail- und Summenexport aggregiert ab und
erhaelt ausgefuehrte Teilfills auch dann, wenn die Order spaeter den Status
`CANCELED` erhielt. Weil die historische Pionex-API den verbleibenden Zeitraum
nicht mehr bereitstellt, wird die exakt benoetigte Mindestmenge von
`0.16876807 HNT` konservativ mit `0.00 EUR` Kostenbasis angesetzt. Sie wird
weder als Reward noch als externer Zufluss klassifiziert. Daher kann
`reconciliation_ready=true` bei gleichzeitigem `strict_ready=false` und
`missing_primary_acquisition_evidence=true` vorliegen. Der Report ist Bestandteil
des Jahresbelegpakets 2022.

`GET /api/v1/tax/cross-cex-transfer-evidence`

Liefert den SHA-, Event- und Registry-gebundenen Nachweis fuer eigene Transfers
zwischen CEX und Wallets. Jeder Datensatz bindet Withdrawal, Ziel-TxID,
Quell-/Zielhash, Zeitfenster, Nettomenge, Fee und Wallet-FIFO-Lotfortfuehrung.
Nur wenn alle Entscheidungsflags wahr sind, gilt `ready=true`. Der Report kann
mehrere Jahre enthalten; das Jahresbelegpaket legt nur die Datensaetze des
angeforderten Jahres bei.

`GET /api/v1/tax/fairspot-staking-reconciliation`

Liefert den HNT-Principal-/Reward-Abgleich der historischen Fairspot-
Stakingroute. Main-Wallet-Ausgaenge und Ruecklaeufe werden gegen einen
unabhaengigen, SHA-gebundenen Fairspot-CSV-Export abgeglichen. Der Principal
bleibt ein steuerneutraler Transferpfad mit fortgefuehrter FIFO; nur die
Ruecklauf-Mehrmenge wird als Reward mit Tax-Lot bewertet. Die Fairspot-Adresse
bleibt aus dem aktuellen Portfolio ausgeschlossen. Report und Quell-CSV liegen
im Jahresbelegpaket 2022.

`GET /api/v1/tax/solana-staking-position-reconciliation`

Liefert den Event-, Programm- und SHA-gebundenen Nachweis fuer die dokumentierte
SHARK-Stakingposition. Der Report trennt Principal und Reward, prueft die
Mengenformel, deterministische Event-IDs, fortgefuehrte FIFO-Kostenbasis,
Reward-Tax-Lot samt Tagespreis sowie den nativen SOL-Rent-Ruecklauf per exakter
Lamport-Reconciliation. Alle Flags muessen fuer `strict_ready=true` wahr sein.
Der Nachweis liegt im Jahresbelegpaket 2026 und im versionierten
Stichtag-/Zugewinndossier.

`GET /api/v1/export/tax-years/{year}/evidence-package.zip`

Erzeugt das vollstaendige Jahresbelegpaket. Ein fingerprintgebundener
Disk-Cache vermeidet wiederholte FIFO-, BMF- und Belegberechnungen, solange
Datenbank, Steuer-/FIFO-Code, Quellenregistry und Governance-Artefakte
unveraendert sind. Der Response-Header `X-Steuerreport-Cache` meldet `miss`
beim Neuaufbau und `hit` bei einem validen Cache-Treffer. Die ZIP-Datei fuehrt
Groesse und SHA-256 jeder enthaltenen Nachweisdatei im Jahresmanifest.

## Revisionssicherer Abgabestand

`GET /api/v1/tax-filing-snapshots?year=2025`

Liefert das append-only Register archivierter Jahrespakete. `reference`
bedeutet nur, dass ein historischer Berechnungsstand gesichert wurde;
`submitted` wird ausschliesslich nach ausdruecklicher Nutzerbestaetigung mit
tatsaechlichem Uebermittlungszeitpunkt erzeugt. Ein Altstand wird nie
ueberschrieben. ZIP, Jahresmanifest und jede darin manifestierte Datei sind
ueber SHA-256 gebunden; `integrity_status` ist vor jeder fachlichen Verwendung
auszuwerten.

`POST /api/v1/tax-years/{year}/filing-snapshots`

Ohne `source_snapshot_id` erzeugt und archiviert der Endpunkt das aktuelle
Jahresbelegpaket. Mit `source_snapshot_id` wird exakt das bereits archivierte
Paket als neue Revision referenziert. Fuer `state=submitted` sind
`submitted_at` und der exakte Bestaetigungstext
`ICH BESTAETIGE DIE TATSAECHLICHE ABGABE` zwingend. `filing_kind` trennt
`original` und `correction`. Der Aufruf schreibt weder Imports noch Preise,
Ledger, FIFO-Lots oder Tax-Lines.

`POST /api/v1/tax-filing-snapshots/{snapshot_id}/usage-confirmation`

Dokumentiert append-only, dass ein hashverifiziertes Referenzpaket nach
ausdruecklicher Nutzererklaerung als Grundlage einer Steuererklaerung verwendet
wurde, obwohl der tatsaechliche ELSTER-Uebermittlungszeitpunkt noch nicht
vorliegt. Der Request enthaelt `statement`, `actor` und `source`. Der Endpunkt
veraendert weder das Paket noch seinen Zustand und erzeugt insbesondere kein
erfundenes `submitted_at`. Wiederholte identische oder weitere Aufrufe bleiben
idempotent beim ersten Nutzungsereignis. Ein fehlender oder hashabweichender
Archivinhalt blockiert die Bestaetigung.

`GET /api/v1/tax-years/{year}/filing-snapshot-comparison`

Vergleicht vorrangig die neueste bestaetigte Abgabe, danach ein ausdruecklich
als verwendet bestaetigtes Referenzpaket und erst sonst die neueste reine
Referenz mit der aktuellen Jahresberechnung. Private Veraeusserungen,
Rewards/Mining/Staking und Derivate bleiben getrennte deklarationsrelevante
Kategorien. Erloese, Anschaffungskosten und steuerfreie Veraeusserungen werden
als Nachweiswerte separat ausgewiesen. `amendment_review_required=true` ist
eine Korrekturpruefung, keine automatische rechtliche Feststellung und keine
automatische Aenderung von Steuerdaten.

`submission_timestamp_required=true` kennzeichnet eine bestaetigte
Paketnutzung ohne belegten ELSTER-Zeitpunkt. `baseline_selection` lautet in
diesem Fall `confirmed_used_reference`. Dieser Zustand aktiviert bei
deklarationsrelevanten Deltas die Korrekturpruefung, behauptet aber noch keine
vollstaendig verifizierte Uebermittlung.

`GET /api/v1/tax-years/{year}/filing-snapshot-comparison.html`

Liefert dieselbe Korrekturpruefungsakte als lesbare, druckbare Webseite.
`GET /api/v1/export/tax-years/{year}/filing-snapshot-comparison.csv` liefert
die Deltas verlustfrei als CSV.

`GET /api/v1/tax-filing-snapshots/{snapshot_id}/package.zip`

Prueft den Paket-Hash erneut und liefert nur bei intakter SHA-256-Bindung das
archivierte ZIP. Bei fehlender oder veraenderter Datei antwortet der Endpunkt
mit HTTP `409` statt einen scheinbar gueltigen Beleg auszugeben.

### Steuerjahr-Auditvergleich

`GET /api/v1/tax-years/{year}/filing-snapshots`

Ist die jahresspezifische Aliasroute fuer das append-only Snapshot-Register.
Sie liest ausschliesslich den vorhandenen Registerstand.

`GET /api/v1/tax-years/{year}/filing-audit-report`

Vergleicht den hashverifizierten Referenzstand mit der aktuellen V2-Auswertung
auf Einzelpositions- und Aggregatebene. Der Report bindet Snapshot-ID,
Paket-/Manifest-SHA-256, UTC- und Europe/Berlin-Zeitstempel,
Software-/Methodenversion, Datenbank-/Runtime-Fingerprint, Quellen- und
Importdatei-Hashes, Zeilennummern, FIFO-Lots sowie die Ursachenklassifikation.
Unbekannte Ursachen erhalten immer eine gesonderte Erklaerung und bleiben
reviewpflichtig. Der Status `reconciliation_failed` wird gesetzt, sobald die
Einzelpositionen nicht exakt auf eine der sechs geforderten Summen ueberleiten.

Der Report ruft read-only die Vergleichs-, Snapshot-, Methodik-, Treiber-,
Umsatz- und drei Gain-Evidence-Routen ab. Handels-/Swapvolumen,
tatsaechliche EUR-Einzahlungen, EUR-Auszahlungen, steuerliche Ergebnisse und
interne Transfers werden getrennt ausgewiesen. Handelsvolumen wird nie als
Einkommen oder Auszahlung bezeichnet. Es wird keine Datenbankzeile, Tax-Line,
FIFO-Zuordnung oder steuerliche Korrekturentscheidung veraendert.

Der Auditvertrag `tax-filing-audit-v2` fuehrt zusaetzlich eine
`source_reconciliation` ein. Primaere Quellen sind derzeit Binance- und
Solana-/Helium-Evidenz; Blockpit ist ausschliesslich
`aggregator_mirror`. Ein Blockpit-Transfer wird nur dann einer primaeren
Gegenbuchung zugeordnet, wenn Transaktions-ID, Asset und Gegenmenge exakt
uebereinstimmen. Beide Belege bleiben erhalten, bilden aber nur eine logische
Transfergruppe und keinen zweiten steuerpflichtigen Vorgang. Nicht gematchte
Blockpit-Steuer- und Derivatepositionen erhalten
`source_validation_status=unmatched_review` und
`tax_inclusion_status=pending_review`; sie werden nicht als fachlich bestaetigt
freigegeben. Die Deltazeilen enthalten dafuer Quellenrolle,
Gegenereignis-IDs, logische Transfergruppen-ID und den Steuerstatus.

Der Abgleich prueft zusaetzlich primaere Quellen direkt gegeneinander. Binance-
und Solana/RPC-Transferereignisse mit identischer Transaktions-ID, identischem
Asset und exakt entgegengesetzter Menge werden als ein internes Transferereignis
markiert. Sie werden nicht als zwei unabhaengige Zu- oder Abgaenge bewertet;
die beiden Rohbelege bleiben jedoch separat nachvollziehbar.

Die Quellenpruefung ist Bestandteil des aktuellen Eingabefingerprints. Auch eine
Aenderung an reinen Transfer-/Quellenbelegen wird dadurch als neue
Auswertungsgrundlage erkannt. Solscan-/RPC- bzw. Binance-Gegenbelege werden
nicht als zusaetzliche Transaktionen gezaehlt, sondern als Belege derselben
logischen Ereignisgruppe gefuehrt.

`GET /api/v1/tax-years/{year}/filing-audit-report.json` und
`GET /api/v1/tax-years/{year}/filing-audit-report.md`

Liefern die content-addressed Auditdateien. Beide Dateien werden unter einem
aus dem stabilen Vergleichsinhalt abgeleiteten Report-ID-Pfad einmalig mit
Schreibschutz erzeugt. Ein erneuter Lauf mit unveraenderten Eingaben verwendet
denselben Report-ID-/Inhaltsfingerprint und ueberschreibt kein Artefakt. Die
JSON-Datei enthaelt eine leere menschliche Freigabeliste sowie
`human_approvals_required=true`; wesentliche Aenderungen bleiben manuell zu
pruefen.

`GET /api/v1/tax/wallet-fifo-runs/latest`

Liefert den letzten versionierten Parallel-Run oder `null`, wenn noch kein Lauf
vorliegt. Der `input_fingerprint` bindet den Lauf an Canonical Events,
Tax-Lines, Rohbelege, Review-Entscheidungen, Preise, Settings, Schema und
Stichtag. Seit `wallet_fifo_input_v2_semantic` werden zufaellige technische
UUIDs von Tax-Lots, Tax-Lines, Import-Batches und Review-Zeilen nicht mehr in
den Fingerprint aufgenommen. Fachlich identische FIFO-Rebuilds machen einen
Lauf daher nicht faelschlich veraltet. `component_sha256` weist die Hashes der
einzelnen Eingabebereiche aus; `semantic_sha256` erlaubt den Vergleich
fachlich gleicher Laeufe.
`method_delta_explanation_status` und die zugehoerigen Gruppen-Zaehler zeigen,
ob die Abweichung bereits als Pool-Reihenfolge erklaert ist oder noch eine
Ereignis-/Mengenluecke enthaelt.

Seit `report_schema_version=wallet_fifo_run_v2_provider_basis_classification`
wird `unmatched_count` in zwei beweiskraeftigere Teilmengen zerlegt:

- `provider_basis_gap_count`: Der Abgang ist mengenmaessig vollstaendig einem
  belegten Provider-Settlement zugeordnet; es fehlt ausschliesslich die vom
  Anbieter nicht exportierte Einzelfill-Kostenbasis.
- `unexplained_unmatched_count`: Weder ein passendes Wallet-Lot noch ein
  vollstaendig mengenreconciliertes Provider-Settlement liegt vor.

Beide Klassen bleiben fuer die strenge FIFO-Freigabe blockierend. Die erste
Klasse darf aber weder als unbekannte Wallet-Herkunft noch als Aufforderung zu
weiteren, nachweislich nicht verfuegbaren Nutzerexporten dargestellt werden.
Die produktive globale FIFO und vorhandene Steuerwerte werden dadurch nicht
veraendert.

`GET /api/v1/tax/wallet-fifo-runs/latest/method-acceptance`

Liefert die aktuelle, read-only Methodenabnahmeakte des neuesten Runs. Die
Antwort prueft die Bindung an den aktuellen semantischen Input-Fingerprint,
den Methodendifferenz-Report, alle Jahre, klassifizierte Abgaenge, offene
Zuflussherkunft, Transfer-/Anschaffungskostenbelege sowie Ereignis-, Mengen-
und Erlosparitaet. Die Felder `provider_basis_gap_count` und
`unexplained_unmatched_count` trennen mengenreconciliierte Provider-Luecken
von wirklich unbekannten Abgaengen. Die drei Gruppenfelder
`provider_basis_event_set_gap_groups_count`,
`provider_basis_quantity_gap_groups_count` und
`unexplained_method_gap_groups_count` binden dieselbe Trennung an den
Methodendifferenz-Report. Eine Provider-Luecke bleibt ueber
`provider_basis_complete` blockierend, wird aber nicht mehr als unbekannte
Wallet-Transaktion bezeichnet. `decision_ready=true` bedeutet nur, dass eine dokumentierte
fachliche Entscheidung moeglich ist. `strict_ready=true` wird erst dann wahr,
wenn eine Freigabe gespeichert und die Zielmethode kontrolliert produktiv
aktiviert wurde.

`GET /api/v1/tax/wallet-fifo-runs/latest/method-delta-explanation`

Liefert die read-only Ereignis- und Lot-Erklaerung des letzten Parallel-Runs.
Optionale Query-Parameter sind `year`, `asset` und `event_limit` (1 bis 50).
Je Jahr/Asset werden Ereignis-, Mengen- und Erlosparitaet separat von der
Cost-Basis-Differenz ausgewiesen. Der Treiber
`pool_fifo_cost_basis_reordering` bedeutet: dieselbe Veraeusserung mit derselben
Menge und demselben Erlos verbraucht in der Wallet-/Depot-Methode andere
historische Anschaffungslots. Das ist kein zusaetzlicher Umsatz.

Die Erlos-Reconciliation bindet den Canonical Event ein. Sie weist
`expected_proceeds_delta_eur`, `unexplained_proceeds_delta_eur`,
`proceeds_delta_reconciled`, Quote-Asset-Gebuehr und angewandtes Netting je
Methode aus. `proceeds_delta_groups_count` ist das rohe Erlosdelta ueber
0,01 EUR; nur `unexplained_proceeds_delta_groups_count` bleibt nach Gebuehren-
und Mengenreconciliation ein Bewertungsreview. Ein mengenproportional voll
erklaertes Delta verwendet den Treiber `quantity_proceeds_allocation`.

`GET /api/v1/tax/wallet-fifo-runs/{run_id}/method-delta-explanation`

Liefert denselben Erklaerreport fuer einen bestimmten versionierten Lauf. Der
Report ist an dessen `input_fingerprint_digest` und `semantic_sha256` gebunden.
Die vollstaendige Ereignisliste bleibt als
`wallet_fifo_method_delta_events.csv.gz` im Run erhalten; die JSON-Antwort
liefert je Gruppe die groessten 1 bis 50 Ereignisse.

`GET /api/v1/tax/wallet-fifo-runs/{run_id}`

Liefert einen bestimmten versionierten Run. Das wird insbesondere vom
Stichtagsdossier verwendet, damit beide FIFO-Zeitpunkte dauerhaft aufrufbar
bleiben, auch wenn spaeter weitere Runs erzeugt werden.

`GET /api/v1/tax/wallet-fifo-runs/{run_id}/method-acceptance`

Liefert die Methodenabnahmeakte fuer genau den angegebenen Run. Ein veralteter
Fingerprint, ein fehlender oder abweichender Methodendifferenz-Hash und jeder
offene Daten-/Belegcheck bleiben als Blocker sichtbar.

`POST /api/v1/tax/wallet-fifo-runs/{run_id}/method-acceptance`

Speichert eine explizite, an Run- und Report-Hashes gebundene
Methodenentscheidung als Review-Entscheidung. Erlaubte Entscheidungen sind
`approved_for_controlled_migration`,
`retain_global_fifo_pending_professional_review` und
`rejected_requires_rework`. Der Request verlangt eine Begruendung, einen
Akteur und drei ausdrueckliche Bestaetigungen zu materiellen Steuerdeltas,
konsistenter Methodenanwendung und fehlender automatischer Aktivierung. Eine
Freigabe ist bei offenen Abnahmechecks nicht erlaubt. Wiederholte identische
Entscheidungen sind idempotent. Der Endpunkt schreibt keine Tax-Lots,
Tax-Lines, Ledger-, Preis- oder Importdaten und schaltet die produktive
FIFO-Methode nicht um.

`POST /api/v1/tax/wallet-fifo-migrations/rehearsals`

Erzeugt eine gebundene, read-only Migrationsprobe fuer einen expliziten
`run_id` oder den neuesten Wallet-FIFO-Lauf. `provider_basis_gap_count` und
`unexplained_unmatched_count` uebernehmen die beweisgebundene Klassifikation
des Runs. Die Checks `no_unexplained_wallet_fifo_unmatched` und
`provider_basis_complete` halten unbekannte Datenluecken und fehlende
Provider-Kostenbasen getrennt; beide werden niemals automatisch mit
erfundenen Anschaffungskosten geschlossen. Der Service spielt alle Lots und
Tax-Lines in eine temporaere DuckDB mit dem erweiterten Produktivschema ein,
liest sie wieder aus und prueft Eindeutigkeit, Lot-Referenzen, Mengen,
Gewinnarithmetik, Methodenmetadaten und Jahresparitaet. Vor und nach der Probe
wird der produktive semantische Input-Fingerprint verglichen. Die temporaere
Datenbank wird automatisch geloescht; `production_write_performed` bleibt
`false` und die produktive FIFO-Methode wird nicht aktiviert.

Die Stati trennen Technik und Governance:

- `blocked`: mindestens ein technischer Check ist offen.
- `ready_for_method_decision`: Staging ist technisch exakt, aber eine an den
  Run gebundene Freigabe fehlt.
- `ready_for_controlled_migration`: Technik und explizite Freigabe sind
  vorhanden; es wurde weiterhin nichts produktiv geschrieben.
- `already_active`: die Zielmethode ist laut Methodenakte bereits aktiv.

`GET /api/v1/tax/wallet-fifo-migrations/rehearsals/latest`

Liefert die letzte Migrationsprobe oder `null`. Das Cockpit verwendet diesen
Endpunkt fuer den sichtbaren Technik-, Entscheidungs- und Schreibstatus.

`GET /api/v1/tax/wallet-fifo-migrations/rehearsals/{rehearsal_id}`

Liefert eine bestimmte versionierte Migrationsprobe. Freie Dateipfade werden
nicht akzeptiert.

`GET /api/v1/tax/wallet-fifo-migrations/apply-readiness`

Liefert das strikt read-only Apply-Gate. Optionale Query-Parameter sind
`run_id` und `rehearsal_id`; ohne sie werden die neuesten Artefakte verwendet.
Geprueft werden aktueller Input-Fingerprint, vollstaendiger All-Lots-Beleg,
Run-/Rehearsal-Bindung, technische Staging-Checks, explizite und gebundene
Methodenfreigabe, atomarer Tabellentausch, Wallet-FIFO-Folge-Rebuild sowie
Schreibbarkeit und freie Kapazitaet des ausgelagerten Backup-Ziels. Der Status
ist `blocked`, `ready_for_controlled_apply` oder `already_active`. Der GET-
Aufruf erzeugt weder Backup noch Steuer- oder Methodendaten.

`POST /api/v1/tax/wallet-fifo-migrations/apply`

Fuehrt den kontrollierten Produktivwechsel nur aus, wenn alle Apply-Gates
bestehen. Der Request bindet `run_id`, `rehearsal_id`, Rehearsal-SHA-256 und
`decision_id` und verlangt `execute=true`, die Aktivierungsphrase
`WALLET_DEPOT_FIFO_V1_AKTIVIEREN` sowie drei ausdrueckliche Bestaetigungen.
Unmittelbar vor dem Schreibvorgang werden Fingerprint und Gates unter einem
exklusiven Store-Lock erneut geprueft. Danach erzeugt und verifiziert der
Service eine bytegleiche DuckDB-Sicherung. Lots, Tax-Lines, Run-Summary und
unmatched Abgaenge werden in einer einzigen Transaktion ersetzt. Ein fehlender
oder veralteter Nachweis fuehrt zu HTTP 422, bevor produktiv geschrieben wird.

Der Apply ist idempotent. Bei bereits aktiver Zielmethode und identischer
Run-/Rehearsal-/Decision-Bindung wird `already_active` geliefert und kein
zweites Backup erzeugt. Es gibt absichtlich keinen allgemeinen
Aktivierungsschalter im Frontend.

`GET /api/v1/tax/wallet-fifo-migrations/applies/latest`

Liefert das letzte versionierte Apply-Artefakt oder `null`. Das Artefakt
enthaelt Backup-Pfad, Groesse und SHA-256, gebundene IDs, Zielmengen,
Jahresparitaet und den nach dem Apply erneut geprueften Methodenstatus.

`GET /api/v1/tax/wallet-fifo-runs/{run_id}/evidence/{filename}`

Laedt eine im Run-Manifest freigegebene gzip-CSV- oder JSON-Belegdatei. Freie
Pfade oder nicht bekannte Dateinamen werden nicht akzeptiert. Zu den
freigegebenen Methodendifferenz-Belegen gehoeren
`wallet_fifo_method_delta_events.csv.gz` und
`wallet_fifo_method_delta_explanation.json`.

`POST /api/v1/tax/fifo/rebuild`

Erzeugt FIFO-Lots und steuerliche Ergebniszeilen aus Canonical Trade Events.
Der letzte `tax_run_summary.fifo_method` bestimmt die produktive Methode. Vor
einer Aktivierung bleibt das globale Asset-FIFO aktiv; nach einem kontrollierten
Apply dispatcht derselbe Endpunkt dauerhaft auf Wallet-/Depot-FIFO. Ein neuer
Wallet-FIFO-Rebuild mit unmatched Abgaengen wird vor dem Tabellentausch
abgebrochen. Jeder Tabellentausch ist transaktional und prueft Zeilenzahlen,
Lot-Referenzen und Methodenmetadaten vor dem Commit.
Positive Trade-Mengen erzeugen Lots, negative Trade-Mengen verbrauchen FIFO.
EUR-Werte kommen aus `quote_asset=EUR` und `quote_quantity` oder ersatzweise aus
dem Price-Ledger.
Gebuehren im erworbenen Asset reduzieren die tatsaechlich erhaltene Lot-Menge,
ohne die volle Anschaffungsausgabe als Cost Basis zu kuerzen. Gebuehren im bei
einer Veraeusserung erhaltenen Quote-Asset reduzieren Erlos und erhaltene
Quote-Lot-Menge. Globale FIFO und Wallet-/Depot-FIFO verwenden damit dieselbe
Netto-Logik; Backend und Datenbank behalten volle Decimal-Genauigkeit.
Bei Crypto-zu-Crypto-Kaeufen kann die nicht-stabile Quote-Seite ebenfalls als
Veraeusserung erfasst werden, wenn fuer das Quote-Asset bereits ausreichende
FIFO-Lots vorhanden sind. Stablecoin-Quote-Seiten bleiben im MVP deaktiviert,
damit unvollstaendige historische Startbestaende keinen Exportblocker erzeugen.

`GET /api/v1/tax/lines`

Listet steuerliche Ergebniszeilen mit Anschaffungskosten, Erloes,
Gewinn/Verlust und Haltedauer. Die rueckwaertskompatiblen Metadaten
`pool_id`, `acquisition_source_event_id`, `origin_lot_id` und `fifo_method`
weisen bei Wallet-/Depot-FIFO den Pool und die fortgefuehrte Herkunft aus.

`GET /api/v1/tax/lots`

Listet FIFO-Lots aus dem letzten Steuerlauf mit Anschaffungszeitpunkt,
Gesamtmenge, Restmenge und Kostenbasis. `pool_id`, `origin_lot_id` und
`fifo_method` sind fuer eine methodengebundene Wallet-/Depot-Persistenz
vorbereitet. Alte Zeilen ohne gespeicherten Methodenwert werden beim Lesen
konservativ als `global_asset_with_wallet_fifo_evidence_overlay_v1`
interpretiert.

`GET /api/v1/tax/summary`

Liefert den letzten FIFO-Lauf mit Tax-Line-Anzahl, unmatched Abgaengen und
Run-ID. Neue Laeufe fuehren zusaetzlich `fifo_method` und den optionalen
`input_fingerprint_digest`. Das Frontend nutzt diese Daten im Steuerlauf-Tab.

`GET /api/v1/tax-years/{year}/asset-fifo-drilldown?asset=TRUMP&limit=200`

Liefert fuer ein Asset und Steuerjahr die vorhandene FIFO-Belegkette aus
`tax_lines`, `tax_lots`, `canonical_events`, `raw_objects` und
`raw_import_batches`. Der Endpunkt ist read-only, berechnet FIFO nicht neu und
veraendert keine Steuerdaten. Er zeigt je Tax-Line Erwerb, Veraeusserung,
Haltefrist, Anschaffungskosten, Veraeusserungserloes, Gewinn/Verlust sowie
Rohimport-Datei/Zeile fuer Erwerbs- und Disposal-Event.

Wichtige Felder:

- `asset`, `year`, `lines_count`
- `taxable_gain_loss_eur`, `tax_free_gain_loss_eur`, `gain_loss_eur`
- `disposal_proceeds_eur`, `acquisition_cost_eur`
- `quote_asset_occurrences`
- `lines[].acquisition_event`, `lines[].disposal_event`
- `lines[].acquisition_raw`, `lines[].disposal_raw`

`GET /api/v1/tax-years/{year}/asset-fifo-plausibility?limit=100&min_abs_gain_eur=100`

Scannt ein komplettes Steuerjahr ueber alle Assets. Der Endpunkt vergleicht je
Asset das direkte FIFO-Ergebnis mit Tax-Lines, in denen dasselbe Asset nur als
Erwerbs-, Veraeusserungs- oder Quote-Bein vorkommt. Dadurch werden
Quote-/Stablecoin-Effekte sichtbar, bei denen ein Gewinn nicht auf dem
Asset-Namen selbst, sondern auf einem Gegenwaehrungs-FIFO-Bein erscheint.

Wichtige Felder:

- `rows[].asset`, `rows[].risk_level`
- `rows[].direct_gain_loss_eur`, `rows[].direct_tax_lines_count`
- `rows[].linked_gain_loss_eur`, `rows[].linked_tax_lines_count`
- `rows[].total_related_gain_loss_eur`
- `rows[].hidden_quote_gain_loss_eur`
- `rows[].reasons`, `rows[].drilldown_endpoint`

`GET /api/v1/tax-years/{year}/asset-fifo-correction-review?limit=100&min_abs_gain_eur=100`

Verdichtet den Plausibilitaetsreport zu einer Korrektur-/Belegpruefung je
Asset. Der Endpunkt ist read-only und unterscheidet, ob ein Wert nur in der
Darstellung/Attribution erklaert werden muss oder ob nach Rohbelegpruefung eine
Normalizer-/FIFO-Neubewertung moeglich ist.

Wichtige Felder:

- `rows[].recommended_action`
- `rows[].tax_sum_impact`
- `rows[].related_raw_evidence_count`
- `rows[].related_missing_raw_evidence_count`
- `rows[].conclusion`, `rows[].next_step`
- `possible_recalculation_assets_count`
- `attribution_review_assets_count`

## Derivate

`POST /api/v1/derivatives/rebuild`

Erzeugt den Derivate-Lauf aus Canonical Events mit `event_type=derivative`.
Der MVP bewertet belegte Futures-/Derivate-Cashflows zum historischen EUR-Preis
des Event-Assets und speichert daraus Derivate-Zeilen.

`GET /api/v1/derivatives/lines`

Listet Derivate-Zeilen mit Event, Quelle, Asset, Menge, EUR-Preis,
EUR-Ergebnis und Preisquelle.

`GET /api/v1/derivatives/summary`

Liefert Anzahl Derivate-Zeilen, aggregiertes EUR-Ergebnis und fehlende
EUR-Bewertungen. Fehlende Derivate-Preise erzeugen ein blockierendes
Review-Issue `derivative_missing_prices`.

## Pipeline und Demo

`POST /api/v1/pipeline/rebuild`

Fuehrt die Kernpipeline aus: Normalisierung, Balance-Ledger, Flow-Ledger,
FIFO-Steuerlauf, Derivate-Lauf und Review-Gate.

`POST /api/v1/demo/seed`

Laedt kleine Demo-Daten, setzt Demo-Preise und fuehrt die Pipeline aus. Dieser
Endpunkt ist fuer UI- und Smoke-Tests gedacht, nicht fuer produktive Daten.

## Export

`POST /api/v1/export/pdf`

Erzeugt PDF-Pakete. Das 100-Seiten-Limit je Datei ist verbindlich. Ein Export
mit 230 Seiten muss in 100/100/30 Seiten zerfallen. Blockierende Review-Gates
erzeugen nur ein blockiertes Paket mit `page_count=0`.

`GET /api/v1/export/packages`

Listet erzeugte oder blockierte Exportpakete mit Seitenzahl, Status und
Blockierungsgrund.

`GET /api/v1/export/packages/{package_id}/download.pdf`

Laedt ein erzeugtes PDF-Exportpaket als Datei herunter. Blockierte oder
unbekannte Pakete liefern `status=error` und werden nicht als PDF ausgeliefert.

`DELETE /api/v1/export/packages/{package_id}`

Loescht ein erzeugtes oder blockiertes Exportpaket aus der Export-Historie.
Wenn das Paket nicht existiert, kommt `status=warning`.

`GET /api/v1/export/readiness`

Liefert eine kompakte Export-Freigabe mit Review-Gate, V1/V2-Parity-Gate,
Anzahl offener Issues, Tax-Line-Stand, Derivate-Stand, unmatched FIFO-Abgaengen
und hartem PDF-Seitenlimit. `allow_export` ist nur `true`, wenn Review-Gate und
Parity-Release-Gate beide frei sind.

Wichtige Felder:

- `review_issues_current_open`, `review_issues_historical_open`,
  `review_blocking_issues_open`
- `parity_release_ready`, `parity_unresolved_groups`,
  `parity_blocking_groups`, `parity_blocking_difference_eur`,
  `parity_accepted_groups`, `parity_groups_total`
- `tax_lines_count`, `derivative_lines_count`, `unmatched_disposals`
- `max_pdf_pages_per_file`

`POST /api/v1/export/audit`

Erzeugt maschinenlesbares Audit-Paket.

`POST /api/v1/export/elster-prep`

Erzeugt ELSTER-nahe Vorbereitungsdaten, keine direkte ERiC-Uebertragung.

## Review-Aufgaben

`GET /api/v1/review/tasks?include_reconciliation=false`

Liefert eine gefuehrte, read-only Aufgabenliste aus Review-Gate,
Preisdeckung, Price-Quality-Buckets und Review-Entscheidungsvorschlaegen.
Optional kann mit `include_reconciliation=true` auch Portfolio-Reconciliation
geladen werden. Die Aufgaben priorisieren FIFO-, Preis-, Import-, Wallet-,
Preisqualitaets- und Live/Ledger-Klaerfaelle. Der Endpunkt schreibt keine
Steuerdaten und ersetzt keine Review-Entscheidung; er verweist auf bestehende
Detail-/Aktionspfade.

Wichtige Felder:

- `open_tasks`, `blocking_tasks`, `fifo_relevant_tasks`, `evidence_tasks`
- `tasks[].priority`, `tasks[].category`, `tasks[].blocks_export`
- `tasks[].scope`, `tasks[].action_path`, `tasks[].evidence_refs`
- `tasks[].asset`, `tasks[].source_group`, `tasks[].value_eur`

Preisqualitaets-Bucket-Aufgaben haben `source=price_quality_manual_review`,
`scope=price_quality_bucket:<bucket>` und verweisen direkt auf die jeweiligen
Bucket-Endpunkte.
Quellenabgleich-Aufgaben haben `source=source_reconciliation`,
`scope=source_reconciliation:<source_id>` und verweisen direkt auf
`/api/v1/sources/{source_id}/reconciliation`. Sie sind gefuehrte
Pruefaufgaben fuer API-Live-vs-Ledger-Deltas und schreiben keine
Steuerdaten.

## Admin

`GET /api/v1/admin/status`

Liefert Datenbankstatus, Anzahl Settings und ob lokale oder externe KI aktiv
ist.

## Lokale KI

`GET /api/v1/ai/local-asset-fifo-correction-review`

Liefert den Status des letzten lokalen Asset-FIFO-Korrekturreviews aus
`var/local_ai_prework/asset_fifo_correction_review_20260620`. Der Endpunkt ist
read-only und startet keinen KI-Lauf.

Wichtige Felder:

- `status`, `llm_status`, `latest_run_id`
- `candidates_count`
- `years[].possible_recalculation_assets_count`
- `years[].attribution_review_assets_count`
- `candidates[].asset`
- `summary_md`, `local_ai_review_md`

`GET /api/v1/ai/local-asset-fifo-correction-review/artifacts/{artifact}`

Laedt ein Artefakt des letzten lokalen Asset-FIFO-Korrekturreviews. Erlaubte
Artefakte:

- `summary`
- `review`
- `findings`
- `run-status`

`GET /api/v1/admin/settings`

Listet alle gespeicherten Admin-Settings.

`PATCH /api/v1/admin/settings`

Schreibt genau ein Setting. `value_json` muss gueltiges JSON sein. Ungueltiges
JSON liefert `status=error` mit `invalid_setting_json`.

`DELETE /api/v1/admin/settings/{key}`

Loescht ein Admin-Setting. Wenn der Key nicht existiert, kommt
`status=warning`.

`GET /api/v1/admin/database`

`POST /api/v1/admin/snapshots`

## KI

`POST /api/v1/ai/tasks`

Erzeugt eine KI-Aufgabe. Lokale Aufgaben werden als `queued` gespeichert.
Externe Aufgaben schlagen fehl, solange `ai.external.enabled` nicht im Admin
aktiviert wurde.
Die UI kann Typ, Prompt und `allow_external` setzen; Ausfuehrung erfolgt nicht
implizit im Request.

`GET /api/v1/ai/tasks`

Listet KI-Aufgaben.

`DELETE /api/v1/ai/tasks/{task_id}`

Loescht eine KI-Aufgabe aus der Aufgabenliste. Wenn die Aufgabe nicht existiert,
kommt `status=warning`.

Externe KI-Aufgaben muessen explizit ueber Admin aktiviert sein.

## Audit und ELSTER-Prep

`POST /api/v1/export/audit`

Erzeugt ein maschinenlesbares Audit-Summary mit Zaehlern fuer Import-Batches,
Raw Objects, Canonical Events, Ledger, Flow-Ledger, Exportpakete, aktuelle
Review-Gates und V1/V2-Parity-Gate. `export_ready` ist nur `true`, wenn Review
und Parity beide frei sind. Offene Preis-Luecken werden mit Anzahl, Asset-Liste
und vollstaendiger Gap-Liste in das Audit aufgenommen.

`GET /api/v1/export/audit.json`

Download des Audit-Summary als JSON-Datei. Enthalten sind auch alle
Review-Entscheidungen als Audit-Liste, die aktuelle Preis-Gap-Liste und der
Parity-Freigabestand.

`GET /api/v1/export/review-decisions.csv`

Download aller Review-Entscheidungen als CSV-Audit-Tabelle.

`GET /api/v1/export/price-gaps.csv`

Download aller aktuellen Preis-Gaps als CSV-Audit- und Arbeitsliste.

`GET /api/v1/export/price-requirements.csv`

Download des datumsgenauen historischen Preisbedarfs als CSV-Datei.

`GET /api/v1/prices/quality`

Liefert eine read-only Preisqualitaetsdiagnose aus `price_ledger` und
`tax_lines`. Der Endpunkt gruppiert Low-Confidence-, Proxy-/Derived- und
ungueltige Preiszeilen nach Asset, Jahr und Quelle und markiert, ob die Gruppe
ein Asset/Jahr mit Tax-Lines beruehrt. Er schreibt keine Preise und akzeptiert
keine Preisquelle automatisch.

Wichtige Felder:

- `low_confidence_count`, `proxy_count`, `zero_or_negative_count`
- `tax_relevant_issue_groups`
- `groups[].risk_level`, `groups[].status`, `groups[].tax_lines_count`
- `source_summaries[]`
- `latest_assets[]`

`GET /api/v1/prices/quality/group?asset=HNT&year=2022&source=derived:event_quote`

Liefert einen read-only Drilldown fuer eine Preisqualitaetsgruppe. Enthalten
sind die aggregierte Gruppe, Price-Ledger-Samples mit verknuepften Canonical
Events, Tax-Line-Samples, Event-Quellen-Zaehler und Quote-Asset-Zaehler.
Dieser Endpunkt dient der Belegpruefung und schreibt keine Daten.

`POST /api/v1/prices/quality/decisions`

Speichert eine fachliche Preisqualitaetsentscheidung als Review-Decision fuer
eine Gruppe aus `asset`, `year` und `source`. Erlaubte Status:
`accepted_event_quote`, `external_price_required`,
`manual_review_required`. Die Entscheidung erscheint im Audit-Export und im
Preisqualitaetsreport, aendert aber keine Preiszeile und startet keinen
FIFO-/Pipeline-Rebuild.

`GET /api/v1/prices/quality/manual-review`

Liefert eine priorisierte read-only Arbeitsliste fuer alle
Preisqualitaetsgruppen mit `decision_status=manual_review_required`.
Sortiert wird nach Tax-Line-Anzahl, Preiszeilen und Asset/Jahr. Die Antwort
enthaelt Grundsignale wie Event-Quellen, Quote-Assets, Beispiel-Refs und einen
naechsten Pruefschritt.

Zusaetzliche Felder je Gruppe:

- `review_bucket`: automatische Arbeitsgruppe, z. B.
  `binance_normalizer_review`, `solscan_signature_review`,
  `stablecoin_fx_review`, `mixed_quote_source_review` oder
  `event_quote_evidence_review`
- `evidence_ref`: direkter Drilldown-Pfad fuer die Gruppe

Die Sample-Ermittlung erfolgt gebuendelt, damit alle Manual-Gruppen in einem
Dashboard/API-Call geladen werden koennen.

`GET /api/v1/prices/quality/stablecoin-fx-review`

Liefert eine read-only Arbeitsliste fuer Manual-Gruppen aus dem Bucket
`stablecoin_fx_review`. Der Endpunkt trennt `USDT`, `USDC`, `BUSD` und `EUR`
von normalen Asset-Event-Quotes, damit USD/EUR-FX bzw. `EUR=1` nicht mit
beliebigen Derived-Quotes vermischt wird.

Wichtige Felder:

- `groups_count`, `tax_relevant_groups_count`, `total_tax_lines_count`
- `groups[].expected_price_basis`
- `groups[].recommended_action`
- `groups[].evidence_ref`

Der Endpunkt schreibt keine Preise, aendert keine Tax-Lines und startet keinen
FIFO-/Pipeline-Rebuild.

`GET /api/v1/prices/quality/solscan-signature-review`

Liefert eine read-only Arbeitsliste fuer Manual-Gruppen aus dem Bucket
`solscan_signature_review`. Der Endpunkt trennt echte Onchain-Signatur-Refs
von CEX-/CSV-Refs und priorisiert Solana-RPC/Solscan-Gruppen nach
steuerlicher Wirkung.

Wichtige Felder:

- `groups_count`, `tax_relevant_groups_count`, `total_tax_lines_count`
- `total_signature_refs`
- `groups[].signature_count`, `groups[].signature_refs`
- `groups[].non_signature_ref_count`, `groups[].non_signature_refs`
- `groups[].recommended_action`
- `groups[].evidence_ref`

Der Endpunkt schreibt keine Preise, aendert keine Tax-Lines und startet keinen
FIFO-/Pipeline-Rebuild.

`GET /api/v1/prices/quality/binance-normalizer-review`

Liefert eine read-only Arbeitsliste fuer Manual-Gruppen aus dem Bucket
`binance_normalizer_review`. Der Endpunkt markiert Binance-Gruppen mit
fehlenden Quote-Feldern, `unknown` Events, Zero-Quantity-Samples oder
fehlenden Sample-Refs.

Wichtige Felder:

- `groups_count`, `tax_relevant_groups_count`, `total_tax_lines_count`
- `missing_quote_groups_count`
- `unknown_or_zero_groups_count`
- `missing_sample_ref_groups_count`
- `groups[].has_missing_quote_fields`
- `groups[].has_unknown_events`
- `groups[].has_zero_quantity_samples`
- `groups[].missing_sample_refs`
- `groups[].recommended_action`
- `groups[].evidence_ref`

Der Endpunkt schreibt keine Preise, aendert keine Tax-Lines und startet keinen
FIFO-/Pipeline-Rebuild.

`GET /api/v1/prices/quality/event-quote-evidence-review`

Liefert eine read-only Arbeitsliste fuer Manual-Gruppen aus dem Bucket
`event_quote_evidence_review`. Der Endpunkt klassifiziert die Restgruppen nach
`stable_quote_sample`, `non_stable_quote_sample`,
`blockpit_solana_derived_quote` oder `missing_quote_sample`.

Wichtige Felder:

- `groups_count`, `tax_relevant_groups_count`, `total_tax_lines_count`
- `stable_quote_groups_count`
- `missing_sample_ref_groups_count`
- `groups[].evidence_class`
- `groups[].stable_quote_evidence`
- `groups[].missing_sample_refs`
- `groups[].recommended_action`
- `groups[].evidence_ref`

Der Endpunkt schreibt keine Preise, aendert keine Tax-Lines und startet keinen
FIFO-/Pipeline-Rebuild.

`GET /api/v1/export/tax-lines.csv`

Download der steuerlichen Ergebniszeilen als CSV-Datei.

`GET /api/v1/export/derivative-lines.csv`

Download der Derivate-Ergebniszeilen als CSV-Datei.

## Altreport-/V1-Plausibilitaetsvergleich

`POST /api/v1/parity/v1/import/wiso`

Importiert aggregierte WISO-Steuer-CSV-Werte als Altreport-
Plausibilitaetswerte. Das Feld `source` beschreibt die Herkunft des
Referenzexports und ist keine V2-Matching-Dimension.

`GET /api/v1/parity/compare`

Vergleicht Altreport-Referenzen mit V2-Metriken. Der Vergleich versucht zuerst
einen exakten Schluessel und nutzt danach einen source-unabhaengigen V2-
Fallback, damit WISO-Dateinamen nicht als fachlicher Ledger-Ursprung
interpretiert werden. Fehlt eine V2-Metrik und der Altreport-Wert ist exakt
`0`, wird dies als Match gegen `0` behandelt, damit Nullwerte nicht als
fehlende Aktivitaet erscheinen.

Der Vergleich ist ein Plausibilitaetswerkzeug. Altreports koennen unvollstaendig
sein; bei Abweichungen entscheidet die belegte Rohdatenkette in V2.
Bis eine Abweichung belegt entschieden ist, gilt V1 fuer die Release-
Paritaet als fuehrende Referenz.

`GET /api/v1/parity/diagnostics`

Verdichtet offene Paritaetsprobleme nach Jahr, Asset und Status. Die Antwort
enthaelt Issue-Anzahl, betroffene Metriken, EUR-Summen und maximale Differenz.
Diese Sicht ist fuer die Priorisierung gedacht: grosse `diff`-Gruppen deuten
auf Bewertungs-/Deduplizierungsprobleme hin, `missing_v2` auf noch nicht
importierte oder noch nicht normalisierte Quellen.
Jede Gruppe enthaelt einen stabilen `scope` und einen `decision_status`.
Ohne Review-Entscheidung ist der Status `unreviewed`.

`GET /api/v1/parity/release-readiness`

Bewertet, ob V2 fachlich V1 abloesen darf. Diese Freigabe ist strenger als die
technische Export-Freigabe. Gruppen mit `unreviewed`,
`needs_manual_evidence` oder `v2_missing_data` blockieren den Paritaets-
Release. Akzeptierte Gruppen sind `v1_known_wrong`, `v2_corrected` und
`accepted_difference`.

`GET /api/v1/parity/group-detail?scope=...`

Liefert fuer eine Paritaetsgruppe die V1-/V2-Metriken und, sofern es sich um
eine Tax-Gruppe mit Jahr und Asset handelt, die V2-Tax-Herkunft:
Quelle, Account, Datei, Tax-Line-Anzahl, Event-Anzahl, Mengen, EUR-Werte,
Zeitraum und Beispiel-Rohereignisse. Diese Detailansicht ist der Arbeitsbeleg,
um grobe Paritaetsgruppen wie `2022 HNT` gegen konkrete Import- und
Normalisierungsquellen zu pruefen.

`POST /api/v1/parity/decisions`

Speichert eine Review-Entscheidung fuer einen Paritaets-Scope. Moegliche
Statuswerte sind `v1_known_wrong`, `v2_missing_data`, `v2_corrected`,
`needs_manual_evidence` und `accepted_difference`. Die Entscheidung veraendert
keine berechneten V1/V2-Zahlen und lockert kein Review-Gate; sie klassifiziert
die Abweichung fuer Audit und UI.

`POST /api/v1/export/elster-prep`

Erzeugt ELSTER-nahe Vorbereitungsdaten. `direct_eric_submission=false` ist im
MVP verbindlich, weil direkte ERiC-Uebertragung erst spaeter mit
Hersteller-/Zertifikatsprozess umgesetzt wird.

## MoonPay-Anschaffungsbelege

### `GET /api/v1/tax/moonpay-receipts`

Liefert den read-only Abgleich des SHA-256-gebundenen MoonPay-Trade-History-
Exports mit vorhandenen Solana-Canonical-Events und, falls vorhanden, den
nativen Sparkassen-CAMT.052-Dateien. Die Antwort weist unter anderem
Zuordnungsquote, MoonPay-Basisbetrag, Bruttoabbuchung, EUR-Kostenbasis,
Gebuehrenbestandteile, UTC-Zeitdifferenz, Trade-ID, TxID und die vollstaendige
Decision Layer aus.
Optional begrenzt `as_of` den Report stichtagsgenau.

Der Primaerexportpfad kann fuer andere Installationen mit
`STEUERREPORT_MOONPAY_TRADE_HISTORY_PATH` gesetzt werden. Ohne Variable gilt
der lokale Standardpfad; ein fehlender Export wird als Evidence Gap gemeldet
und niemals durch Demo- oder Schaetzwerte ersetzt.

Der CAMT-Verzeichnis-Pfad kann mit `STEUERREPORT_SPARKASSE_CAMT_DIR` gesetzt
werden. Produktiv wird andernfalls der neueste Ordner `*-camt52v8Booked` unter
dem lokalen Sparkassen-Transferverzeichnis verwendet. Es werden ausschliesslich
MoonPay-EUR-Abbuchungen gelesen. Kontonummern und sonstige Umsaetze werden weder
importiert noch ueber die API ausgegeben; der Gesamtbeleg wird semantisch
SHA-256-gebunden.

`baseCurrencyAmount` ist im vorliegenden MoonPay-Export der Basisbetrag vor den
separat ausgewiesenen Gebuehren. Die steuerliche Anschaffungskostenbasis und
der tatsaechliche Bankabgang ergeben sich aus `baseCurrencyAmount + feeAmount +
extraFeeAmount + networkFeeAmount`. `total_base_payment_amount_eur`,
`total_fee_components_eur`, `total_bank_debits_eur` und
`total_receipt_cost_basis_eur` halten diese Werte getrennt nachvollziehbar. Der
GET-Endpunkt schreibt keine Events, Lots, Tax-Lines, Ledger- oder Reviewdaten.

### `GET /api/v1/tax/moonpay-receipts/trade-history.csv`

Liefert den unveraenderten, im Report gehashten Primaerexport als Download.
`X-Content-SHA256` enthaelt den Hash des ausgelieferten Inhalts.

### `GET /api/v1/tax/moonpay-receipts/{tx_id}/document`

Liefert den zu einer TxID gebundenen Primaerbeleg. Bei Zuordnung aus der
Trade-History wird derselbe unveraenderte CSV-Export ausgeliefert; optionale
Einzelbelege werden aus dem V2-Belegspeicher geladen und vor Ausgabe erneut
gegen ihren SHA-256 geprueft.

### `POST /api/v1/tax/moonpay-receipts`

Optionaler V2-Pfad fuer einen einzelnen PDF-, JPEG-, PNG-, CSV- oder TXT-Beleg,
falls eine Transaktion nicht im Trade-History-Export enthalten ist. Der Upload
schreibt nur den lokalen Beleg und sein Manifest. Eine Steuer-/FIFO-Neuberechnung
bleibt eine bewusste separate Aktion.

## Direkter V2-Quellen-Liveabgleich

### `GET /api/v1/portfolio/reconciliation`

Vergleicht das unveraenderte V2-Balance-Ledger mit den zuletzt erfolgreich
gespeicherten API-/RPC-Ankern. Freigegebene Ledger-Overlays aus der
Quellenregistry wirken nur auf diesen read-only Abgleich, wenn im aktuellen
Datenbestand unter derselben TxID sowohl der Providerbeleg mit passender
Bruttomenge als auch der positive Eingang auf der registrierten eigenen
Zielwallet mit passender Nettomenge vorhanden sind.

Zusaetzliche Reportfelder:

- `total_ledger_value_eur`: unveraenderter Rohledgerwert,
- `ledger_adjustment_value_eur`: Summe der validierten Evidence-Overlays,
- `total_reconciled_ledger_value_eur`: Rohledger plus Evidence-Overlays,
- `applied_ledger_adjustments_count`: Anzahl tatsaechlich angewandter Overlays.

Zusaetzliche Zeilenfelder:

- `raw_ledger_quantity` und `raw_ledger_value_eur`,
- `ledger_adjustment_quantity` und `ledger_adjustment_value_eur`,
- `ledger_adjustment_ids` und `ledger_adjustment_tx_ids`,
- `ledger_quantity` und `ledger_value_eur` als reconciliertes Ergebnis.

`live_anchor_reconciled_with_evidence_overlay` bedeutet, dass der API-/RPC-
Anker erst nach einem solchen vollstaendig TxID-gebundenen Belegoverlay mit
dem Ledger uebereinstimmt. Der Endpunkt schreibt keine Canonical Events,
Ledgerzeilen, Lots, FIFO-Ergebnisse, Preise oder Steuerzeilen.

### `POST /api/v1/portfolio/reconciliation/refresh`

Fragt Binance, Bitget, Pionex sowie die konfigurierten Solana-Wallets read-only
ab und bindet je Quelle einen versionierten Connector-Lauf. Positive Bestaende
ersetzen den aktuellen Snapshot-Anker; eine erfolgreiche leere Antwort wird als
`empty_response` und damit als bestaetigter Nullsaldo gespeichert. Fruehere
Snapshot-Zeilen bleiben dabei als historische Referenz erhalten, gelten aber
nicht mehr als aktueller Anker. Sind `secret.cex.<connector>.api_key`,
`api_secret` und bei
Bitget `passphrase` im V2-Secret-Store vorhanden, werden die CEX-Endpunkte
direkt aus V2 aufgerufen. Ein fehlgeschlagener Connector loescht seinen
vorhandenen Snapshot nicht.

Die Laufmetadaten werden in `portfolio_live_connector_runs` gespeichert. Fuer
die aktuelle Anzeige sind nur die Zustaende `refreshed` und `empty_response`
erfolgreich. `connector_error` und `missing_configuration` erhalten den letzten
erfolgreichen Anker, machen ihn aber nach Ablauf des Frischefensters nicht
weiter zu einem aktuellen Wert.

Der letzte Lauf bleibt ueber
`GET /api/v1/sources/connector-diagnostics` und neue
Quellenregistry-Laeufe sichtbar. Ein spaeterer Fehler wie `APIKEY_EXPIRED`
darf daher nicht in einer pauschalen Aufforderung zum erneuten Abruf enden;
die API und UI nennen stattdessen die erforderliche Credential-Erneuerung.

Wichtige Ergebnisfelder:

- `fetched_at`
- `imported_snapshots`
- `connector_results[].status`
- `connector_results[].snapshots`
- `connector_results[].previous_snapshot_at`
- `snapshots[].account_type`
- `snapshots[].product_id`
- `snapshots[].position_id`
- `snapshots[].event_type`

Ein erfolgreicher `empty_response` ist kein API-Fehler und erzeugt deshalb
keine Warnung. Wenn gleichzeitig ein alter Ledger-Restbestand existiert, wird
dieser weiterhin im Quellen-/Reconciliation-Drilldown gezeigt, aber nicht in
den aktuellen Portfolio-Gesamtwert aufgenommen.

Binance Spot und Simple Earn werden als getrennte Komponenten gespeichert.
Das Locked-Earn-Feld `rewardAmt` ist eine kumulierte Produktkennzahl und kein
zusaetzlicher verfuegbarer Bestand; es wird deshalb nicht als Portfolio-
Snapshot gespeichert. Reward-Einkommen stammt aus der separaten
Simple-Earn-Reward-Historie.

### `GET /api/v1/sources/{source_id}/reconciliation`

Der Asset-Abgleich trennt den gesamten API-Livewert vom FIFO-/Ledger-
Abgleichswert. Falls ein Connector einen echten noch nicht gutgeschriebenen
Anspruch separat ausweist, bleibt dieser im Live-Vermoegen sichtbar, wird aber
nicht als fehlende Ledgerbuchung behandelt.

Zusaetzliche Felder:

- `live_nonledger_accrual_value_eur`
- `reconciliation_live_value_eur`
- `raw_delta_value_eur`
- `rows[].live_nonledger_accrual_quantity`
- `rows[].reconciliation_live_quantity`
- `rows[].raw_delta_quantity`

`delta_value_eur` und `rows[].delta_quantity` bezeichnen den steuerlichen
FIFO-/Ledger-Abgleich, nicht eine automatische Korrekturbuchung.

### `GET /api/v1/sources/binance/reconciliation/evidence`

Ergaenzt dieselben Brutto-/Abgleichsfelder um Binance-Import-Batches,
Produkt-Historienbedarf, Event-Aggregate und getrennte Live-Komponenten. Der
Endpunkt bleibt read-only.

## Reward-Ursprung und Steuersphaere

### `GET /api/v1/tax-years/business-reward-inventory-review`

Liest bestehende HNT/IOT/MOBILE-Tax-Lines und verbindet sie ueber das
verwendete Tax-Lot mit dem urspruenglichen Canonical Event. Der Endpunkt
unterscheidet:

- `potential_business_inventory`: Mining oder belegter On-Chain-Reward,
- `origin_classification_review`: Income-/Transfer-Ursprung noch nicht
  eindeutig als Reward, Migration oder FIFO-Fortfuehrung belegt,
- `separate_income_review`: insbesondere CEX-Staking/-Reward mit eigener
  Einkunftspruefung,
- `non_reward_origin`: direkter Ursprung ist kein Reward-/Mining-Ereignis,
- `missing_origin`: Tax-Lot oder Anschaffungsereignis ist nicht vollstaendig
  verknuepft.

Wichtige Ergebnisfelder:

- `strict_ready`
- `affected_years`
- `potential_business_tax_lines_count`
- `unresolved_tax_lines_count`
- `potential_business_acquisition_cost_eur`
- `potential_business_proceeds_eur`
- `potential_business_gain_loss_eur`
- `rows[].blocks_private_fifo_classification`
- `rows[].sample_origin_event_id`
- `rows[].sample_disposal_event_id`

`strict_ready=false` blockiert die Aussage, die betroffenen Verwertungen seien
abschliessend private FIFO-Vorgaenge. Der Endpunkt nimmt keine Entnahme an und
schreibt weder Canonical Events noch Lots, Tax-Lines, Preise, Ledger oder
Review-Entscheidungen.

## Krypto-zu-Krypto-Bewertungsrangfolge

### `GET /api/v1/tax/crypto-swap-valuation-review`

Query-Parameter:

- `year`: optionales deutsches Berichtsjahr nach `Europe/Berlin`,
- `limit`: Anzahl der groessten Detaildeltas, 1 bis 5.000, Standard 200.

Der read-only Endpunkt vergleicht fuer positive wirtschaftliche
Krypto-zu-Krypto-Trade-Events zwei Regeln:

- aktive V2-Regel: erhaltener Token nur bei Stable-Value-Ankern, sonst Wert
  des hingegebenen Quote-Tokens,
- BMF-Preview nach Rn. 58: Marktwert des erhaltenen Tokens zuerst, Wert des
  hingegebenen Tokens nur als belegter Fallback.

Wichtige Ergebnisfelder:

- `candidates_count`
- `policy_mismatch_count`
- `material_delta_count`
- `received_price_fallback_review_count`
- `missing_both_prices_count`
- `signed_value_delta_eur`
- `absolute_value_delta_eur`
- `rows[].current_basis`
- `rows[].bmf_preview_basis`
- beide Preise mit Quelle, Zeitpunkt und Confidence

`value_delta_eur` ist das direkte Transaktionswertdelta. Es ist ohne
vollstaendigen FIFO-Parallel-Lauf weder eine Jahres-G/V- noch eine
Steuerdifferenz. Der Endpunkt schreibt keine Preise, Lots oder Tax-Lines.

### `GET /api/v1/tax/crypto-swap-fifo-parallel-preview/latest`

Liefert das letzte versionierte In-Memory-FIFO-Artefakt sofort aus. Es
vergleicht die aktive globale FIFO mit derselben FIFO unter der
Erhaltener-Token-zuerst-Preisrangfolge. Enthalten sind:

- G/V-Delta pro Jahr,
- technische Gruppen bis/ueber 365 Tage,
- groesste Asset- und Disposal-Event-Deltas,
- Tax-Line-, Lot- und unmatched-Paritaet,
- voller Account, TxID und Event-ID im Detailvertrag.

### `POST /api/v1/tax/crypto-swap-fifo-parallel-preview/run`

Request:

```json
{
  "limit": 200
}
```

Fuehrt beide globalen FIFO-Varianten vollstaendig im Arbeitsspeicher aus und
ersetzt danach nur das versionierte JSON-Artefakt unter
`var/swap_valuation_parallel/`. Der Lauf kann auf dem Produktivbestand etwa
eine Minute dauern. Er schreibt keine Tax-Lots, Tax-Lines, Run-Summaries,
unmatched Abgaenge, Preise oder Canonical Events.

## Gemeinsames BMF Preis-/Wallet-/Reward-Staging

### `GET /api/v1/tax/bmf-combined-fifo-staging/latest`

Liefert die letzte versionierte Vier-Wege-Entscheidungsakte ohne Neuberechnung.
Verglichen werden:

- aktive globale Asset-FIFO mit aktiver Preisrangfolge,
- globale Asset-FIFO mit Marktwert des erhaltenen Tokens zuerst,
- Wallet-/Depot-FIFO mit aktiver Preisrangfolge,
- Wallet-/Depot-FIFO mit Marktwert des erhaltenen Tokens zuerst.

Die vier Szenarien verwenden denselben Canonical-Event-, Preis- und
Evidence-Stand. Die Zielvorschau gruppiert ihre Tax-Lines zusaetzlich nach
Reward-Ursprung. `outside_reward_scope` bedeutet nur, dass der direkte
Anschaffungsursprung nicht unter den Reward-Audit faellt; es ist keine
automatische Privatklassifikation.

Wichtige Ergebnisfelder:

- `productive_tax_tables_unchanged`
- `input_fingerprint_digest`
- `productive_tax_component_sha256`
- `price_policy_delta_eur`
- `wallet_scope_delta_eur`
- `combined_delta_eur`
- `interaction_delta_eur`
- `potential_business_inventory_tax_lines_count`
- `unresolved_reward_origin_tax_lines_count`
- `year_rows`, `top_assets`, `sphere_rows`, `top_events`
- `top_events[].active_global_quantity`
- `top_events[].received_first_global_quantity`
- `top_events[].active_wallet_quantity`
- `top_events[].received_first_wallet_quantity`

### `POST /api/v1/tax/bmf-combined-fifo-staging/run`

Request:

```json
{
  "years": [2021, 2022, 2023, 2024, 2025, 2026],
  "as_of": null,
  "limit": 200
}
```

Fuehrt alle vier Varianten read-only aus. `as_of=null` bedeutet bei Auswahl
des laufenden Jahres den aktuellen UTC-Zeitpunkt, sonst das Ende des hoechsten
angeforderten Jahres. Der Dienst hasht produktive Tax-Lots und Tax-Lines vor
und nach der Berechnung und bricht ohne Artifact-Write ab, falls sich der Hash
aendert. Nur ein versioniertes JSON und `var/bmf_fifo_staging/latest.json`
werden atomar geschrieben. Auf dem vollstaendigen Produktivbestand kann der
Lauf mehrere Minuten dauern.

## BMF FIFO-Eventbelege

### `GET /api/v1/tax/bmf-fifo-event-evidence/latest`

Liefert die letzte versionierte Primaerbeleg-Worklist. Im Modus
`priority_delta` umfasst sie die priorisierten Delta-Events des
BMF-Gesamtstagings. Im Modus `full_ledger` bindet sie zusaetzlich alle
Canonical Events der Staging-Jahre und den vollstaendigen FIFO-Steuergraphen.
Je Disposal- und Acquisition-Event bindet der Report:

- Canonical Event mit UTC-Zeit, Asset, Menge, Quote-Bein und Account,
- Original-Rohimport mit Batch, Datei, Zeile und Payload-SHA-256,
- volle TxID, Source-Referenz oder CEX-Datei-/Zeilenkennung,
- erhaltenen und hingegebenen historischen EUR-Preis mit Preis-ID, Quelle,
  Zeitpunkt, Confidence, Alter und Wert,
- Reward-Ursprung und die vier G/V-Szenarien des Stagings,
- eine rohbelegte Herkunftsentscheidung mit Belegmarkern, Steuersphaere und
  Kennzeichen, ob eine FIFO-Vorlot-Fortfuehrung erforderlich ist.

Die Herkunftsentscheidung unterscheidet insbesondere:

- `potential_business_inventory`: Helium-Mining-/Netzwerk-Reward,
- `documented_swap_acquisition`: durch On-Chain-Swapmarker belegter Erwerb,
- `internal_transfer_fifo_carry_review`: interne Binance-/Bitget-Umbuchung;
  weder Verkauf noch Ertrag, Vorlot-Verknuepfung bleibt zu pruefen,
- `opening_reconstruction_limit`: dokumentierte Rekonstruktionsgrenze ohne
  behauptete Originalanschaffung,
- `separate_income_review`: CEX-Earn-/Staking-Ertrag ausserhalb des
  Helium-Netzwerk-Rewardpfads,
- `origin_classification_review` oder `missing_origin`: echte Rest-Unklarheit.

`derived_*` und `stale_*` sind Review-Signale. Fehlendes Canonical Event,
fehlender Rohbeleg, fehlende On-Chain-Kennung oder fehlender Preis des
erhaltenen Tokens blockiert. `full_ledger_scope=false` weist ausdruecklich
darauf hin, dass dies die gerankte Staging-Worklist und kein stillschweigender
Vollstaendigkeitsnachweis fuer das gesamte Ledger ist.

Deterministisch durch die Wallet-FIFO erzeugte Transfergebuehren sind keine
eigenen Blockchain-Events. Solche Zeilen tragen
`synthetic_derivation=wallet_fifo_explicit_transfer_fee`, die zugrunde
liegenden `parent_event_ids`, deren `parent_source_evidence` und den Preis des
hingegebenen Gebuehrenassets. Sie bleiben fachlich im Review, blockieren aber
nicht faelschlich wegen eines nicht existierenden Canonical Events.

### `POST /api/v1/tax/bmf-fifo-event-evidence/run`

Request:

```json
{
  "limit": 200,
  "issue_limit": 500,
  "min_abs_delta_eur": "0.01",
  "scope_mode": "priority_delta"
}
```

`scope_mode=full_ledger` erzeugt neben dem kompakten JSON-Report ein
deterministisches, gzip-komprimiertes JSONL-Artefakt mit jedem Eventbeleg. Der
Report nennt Pfad, Kompression, Bytegroesse und SHA-256. Die API-Antwort selbst
bleibt durch gruppierte Ledger-/Herkunftszeilen und begrenzte Issues klein.

Der Lauf benoetigt ein vorhandenes BMF-Gesamtstaging, prueft dessen Tax-Hash
gegen den aktuellen Datenstand und schreibt ausschliesslich versionierte JSON-
Artefakte unter `var/bmf_event_evidence/`. Tax-Lots, Tax-Lines, Canonical
Events, Rohimporte, Ledger und Preise bleiben unveraendert.

### `GET /api/v1/tax/bmf-fifo-event-evidence/events.jsonl.gz`

Laedt das komprimierte Einzelevent-Artefakt des letzten Laufs herunter. Der
Response nutzt `Content-Type: application/gzip` und liefert den gebundenen Hash
zusaetzlich als `X-Content-SHA256`. Der Pfad wird serverseitig auf das
Eventbeleg-Artefaktverzeichnis begrenzt; ein beliebiger Dateidownload ist nicht
moeglich.

## BMF Event-Preisanker

### `GET /api/v1/tax/bmf-event-price-remediation/latest`

Liefert den letzten gezielten Preisanker-Lauf fuer die offenen Preisrollen der
BMF-FIFO-Eventbeleg-Worklist. Jeder Job enthaelt Asset, UTC-Tag, Rollen,
betroffene Event-IDs, vorherige Preisqualitaet, Provider-ID, Provider- und
FX-URL, SHA-256 der Antworten, USD-Preis, ECB-USD/EUR-Kurs, EUR-Preis,
Confidence und Importstatus.

Wichtige Statuswerte:

- `planned`: unabhaengiger Anker wurde im Dry-Run belegt,
- `imported`: Anker wurde additiv in `price_ledger` eingefuegt,
- `already_ready`: identischer V2-Anker existiert bereits,
- `token_risk_blocked`: Asset ist als `spam_review` markiert,
- `provider_failed` oder `fx_failed`: externer Beleg fehlt,
- `request_limit`: `max_jobs` hat den Lauf begrenzt.

### `POST /api/v1/tax/bmf-event-price-remediation/run`

Request:

```json
{
  "execute": false,
  "include_roles": ["received", "given"],
  "max_jobs": 1000,
  "timeout_seconds": 20,
  "config_path": "/workspace/steuerreport-v2-plan/configs/crypto_price_sources.json"
}
```

`execute=false` schreibt nur versionierte Report- und Provider-Artefakte unter
`var/bmf_event_price_remediation/`. `execute=true` importiert deduplizierte
Preisanker additiv und fuehrt danach die Eventbelegpruefung erneut aus.

USD-Paritaets-Stablecoins verwenden den USD/EUR-Referenzkurs des ECB-Providers
aus Frankfurter v2. Andere konfigurierte Assets verwenden einen historischen
DefiLlama-Preis um 00:00 UTC und denselben ECB-Kurs. Wochenend-/Feiertagskurse
weisen den tatsaechlichen vorherigen `fx_rate_date` aus. Vollstaendige
Providerpayloads werden mit URL und SHA-256 archiviert.

Vor und nach jedem Lauf wird der Hash der produktiven Tax-Komponenten
verglichen. Tax-Lots und Tax-Lines werden nicht neu gebaut. Ein
`spam_review`-Asset wird vor Providerzugriff gesperrt; ein externer Kurs darf
keine offene Token-Identitaetspruefung ersetzen. Nach jedem ausgefuehrten
Preisimport muss das Vier-Wege-Staging neu erzeugt werden, weil sein
`input_fingerprint_digest` den Preisbestand einschliesst.

## Erbgeld- und Trade-Republic-Nachweis

### `GET /api/v1/divorce/inheritance-origin`

Erzeugt einen read-only, datensparsamen Mittelherkunftsreport fuer den
Trennungs- und Endvermoegensstichtag. Query-Parameter:

- `separation_date`, Standard `2025-06-13`,
- `end_asset_date`, Standard `2026-07-24`.

Der Service parst native Sparkassen-CAMT.052-Dateien strukturiert und gibt
keine IBAN, Gegenpartei oder Verwendungszwecke aus. Sichtbar sind nur
SHA-256-Referenzen, Datum, EUR-Betrag und der klassifizierte Anbieter. Der
Report trennt:

- primaeren Nachlasskonto-Uebertrag und weitere Erbmittelzufluesse,
- CAMT-Bankbuchungen und dokumentbasierte Nettobetraege,
- Nutzerdeklaration `inheritance` als Review Decision,
- formalen Erbnachweis,
- Bank-/Plattformmatch ohne Doppelzaehlung,
- Krypto-Ledger-Abdeckung,
- externe Depotwerte von Trade Republic und Coinbase am Stichtag.

Trade Republic stellt eine offizielle PSD2-Schnittstelle fuer lizenzierte
AISP/PISP mit eIDAS-QSeal bereit. Sie ist keine direkte private Retail- oder
Depot-API. Deshalb ist der produktive V2-Pfad
`official_document_import`: Kontoauszuege, Einzelabrechnungen, Depot-/Cash-
Auszug am Stichtag und Steuerunterlagen werden unter dem konfigurierbaren
Dokumentroot gehasht erfasst. Ohne Stichtagswert bleibt der Report blockiert.

`inheritance_credit` bleibt als kompatibler primaerer Nachlasskonto-Uebertrag
erhalten. `inheritance_credits` listet alle einzeln belegten Teilpositionen und
`inheritance_credit_eur` ist deren Summe. Jede Position weist `credit_kind`,
`evidence_source`, `date_basis`, Klassifikationsquelle sowie SHA-256-Referenzen
aus. Ein Dokumentdatum wird niemals als angeblicher Bankbuchungstag ausgegeben.
Die Aggregation ist eine Mittelherkunftsspur; spaetere Auszahlungen bereits
geerbter Vermoegenswerte duerfen in einer familienrechtlichen Bewertung nicht
zusaetzlich zum urspruenglichen Vermoegenswert doppelt angesetzt werden.

Konfiguration:

- `STEUERREPORT_SPARKASSE_CAMT_DIR`,
- `STEUERREPORT_TRADE_REPUBLIC_DOCUMENT_ROOT`,
- `STEUERREPORT_INHERITANCE_DOCUMENT_ROOT`,
- `STEUERREPORT_INHERITANCE_DOCUMENT_PATH` als administrativ bereits
  gepruefter Kompatibilitaetspfad.

### `GET /api/v1/divorce/inheritance-origin.csv`

Liefert die datensparsame Einzelspur der identifizierten Investmentabfluesse
als CSV. Der Download enthaelt keine Rohbankdaten. JSON und CSV werden auch in
das Zugewinn-Belegpaket und in neue versionierte Stichtagslaeufe aufgenommen.

### `GET /api/v1/divorce/inheritance-credit-candidates`

Liefert alle positiven CAMT-Gutschriften im angeforderten Stichtagszeitraum als
datensparsame Reviewliste. Der Contract enthaelt nur Datum, EUR-Betrag,
Transaktions- und Dateihash sowie den Status `automatic`, `reviewed` oder
`unclassified`. Gegenpartei, IBAN und Verwendungszweck verlassen den Parser
nicht. Eine normale Gutschrift wird dadurch nicht automatisch als Erbe
behandelt.

### `POST /api/v1/divorce/inheritance-credit-decisions`

Klassifiziert genau eine ueber ihren `transaction_reference_sha256` gebundene
CAMT-Gutschrift als `estate_asset_realization` oder `estate_refund`. Optional
kann `supporting_evidence_ref` auf einen zuvor importierten Erbnachweis zeigen.
Die idempotente Review Decision veraendert keine CAMT-Datei und keine
Steuer-/FIFO-Daten.

```json
{
  "transaction_reference_sha256": "64-stelliger-sha256",
  "credit_kind": "estate_asset_realization",
  "supporting_evidence_ref": "inheritance-document:sha256:...",
  "actor": "user"
}
```

### `POST /api/v1/divorce/inheritance-document-credit-decisions`

Bindet einen Nettobetrag aus einem importierten Nachlassdokument. Der Request
enthaelt Dokumenthash, Dokumentdatum, EUR-Nettobetrag und Art. Dieser Pfad ist
fuer Belege vorgesehen, deren Zahlung auf einem anderen oder noch nicht
importierten Bankkonto liegt. Der Betrag entsteht niemals automatisch aus dem
Dateinamen oder aus unstrukturiertem Freitext; er muss gegen das Original
gesichtet werden.

```json
{
  "document_sha256": "64-stelliger-sha256",
  "document_date": "2025-05-14",
  "amount_eur": "1095.09",
  "credit_kind": "estate_refund",
  "actor": "user"
}
```

### `GET /api/v1/divorce/inheritance-credits.csv`

Exportiert alle akzeptierten Erbmittelzufluesse mit Betrag, Datumsbasis,
Belegart, Entscheidungs-ID und Hashreferenzen. Namen, Dateinamen, Kontodaten und
Rohverwendungszwecke sind nicht enthalten.

### `POST /api/v1/divorce/sparkasse-camt`

Nimmt native Sparkassen-CAMT.052-Dateien als XML oder ZIP per
`multipart/form-data` entgegen:

- `file`: XML/ZIP, maximal 100 MiB Uploadgroesse,
- `separation_date`: Standard `2025-06-13`,
- `end_asset_date`: Standard `2026-07-24`.

Vor dem Speichern prueft V2 Dateiformat, XML-Wohlgeformtheit,
CAMT.052-Namespace und Berichtsstruktur. DTDs/Entities, uebergrosse XML-Dateien,
Archive ohne CAMT-XML und ZIP-Bomben-Kandidaten werden verworfen. ZIP-Mitglieder
werden nicht unter ihren Originalnamen entpackt. Gueltige Dokumente werden
hashbasiert, neutral benannt und ohne Ueberschreiben oder Loeschen ergaenzt.
Hashgleiche XML-Inhalte sind idempotent. Der Response enthaelt den aktualisierten
Mittelherkunftsreport, aber keine Kontodaten oder Originaldateinamen.

### `GET /api/v1/divorce/inheritance-documents`

Liefert den datensparsamen Status formaler Erbnachweise. Sichtbar sind nur
SHA-256, Medientyp, Groesse, Quellenart und Reviewstatus. Browser-Uploads bleiben
`candidate_present`, bis das Original ausdruecklich geprueft wurde. Ein ueber
`STEUERREPORT_INHERITANCE_DOCUMENT_PATH` administrativ konfigurierter Altpfad
bleibt aus Kompatibilitaetsgruenden als bereits geprueft markiert.

### `GET /api/v1/divorce/inheritance-documents.csv`

Liefert denselben Hash- und Reviewindex als CSV. Er wird in beide
Zugewinn-/Stichtagsdossiers aufgenommen; Originaldokumente und Dateinamen werden
nicht kopiert.

### `POST /api/v1/divorce/inheritance-documents`

Browser-Upload eines PDF-, JPEG- oder PNG-Dokuments, maximal 50 MiB. V2 prueft
Dateiendung und Dateisignatur, speichert neutral und hashbasiert und erzeugt
noch keine fachliche Freigabe.

### `POST /api/v1/divorce/inheritance-documents/review-decisions`

Bindet einen vorhandenen Kandidaten nach Sichtpruefung als
`divorce_formal_inheritance_evidence` an seine SHA-256-Summe:

```json
{
  "document_sha256": "64-stelliger-sha256",
  "actor": "user"
}
```

Die Entscheidung ist idempotent und schreibt ausschliesslich eine Review
Decision. Sie bestaetigt den manuellen Originalabgleich; sie nimmt keine
automatische rechtliche Echtheitspruefung vor und aendert weder Ledger noch
FIFO oder Steuerdaten.

### `GET /api/v1/divorce/trade-republic/documents`

Prueft alle lokalen Trade-Republic-Dokumente am konfigurierten Dokumentroot.
Unterstuetzt werden PDF, CSV und ZIP. ZIP-Mitglieder werden im Speicher gelesen
und nicht in das Dateisystem entpackt. Der Contract liefert ausschliesslich:

- SHA-256 von Dokument und optionalem ZIP-Container,
- Dokument- und Parserstatus,
- inhaltlich erkanntes Stichtagsdatum,
- extrahierte Cash-, Depot- und Gesamtwerte,
- Kandidaten- und Reviewstatus.

Dateiname, Dokumenttext, Depotnummer und personenbezogene Rohdaten werden nicht
ausgegeben. Ein Datum nur im Dateinamen erzeugt hoechstens
`candidate_present`; es ist kein freigabefaehiger Stichtagsbeleg.

### `GET /api/v1/divorce/trade-republic/documents.csv`

Liefert denselben datensparsamen Dokumentnachweis als CSV. Die CSV wird auch in
das Zugewinn-Belegpaket und in versionierte Stichtagslaeufe aufgenommen. Die
Originaldokumente selbst werden nicht in diese Pakete kopiert.

### `POST /api/v1/divorce/trade-republic/documents`

Browser-Upload eines offiziellen PDF-, CSV- oder ZIP-Dokuments als
`multipart/form-data`:

- `file`: Dokument, maximal 100 MiB,
- `end_asset_date`: Stichtag, Standard `2026-07-24`.

V2 speichert die Datei unter einem neutralen, hashbasierten Namen im
konfigurierten Dokumentroot. Hashgleiche Uploads werden dedupliziert; vorhandene
Dateien werden nicht ueberschrieben oder geloescht.

### `POST /api/v1/divorce/trade-republic/valuation-decisions`

Akzeptiert einen zuvor geprueften Stichtagskandidaten als
`divorce_external_asset_valuation`. Request:

```json
{
  "end_asset_date": "2026-07-24",
  "document_sha256": "64-stelliger-sha256",
  "actor": "user"
}
```

Die Entscheidung wird nur gespeichert, wenn Datum und eindeutiger Gesamtwert
im Dokumentinhalt erkannt wurden. Ein Dateiname, ein mehrdeutiger Wert oder ein
vom Client frei gelieferter EUR-Betrag genuegt nicht. Wiederholungen desselben
Belegs sind idempotent. Die Operation schreibt ausschliesslich eine Review
Decision und aendert keine Canonical Events, Tax-Lots, Tax-Lines, FIFO, Ledger
oder Preise.

## Coinbase V2-Quelle

Coinbase ist als eigener CEX-Connector `coinbase` registriert. Credentials
werden ueber den vorhandenen V2-Pfad
`POST /api/v1/admin/cex-credentials` gespeichert:

```json
{
  "connector_id": "coinbase",
  "api_key": "organizations/{org_id}/apiKeys/{key_id}",
  "api_secret": "-----BEGIN EC PRIVATE KEY-----\\n...",
  "passphrase": null
}
```

Der Connector akzeptiert die von Coinbase App/Advanced Trade geforderte
ECDSA-P-256-Schluesselart und erzeugt pro Request ein zwei Minuten gueltiges,
pfadgebundenes ES256-JWT. `POST /api/v1/portfolio/reconciliation/refresh`
bezieht Coinbase im Standardlauf automatisch ein, sobald beide Coinbase-
Credentials vollstaendig im V2-Secret-Store liegen. Ein expliziter Request mit
`connectors=["coinbase"]` meldet fehlende Konfiguration getrennt. Gespeichert
werden ausschliesslich positive aggregierte Live-Bestaende als Snapshot-Anker.
Private Keys werden nicht in Responses oder Logs ausgegeben.

Das Importprofil `coinbase` verarbeitet den offiziellen Transaction-History-
CSV-Aufbau mit `Timestamp`, `Transaction Type`, `Asset`,
`Quantity Transacted`, `Spot Price Currency`, `Subtotal`,
`Fees and/or Spread` und optionaler Transaction-ID. Buy/Sell, Send/Receive und
Rewards werden getrennt normalisiert; `Subtotal` und Gebuehr bleiben getrennte
Decimal-Felder. Der Import laeuft ueber die vorhandenen Preview-, Batch- und
Pipeline-Pfade.

Wichtig: Die Coinbase-API liefert einen aktuellen Saldo, aber keinen frei
rueckdatierbaren Gesamtwert fuer den 24.07.2026. Ein Live-Snapshot darf deshalb
nicht als historischer Stichtagswert verwendet werden. Dafuer werden die
vollstaendige Transaction History oder ein offizieller Account-Statement-Beleg
sowie die vorhandenen Stichtagspreis- und FIFO-Gates benoetigt.

### `GET /api/v1/divorce/coinbase/connector`

Berechnet fuer `end_asset_date` den Coinbase-Bestand ausschliesslich aus den
importierten Canonical Events und bewertet positive Mengen ueber den
vorhandenen Stichtagspreisservice. Der Response enthaelt:

- Credential- und letzten Live-Snapshot-Status,
- Importanzahl, Eventanzahl und Historienzeitraum,
- ein semantisches `history_manifest_sha256` ohne Dateinamen, das Dateihashes,
  Event-IDs, Zeitpunkte, Typen, Assets, Mengen, Quotes, Gebuehren, Konten und
  Transaktionsreferenzen bindet,
- Positionen, Mengen, Preisquelle und Preiszeitpunkt,
- fehlende Preise und negative Mengen als harte Review-Gates,
- Kandidaten- oder bereits freigegebenen Stichtagswert.

Der Status `imported_pending_review` bedeutet nicht, dass die Historie
vollstaendig ist. `valuation_review_ready=true` bedeutet nur, dass ein technisch
berechenbarer Kandidat ohne fehlende Preise und negative Mengen vorliegt.

### `GET /api/v1/divorce/coinbase/connector.csv`

Liefert denselben Historien-, Mengen-, Preis- und Reviewnachweis als CSV. Die
Datei wird als `coinbase-history-valuation-evidence.csv` in das Zugewinndossier
und als `coinbase_history_valuation_evidence.csv` in versionierte
Stichtagslaeufe aufgenommen.

### `POST /api/v1/divorce/coinbase/valuation-decisions`

Bindet den serverseitig berechneten Coinbase-Stichtagswert an das aktuelle
Historienmanifest:

```json
{
  "end_asset_date": "2026-07-24",
  "history_manifest_sha256": "64-stelliger-sha256",
  "actor": "user",
  "rationale": "Vollstaendige offizielle Historie geprueft"
}
```

Der Client uebergibt keinen EUR-Wert. V2 lehnt eine veraltete oder unbekannte
Manifest-Summe, fehlende Preise und negative Mengen ab. Wird spaeter ein
weiterer Coinbase-Batch importiert, entsteht ein neues Manifest und die alte
Freigabe gilt nicht fuer den neuen Datenstand. Eine identische Wiederholung ist
idempotent; eine abweichende Freigabe wird nicht ueberschrieben.

### Review Decisions

Eine Nutzerangabe zur Mittelherkunft wird mit
`decision_type=divorce_capital_origin`, `capital_origin=inheritance` und einem
der folgenden `flow_id`-Werte gespeichert:

- `binance_fiat_deposits`,
- `moonpay_apple_pay_onramp`,
- `coinbase_bank_transfers`,
- `trade_republic_bank_transfers`.

Ein externer Depotwert wird erst mit
`decision_type=divorce_external_asset_valuation`, `provider`,
`valuation_date`, `value_eur` und zwingendem `evidence_ref` akzeptiert. Bei
Trade Republic wird der Wert aus dem geprueften Dokument gewonnen; bei
Coinbase aus Historienmanifest, rekonstruierten Mengen und Stichtagspreisen.
In beiden Faellen kann der Browser den EUR-Wert nicht frei vorgeben. Die
Entscheidung ist kein Live-API-Ersatz und aendert keine Krypto-FIFO- oder
Steuerdaten.

## Sparkassen-PDF-Auszugbelege

Die PDF-Auszugbelege sind eine read-only Ergaenzung zur strukturierten
CAMT.052-Bankspur. Der produktive Standard sucht das lexikografisch neueste
Verzeichnis `S_*_Postfach_-_Sammeldownload` unter
`/workspace/steuerreport/usertransfer`. Alternativ setzt
`STEUERREPORT_SPARKASSE_STATEMENT_DIR` ein explizites Verzeichnis.

### `GET /api/v1/divorce/sparkasse-statements`

Extrahiert lokal aus PDFs mit maschinenlesbarer Textebene:

- Auszugsnummer, Auszugsjahr und Zeitraum,
- Anfangs- und Endsaldo mit voller Decimal-Genauigkeit,
- nur die letzten vier Stellen des Kontos plus SHA-256-Kontofingerprint,
- Kryptoplattform-Abbuchungen mit Buchungsdatum, Anbieter, EUR-Betrag und
  PDF-Seitenreferenz,
- den exakten, mehrdeutigen oder fehlenden Gegenbeleg aus CAMT.052 anhand von
  Buchungsdatum, normalisiertem Anbieter und exaktem EUR-Betrag.

Dateinamen, volle IBAN, Kontoinhaber, Gegenparteien und Verwendungszwecke
werden nicht ausgegeben. Jede Datei und der gesamte Dokumentbestand sind per
SHA-256 gebunden. `calculation_effect=corroboration_only_no_duplicate_flow`
bedeutet, dass der PDF-Treffer nur den bestehenden CAMT-Investmentfluss
zusaetzlich belegt. Er erzeugt weder einen zweiten Investmentfluss noch ein
Canonical Event, Ledger Entry, Tax Lot oder eine Steuerzeile.

### `GET /api/v1/divorce/sparkasse-statements.csv`

Liefert denselben datensparsamen Dokument- und PDF-zu-CAMT-Abgleich als CSV.
Der Endpoint ist read-only. Bei einem PDF ohne maschinenlesbare Textebene wird
`text_unavailable` gemeldet; es findet keine automatische OCR und keine
Interpretation unbekannter Transaktionen statt.

## Aktueller Kryptosteuer-Rechtsstand

### `GET /api/v1/tax-methodology/legal-research/sources`

Liefert die versionierte Registry der ueberwachten offiziellen
Gesetzesabschnitte, BMF-Schreiben, Gerichtsentscheidungen und
Gesetzgebungsfundstellen sowie die konfigurierten BMF-, BFH- und Bundestags-
Suchmonitore. Nur fest erlaubte offizielle HTTPS-Hosts sind zulaessig. Der
Response enthaelt keine Secrets und keine persoenlichen Falldaten. Jede
Direktquelle besitzt eine versionierte `reviewed_sha256`-Baseline; ein
Monitorlauf kann diese Baseline nicht automatisch uebernehmen oder ersetzen.

### `GET /api/v1/tax-methodology/legal-research/freshness`

Liefert den letzten versionierten Aktualitaetslauf mit:

- `generated_at`, `fresh_until`, `registry_version`, `status` und `is_fresh`,
- Einzelchecks mit URL, HTTP-Status und Inhalts-Hash,
- Suchmonitorstatus und neu entdeckten offiziellen Fundstellen,
- geaenderten oder fehlgeschlagenen Quellen,
- Findings, Folgeaktionen und Artefaktpfad.

Ein beim Lesen abgelaufenes Ergebnis wird als `stale` ausgegeben. Nur
`status=fresh`, erreichbare Pflichtquellen und eine leere Reviewliste erfuellen
die BMF-Matrix-Anforderung `current_legal_sources`. Der Endpoint startet keine
Webabfrage und aendert keine Steuerdaten; den Lauf fuehrt der separate
Systemd-Dienst aus.

Bei Bundestags-HIB-Kurzmeldungen entfernt die Inhaltsnormalisierung
ausschliesslich den dynamischen, am Dokumentende stehenden Footer
`Stand: TT.MM.JJJJ`. Der eigentliche Artikeltext, das Artikeldatum und alle
anderen sichtbaren Inhalte bleiben Bestandteil des SHA-256-Fingerprints. So
loest ein taeglich geaendertes Druckdatum keinen falschen Rechtsquellenalarm
aus; jede fachliche Textaenderung bleibt fail-closed reviewpflichtig.

## KI-Provider Und Explizite Textaufgaben

`GET /api/v1/ai/provider` liest Konfiguration, Revisionshash, Aktivierungen
und Key-Metadaten ohne Netzwerkabfrage oder Secret-Werte. Frische Installationen
haben keine Adresse, Modell-ID oder Keys und erlauben keine Cloud-Zugriffe.
Ein bisheriges lokales Installationsprofil wird nur als kompatibler Startwert
gelesen; gespeicherte neue Provider-Einstellungen haben Vorrang.

`PUT /api/v1/ai/provider` speichert `provider` (`local`, `openrouter`, `cloud`),
`base_url`, `model`, Token-/Zeitlimit, optionale lokale Thinking-Steuerung,
`local_enabled`, `external_enabled` und die erwartete `revision` atomar.
`api_key=null` behaelt den vorhandenen Key, ein neuer Wert ersetzt ihn;
`clear_api_key=true` entfernt ihn. Key-Werte werden nur mit verfuegbarem Vault
verschluesselt gespeichert und an Anbieter plus Adresse gebunden. Bei einem
Adresswechsel ist Ersetzen oder explizites Entfernen erforderlich. Cloud
erfordert HTTPS; fuer `openrouter` gilt `https://openrouter.ai/api/v1`.

`POST /api/v1/ai/provider/models` fragt ausdruecklich die Modellliste ab;
`POST /api/v1/ai/provider/test` sendet ausschliesslich einen neutralen Testtext
mit standardmaessig 128 Antworttoken. `probe_max_tokens` ist fuer Modelle mit
groesserem Reasoning-Bedarf bis 2048 konfigurierbar, begrenzt durch `max_tokens`.
Beide verwenden die gespeicherte Verbindung,
Cloud nur nach globaler Aktivierung und mit Key. Tests koennen kostenpflichtig
sein. Es gibt keine automatischen Abrufe beim Lesen/Speichern, keine Redirects,
keine Wiederholungen und keinen stillen Modellwechsel. Anbieterfehler werden
als feste Fehlercodes ohne Originalbody, Key oder Anfrageinhalt ausgegeben.

`POST /api/v1/ai/tasks` legt weiterhin Aufgaben an; die Ausfuehrung startet erst
ueber `POST /api/v1/ai/tasks/{task_id}/execute`. Fuer Cloud muessen die Aufgabe
`allow_external=true` und der Ausfuehrungsaufruf `confirm_external=true` enthalten.
Die Oberflaeche sendet ausserdem `provider_revision`; bei zwischenzeitlich
geaenderter Konfiguration wird die Ausfuehrung vor der Uebermittlung blockiert.
Jede Ausfuehrung bindet ihren Provider-Snapshot an dessen Revision.

Statusfolge: `queued` -> `running` -> `done` oder `failed`. Ein atomarer Claim
verhindert parallele Doppelaufrufe derselben Aufgabe. `done` liefert bei
erneutem Ausfuehrungsaufruf das gespeicherte Ergebnis; Fehler werden nicht
automatisch wiederholt. Nach einem Prozessabbruch ist `running` kein Nachweis
einer abgeschlossenen oder nicht abgerechneten Anfrage. Vor einer neuen Aufgabe
muessen Verlauf und Anbieterstatus geprueft werden.

Der Modellkontext besteht nur aus der festen Systemanweisung und maximal
32000 Zeichen eingegebenem Text. Es gibt keine SQL-/Datei-/Korrekturwerkzeuge,
keinen automatischen Datenexport und keine Fachbuchungen aus Modellantworten.
`result_json` enthaelt sichtbare Antwort, Provider, angeforderte/gemeldete
Modell-ID, Revisionshash, begrenzte Nutzungsmetadaten und `review_only=true`.
Reasoning-only-Antworten gelten als fehlgeschlagen. Validierungsantworten der
KI-Endpunkte spiegeln keine Eingabewerte zurueck. Die bestehende Verantwortung
des Betreibers fuer Zugriffsschutz und Transportabsicherung bleibt bestehen.

Die Modellliste ergaenzt `is_free` (bool oder null),
`prompt_price_usd_per_token`, `completion_price_usd_per_token`,
`request_price_usd` und `context_length`. Preisfelder werden ausschliesslich
fuer den OpenRouter-Katalog interpretiert. Die Pruefung verwendet endliche,
nichtnegative Decimal-Werte. `is_free=true` verlangt null fuer beide Textpreise
und den Anfragepreis (ohne ausgewiesene Anfragegebuehr wird null angesetzt).
Ein positiver Preis ergibt false, unbekannte oder ungueltige Preise ohne
positiven Gegenbeleg ergeben null. Der Namenszusatz `:free` ersetzt diese
Preispruefung nicht. Diese Metadaten sind ein Katalogstand, keine Preisgarantie;
der Abruf startet keine Modellinferenz und aendert keine gespeicherte Auswahl.
