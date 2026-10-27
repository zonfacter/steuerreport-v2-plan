# CEX-Historienadapter: Quellen und Grenzen

Referenz- und Abrufdatum aller nachstehenden Quellen: **2026-10-27 (UTC)**.
Nur offizielle Provider-Dokumentation wurde fuer Endpunktsemantik verwendet.
Keine echten Schluessel, Konten oder Provider-API-Aufrufe wurden getestet.
Die Verifikation erfolgt ausschliesslich mit isolierten Antwort-Mocks.

## Integrationsvertrag

`CexHistoryCollector(store, target, options).fetch_page(cursor, check)` liefert
eine `HistoryPage`. `requires_symbols(provider)` ist eine modulweite Funktion;
Provider-Namen werden ohne Beachtung der Gross-/Kleinschreibung behandelt.
Binance und Pionex verlangen ein explizites Symbolset. Fehlende Symbole fuehren
zu `cex_history_symbols_required` mit `resumable=False`, nicht zu einer leeren
oder vermeintlich vollstaendigen Historie. Keine Marktsuche aus aktuellen Salden.

Eine Seite enthaelt hoechstens 100 Provider-Datensaetze und verursacht hoechstens
zwei logische Adapter-Aufrufe: einen Historienabruf und gegebenenfalls einen Abruf
der Symbol-Metadaten. Der zentrale HTTP-Transport kann kontrollierte Retries
ausfuehren; inklusive dieser Versuche gilt ein hartes Limit von fuenf Requests
pro Seite. Der lokale Balance-Service-Untertyp umhuellt den bestehenden Signierer,
ruft auch vor jedem Retry `check()` auf und blockiert einen sechsten Versuch vor
dem Transport. `requests` beruecksichtigt diese Signiervorgaenge. Transport,
Signierer, Limits und die vom Elternjob gesetzte Outbound-Scope bleiben zentral.
Ein Netzwerkfehler, Abbruch oder ungueltiger Datensatz liefert keinen neuen Cursor.
Der uebergebene Cursor wird niemals veraendert.

Nur `CexBalanceService(store, connection_id=target.connection_id)._credentials(...)`
wird verwendet. Fehlende/leere Connection-IDs werden standardmaessig abgewiesen.
Einzige Ausnahme: `connection_id is None`, `legacy_credentials is True` und
`target.account == provider` muessen gleichzeitig gelten. Nur dann darf der
Elternresolver den einzelnen bekannten Legacy-Provider-Schluesselsatz freigeben;
die Pruefung, dass keine individuellen Connections existieren, bleibt dort.
Leere Strings erlauben diese Ausnahme nicht. Explizite ungueltige Connections
werden auch mit gesetztem Legacy-Flag niemals durch globale Schluessel ersetzt.
Der Adapter liest oder schreibt keine DB.

`target.account` ist das exakte Buchungskonto, auch fuer `connection:<UUID>` und
Legacy-Konten wie `binance`. Provider-Kontonamen aus Antworten werden nicht
uebernommen. Die bestehenden `source_profiles` bestimmen die Zeilenschluessel;
`HistoryRecord.source` bleibt `binance`, `bitget`, `pionex` bzw. `coinbase`.
Es werden keine neuen produktiven Profile eingefuehrt. Insbesondere werden
Binance-`utc time`/`coin`/`change`, Bitget-`time`/`amount`/`type` und die abweichenden
Coinbase-Quote-/Fee-Spalten beruecksichtigt. Zeitangaben enthalten explizites UTC.

Identitaeten bestehen aus Provider, **exaktem Zielkonto**, Endpunkt und externer
Record-ID. Bei Fills kommt das Symbol hinzu, da Trade-IDs marktbezogen sein
koennen. Order-ID oder TX-Hash ersetzen keine fehlende Fill-/Transfer-Record-ID.
Die Identitaet ist unabhaengig von Job, Seite, Abrufzeit und Connection-Label.

`record.raw['payload']` ist eine unveraenderte Kopie des einzelnen originalen
Provider-Records. `record.raw['endpoint']` enthaelt die Herkunft. Der finanzielle
Digest des Elternimports soll `rows` plus `raw.get('payload', raw)` verwenden,
nicht Response-Umschlaege, Abfragefenster oder aktuelle Marktmetadaten.
Der vollstaendige dekodierte Antwortkoerper steht separat in
`page.extra['response']`, sein Endpunkt in `page.extra['endpoint']`. Ein Elternjob,
der diesen Seitenumschlag archivieren will, muss `extra` gesondert persistieren;
der einzelne Provider-Record bleibt auch ohne dieses Archiv in jedem Raw-Record
erhalten. Bytes/HTTP-Header werden nicht als Originaldatei vorgetaeuscht.

Zeitbereich: `[options.start, options.end]`, passend zum inklusiven gerundeten Ende
des Elternjobs. Intern wird eine halboffene Millisekundengrenze verwendet.
Zeitzonen und Millisekunden-Praezision
sind erforderlich. Cursor-Version 1 bindet Provider, Quelle, Konto, Connection,
Zeitraum und normalisierte Symbole per Hash. Er enthaelt nur JSON-Werte und keine
Schluessel. Elternjobs uebernehmen dauerhafte Speicherung, Crosspage-Deduplikation,
Freigaben und Quellbindung. Widerspruechliche identische Record-IDs innerhalb
einer Seite werden abgewiesen. `done=True` bedeutet ausschliesslich: Die hier
implementierten Endpunkt-/Symbol-/Zeitfenster sind durchlaufen.
**`complete_history_proven` bleibt immer `False`.**

## Binance

Offizielle Quellen:

- [Account trade list / myTrades](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/account)
- [Capital: Deposit History und Withdraw History](https://developers.binance.com/en/docs/catalog/core-trading-wallet/api/rest-api/capital)
- [Exchange information](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/general)

`GET /api/v3/myTrades`: Symbol ist Pflicht, `limit=100` liegt unter dem Maximum
1000. Der Abstand zwischen `startTime` und `endTime` darf 24 Stunden nicht
ueberschreiten. Die dokumentierten Parameterkombinationen erlauben **nicht**
`fromId` zusammen mit Zeitgrenzen. Der Adapter verwendet daher inklusive
Milliskundenfenster von hoechstens einem Tag und teilt volle Seiten binaer.
Die bereits zurueckgegebenen Records koennen in Teilfenstern erneut erscheinen;
der Elternjob muss sie nach stabiler Identitaet deduplizieren. Eine volle Seite
im einzelnen Millisekundenfenster blockiert mit `cex_history_timestamp_saturated`.
Es wird nicht mit `letzter Zeitstempel + 1` ueber unbekannte Fills gesprungen.

`isBuyer` muss ein JSON-Boolean sein; `qty` und `quoteQty` liefern beide
tatsaechlichen Handelsmengen. `commission`/`commissionAsset` bleiben eine
separate Gebuehr, auch wenn sie in einem dritten Asset bezahlt wurde.
`GET /api/v3/exchangeInfo` liefert `baseAsset`/`quoteAsset`; es gibt keine
Suffix-Heuristik fuer kompakte Paare. Fehlende/veraltete Metadaten, etwa bei
delisteten Maerkten, blockieren die Seite statt Assets zu erraten.

`GET /sapi/v1/capital/deposit/hisrec` und
`GET /sapi/v1/capital/withdraw/history` verwenden 30-Tage-Fenster, explizite
Zeitgrenzen, `limit=100` und `offset`. Das unterschreitet die dokumentierte
90-Tage-Fenstergrenze. Funding bleibt unabhaengig von den Fill-Symbolen ungefiltert.
Deposit-Status `1` wird als Transferzufluss normalisiert, nicht als Einkommen.
Nicht abgeschlossene Deposits bleiben **Rohbelege ohne Buchungszeilen**.
Status `6` (gutgeschrieben, aber nicht abhebbar) und erfolgreiche Withdrawals
erzeugen dagegen ein `unknown`-Ereignis mit Menge null, dem tatsaechlichen Asset,
Zeitpunkt und Konto sowie `history_classification_required='1'`. Es ist kein
Abfluss, Trade oder Einkommen und hat keine angenommene Gebuehr. Der Elternjob
muss den Export ueber das Review-Gate bis zur Klassifikation blockieren; die
bestehende validierte AI-Korrektur kann das Ereignis anschliessend bearbeiten.
Withdrawal-`amount`/`transactionFee` werden im Original erhalten, aber ohne
Brutto-/Nettonachweis nicht zu einem Kontodelta zusammengesetzt. Fuer Belege
wird `insertTime` bzw. das dokumentiert in UTC liegende `applyTime` verwendet;
es wird kein Abschlusszeitpunkt erfunden.

Luecken: Earn/Rewards, Convert, Fiat, Margin, Futures, interne Umbuchungen,
fehlende Symbolsets sowie nicht mehr angebotene historische Maerkte.
Die konservative Fensterstrategie braucht seit 2009 pro Symbol mehrere Tausend
leere Tagesabfragen. Es gibt keine heuristische Verkuerzung anhand von Salden.
Die offiziell zulaessige Alternative `symbol + fromId` ohne Zeitfilter wird hier
nicht mit Zeitfiltern vermischt; eine spaetere reine ID-Scan-Strategie benoetigt
eine eigene Grenz-/Deduplikationsverifikation. Der Job bleibt abbrech-/fortsetzbar.

## Bitget

Offizielle Quellen:

- [Classic Spot Trade: Get Fills](https://www.bitget.com/docs/catalog/classic-spot-trade/classic-spot-trade#get-fills)
- [Classic Spot Account: Get Deposit Records / Get Withdrawal Records](https://www.bitget.com/docs/catalog/classic-spot-account/classic-spot-account#get-deposit-records)
- [Classic Spot Market: Get Symbol Info](https://www.bitget.com/docs/catalog/classic-spot-market/classic-spot-market#get-symbol-info)

Die frueheren `/api-doc/spot/...`-Dokumentationslinks leiteten beim Abruf auf die
UTA-Einfuehrung um. Fuer diesen Adapter wurden die aktuellen **Classic**-Seiten
gelesen; die Account-/Market-Seiten mussten als offizielles HTML abgerufen werden.

`GET /api/v2/spot/trade/fills`: `symbol` ist optional; der Adapter kann alle
Spot-Symbole abrufen oder explizite Symbole einzeln durchlaufen. Er sendet
30-Tage-Fenster (unterhalb des Maximums 90 Tage), `limit=100` und fuer Folgeseiten
`idLessThan=<kleinste tradeId>`. Der aktuelle offizielle v2-Response ist eine
**Liste in `data`**, kein Futures-`fillList`/`endId`-Objekt. Ein anderes Shape wird
nicht geraten. `orderId` ist keine geeignete Fill-Paginierungs-ID.
Die API liefert laut Dokumentation nur Fills der letzten 90 Tage. Daher wird
**nur fuer Fill-Streams** der Scanbeginn auf das aktuelle UTC-Abrufdatum minus
90 Tage plus eine Minute Sicherheitsabstand geklemmt. Dieser Beginn steht als
`fill_start` dauerhaft im Cursor und driftet beim Resume nicht. Jede Seite nennt
die ausgelassene Abdeckung explizit; CSV-Exporte bleiben noetig. Liegt der gesamte
gewuenschte Zeitraum vor dieser Grenze, werden keine unzulaessigen Fill-Abfragen
gesendet. Deposit-/Withdrawal-Streams beginnen unveraendert am Originalstart.
Die globale Optionsbindung wird nicht durch das Retentionsfenster ersetzt.

`size`/`amount` liefern Basis-/Quotemenge; `baseCoin`/`quoteCoin` kommen aus
`GET /api/v2/spot/public/symbols`. Die `cTime`-Tabelle nennt Sekunden, das offizielle
Beispiel Millisekunden. Der Adapter akzeptiert eindeutig zehnstellige Sekunden
und Millisekunden und schreibt in beiden Faellen UTC. `feeDetail` muss die
dokumentierte einzelne Objektform mit `feeCoin` und `totalFee` haben. Negative
`totalFee` werden einmal als gezahlte Gebuehr normalisiert. `totalDeductionFee`
wird nicht nochmals addiert. Positive Rebates, `newFees` und andere mehrdeutige
Fee-Shapes blockieren statt Einkommen oder Gebuehren zu erfinden.

`GET /api/v2/spot/wallet/deposit-records` und
`GET /api/v2/spot/wallet/withdrawal-records`: explizite 30-Tage-Fenster,
`limit=100`, `idLessThan=<kleinste orderId>`. `type` muss zum Endpunkt passen;
nur `status=success` bei Deposits erzeugt einen Transferzufluss. `pending` und
`fail` bleiben Rohbelege ohne Bestandswirkung. Erfolgreiche Withdrawals erzeugen
wie bei Binance ein `unknown`-Null-Ereignis mit
`history_classification_required='1'`, tatsaechlichem Asset/Zeitpunkt/Konto und
ohne Mengen-/Gebuehrenannahme. Der Marker erzwingt beim Elternjob eine manuelle
Klassifikation statt eine erfolgreiche Auszahlung still zu ueberspringen.
Die Dokumentation nennt `size` und `fee`, belegt aber hier keine fuer den
Adapter hinreichend eindeutige Netto-/Bruttobeziehung. Fehlende Details werden
nicht aus Kontostaenden oder Handelsvolumen abgeleitet.

Luecken: alte Fills, UTA, Earn, Convert, Margin, Futures, interne Umbuchungen und
nicht eindeutig dokumentierte Fee-Varianten. Eine leere alte Fill-Seite beweist
keine Abwesenheit historischer Trades.

## Pionex

Offizielle Quellen:

- [Get Fills](https://pionex-doc.gitbook.io/apidocs/restful/orders/get-fills)
- [Authentication](https://pionex-doc.gitbook.io/apidocs/restful/general/authentication)
- [Offizielle Trade-OpenAPI](https://raw.githubusercontent.com/pionex-official/pionex-open-api/main/openapi.yaml)
- [Offizielle Wallet-OpenAPI](https://raw.githubusercontent.com/pionex-official/pionex-open-api/main/openapi_wallet.yaml)

`GET /api/v1/trade/fills`: Pflichtsymbol `BASE_QUOTE`, `startTime`/`endTime` in
Millisekunden, absteigend sortierte Fills. Es gibt keinen dokumentierten
`limit`-/ID-Cursorparameter. Bei mehr als 100 Fills liefert die API nur die
neuesten 100. Der Adapter sendet **kein erfundenes Limit** und verwendet dieselbe
Zeitfensterteilung mit Saturierungsblockade wie bei Binance. Anders als Binance
dokumentieren die gepruefte Fill-Seite und die offizielle OpenAPI kein maximales
Zeitintervall. Daher wird zuerst der gesamte gewuenschte Zeitraum abgefragt und
nur bei vollen 100er-Seiten geteilt. Das vermeidet Tausende leere Tagesabfragen
bei duennen Historien, ohne Maerkte oder Kontobeginn aus Salden zu erraten.
Ein undokumentiertes Provider-Limit wird als Fehler behandelt, nicht als
Vollstaendigkeitsnachweis. Der numerische Filterwert null wird laut Pionex
ignoriert; bei Unix-Epoche null beginnt die Abfrage daher explizit bei
Millisekunde 1 und nennt diese Grenze. Selbsthandel kann
Maker-/Taker-Records erzeugen; widerspruechliche gleiche Record-IDs werden nicht
zu einer einzelnen vermeintlich gesicherten Buchung zusammengezogen.

`size` und der tatsaechliche Fill-`price` ergeben die Quotemenge. Das ist keine
Marktpreisannahme. `fee`/`feeCoin` werden separat erhalten; negative oder fehlende
Gebuehrenwerte werden nicht still auf null gesetzt. Basis-/Quoteasset sind im
dokumentierten Spot-Symbol explizit getrennt.

Der lokale `_pionex_get` ergaenzt den fehlenden Parameter-Support des bestehenden
Balance-Helfers, ohne diesen zu veraendern. Er sortiert Query-Schluessel inkl.
frischem `timestamp` aufsteigend, signiert `GET + PATH + '?' + QUERY` per
HMAC-SHA256 und delegiert an denselben `_get_json`/`request_signer`-Transport.
Nur validierte ASCII-Symbole und Ganzzahlen gelangen in die Query; Signaturwerte
bleiben wie dokumentiert unkodiert, die HTTP-URL wird separat kodiert.

Die geprueften offiziellen Trade-/Wallet-Spezifikationen enthalten keine
allgemeinen Deposit-/Withdrawal-History-Endpunkte. Solche Endpunkte werden
nicht erfunden. Bot-, Earn-, Futures- und Funding-Historien bleiben Luecken.

## Coinbase

Offizielle Quellen:

- [Advanced Trade: List Fills](https://docs.cdp.coinbase.com/api-reference/advanced-trade-api/rest-api/orders/list-fills)
- [Advanced Trade REST Endpoints](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/rest-api)
- [Coinbase Markets Trading Rules, Abschnitte 1.9 und 5](https://www.coinbase.com/legal/trading_rules)

`GET /api/v3/brokerage/orders/historical/fills`: `limit=100`,
`product_types=SPOT`, optional ein `product_ids`-Filter pro Symbol,
`start_sequence_timestamp`, `end_sequence_timestamp` und der dokumentierte
opake `cursor`. Kein `has_next`-Feld wird erfunden. Ein nichtleerer Cursor wird
auch bei weniger als 100 Records verfolgt. Eine volle Seite ohne Cursor, ein
unveraenderter Cursor und ein Cursor bei leerer Seite blockieren. Der offizielle
Hinweis auf instabile Paginierung verhindert jede Vollstaendigkeitszusage.

Da die Startgrenze als exklusiv beschrieben ist, beginnt der Serverfilter eine
Millisekunde vor dem gewuenschten Start; die exklusive Server-Endgrenze liegt eine
Millisekunde nach dem inklusiven gewuenschten Ende. Alle Records werden validiert
und dann lokal auf `[start,end]` gefiltert; die Pagination beruht weiter auf dem gesamten
Response. `proof_token_required=true` wird als Setup-/Berechtigungsproblem
abgewiesen, nicht als leere Historie interpretiert. Es gibt keinen Proof-Token-
Bypass und keinen Zugriff auf andere Portfolios mit einem anderen Schluessel.

Nur `trade_type=FILL`, eindeutiges `BUY`/`SELL` und Spot-Paare `BASE-QUOTE` sind
zulaessig. Externe Record-ID ist `entry_id`, nicht `order_id`. Bei
`size_in_quote=false` wird Basisgroesse mit dem echten Fill-Preis multipliziert;
bei `true` wird eine Basisgroesse nur bei mathematisch exakter dezimaler
Division abgeleitet. Nicht abbrechende Dezimaldivisionen blockieren. `commission` wird
gemaess den Trading Rules einmal im Quoteasset angesetzt. Fehlende Mengen,
Gebuehren oder uneindeutige Richtungen werden nicht aus anderen Feldern geraten.

Die Advanced-Trade-Endpunktliste bietet keine allgemeine Ein-/Auszahlungshistorie.
Coinbase-App-/OAuth-, Exchange- und Prime-APIs sind andere Vertraege und werden
nicht unterstellt. Simple Buy, Convert, Transfers, Funding, Staking und Rewards
bleiben explizite Luecken dieses Adapters.

## Tests

`python3 -B -m pytest -q -p no:cacheprovider tests/unit/test_history_cex.py`

Die Tests blockieren reale HTTP-Aufrufe und Credential-Aufloesung standardmaessig.
Sie pruefen Provider-Shapes, Profile/Normalizer, Konto- und Connection-Isolation,
Rohbelege und stabile IDs, Cancellation vor allen Adapter-Aufrufen, JSON-Resume,
Zeit-/Symbolfilter, volle Seiten und Saturierung, Funding-Status, Gebuehren,
fehlerhafte Antworten, Mengen/Richtungen/IDs und den Pionex-Signaturinput.
Produktionsimporte, DB-Migrationen, Freigaben und Deployment sind nicht Teil
dieser isolierten Adapterarbeit.
