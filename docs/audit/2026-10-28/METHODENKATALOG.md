# Methodenpruefung Paket C / F03

Stand: 2026-10-28. Isolierter technischer Pruefstand, keine individuelle
Steuerberatung, Jahresfreigabe oder Methodenaktivierung. AGENTS.md und der
Koordinatorvertrag VERTRAG.md wurden vor Quellcodeaenderungen gelesen und
bestaetigt. Ausgang: 1aecfb131d189267a01a6303f5a9b67a5a99efe2.

## Amtliche Primaerquellen

Unabhaengig recherchiert und am Prueftag abgerufen. Die Web-Oeffnungen meldeten
teilweise 503/Timeout; die amtliche BMF-HTML-Fassung wurde danach direkt per
HTTPS und HTMLParser gelesen, insbesondere Rz. 43, 53-63 und 91. Keine
Sekundaerquellen als Rechtsbeleg verwendet.

| Quelle | Bestaetigter Inhalt / Abgrenzung |
| --- | --- |
| [EStG Paragraph 23 Abs. 1 Satz 1 Nr. 2, Abs. 2, Abs. 3](https://www.gesetze-im-internet.de/estg/__23.html) | Andere Wirtschaftsgueter: nicht mehr als ein Jahr; andere Einkunftsarten gehen vor. Gewinn ist Erloes abzueglich Kosten. Freigrenze betrifft den Gesamtgewinn des Kalenderjahres. |
| [BGB Paragraph 187 Abs. 1](https://www.gesetze-im-internet.de/bgb/__187.html) | Ereignistag wird beim Fristbeginn nicht mitgerechnet. |
| [BGB Paragraph 188 Abs. 2 und 3](https://www.gesetze-im-internet.de/bgb/__188.html) | Ende mit Ablauf des entsprechenden Kalendertags; fehlt der Tag, Monatsende. |
| [BMF 06.03.2025, Rz. 53-56](https://amtliche-handbuecher.bundesfinanzministerium.de/esth/2025/B-Anhaenge/Anhang-04/anhang-4.html) | Private Jahresfrist; Anschaffung/Verkauf in Rz. 54. CEX-Handelszeit, regelmaessig Walletzeit bei direktem Handel, alternativ belegter Vertragsschluss stehen in Rz. 55, NICHT 54. Tausch startet neu; Change behaelt die Herkunft. |
| BMF, gleiche Quelle, Rz. 57-63 | Gewinn/Kosten und EUR-Entgelt; Swap-Bewertung; Einzelbetrachtung, vereinfachte FIFO-Wertermittlung, walletbezogene Methodenbindung. Keine pauschale Zehnjahresverlaengerung fuer Currency/Payment Token. |
| BMF, gleiche Quelle, Rz. 43 und 91 | Marktkurs und dokumentierte gleichmaessige Tageskursverfahren, auch Tagesdurchschnitt/-zeit/-schluss; unser technischer UTC-Filter ist kein allgemeines BMF-Verbot spaeterer Tageskurse. |
| [Amtliche EStH-Tabelle 2025](https://amtliche-handbuecher.bundesfinanzministerium.de/esth/2025/tabellarische-Uebersicht/inhalt.html) | 600 EUR fuer 2023; 1.000 EUR fuer 2024/2025. BMF Rz. 53 nennt ebenfalls den Wechsel bis/ab VZ 2023/2024. |

Die nicht auffindbare mitgeteilte BMF-Quellenpruefung und die gelieferten
V1-/V2-Repros wurden NICHT gelesen oder exakt wiederholt. Auch aus den
amtlichen Quellen folgt keine individuelle Zuordnung aller Daten zu
Privatvermoegen. Betriebsvermoegen, Derivate, Security-/Utility-Sonderfaelle
und ungeklaerte Reward-Herkunft bleiben gesondert fachlich zu pruefen.
Die Suche nach einer neueren amtlichen Kryptowerte-Fassung ergab weiterhin
das Schreiben vom 06.03.2025; die [BMF-Positivliste vom 20.03.2026, Eintrag 959](https://www.bundesfinanzministerium.de/Content/DE/Downloads/BMF_Schreiben/Weitere_Steuerthemen/Normenflut/2026-03-20-anlage-1.pdf?__blob=publicationFile&v=2)
fuehrt dieses Schreiben. Das ist keine Garantie gegen unbekannte spaetere
Einzelfallrechtsprechung.

## Herleitung Und Implementiertes Modell

Technische Herleitung aus Jahresfrist und Fristende, nicht woertliche
BMF-Vorgabe einer Software-Zeitzone: `event_time` und Lotzeiten werden als
UTC-Zeitpunkte verstanden, naive DB-Timestamps als UTC. Daraus wird das Datum
in `Europe/Berlin` gebildet. Ende ist der gleiche Kalendertag des Folgejahres,
am 29. Februar auf den 28. Februar gekuerzt. Der gesamte Jahrestag ist noch
innerhalb, erst der Folgetag ab Berliner Mitternacht ausserhalb.

`tax_time.py` enthaelt `private_holding_anniversary`,
`private_disposal_tax_free_at`, `private_disposal_within_year`, das entsprechende
SQL-Praedikat und `tax_line_within_year_sql`. SQL nutzt UTC-naive Spalten,
explizite Zeitzonen und DuckDB-Kalenderjahresaddition mit Februar-Kuerzung.
Die Sitzungszeitzone darf das Ergebnis nicht veraendern. Die generierte SQL
ist ausschliesslich fuer interne vertrauenswuerdige Spaltenausdruecke bestimmt.
Bindung fuer neue CSV-/Audit-Ableitungen:
`PRIVATE_HOLDING_POLICY_VERSION = "de_private_calendar_holding_berlin_v1"`.
Die vorhandene Berichtsjahr-Policy `de_calendar_year_v1` bleibt separat.

Fuer alte Tax-Lines ohne eigenes Anschaffungsdatum gilt das verknuepfte Lotdatum.
Ein vorhandenes Line-Datum hat Vorrang, insbesondere bei fortgefuehrten
Wallet-Lots. Fehlende Daten beweisen keinen Fristablauf: das SQL-Praedikat
erteilt dann keine Fristbefreiung. Das ersetzt kein Vollstaendigkeitsgate.
Python-Verbraucher erhalten regulaer die nichtoptionalen Vertragsdaten.

`holding_days` bleibt unveraendert als beschreibender Abstand erhalten.
Die 365-Tage-Grenze fuer die Anzeigegruppe `next_year` ist lediglich eine
Gruppierung bereits berechneter verbleibender Planungstage, keine Steuerregel.

### Zeitquellenannahmen

Die Fristfunktion kann nicht beweisen, dass ein importiertes Datum der
massgebliche Handels-/Vertragszeitpunkt ist. Voraussetzung sind die
Zeitsemantik der Quelle, Zeitzone/Offset, Originalbeleg und Zuordnung zum
wirtschaftlichen Vorgang. Walletbuchung darf nicht automatisch einen
abweichenden CEX-Handel ersetzen. Ein abweichender Vertragsschluss benoetigt
Belege und menschliche Freigabe; keine Rekonstruktion durch F03.
Quellperiodenaggregate, insbesondere die bestehende Helium-Jahreszuordnung,
werden durch F03 nicht in Einzelanschaffungsnachweise umgewandelt.

### Freigrenzen

Die bestaetigte Regel lautet: Gesamtgewinn **weniger als** 600 EUR bis VZ 2023,
weniger als 1.000 EUR ab VZ 2024. Gleichheit ist nicht unter der Freigrenze;
es handelt sich nicht um einen abzuziehenden Freibetrag. Historisch aeltere
Rechtsstaende sind nicht mit diesem pauschalen Vor-2024-Wert freigegeben.

Inspektion der vorhandenen Tax-Year-Verbraucher findet keine gebundene
persoenliche Gesamtgewinn-/Freigrenzenberechnung. Daher bewusst KEINE neue
Steuerbefreiung von einzelnen Kryptozeilen, Konten oder Teilbestandsjahren.
Die Fristklassifikation bedeutet nur innerhalb/ausserhalb des modellierten
Zeitraums, nicht endgueltig zu zahlende Einkommensteuer. Weitere private
Veraeusserungsgeschaefte und Verlustverrechnung bleiben vor Jahresfreigabe
einzubeziehen. Die 50-EUR-Fixture bleibt in 2024 innerhalb der Frist sichtbar,
obwohl sie isoliert unter 1.000 EUR liegt.

## Vorhandene Faehigkeiten Und Offene Punkte

Die extern genannten G11-G17/G24 sind in diesem Checkout nicht als
identifizierbare Pruefliste vorhanden. Keine erfundene Zuordnung oder
Abnahme dieser Kennungen. Fuer die genannten Themen, insbesondere G15/G16,
liegt folgende konkrete Codepruefung vor:

| Thema / Fundstelle | Nachweisstatus und Grenze |
| --- | --- |
| `tax.py:preview_global_fifo`, `_consume_fifo_asset` | Mengenverbrauch, EUR-Kosten/Erloes und Herkunft vorhanden; algebraisch mit synthetischen Belegen geprueft. Kein Privatnachweis durch FIFO. |
| `tax_wallet_fifo.py:replay`, `_move_lots`, `_year_deltas` | Wallet-Vorschau und fortgefuehrte Lotdaten vorhanden; keine Methodenaktivierung. Jahreszuordnung nutzt bereits `reporting_tax_year`. |
| `fifo_methods.py:active_fifo_scope` | Liest den neuesten Run und faellt auf globale Methode zurueck. Nur in eigener synthetischer DB geprueft; reale aktive Methode NICHT abgefragt. |
| `tax_time.py`, `tax.py:holding_period_report`, `tax_years.py`, `reports.py:_year_cards` | F03: zentrale Berliner Frist fuer Planung, Python und SQL; Detail-, Treiber-, Zahlungs-, Stablecoin- und Gain-Evidence-Ansichten konsumieren sie. |
| `tax.py:_eur_value`, `_lot_from_buy` | Bestehende Luecke: fehlende Bewertung kann weiterhin einen vorlaeufigen Null-Kosten-Lot erzeugen. F03 erfindet keinen Anschaffungswert und behauptet keine vollstaendige Missing-Cost-Basis-Modellierung. |
| `tax_years.py:income_report`, `income_asset_breakdown_from_lots` | Income-Report meldet fehlende Bewertung separat. Lot-basierter Ausweis kann vorhandenen Null-Lot als Wert behandeln; fehlender Wert ist nicht durch einen vorhandenen Lot geloest. Finale Freigabe benoetigt ein uebergeordnetes Gate. |
| `tax_wallet_fifo.py:_process_fairspot_return` | Bestehende Reward-Komponente kann mit synthetischer Herkunft `staking-reward:...` und fehlendem Preis als Nullwert entstehen. Das ist kein Originalbeleg und keine in C reparierte Methodenabnahme. |
| Reward-Fixture | Belegter synthetischer Zufluss 100 EUR wird Lotbasis 100; Verkauf 150 ergibt separat 50 EUR Gewinn, nicht nochmals 150 EUR Income. Keine automatische Privat-/Betriebseinordnung. |
| `tax_years.py:_income_price_lookup`, `_income_price_at` | Begrenzt auf positive Kurse am gleichen UTC-Tag und nicht nach Ereignis; alte Primaerkurse duerfen keinen aktuellen Kandidaten verdraengen. Quellenprioritaet sonst unveraendert. |
| `bmf_compliance.py`, `tax_methodology.py`, `wallet_fifo_acceptance.py` | Vorhandene Review-/Methoden-/Sphaerenpruefungen inspiziert, NICHT veraendert oder als Originalreview abgenommen. |

## Integrationsgrenze

Keine Aenderungen an Datenmodell, DB, zentralen Contracts, API, Version,
Frontend, `price_lookup.py` oder `valuation.py`. Keine productive DB gelesen,
keine echten Provider-/KI-Aufrufe, keine Originalimporte veraendert.
Die amtliche Recherche war oeffentliches HTTPS ohne Finanzdaten.
F04/Readiness/Filing-Bindung/Export-Status bleiben beim Koordinator.
Die PricePoint-Verbraucher in C benoetigen von B keine neuen Vertragsfelder.
Der zentrale Modellcommit `ef24dbab505517944de1a546cefc840a99dd81d9`
wurde nicht benoetigt und nicht cherry-gepickt.

Nachtraeglich ausdruecklich delegiert: ausschliesslich aktuelle
Haltefristklassifikation in `swap_valuation_parallel.py:_Totals.add`.
`api/app.py` (CSV-Klassifikation, im Ausgangsstand Zeilen 6984/6987) und
`tax_filing_audit.py` (493, 798-817) bleiben beim Parent. Bei Letzterem sind
historisch tatsaechlich verwendete Archivlabels zu erhalten; sie duerfen
nicht nachtraeglich als neue Kalenderklassifikation ausgegeben werden.
