# Steuerreport V2 0.2.0rc38

Releasekandidat fuer nachvollziehbare Importpruefung. Er ist keine steuerliche
Abnahme und bestaetigt keine vollstaendige Migration aus der nativen Anwendung.

## Aenderungen

- **#13:** Binance-Spot-CSV und API-Fills koennen anhand stabiler Trade-ID,
  Handelspaar und Finanzdaten einzeln geprueft werden. Entscheidungen werden
  protokolliert; ungeklaerte Ueberschneidungen bleiben gesperrt. Der gemeinsame
  Lock setzt den dokumentierten Einprozessbetrieb voraus.
- **#22:** Der gefuehrte Bitget-Import bindet Datei, Verbindung, Exportzeitzone
  und Produktscope. Zeitkonflikte und bestimmte ungeklaerte Margin-Gebuehren
  blockieren die Vorschau. Altpfade ohne Scope erhalten einen ausdruecklichen
  Hinweis auf den nicht verifizierten UTC+08-Fallback.
- Schema 3 ergaenzt Importkontext pro Batch. Historische Originalbelege werden
  nicht umgeschrieben; vorhandene Bitget-Batches erhalten einen nicht
  verifizierten Legacy-Kontext. Neue und migrierte Kontexte sind gleichermassen
  NOT NULL. Neuere Schemata werden vor Schemaoperationen abgewiesen. Vor
  Aktualisierung Sicherung und Restore samt vorherigem Image und Schema pruefen.
- Ein lesender Vergleichshelfer fuer isolierte Schema-2-/Schema-3-Kopien prueft
  Tabellen, Zeilen und die dokumentierten Legacy-Kontexte. Er erstellt keine
  Sicherung und ersetzt weder den Dateiabgleich von `/state` noch eine fachliche
  Migration aus der nativen Anwendung.

## Grenzen

- Eine falsche Produktscope-Auswahl kann die Margin-Gebuehrenpruefung umgehen.
  Die Zuordnung separat gebuchter Gebuehren, Handelsgegenbeine und die
  vollstaendige Trennung der Produktbestaende sind nicht abgeschlossen.
- Das freie Akteursfeld ist keine serverseitig authentifizierte Identitaet.
  Abgleichentscheidungen aendern keine bereits importierten Ereignisse.
- #4, #8, #13, #19, #20 und #22 bleiben soweit nicht anderweitig ausdruecklich
  nachgewiesen offen. Ein Docker-Restore belegt keine native Datenparitaet.
- Kein automatischer externer Abruf, keine steuerliche Entscheidung und keine
  Jahresfreigabe allein aufgrund dieser Version.

## Aktualisierung

Vor einem produktiven Containerwechsel muessen ein konsistenter Backupstand
des gesamten `/state`, ein Restore in ein separates Volume und ein Rueckweg
mit dem vorherigen Image nachgewiesen sein. Ein aelteres Image darf nicht
ungeprueft auf ein mit Schema 3 migriertes Volume zugreifen.

Der Vergleichshelfer akzeptiert nur getrennte Offline-Kopien unter dem
Temp-Verzeichnis:

```sh
python scripts/compare_schema2_to3_v2.py --before /tmp/schema2.duckdb --after /tmp/schema3.duckdb
```

Ein `passed` bestaetigt ausschliesslich den geprueften Datenbankuebergang. Der
Erhalt von Profil, Schluesseln, Rohdateien und anderen Dateien ist separat
nachzuweisen; sensible Kopien und Ergebnisse mit Datenbank-Hashes sind privat zu
behandeln. Nichtsystemische Views, zusaetzliche Schemas, Sequenzen, Makros,
benutzerdefinierte Typen und persistente Datenbank-Secrets werden derzeit nicht
verglichen, sondern fuehren zu einer ausdruecklichen Ablehnung. Das gilt auch
fuer Tabellen mit expliziter Collation.
