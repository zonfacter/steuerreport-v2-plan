# Synthetischer Cross-Year-Gegenfall fuer #20

Basis: frisch abgerufenes `origin/main` `96c5ad5eda4b2104b09b86f86c373b68e43aed60`.
Diese Basis enthaelt den integrierten synthetischen Referenztest aus PR #35;
die unabhaengigen Entwuerfe zu #49 und #46 sind nicht vorausgesetzt.

Der neue Test verwendet ausschliesslich eine temporaere DuckDB und ein
synthetisches Paket. Zwei 2024 gekaufte Assets werden 2025 teilweise verkauft.
Die unabhaengig vorgegebenen Referenzkosten 50 und 10 EUR ergeben dieselbe
Gesamtsumme wie die aus den Eingaben errechneten 40 und 20 EUR. Auch die
Gewinnsummen stimmen mit 60 EUR ueberein; die Einzelabweichungen sind jedoch
jeweils gegenlaeufig. Der vorhandene V1-Paritaetsdienst muss vier Unterschiede
ausweisen und die ungeprueften Gruppen blockieren. Der neue Snapshotvergleich
liest die aktuellen gespeicherten Aggregate in einer gemeinsamen Lesetransaktion
und meldet in diesem Fall `aggregate_status=equal`. Ereignisse, Lots, Tax-Lines
und Detailreconciliation bleiben `not_compared`: Aggregatgleichheit ist keine
Einzelpositionsparitaet. Der separate Paritaetsdienst bleibt blockiert.
Das synthetische archivierte Paket bleibt
bei beiden Rebuilds bytegleich und integritaetsgeprueft.

Die Referenzwerte simulieren einen Widerspruch, keine autoritative V1-Rechnung
und keine bestaetigte Regelkorrektur. Dieser Test implementiert keinen
allgemeinen Einzel-/Aggregat-Abgleich und keinen `reconciliation_failed`-Status.
Er prueft weder fehlende Kostenbasis noch echte V1-Ausfuehrung, gebundene
Quellen, Methoden- oder Alt-/Neu-Datenparitaet. #19 und #20 bleiben dafuer offen;
insbesondere fehlt der eindeutig zugeordnete, konsistente Legacy-Eingabestand.
Es erfolgt keine Jahresfreigabe, automatische Korrektur oder produktive Nutzung.
