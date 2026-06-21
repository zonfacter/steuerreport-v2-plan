# API Contracts V2

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
`G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY`. Die Schnittstelle aggregiert
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

Wertet die Datei `Wallet.G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY-month.csv`
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
letztem Live-Stand und Import-/Review-Kontext. Wenn ein gespeicherter
Live-Snapshot vorhanden ist, kann `value_eur` der API-Anzeigewert sein;
`ledger_value_eur`, `delta_value_eur`, `live_anchor_source` und
`display_warning` bleiben zur steuerlichen Einordnung sichtbar.

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
- Rewards: `reward`, positive Menge auf dem Earn-Produktkonto
- Locked-Subscriptions mit `type=AUTO`: belegtes Transfer-Event mit Menge `0`,
  weil dies eine Auto-Renewal-/Rollover-Buchung derselben Position ist und den
  Bestand nicht erneut erhoehen darf

Der Endpoint ist kein Live-Balance-Fix. Er erzeugt belegbare Historienereignisse
aus Binance-API-Rohdaten; verbleibende Live-vs-Ledger-Deltas bleiben im
Reconciliation-Drilldown sichtbar und duerfen nicht automatisch als FIFO-Trade
oder Ledger-Korrektur gebucht werden.

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

## Preise

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
`coingecko:simple-price:eur`. Diese aktuellen Preise gewinnen im
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

`POST /api/v1/tax/fifo/rebuild`

Erzeugt FIFO-Lots und steuerliche Ergebniszeilen aus Canonical Trade Events.
Positive Trade-Mengen erzeugen Lots, negative Trade-Mengen verbrauchen FIFO.
EUR-Werte kommen aus `quote_asset=EUR` und `quote_quantity` oder ersatzweise aus
dem Price-Ledger.
Bei Crypto-zu-Crypto-Kaeufen kann die nicht-stabile Quote-Seite ebenfalls als
Veraeusserung erfasst werden, wenn fuer das Quote-Asset bereits ausreichende
FIFO-Lots vorhanden sind. Stablecoin-Quote-Seiten bleiben im MVP deaktiviert,
damit unvollstaendige historische Startbestaende keinen Exportblocker erzeugen.

`GET /api/v1/tax/lines`

Listet steuerliche Ergebniszeilen mit Anschaffungskosten, Erloes,
Gewinn/Verlust und Haltedauer.

`GET /api/v1/tax/lots`

Listet FIFO-Lots aus dem letzten Steuerlauf mit Anschaffungszeitpunkt,
Gesamtmenge, Restmenge und Kostenbasis.

`GET /api/v1/tax/summary`

Liefert den letzten FIFO-Lauf mit Tax-Line-Anzahl, unmatched Abgaengen und
Run-ID. Das Frontend nutzt diese Daten im Steuerlauf-Tab.

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
