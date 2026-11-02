# Issue 49: Unvollstaendiger Review-Draft zum Preisbackfill

Stand: unabhaengige Aenderung auf `181e05f`, keine Integration von #44 oder #46.
Nur zur technischen Pruefung; keine Freigabe und keine vollstaendige Loesung von
Issue #49. Idempotenz, Prozessabbruch, parallele Aufrufe, Speicherfehler und
Wiederanlauf bleiben offen.

## Technische Grenze

`ExternalPriceBackfillService.run` ermittelt offene Bedarfe, ruft Provider auf,
speichert Preiszeilen mit `DuckDbStore.add_price_points` und startet danach
`PipelineService.rebuild_all`. Der Store vergibt fuer jede Einfuegung neue
UUIDs. Die Pipeline normalisiert und baut mehrere abgeleitete Bereiche ueber
eigene Verbindungen neu auf. Eine gemeinsame Transaktion fuer Preiszeilen und
alle Pipelinefolgen ist nicht vorhanden. Weder eine Exception noch HTTP 500
beweist einen Rollback; auch vorhandene Archivstaende werden nicht repariert.

Nach Rueckkehr der Speicherfunktion nennt die Antwort die von ihr erhaltenen
IDs. Pipeline-Ausnahmen werden als Teilzustand gemeldet. Eine abgefangene
Speicherausnahme ergibt HTTP 500 mit `storage_status=unknown` und ohne IDs oder
gespeicherte Anzahl; der Pipeline-Aufruf hat dann nicht begonnen. Speicher- und
Pipeline-Ausnahmen werden ohne Exception-Text oder Traceback protokolliert.
Ein erfolgreicher Pipeline-Ruecksprung ist keine Aussage ueber steuerliche
Richtigkeit. Die Antwort ist nicht dauerhaft als Jobjournal gespeichert.
Ein Absturz, nicht abgefangener Fehler, Timeout oder Verbindungsabbruch kann
die Antwort verhindern: Dann bleiben Preis- und Pipelinezustand unbekannt.
Keine automatische Loeschung, Korrektur oder Wiederholung erfolgt.

Die Auswahl offener Bedarfe kann einen normalen spaeteren Wiederholungslauf
vermeiden, ist aber kein Idempotenzvertrag. Zwei Aufrufe koennen denselben
Bedarf vor dem Schreiben lesen; geaenderte oder nicht abgedeckte Bedarfe,
andere Quellen und Wiederanlauf sind ebenfalls nicht durch einen dauerhaften
Auftragsschluessel geschuetzt. Ein eingefrorener synthetischer Plan zeigt
erneuten Abruf und doppelte Einfuegung. Fuer sichere Wiederaufnahme waeren unter
anderem dauerhafte Auftragsidentitaet, konsistente Planung, Konkurrenzschutz,
Providerkosten-Regeln, nachweisbarer Schreibstatus und abgestimmte
Pipeline-Recovery erforderlich. Ihre konkrete Ausgestaltung ist offen.

## HTTP und Clients

HTTP 500 signalisiert einen internen Fehler, ohne einen Konflikt oder Rollback
zu behaupten. HTTP 409 wuerde einen bekannten Konflikt suggerieren; HTTP 200
koennte von Clients, die den Antwortstatus ignorieren, als Erfolg gelten.
Der vorhandene UI-Fehlerpfad verwirft bei HTTP-Fehlern den Antwortinhalt und
meldet den Speicher- und Pipelinezustand als unbekannt mit Warnung vor
Wiederholung. Er unterscheidet Speicherfehler nicht von anderen Fehlern.
Das historische Backfill-Formular ist im aktuellen Quellstand nicht gerendert;
die tatsaechliche Bedienbarkeit und Anzeige sind nicht nachgewiesen. Ein
isolierter Frontend-Test prueft den Meldungstext, aber keinen Browserablauf.
Clients koennen HTTP-Fehler ignorieren oder automatisch
wiederholen. Der bestehende Pipeline-Teilzustand nutzt HTTP 200 und `warning`:
Altclients, die nur HTTP 200 auswerten, koennen ihn weiterhin als Erfolg lesen.
Kompatibilitaet und Wiederholverhalten fremder Clients sind nicht nachgewiesen;
keine Freigabe. Der Schutz deckt nur die hier abgefangenen Exceptions ab, nicht
unabhaengige Logs anderer Komponenten oder unbehandelte Fehler anderswo.

## Testgrenzen

Die Tests verwenden eine temporaere DuckDB, synthetische Ereignisse und Preise
und ersetzen Provider und FX-Referenz vollstaendig. SQL-Pruefungen vergleichen
den Bestand unabhaengig von der API-Antwort und weisen eine simulierte,
bereits gespeicherte Pipeline-Nebenwirkung nach. Der Wiederholungstest mit
festgehaltenem Plan simuliert einen veralteten Plan, aber keine echten
gleichzeitigen Prozesse. Prozessabbruch, tatsaechlicher paralleler Zugriff,
Netzwerkverlust, Neustart, Providerkosten und die echte gesamte Pipeline sind
nicht als sicher nachgewiesen. Andere Preisimport- und Backfill-Endpunkte sind
von dieser Aenderung nicht abgedeckt. #44 aendert dieselben Dateien und
Vertrags-/Warnungsbereiche; Integration und Konfliktaufloesung sind gesondert
abzustimmen. #46 bleibt ebenfalls unabhaengig.

## Review-Pruefstand

- OpenAPI und Endpunktreferenz regeneriert; beide Generatoren bestehen
  `--check`. Die Referenzaenderung betrifft Datum und Quellzeilen.
- `ruff check src tests scripts`: bestanden mit Ruff 0.15.11.
- 12 gezielte Tests: Teilzustand einschliesslich Log-Canary vor und nach dem
  Speicher-Insert, OpenAPI-Vertrag,
  Referenzgenerator und Preis-Store bestanden. Ein interaktiver UI-Test und
  die vollstaendige Testsuite sind damit nicht abgedeckt.
- Keine produktiven Daten, Container oder echten Preisprovider fuer diese
  Pruefungen; die beobachteten Duplikat- und Speicherfehler bleiben offen.
