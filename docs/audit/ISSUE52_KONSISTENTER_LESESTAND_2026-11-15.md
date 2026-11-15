# Issue 52: konsistenter Lesestand, noch nicht integriert

Historischer Zwischenstand. Die anschliessende lokale Einbindung ist in
[ISSUE52_VERGLEICH_INTEGRATION_2026-11-15.md](ISSUE52_VERGLEICH_INTEGRATION_2026-11-15.md)
beschrieben; die untenstehenden Grenzen des vollen Summary bleiben bestehen.

Basis: lokaler Archivbindungsstand `6ee5146`; kein Release und keine
Produktionsaenderung. Der Archivbindungsdiff deaktiviert derzeit alle
Aggregatvergleiche. Das ist keine fertige Erfuellung der Vergleichsfunktion.

## Gepruefter Mechanismus

`DuckDbStore.read_snapshot()` haelt eine DuckDB-Transaktion mit
`BEGIN TRANSACTION READ ONLY`. Der zurueckgegebene interne Store reicht fuer
seine Methoden dieselbe Verbindung weiter; innere Kontextmanager schliessen
die Transaktion nicht. Verlassen rollt die reine Lesetransaktion zurueck.
Ein danach verwendeter Snapshot-Store wird abgewiesen. Kein Datenbankklon.

Vier synthetische Tests bestehen:

- Zweite unabhaengige Store-Instanz schreibt nach dem ersten Lesen: Der
  Snapshot behaelt den vorigen Stand; der normale Store sieht beide Zeilen.
- Schreiben im Snapshot wird von DuckDB verweigert; anschliessendes normales
  Schreiben bleibt moeglich.
- Schliessen eines inneren Verbindungskontexts beendet den Snapshot nicht.
- Der echte leere Jahres-Summary-Pfad laeuft in der Lesetransaktion.

Reproduktion:

```bash
PYTHONPATH=src python -m pytest -q tests/unit/test_read_snapshot.py
```

Ergebnis: 4 bestanden. Ruff und Diff-Whitespace-Pruefung bestanden.
Der erste Summary-Testversuch hatte einen fehlenden expliziten Testprofilpfad
und scheiterte deshalb am Profilimport; mit echter leerer synthetischer
Profildatei bestanden. Es wurden keine privaten Profile oder Provider genutzt.

## Grenzen und naechste Integration

Der Vergleich nutzt den Mechanismus noch nicht. Die API liefert bisher einen
bis zu 60 Sekunden gecachten Summary; dieser darf nicht nachtraeglich als
frischer transaktionsgebundener Stand bezeichnet werden. Konsumenten muessen
den aktuellen Summary im Lesestand neu ermitteln. Das Resultat bleibt eine
Jahresaggregation, kein Ereignis-/Lot-/Tax-Line-Abgleich.

Der interne Store ist fuer vertrauenswuerdige, synchrone Services gedacht,
nicht fuer beliebiges SQL, Threaduebergabe oder Benutzer-/KI-Abfragen.
Andere neu erzeugte Store-Instanzen und Datei-/Artefaktlesezugriffe werden
dadurch nicht an denselben Stand gebunden. Diese Pfade muessen vor Einbindung
untersucht werden. Schema-Initialisierung des normalen Stores findet wie
bisher vor Beginn der Lesetransaktion statt. Keine Aussage ueber unveraenderte
Dateisystem-Metadaten, Preisqualitaet, fachliche Vollstaendigkeit oder Freigabe.

## Unabhaengiger Aufrufpfad-Review

Die volle `TaxYearService.filing_summary` darf nicht als dateisystemseitig
rein lesend oder transaktionsgebunden bezeichnet werden: `bmf_closure_appendix`
erreicht `WalletFifoPreviewService.provenance_closure_report`, einen klassenweiten
300-Sekunden-Cache und gegebenenfalls den schreibenden Preview-Diskcache.
Registry-/Solana-/Ownership-/Swap-Dateien werden ausserhalb der DB-Transaktion
gelesen. Der obige echte Summary-Test beweist daher nur die Lauffaehigkeit mit
DB-Schreibschutz, keine unveraenderten Artefakte oder Gesamtberichtskonsistenz.

Die sechs Geldaggregate werden im Summary direkt aus `_status_for_year`
uebernommen. Dieser engere DB-Pfad ist der naechste Integrationspunkt, mit
frischem Service und derselben Connection. Beilagen und Cached-Summary sollen
nicht als Inputs dieses Aggregatvergleichs verwendet werden. Eine neue
Store-Instanz in den geprueften Domain-Lesepfaden wurde im statischen Review
nicht gefunden. Der vorliegende Snapshot-Store erbt die Store-Methoden, damit
deren `self.connect()` die gebundene Verbindung und nicht den Original-Store
verwendet.
