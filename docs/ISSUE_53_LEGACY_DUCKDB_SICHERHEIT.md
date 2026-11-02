# Issue 53: Legacy-Läufe vorsorglich gesperrt

Neue Basis: `origin/main` `96c5ad5eda4b2104b09b86f86c373b68e43aed60`
(lokale Referenz und `git ls-remote` stimmten am 02.11.2026 ueberein).
Persistenter Arbeitsbaum: `/root/steuerreport-issue53-main-20261102`, Branch
`codex/issue53-main-20261102`, anfangs sauber. Der urspruengliche isolierte
Commit `32210257542fe2324aebdae72c17572c2ef62def` basierte auf dem aelteren
`6807e39730389617d48435d534cb5761beff2201`. Die beiden Skripte und der
historische Backfill-Service waren zwischen diesen Basen unveraendert; die
Uebertragung auf main erzeugte keinen Textkonflikt. Keine Integration oder Push.

## Befund und Entscheidung

`run_v1_solana_rpc_migration_v2.py` und
`import_jup_solscan_balance_change_v2.py` kopierten fuer Stage und Backup nur
die DuckDB-Hauptdatei und ueberschrieben sie bei Live-Fehlern mit dieser Kopie.
WAL-Inhalt und parallele Schreibvorgaenge waren nicht abgesichert. Ein
Dateikopierer kann weder den vollstaendigen Zustand noch einen erfolgreichen
Rollback nachweisen.

Die beiden CLI-Datenbanklaeufe, einschliesslich Dry-Run/Stage, blockieren vor
Fetch, Datenbankzugriff und Schreiboperationen mit Exit 2. Sie erstellen kein
Backup und versuchen keinen Restore. `target_changed: false` betrifft nur den
gesperrten Aufruf, nicht Aktionen anderer Prozesse. Der Solscan-Fetch-only-Modus
bleibt getrennt bestehen; er kann weiterhin Provider und Cache verwenden und
zur Schluesselsuche auf die konfigurierte Datenbank zugreifen. Er ist kein
Datenbankimport.

## Abgrenzung und Wiederaufnahme

Der Audithelfer `docs/audit/2026-10-28/ops_restore.py` prueft ein Archiv in
einem isolierten Volume und vergleicht Datei- und Tabellenzustand. Er ist an
einen laufenden Quellcontainer und ein Image gebunden und bietet keinen
verifizierten automatischen Restore auf die laufende Zieldatei. Issue #11 ist
offen und fordert insbesondere eine nachgewiesene Schreibpause, ein vollstaendiges
Archiv inklusive privater Dateien und Schluessel sowie einen Restore in ein
neues Ziel. Dieser Helfer wird deshalb nicht als Ersatz fuer den alten
Live-Rollback aufgerufen.

Wiederfreigabe benoetigt einen fuer alle Beteiligten durchsetzbaren
Schreibstopp ueber Snapshot, Stage und Live-Lauf, einen validierten vollstaendigen
Backup-/Restorevertrag einschliesslich WAL und Zustand sowie Fehler- und
Abbruchtests. Die manuellen internen Importfunktionen sind keine sichere
Backup-/Restore-Schnittstelle. Weitere Legacy-Skripte verwenden ebenfalls
Dateikopien und sind durch diese gezielte Sperre nicht abgesichert.

Die gesperrten CLIs erreichen auch bei `RequestCancelled` und
`RequestDeadlineExceeded` weder den Import noch einen generischen
Restore-Fehlerpfad. Bei direktem Aufruf interner Funktionen koennen bereits
Teilschritte geschrieben sein; die Signale werden dort ohne Rueckkopie an den
Aufrufer weitergegeben. Das beweist keinen Rollback. Der beobachtete
Integrationsstand reicht diese Signale beim historischen Provider-Abruf vor
der Speicherung weiter; diese Service-Aenderung ist nicht Bestandteil dieses
Branches und muss bei der Integration erhalten bleiben.

## Benutzerpfade und Konflikt mit #54

Die beiden direkt aus einem Checkout gestarteten CLI-Imports sind einschliesslich
Dry-Run nicht mehr ausfuehrbar. Solscan `--fetch-only` bleibt unveraendert. Die
internen Python-Funktionen sind nicht gesperrt und sind keine sichere
Restore-Schnittstelle. Das Standard-`Dockerfile` kopiert `src/`, aber nicht
`scripts/`; es enthaelt diese CLIs daher nicht. Die API-Endpunkte
`/api/v1/prices/backfill/external` und `/api/v1/prices/backfill/current-portfolio`
und das Frontend rufen separate Services auf, die dieser Diff nicht aendert.
Das ist ein Quellbefund zum Standardimage, kein Nachweis fuer alle individuellen
Installationen, externe Aufrufer oder einen laufenden Produktivbetrieb.

Der offene Draft #54 hatte bei der Abfrage den Head
`7f9ba86b5db085e64973a1dfc262bc6e4c6a5389` und aendert dieselben CLI-Zweige.
Eine reine `git merge-tree --write-tree --name-only`-Probe gegen diesen Head
und den vorbereiteten main-basierten Commit meldete Inhaltskonflikte in beiden
Skripten; sie veraenderte keinen Branch und keinen Worktree.
Dort erhalten Teilfehler eigene Stage-/Live-Ergebnisse und bestaetigte
Preis-IDs; der generische Live-Exception-Zweig kopiert jedoch weiterhin das
ungepruefte Backup zurueck. Der hier gesperrte CLI-Lauf kann diese Ergebnisse
nicht erzeugen; #54-Tests, die Stage und Live erreichen, muessen bei der
Zusammenfuehrung angepasst werden. Die #54-Regeln im Service und in internen
Hilfsfunktionen, insbesondere Weitergabe von Abbruchsignalen vor historischer
Speicherung, duerfen dabei nicht verloren gehen. Bis zu einer nachgewiesenen
sicheren Wiederfreigabe darf kein generischer automatischer Restore oder
irrefuehrender Erfolgsstatus zurueckkehren. #54 wurde nicht veraendert.

Die Tests weisen die Sperre und den Erhalt synthetischer Dateien bei aktivem
und nach abgeschossenem Schreibprozess verbliebenem WAL nach. Da kein Live-Lauf
stattfindet, sind Fehler nach einem Live-Write und ein echter Rollback nicht
ausgefuehrt und nicht als erfolgreich nachgewiesen.
Auf der main-Basis bestanden 29 gezielte Tests, darunter drei synthetische
API-Backfill-Tests mit Dry-Run beziehungsweise Mock-Provider. Ein erster
Testversuch mit System-Python konnte wegen fehlendem PyNaCl nicht gesammelt
werden; der erfolgreiche Lauf nutzte eine vorhandene Python-Testumgebung.
