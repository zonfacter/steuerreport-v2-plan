# Issue 49: Historischer Preisbackfill und Teilzustand

Stand: unabhaengige Aenderung auf `181e05f`, keine Integration von #44 oder #46.
Sie loest Issue #49 nicht vollstaendig.

## Technische Grenze

`ExternalPriceBackfillService.run` ermittelt offene Bedarfe, ruft Provider auf,
speichert Preiszeilen mit `DuckDbStore.add_price_points` und startet danach
`PipelineService.rebuild_all`. Der Store vergibt fuer jede Einfuegung neue
UUIDs. Die Pipeline normalisiert und baut mehrere abgeleitete Bereiche ueber
eigene Verbindungen neu auf. Eine gemeinsame Transaktion fuer Preiszeilen und
alle Pipelinefolgen ist nicht vorhanden. Weder eine Exception noch HTTP 500
beweist einen Rollback; auch vorhandene Archivstaende werden nicht repariert.

Nach Rueckkehr der Speicherfunktion nennt die Antwort die von ihr erhaltenen
IDs. Nur die Pipeline-Ausnahme wird abgefangen und als Teilzustand gemeldet.
Ein erfolgreicher Pipeline-Ruecksprung ist keine Aussage ueber steuerliche
Richtigkeit. Die Antwort ist nicht dauerhaft als Jobjournal gespeichert.
Ein Absturz, Schreibfehler nach Commit, Timeout oder Verbindungsabbruch kann
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
