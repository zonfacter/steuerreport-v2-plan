# Marktpreise: nativer Bestand und Docker

Stand: 2026-10-30. Dieses Dokument beschreibt vorhandene Funktionen und
offene Arbeiten; es bestaetigt weder vollstaendige Preisdeckung noch einen
automatischen Tagesabruf.

## Vorhandene Bausteine

| Bereich | Nativer Engine-Quellstand | V2/Docker-Quellstand |
| --- | --- | --- |
| Yahoo-Tageshistorie | `src/tax_engine/fx/yahoo_prices.py` liest Tages-Schlusskurse in USD; `scripts/yahoo_price_backfill_usd.py` startet den Backfill. | `configs/crypto_price_sources.json` enthaelt fuer manche Assets Yahoo-Ticker; ein Yahoo-Abruf ist dadurch nicht implementiert. |
| Historische Preise | Der Yahoo-Backfill verwendet konfiguriertes Symbolmapping und schreibt in den nativen FX-Store. | `HistoricalPriceService` und `historical_price_collection.py` planen historische CoinGecko-/DefiLlama-Referenzen mit separater Vorschau, Belegen und ausdruecklicher Uebernahme. |
| Aktuelle Preise | Ein vorhandener Historien-Backfill belegt keinen taeglich laufenden Job. | Der vorhandene Portfolio-Backfill ruft Quellen nur nach expliziter Aktion ab, schreibt ins gemeinsame Preis-Ledger und startet die Berechnungspipeline. Er ist kein steuerneutraler automatischer Marktpreisjob. |

Die reine Existenz eines Connectors beweist weder Anbieterzugang noch
vollstaendige Daten oder steuerliche Eignung. Eine EUR-Bewertung aus USD
benoetigt ausserdem einen zeitlich passenden, belegten USD/EUR-Kurs.
CoinMarketCap und OHLCV-CSV sind weitere native Backfill-Wege; ein Eintrag
in der V2-Konfiguration implementiert keinen entsprechenden V2-Connector.
Die native Solana-Bestandsansicht versucht ferner Jupiter-Preise und fuer SOL
einen CoinGecko-Fallback; daraus folgt kein allgemeiner taeglicher Kursjob.

Der aeltere direkte V2-Backfill und die neuere Preisvorschau unterscheiden
sich bei der Evidenz. In rc40 sendet der direkte Altpfad das Datum als
`DD-MM-YYYY`, obwohl die offizielle Dokumentation `YYYY-MM-DD` nennt.
Der Entwicklungsstand korrigiert das Datumsformat mit Mock-Test; ein Live-Test
des alten oder neuen Formats wurde nicht durchgefuehrt. Das Gesamtproblem wird in
[Issue #39](https://github.com/zonfacter/steuerreport-v2-plan/issues/39)
verfolgt. Der direkte Altpfad darf nicht als gleichwertige beweisgebundene
Vorschau dargestellt werden.

## Bedienung des vorhandenen V2-Standes

Unter **Portfolio & Haltefristen > Historische EUR-Preise** laesst sich der
historische Bedarf planen. Die Planung allein startet keinen externen Abruf.
Ein anschliessender Abruf benoetigt eine ausdrueckliche Bestaetigung und
erstellt eine Vorschau. Die Uebernahme und Neuberechnung sind separate,
ausdruecklich zu bestaetigende Schritte. Fehlende Identitaeten und Daten
bleiben offen; eine Vorschau ist keine steuerliche Jahresfreigabe.

Der dort vorhandene Knopf fuer aktuelle Portfolio-Marktpreise hat eine andere
Wirkung: Er speichert Preise im gemeinsamen Preis-Ledger und berechnet die
Pipeline neu. Er erzeugt derzeit keinen unabhängigen Tagesverlauf und darf
nicht als rein lesende Aktualisierung verstanden werden.

## Noch umzusetzen

1. Bestandsquelle, Bestandszeit und Identitaet pro Position nachvollziehbar
   unterscheiden: native Coins, boersenspezifische Assets und Token mit
   Netzwerk/Contract. Symbolgleichheit allein ist kein Identitaetsnachweis.
2. Eine gesonderte, begrenzte Ablage fuer aktuelle Preisbeobachtungen schaffen,
   ohne Steuer-DuckDB, historische Preisbelege oder archivierte Snapshots zu
   veraendern. Anbieter-Kurszeit, Abrufzeit, Waehrung und ggf. FX belegen.
3. Einen einrichtbaren taeglichen Abruf mit expliziter Aktivierung, Budget,
   Status, Fehleranzeige und manueller Aktualisierung anbinden. Kein Abruf
   allein beim Oeffnen der Seite. Ein ausgefallener Anbieter, ein gestoppter
   Container oder ein nicht unterstuetzter Token kann einen Tageswert
   verhindern; der fehlende Wert muss sichtbar bleiben.
4. Fuer fruehere Tage echte vorhandene historische Quellen nach Zeit, Asset und
   Tarifgrenzen abrufen; keine Tage durch Fortschreiben oder Schaetzen fuellen.
   Portfolio-Verlauf und steuerliche Ereignisbewertung getrennt kennzeichnen.
5. Einstellungen, Bedienung, Mock-Provider-, Neustart-, Speichergrenzen- und
   Nichtveraenderungs-Tests vor produktiver Inbetriebnahme nachweisen.

## Yahoo und freie Quellen

Die native Implementierung verwendet einen Chart-Endpunkt von Yahoo; ein
Ticker in der Konfiguration garantiert weder Zugriff noch Abdeckung. Die
[Yahoo API-Bedingungen](https://legal.yahoo.com/us/en/yahoo/terms/product-atos/apiforydn/index.html)
und gegebenenfalls die konkret fuer den verwendeten Datendienst geltenden
Bedingungen muessen fuer den vorgesehenen Einsatz geprueft werden. Aus der
Existenz des nativen Codes folgt keine pauschale Zusage fuer eine frei
verteilbare, dauerhaft nutzbare Yahoo-Schnittstelle.

Die [DefiLlama-Dokumentation](https://api-docs.defillama.com/) unterscheidet
freie und kostenpflichtige Schnittstellen. Die
[CoinGecko-Dokumentation](https://docs.coingecko.com/docs/errors-and-rate-limits)
beschreibt Zugangstypen und Limits; historische Abdeckung haengt von Quelle,
Asset und Zugang ab. Diese Quellen sind Moeglichkeiten, keine Garantie fuer
jeden Token oder jeden vergangenen Tag.

## Aelteres CoinGecko-Backfill-Skript

`scripts/backfill_coingecko_prices_v2.py` ist nur eine ungepruefte
Kandidatenvorschau. `--execute` ist vor Datenbank- und Netzwerkzugriff
gesperrt: Das Skript archiviert weder einen ausreichenden Providerbeleg noch
beweist sein Symbolmapping die Assetidentitaet. Auch ein gespeicherter
Abfragezeitpunkt ist kein belegter Kurszeitpunkt. Bereits vorhandene Werte
werden durch diese Sperre nicht automatisch bewertet oder veraendert.

Der historische Abruf verwendet das UTC-Datum im Format `YYYY-MM-DD`; die
[CoinGecko-Referenz](https://docs.coingecko.com/reference/coins-id-history)
beschreibt fuer diesen Endpunkt einen Snapshot um 00:00 UTC. Die separate,
ausdruecklich aktivierbare aktuelle Ersatzabfrage ist keine historische
Beobachtung und rechtfertigt keine Jahres- oder Stichtagsfreigabe.
