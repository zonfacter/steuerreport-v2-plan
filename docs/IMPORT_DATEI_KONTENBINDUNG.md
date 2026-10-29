# Dateiimport an Binance-Konto binden

## Umfang

Der gefuehrte Dateiimport kann einen Binance-Export an eine bereits gespeicherte
Binance-Verbindung binden. Die Verbindung wird ausdruecklich anhand ihrer
stabilen UUID ausgewaehlt und serverseitig gegen den gespeicherten Anbieter
`binance` geprueft. Gleichlautende Kontonamen bleiben durch die UUID getrennt.
Der Import liest oder verwendet keine API-Secrets und startet keinen Anbieter-
oder KI-Aufruf.

Bei einer Binance-Datei ohne Konto-/Wallet-Spalte ist die Verbindungsauswahl
Pflicht. Die normalisierte Buchung erhaelt dann als Konto `connection:<UUID>`.
Das ist eine abgeleitete Zuordnung fuer genau diesen neuen Batch. Die originalen
Dateibytes, der Datei-SHA-256 und alle importierten Rohspalten bleiben unveraendert.
Wird eine Verbindung ausgewaehlt, ist sie fuer die normalisierte Kontenzuordnung
massgeblich; eine frei benannte Konto-/Wallet-Spalte im Export ueberschreibt sie
nicht.

## Persistenz und Wiederholungen

Import-Batches speichern die optionale `connection_id` separat von Dateiname,
Dateihash und Rohzeilen. Die Datenbankschemaversion 2 fuegt dafuer eine nullable
Spalte hinzu. Schema-1-Batches werden nicht erraten oder nachtraeglich gebunden;
ihre neue Spalte bleibt `NULL`.

Gleicher Hash bei derselben Verbindung ist eine Dublette. Derselbe Hash kann
fuer eine andere, ausdruecklich ausgewaehlte Verbindung erneut importiert
werden und bleibt ein eigener Batch. Ein ungebundener Altbatch mit gleichem
Binance-Hash blockiert den Import; die Software ordnet ihn nicht still einer
neuen Verbindung zu.

## Noch offen: CSV/API-Identitaet

Die Konto-Bindung beweist nicht, dass eine CSV-Zeile und ein API-Record dieselbe
wirtschaftliche Buchung sind. `history_preview` blockiert weiterhin passende
oder mehrdeutige Legacy-Ereignisse ohne `history_scope_identity`. Eine
Kontenzuordnung allein hebt diese Sperre nicht auf.

Es gibt fuer diesen Fall noch keine Review-Entscheidung, die eine stabile
Recordidentitaet, uebereinstimmende finanzielle Werte (Menge, Gegenwert,
Gebuehr und Zeitsemantik), beide Originalbelege und den Hash der geprueften
Vorschau gemeinsam dauerhaft bindet. Deshalb fuehrt dieser Slice keinen
automatischen Abgleich, kein Zusammenfuehren und keine Ausnahme vom Guard ein.
Unterschiedliche CSV-Zeitraeume, fehlende Anbieter-IDs, abweichende Mengen oder
Gebuehren bleiben gesonderte offene Faelle.

## Abgrenzung

Auch die niedrigstufigen CSV-/Datei-Raw-Endpunkte akzeptieren eine ausdrueckliche
`connection_id`; kontolose Binance-Dateien ohne diese Bindung werden vor dem
Schreiben blockiert. Preview-Endpunkte bleiben lesend und melden die fehlende
Bindung. Die Bindung loest keine CSV-/API-Recordueberlappung auf und ersetzt
keine fachliche Entscheidung. Steuerliche Quellenaktivierung, Eigentumspruefung
und Konto-/Quellenregistry bleiben getrennte Schritte.
