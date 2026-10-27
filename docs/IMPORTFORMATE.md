# Importformate und Spaltenlayouts (0.2.0rc24)

Generiert aus den tatsaechlichen Importprofilen. Keine Zusage fuer beliebige Exporte eines Anbieters.

## Allgemeine Regeln

- Unterstuetzte Dateitypen: .csv, .xlsx und .xls. CSV: UTF-8 mit oder ohne BOM, Komma oder Semikolon als Trennzeichen. Bei Komma als Trennzeichen muessen Felder mit Kommas in doppelte Anfuehrungszeichen eingeschlossen sein. Keine PDF-, ZIP-, JSON-, ODS-, Bild- oder Wallet-Backup-Dateien; Umbenennen aendert das Format nicht.

- Tabellenlayout: eine eindeutige Kopfzeile, darunter je Rohposition eine Datenzeile. Spaltenreihenfolge frei; keine verbundenen Zellen, Summenzeilen oder mehreren Tabellen nebeneinander. Zusaetzliche Spalten bleiben Rohdaten, werden aber nicht automatisch fachlich ausgewertet. Excel: richtiges Blatt waehlen; CSV: kein Tabellenblatt. Vorlagenblattnamen sind identisch mit der auszuwaehlenden Quelle. In Excel Datumswerte vorzugsweise als ISO-Text speichern, keine Formeln als einzige Datenquelle oder Passwortverschluesselung verwenden.

- Technisches Minimum je Profil: gueltiger Zeitpunkt, Asset (oder unterstuetztes Paar-/Speziallayout) und gueltige Menge. Eine vorhandene Spalte mit leeren oder unlesbaren Werten reicht nicht. type ist nicht fuer die Spaltenerkennung verpflichtend, aber fuer eine belastbare Zuordnung wesentlich. Ein importierbarer Spaltenkopf beweist weder vollstaendige Einzelzeilen noch vollstaendige Steuerdaten.

- Spaltennamen: Gross-/Kleinschreibung wird ignoriert, Unterstriche werden zu Leerzeichen, fuehrende/nachfolgende und wiederholte Leerzeichen normalisiert. Andere Satzzeichen und Klammern sind nicht frei austauschbar. Die Tabellen zeigen echte Profil-Aliase in Suchreihenfolge, nicht zusaetzliche Pflichtspalten. In der Regel genuegt ein Alias je Feld. Konkurrierende Alias-Spalten vermeiden; quellenspezifische Sonderregeln koennen Vorrang haben.

- Zeitpunkt: empfohlen 2025-01-15T10:00:00Z oder 2025-01-15T11:00:00+01:00. Beide Beispiele meinen denselben Zeitpunkt. Weitere erkannte Formen sind YYYY-MM-DD HH:MM:SS, YYYY/MM/DD HH:MM:SS, DD.MM.YYYY HH:MM:SS und DD.MM.YYYY HH:MM. Ohne Offset gilt normalerweise UTC; Bitget verwendet UTC+8. Erkannte UTC+/-Angaben in Spaltennamen, bei Binance auch im Dateinamen, koennen die Standardzeitzone vorgeben. Bewahren Sie diese Angaben im Original auf. Unix-Sekunden/-Millisekunden nicht als allgemein unterstuetzt voraussetzen. Ein Datum ohne Uhrzeit ersetzt keine genaue Ausfuehrungszeit.

- Zahlen: vorzugsweise Dezimalpunkt ohne Tausendertrennzeichen, z. B. 0.001 oder -25.50; Dezimalkomma nur mit korrekt getrennten/quotierten Feldern. Keine Waehrungszeichen oder Textzusatz in eigenen Mengenfeldern. Mengen, Handelsgegenwert und Preis je Token sind verschiedene Groessen. Vorzeichen aus dem Beleg erhalten; type kann die Richtung zusaetzlich bestimmen. Ein positiver Zufluss ist nicht automatisch Einkommen, Handelsvolumen keine EUR-Auszahlung.

- Fuer eine vollstaendige Auswertung: Konto/Wallet, Original-ID, Ereignisart, beide Handelsseiten, Gebuehren und benoetigte historische Preise/Anschaffungen belegen. Fehlende Anschaffungswerte oder Preise nicht erfinden und nicht beliebig in quote_quantity eintragen. Die Technik kann ohne diese Angaben Zeilen lesen, waehrend die steuerliche Auswertung offen bleibt. Getrennte Exporte von Trades, Transfers, Rewards und Derivaten gemeinsam auf Vollstaendigkeit und Ueberschneidungen pruefen.

- Grenzen: maximal 20 Dateien, je 25 MiB und zusammen 100 MiB im normalen Importdialog. Erst Vorschau pruefen, dann ausdruecklich freigeben; danach Ereignisse, nicht zugeordnete Zeilen und Review-Hinweise kontrollieren. Eine reine Kopfzeile ist absichtlich nicht importierbar. Die Downloads enthalten keine Beispieltransaktionen, Konten oder Geheimnisse.

- Originale niemals fuer eine Layoutanpassung ueberschreiben. Eine normalisierte Kopie mit Bezug auf Originaldatei und Hash getrennt sichern. Kein anderes Profil waehlen, um eine Pruefung zu umgehen. Blockpit und andere Sammelplattformen sind hier keine weitere primaere Handelshistorie; nicht als zweite Buchung derselben Transaktionen einschleusen. Identische Dateihashes verhindern nicht jede Doppelbuchung aus ueberlappenden Exporten.

## Manuelles CSV (`manual-csv`)

Eigene belegte Tabellen. buy/sell/trade/convert werden als Handel, deposit/withdrawal/transfer als Transfer, reward/mining/staking als entsprechende Ereignisart erkannt. type ist technisch nicht Pflicht, ohne erkennbaren Typ kann aber unknown entstehen. Bei Verkaeufen negative Asset-Menge oder sell; Auszahlungen negativ oder withdrawal. Gegenmenge und Gebuehr als positive Betraege mit eigenem Asset angeben. Betrag ist eine Tokenmenge, nicht automatisch ein EUR-Wert.

Leere CSV: `frontend/public/import-vorlagen/manual-csv.csv`

Fiktives Beispiel, nicht Bestandteil der leeren Vorlage:

```csv
time,asset,amount,type,quote_asset,quote_quantity,fee_asset,fee_quantity,account,tx_id
2025-01-15T10:00:00Z,BTC,0.001,buy,EUR,70,EUR,0.10,beispiel-konto,beispiel-manuell
```

| Feld / Bedeutung | Alternative Namen in Profil-Suchreihenfolge |
| --- | --- |
| Zeitpunkt: technisch erforderlich | `time` / `date` / `datetime` / `timestamp` / `utc time` / `utc_time` |
| Asset: erforderlich oder passende Paar-/Spezialableitung | `asset` / `coin` / `currency` / `token` |
| Tokenmenge: technisch erforderlich | `amount` / `quantity` / `qty` / `change` / `delta` |
| Ereignisart: fuer die Zuordnung wesentlich | `type` / `operation` / `side` / `category` |
| Handelspaar: optionaler Asset-Ersatz | `pair` / `symbol` / `market` / `trading pair` / `coin pair` |
| Gegenasset: bei Handel erforderlich zur Rekonstruktion | `quote_asset` / `quote asset` / `quote` / `counter asset` |
| Gegenmenge: bei Handel erforderlich zur Rekonstruktion | `quote_quantity` / `quote amount` / `quote_amount` / `total` / `value` |
| Gebuehrenasset: sofern eine Gebuehr anfaellt | `fee_asset` / `fee asset` / `fee coin` |
| Gebuehrenmenge: sofern eine Gebuehr anfaellt | `fee_quantity` / `fee amount` / `fee_amount` / `fee` |
| Konto / Wallet: fuer nachvollziehbare Zuordnung | `account` / `exchange` / `wallet` |
| Transaktions-ID: fuer Nachweis und Abgleich | `txid` / `tx_id` / `hash` / `transaction hash` |
| Quellreferenz: optional, z. B. Order-ID | `id` / `orderid` / `order id` / `txid` / `tx_id` / `hash` |

## Binance CSV (`binance`)

Transaktionshistorie mit Operation/Coin/Change. Change ist die vorzeichenbehaftete Bestandsaenderung, nicht der Geldwert. Einen Mehrzeilen-Trade nicht zu einer zusaetzlichen erfundenen Kaufzeile verdoppeln. Handelsgegenwerte und Gebuehren nur aus belegten Zeilen oder den unten genannten Zusatzfeldern uebernehmen. Das Beispiel ist ein Transfer, kein Einkommen. Nicht jeder Binance-Bericht besitzt dieses Layout.

Leere CSV: `frontend/public/import-vorlagen/binance.csv`

Fiktives Beispiel, nicht Bestandteil der leeren Vorlage:

```csv
UTC_Time,Account,Operation,Coin,Change,Remark,tx_id
2025-01-15T10:00:00Z,Spot,Deposit,EUR,100,Rein fiktives Beispiel,beispiel-binance
```

| Feld / Bedeutung | Alternative Namen in Profil-Suchreihenfolge |
| --- | --- |
| Zeitpunkt: technisch erforderlich | `utc time` / `utc_time` / `time` / `date` / `date(UTC)` / `date(UTC+2)` / `timestamp` |
| Asset: erforderlich oder passende Paar-/Spezialableitung | `coin` / `asset` / `currency` / `receive amount` |
| Tokenmenge: technisch erforderlich | `change` / `amount` / `quantity` / `qty` / `receive amount` |
| Ereignisart: fuer die Zuordnung wesentlich | `operation` / `type` / `side` / `category` / `status` |
| Handelspaar: optionaler Asset-Ersatz | `pair` / `symbol` / `market` / `trading pair` / `coin pair` |
| Gegenasset: bei Handel erforderlich zur Rekonstruktion | `quote_asset` / `quote asset` / `quote coin` |
| Gegenmenge: bei Handel erforderlich zur Rekonstruktion | `quote_quantity` / `quote amount` / `total` / `value` / `spend amount` / `indicated amount` |
| Gebuehrenasset: sofern eine Gebuehr anfaellt | `fee_asset` / `fee asset` / `fee coin` |
| Gebuehrenmenge: sofern eine Gebuehr anfaellt | `fee_quantity` / `fee amount` / `fee` |
| Konto / Wallet: fuer nachvollziehbare Zuordnung | `account` / `wallet` |
| Transaktions-ID: fuer Nachweis und Abgleich | `txid` / `tx_id` / `transaction id` / `hash` |
| Quellreferenz: optional, z. B. Order-ID | `id` / `order id` / `transaction id` / `txid` / `tx_id` |

## Bitget CSV (`bitget`)

Beispiel fuer Ein-/Auszahlungshistorie. Handelslisten koennen stattdessen Trading pair und Executed sowie Action und Transacted amount verwenden. Fuer einen Trade wird ein belegter Gegenwert benoetigt, nicht ein beliebiger USD-Schaetzwert. Spot-Finanzhistorie, Orders und Derivate nicht als identische Vorgangsarten behandeln. Ohne explizite Zeitzone nimmt dieses Profil UTC+8 an, auch bei einer Spalte Time. ISO-Zeitstempel mit Z oder Offset haben Vorrang; im Beispiel ist 18:00 UTC+8 gleich 10:00 UTC.

Leere CSV: `frontend/public/import-vorlagen/bitget.csv`

Fiktives Beispiel, nicht Bestandteil der leeren Vorlage:

```csv
Timestamp UTC+8 (Completion),Coin,Quantity,Type,Transaction hash(txid),Account
2025-01-15 18:00:00,USDT,100,Deposit,beispiel-bitget,beispiel-konto
```

| Feld / Bedeutung | Alternative Namen in Profil-Suchreihenfolge |
| --- | --- |
| Zeitpunkt: technisch erforderlich | `time` / `timestamp utc+8 (completion)` / `timestamp utc+8 (created)` / `timestamp utc+8 (order)` / `creation timestamp (+8 utc)` / `timestamp utc+8 (submission)` / `ctime` / `utime` |
| Asset: erforderlich oder passende Paar-/Spezialableitung | `asset` / `coin` / `currency` |
| Tokenmenge: technisch erforderlich | `amount` / `quantity` / `executed` / `surplus/deduction (after fee)` / `size` |
| Ereignisart: fuer die Zuordnung wesentlich | `type` / `action` / `action (english)` / `status` / `sub category` |
| Handelspaar: optionaler Asset-Ersatz | `trading pair` |
| Gegenasset: bei Handel erforderlich zur Rekonstruktion | `quote_asset` / `quote asset` / `fee deducted in` |
| Gegenmenge: bei Handel erforderlich zur Rekonstruktion | `quote_quantity` / `amount in usdt` / `amount (usdt)` / `transacted amount` / `executed amount (usdt)` |
| Gebuehrenasset: sofern eine Gebuehr anfaellt | `fee_asset` / `fee asset` / `fee deducted in` |
| Gebuehrenmenge: sofern eine Gebuehr anfaellt | `fee_quantity` / `fee` / `fee (coin quantity)` / `withdrawal fee` |
| Konto / Wallet: fuer nachvollziehbare Zuordnung | `account` |
| Transaktions-ID: fuer Nachweis und Abgleich | `transaction hash(txid)` / `txid` / `tx_id` / `order no.` / `order number` / `id` |
| Quellreferenz: optional, z. B. Order-ID | `source_ref` / `order no.` / `order number` / `id` / `transaction hash(txid)` |

## Pionex CSV (`pionex`)

Unterstuetzt sind allgemeine Mengenzeilen und spezifische Paar-/Tauschlayouts: Received Currency + Received Quantity mit Sent Currency + Sent Quantity oder Buy Currency + Buy Amount mit Sell Currency + Sell Amount. Ein weiteres Transferlayout nutzt Amount_USDT + Direction; Direction ist kein Nachweis eines Trades. Stornierte Orders ohne Ausfuehrung erzeugen keine Ausfuehrung. Bot-Orders und deren bereits exportierte Einzeltrades nicht doppelt erfassen.

Leere CSV: `frontend/public/import-vorlagen/pionex.csv`

Fiktives Beispiel, nicht Bestandteil der leeren Vorlage:

```csv
time,coin,change,type,quote_asset,quote_quantity,fee_asset,fee_quantity,account,tx_id
2025-01-15T10:00:00Z,USDT,100,deposit,,,,,beispiel-konto,beispiel-pionex
```

| Feld / Bedeutung | Alternative Namen in Profil-Suchreihenfolge |
| --- | --- |
| Zeitpunkt: technisch erforderlich | `time` / `date` / `date(UTC+0)` / `created time` / `created_at` / `timestamp` / `timestamp_utc` |
| Asset: erforderlich oder passende Paar-/Spezialableitung | `asset` / `coin` / `currency` / `base coin` / `received currency` / `buy currency` |
| Tokenmenge: technisch erforderlich | `amount` / `quantity` / `qty` / `change` / `filled amount` / `executed_qty` / `received quantity` / `buy amount` / `amount_usdt` |
| Ereignisart: fuer die Zuordnung wesentlich | `type` / `operation` / `side` / `action` / `tx_type` / `tag` / `direction` |
| Handelspaar: optionaler Asset-Ersatz | `pair` / `symbol` / `market` / `trading pair` / `coin pair` |
| Gegenasset: bei Handel erforderlich zur Rekonstruktion | `quote_asset` / `quote asset` / `quote coin` / `quote` / `sent currency` / `sell currency` |
| Gegenmenge: bei Handel erforderlich zur Rekonstruktion | `quote_quantity` / `quote amount` / `total` / `value` / `deal amount` / `filled total` / `filled value` / `sent quantity` / `sell amount` |
| Gebuehrenasset: sofern eine Gebuehr anfaellt | `fee_asset` / `fee asset` / `fee coin` / `fee currency` |
| Gebuehrenmenge: sofern eine Gebuehr anfaellt | `fee_quantity` / `fee amount` / `fee` |
| Konto / Wallet: fuer nachvollziehbare Zuordnung | `account` / `exchange` / `wallet` / `to_address` / `from_address` |
| Transaktions-ID: fuer Nachweis und Abgleich | `txid` / `tx_id` / `tx-id` / `hash` / `transaction id` / `order id` / `tax_id` |
| Quellreferenz: optional, z. B. Order-ID | `id` / `order id` / `transaction id` / `txid` / `tx_id` / `tx-id` / `tax_id` |

## Coinbase Transaction History CSV (`coinbase`)

Transaction Type mit Buy/Sell/Convert kennzeichnet Handel, Send/Receive einen Transfer. Subtotal ist der Handelsgegenwert; ein Spot-Preis je Token ist nicht dasselbe. Spot Price Currency bezeichnet hier die Waehrung von Subtotal und Fees and/or Spread, nicht das gehandelte Asset. Die Gegenmenge nicht erneut mit der Tokenmenge multiplizieren. Das Profil besitzt keine allgemeine Handelspaar-Spalte als Ersatz fuer Asset.

Leere CSV: `frontend/public/import-vorlagen/coinbase.csv`

Fiktives Beispiel, nicht Bestandteil der leeren Vorlage:

```csv
Timestamp,Asset,Quantity Transacted,Transaction Type,Spot Price Currency,Subtotal,Fees and/or Spread,Account,Transaction ID
2025-01-15T10:00:00Z,BTC,0.001,Buy,EUR,70,0.10,beispiel-konto,beispiel-coinbase
```

| Feld / Bedeutung | Alternative Namen in Profil-Suchreihenfolge |
| --- | --- |
| Zeitpunkt: technisch erforderlich | `timestamp` / `time` / `date` / `created at` / `created_at` |
| Asset: erforderlich oder passende Paar-/Spezialableitung | `asset` / `currency` / `coin` |
| Tokenmenge: technisch erforderlich | `quantity transacted` / `quantity` / `amount` |
| Ereignisart: fuer die Zuordnung wesentlich | `transaction type` / `type` / `operation` |
| Handelspaar: optionaler Asset-Ersatz | Keine allgemeine Spaltenzuordnung in diesem Profil. |
| Gegenasset: bei Handel erforderlich zur Rekonstruktion | `spot price currency` / `native currency` / `quote asset` |
| Gegenmenge: bei Handel erforderlich zur Rekonstruktion | `subtotal` / `quote quantity` / `native amount` |
| Gebuehrenasset: sofern eine Gebuehr anfaellt | `spot price currency` / `native currency` / `fee asset` |
| Gebuehrenmenge: sofern eine Gebuehr anfaellt | `fees and/or spread` / `fees` / `fee` |
| Konto / Wallet: fuer nachvollziehbare Zuordnung | `account` / `portfolio` |
| Transaktions-ID: fuer Nachweis und Abgleich | `transaction id` / `txid` / `transaction hash` / `hash` |
| Quellreferenz: optional, z. B. Order-ID | `transaction id` / `id` / `order id` / `trade id` |

## Helium Legacy/Fairspot (`helium`)

Legacy-/Fairspot- und tabellarische Reward-Daten, nicht jede beliebige Hotspot-Datei. Reward wird in diesem Profil als mining normalisiert; das entscheidet nicht ueber die individuelle steuerliche Vermoegenszuordnung. Alternative assetlose Layouts koennen z. B. hnt_amount, iot_amount, mobile_amount oder Mining Rewards HNT/IOT/MOBILE verwenden; keine Preis-/Oracle-Hilfsspalte als Tokenmenge einsetzen. Bei Period Start (UTC) wird auf das Monatsende 23:59:59 UTC datiert: Ein Monatsbericht belegt keinen exakten Einzelzufluss. Sender + Receiver + Amount ist ein besonderes Transferlayout; eigene Walletzuordnung und Richtung pruefen.

Leere CSV: `frontend/public/import-vorlagen/helium.csv`

Fiktives Beispiel, nicht Bestandteil der leeren Vorlage:

```csv
timestamp,token,amount,type,wallet,tx_id
2025-01-15T10:00:00Z,HNT,0.25,Reward,beispiel-wallet,beispiel-helium
```

| Feld / Bedeutung | Alternative Namen in Profil-Suchreihenfolge |
| --- | --- |
| Zeitpunkt: technisch erforderlich | `time` / `date` / `timestamp` / `block time` / `created_at` / `period start (utc)` |
| Asset: erforderlich oder passende Paar-/Spezialableitung | `asset` / `coin` / `currency` / `token` / `buyCurrency` |
| Tokenmenge: technisch erforderlich | `amount` / `quantity` / `hnt` / `reward` / `rewards` / `buyAmount` / `hnt_amount` / `iot_amount` / `mobile_amount` / `iot tokens` / `mobile tokens` / `mining rewards` / `mining rewards hnt` / `mining rewards iot` / `mining rewards mobile` / `commissions hnt` / `commissions iot` / `commissions mobile` |
| Ereignisart: fuer die Zuordnung wesentlich | `type` / `operation` / `category` / `reward type` |
| Handelspaar: optionaler Asset-Ersatz | `pair` / `symbol` / `market` / `trading pair` / `coin pair` |
| Gegenasset: bei Handel erforderlich zur Rekonstruktion | `quote_asset` / `quote asset` |
| Gegenmenge: bei Handel erforderlich zur Rekonstruktion | `quote_quantity` / `quote amount` / `value` / `eur value` |
| Gebuehrenasset: sofern eine Gebuehr anfaellt | `fee_asset` / `fee asset` |
| Gebuehrenmenge: sofern eine Gebuehr anfaellt | `fee_quantity` / `fee amount` / `fee` |
| Konto / Wallet: fuer nachvollziehbare Zuordnung | `wallet` / `account` / `hotspot` / `hotspot name` / `gateway address` / `address` / `payer` / `payee` / `receiver` / `sender` |
| Transaktions-ID: fuer Nachweis und Abgleich | `txid` / `tx_id` / `txId` / `hash` / `transaction hash` / `transaction_hash` |
| Quellreferenz: optional, z. B. Order-ID | `id` / `txid` / `tx_id` / `txId` / `hash` / `transaction hash` / `transaction_hash` / `block` / `gateway address` |

## Solana RPC Primaerdaten (`solana_rpc`)

Bereits aufbereitete RPC-Tabellendaten, nicht rohe JSON-RPC-Antworten und keine pauschale Solscan-CSV-Unterstuetzung. event_type z. B. sol_transfer, token_transfer, swap_in_aggregated oder swap_out_aggregated; side in/out und Wallet/Signatur beleggetreu angeben. Swaps brauchen beide zusammengehoerigen Legs mit derselben Signatur. Ein positiver token_transfer kann als income/reward klassifiziert werden; eine vorhandene Claim-/Reward-Instruktion ist nicht durch einen beliebigen Spaltennamen ersetzbar. Wallet-Eigentum, Rohbelege und erzeugte Klassifikation pruefen. Die Kopfzeile allein garantiert keine fachlich vollstaendige Onchain-Rekonstruktion.

Leere CSV: `frontend/public/import-vorlagen/solana_rpc.csv`

Fiktives Beispiel, nicht Bestandteil der leeren Vorlage:

```csv
timestamp_utc,asset,quantity,event_type,side,fee_asset,fee,wallet_address,tx_id
2025-01-15T10:00:00Z,SOL,-0.1,sol_transfer,out,SOL,0.000005,beispiel-wallet,beispiel-solana
```

| Feld / Bedeutung | Alternative Namen in Profil-Suchreihenfolge |
| --- | --- |
| Zeitpunkt: technisch erforderlich | `timestamp_utc` / `timestamp` / `time` / `date` |
| Asset: erforderlich oder passende Paar-/Spezialableitung | `asset` / `symbol` / `mint` |
| Tokenmenge: technisch erforderlich | `quantity` / `amount` |
| Ereignisart: fuer die Zuordnung wesentlich | `event_type` / `type` / `side` |
| Handelspaar: optionaler Asset-Ersatz | Keine allgemeine Spaltenzuordnung in diesem Profil. |
| Gegenasset: bei Handel erforderlich zur Rekonstruktion | Keine allgemeine Spaltenzuordnung in diesem Profil. |
| Gegenmenge: bei Handel erforderlich zur Rekonstruktion | Keine allgemeine Spaltenzuordnung in diesem Profil. |
| Gebuehrenasset: sofern eine Gebuehr anfaellt | `fee_asset` |
| Gebuehrenmenge: sofern eine Gebuehr anfaellt | `fee` / `fee_quantity` / `fee_amount` |
| Konto / Wallet: fuer nachvollziehbare Zuordnung | `wallet_address` / `account` / `wallet` |
| Transaktions-ID: fuer Nachweis und Abgleich | `tx_id` / `signature` / `transaction_hash` |
| Quellreferenz: optional, z. B. Order-ID | `tx_id` / `signature` / `transaction_hash` |
