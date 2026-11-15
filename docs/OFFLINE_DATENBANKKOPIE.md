# Offline-Datenbankkopie und Wiederherstellung in ein neues Ziel

Entwicklungsstand, noch kein veroeffentlichtes Image und keine produktive
Updatefreigabe. Das Werkzeug benoetigt keine KI und keine Anbieterzugangsdaten.
Es ist eine kontrollierte **Datenbankkopie**, kein vollstaendiges Backup der
Anwendung und kein automatischer Rollback einer laufenden Installation.

## Voraussetzungen

- Die Quelle muss bereits sauber geschlossen sein. Dieses Werkzeug stoppt
  keine Anwendung, keinen Container und keinen Schreibprozess.
- Keine vorhandene `.wal`-Datei oder `.tmp`-Ablage. Auch nach einem Absturz
  wird ein WAL weder geloescht noch automatisch eingespielt. Zuerst einen
  gesondert freigegebenen Wiederanlauf-/Sicherungsweg verwenden.
- Vertrauenswuerdiges lokales Dateisystem mit wirksamen DuckDB-Dateisperren.
  Netzwerk-/NAS-Sperrsemantik wird nicht automatisch als geeignet zertifiziert.
- Ein privates, bereits vorhandenes Zielverzeichnis, ausreichend freier Platz
  fuer eine ganze weitere Datenbankdatei und Berechtigungen des ausfuehrenden
  Benutzers. Bei grossen Datenbanken dauert die Tabellen-/Hashpruefung.
- Zieldatei und deren `.wal`/`.tmp` duerfen nicht vorhanden sein. Symlinks und
  mehrfach hartverlinkte Quelldateien werden abgewiesen.

Jeder Kopiervorgang laeuft in einem eigenen kurzlebigen Prozess. Der aufrufende
Prozess oeffnet keine Quelldatei; damit verliert er beim Schliessen von Streams
keine prozessweiten POSIX-Sperren bestehender Leser oder anderer Aufrufe.
Der Worker haelt waehrend Lesen, Kopieren und Pruefen eine echte read-only
DuckDB-Verbindung und denselben Quelldateistream offen. Auch die Zielkopie
bleibt bis nach Verlinken und Verzeichnissynchronisation read-only gesperrt.
Das Werkzeug verwendet keinen `DuckDbStore`, fuehrt keine
Schemamigration, keinen Checkpoint und keine Steuerberechnung aus. Quelle und
Kopie werden vollstaendig gehasht; gespeicherte Tabellenwerte werden in kleinen
Paketen gelesen, die Kopie wird erneut geoeffnet. SQL-Views werden dabei nicht
ausgefuehrt, externe Dateizugriffe der Verbindung sind deaktiviert. Das ist
keine fachliche Pruefung der enthaltenen Steuerzahlen oder aller View-Semantiken.

## Bedienung ohne KI

Beispielpfade fuer eine bereits isolierte, geschlossene Testdatenbank; nicht
ungeprueft durch Pfade der laufenden Installation ersetzen:

```bash
python -m steuerreport_v2.db.offline_snapshot \
  --source /private-test/source.duckdb \
  --destination /private-test/backup.duckdb
```

Die JSON-Antwort nennt `scope: database_only`, `source_sha256`, `target_sha256`,
Dateigroesse und Tabellenzahl. Nur `status: verified` mit Exitcode 0 bestaetigt
diesen begrenzten Kopiervorgang. Die Quelle bleibt unveraendert. Neue Dateien
haben Modus 0600; Eigentuemer ist der aufrufende Benutzer. Es wird kein privater
Dateipfad oder Tabelleninhalt in die JSON-Antwort geschrieben.

Fuer eine Wiederherstellungsprobe den zuvor unabhaengig aufbewahrten Hash
angeben und erneut eine **neue** Zieldatei verwenden:

```bash
python -m steuerreport_v2.db.offline_snapshot \
  --source /private-test/backup.duckdb \
  --destination /private-test/restored.duckdb \
  --expected-sha256 ERWARTETER_64_STELLIGER_SHA256
```

Der Platzhalter ist absichtlich kein gueltiger Hash. Ein nicht passender Hash
blockiert die Veroeffentlichung der Zieldatei. Der Hash ist kein Ersatz fuer
die unabhaengige Aufbewahrung oder Signatur einer Sicherungsreferenz.

Aus einem Checkout ist zusaetzlich der Wrapper
`PYTHONPATH=src python scripts/clone_offline_duckdb_v2.py` mit denselben
Argumenten nutzbar. Im Standard-Dockerimage werden `scripts/` nicht installiert;
der Modulaufruf befindet sich dagegen im installierten `src`-Paket. Eine
konkrete Imageausfuehrung dieses neuen Standes ist noch nicht nachgewiesen.
Keine Backupoperation gegen eine laufende produktive Datenbank starten.

## Fehler und unklarer Ausgang

| Grund | Bedeutung und naechster Schritt |
| --- | --- |
| `source_pending_state` | WAL/Temp vorhanden; Quelle nicht anfassen, keine Dateien entfernen |
| `source_unavailable` / `offline_clone_failed` | Quelle fehlt, gesperrt, unlesbar, inkompatibel oder Kopier-/Validierungsfehler; isoliert Ursache pruefen |
| `source_changed` | Quellidentitaet/Inhalt passt waehrend des Laufs nicht mehr; keine positive Kopie gemeldet |
| `source_hash_mismatch` | Erwarteter Sicherungshash passt nicht; kein Restore in neues Ziel veroeffentlicht |
| `destination_exists` / `destination_pending_state` / `destination_changed` | Ziel oder Nebenablage belegt; nicht automatisch loeschen/ersetzen |
| `symlink_not_allowed` / `source_not_unique_regular_file` | Dateizuordnung nicht eindeutig regulaer; zuerst Herkunft klaeren |
| `reserved_sidecar_path` | Quelle/Ziel liegt im reservierten `.wal`-/`.tmp`-Namensraum; andere explizite Datenbankdatei waehlen |
| `publication_state_unknown` | Neue Datei wurde bereits verlinkt; danach trat ein Fehler oder ein neuer Ziel-Sidecar auf. Neue Zieldatei kann vorhanden sein. Vor Wiederholung isoliert Hash und Zustand pruefen |
| `temporary_cleanup_failed` | Eine eigene Zwischenkopie konnte nicht entfernt werden; Berechtigungen und verbliebene Datei isoliert pruefen, keine automatische Wiederholung |
| `worker_state_unknown` | Workerstart, Ausgang oder Ergebnisprotokoll nicht sicher nachgewiesen; Quelle, Ziel und Zwischenkopien vor Wiederholung isoliert pruefen |

Ein bestehendes Ziel wird nie ersetzt. Eine temporare eigene Datei wird bei
normalen Fehlern entfernt; ein harter Prozessabbruch kann eine private
`.steuerreport-offline-*`-Datei zuruecklassen. Sie wird nicht automatisch beim
naechsten Lauf als Sicherung anerkannt oder weggeraeumt. Nach erfolgreicher
Veroeffentlichung wird die neue Zieldatei bei Folgefehlern nicht automatisch
geloescht; der Ausgang bleibt ausdruecklich unklar statt angeblich gerollbackt.
Die Pruefung von Hauptdatei und unabhaengigem WAL/Temp-Pfad ist keine atomare
Mehrdateioperation. Ein Sidecar, das zwischen letzter Pruefung und Verlinken
erscheint, wird danach als unklarer Veroeffentlichungszustand gemeldet; eine
inzwischen von einem fremden Writer verwendbare Zieldatei wird nicht geloescht.
Es gibt keine Behauptung einer gegen beliebige fremde Dateisystemoperationen
koordinierten Online-Wiederherstellung.

## Was fehlt fuer ein vollstaendiges Anwendungsrestore?

`private_profile.json`, Vault-Schluessel, Connector-Token, Originalimporte,
Preisbelege und archivierte Pakete liegen teilweise ausserhalb der Datenbank.
Sie werden hier **nicht** gesichert. Ein funktionsfaehiges Anwendungsrestore
benoetigt weiterhin ein vollstaendiges gebundenes Volume-/Dateiarchiv, passende
Software-/Schemaidentitaet, einen isolierten Start und pruefbaren Rueckweg.
Weder die beiden gesperrten Legacy-CLIs noch ein positives `database_only`
duerfen diesen Nachweis ersetzen. Keine automatische produktive Umschaltung.

Technische Grundlage, geprueft am 15.11.2026 fuer die verwendete DuckDB-1.5-Linie:
[read-only Zugriff und Dateisperren](https://duckdb.org/docs/1.5/connect/concurrency),
[WAL und lokale Dateien](https://duckdb.org/docs/1.5/operations_manual/footprint_of_duckdb/files_created_by_duckdb).
Die engen synthetischen Laufzeitproben stehen im Integrationsnachweis; die
Dokumentation allein beweist kein korrektes NAS-/Produktivverhalten.
