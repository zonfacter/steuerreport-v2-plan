# Issue 49: Aktueller Portfolio-Backfill, isolierter Teilfix

Basis `7f9ba86`; kein produktiver Lauf und keine fachliche Freigabe. Der
historische und der Stichtags-Backfill sind nicht Gegenstand dieses Teilfixes.

Apply reserviert vor Providerzugriff eine dauerhafte Kennung in der DuckDB.
Gleiche Kennungen werden auch nach Neustart vor Provider- und Preisschreibzugriff
blockiert. Die optionale UUID erlaubt einen bewusst neuen Auftrag; ohne UUID
wird die normalisierte Anfrage gehasht. Die Sperre ersetzt keine umfassende
Idempotenz, Quellenbindung oder eine fachliche Pruefung. Andere Parameter,
neue UUIDs, Datenbank-Restore und andere Schreibwege koennen neue Zeilen
erzeugen. Reservierungen werden nicht automatisch geloescht. Ein nachtraeglich
gespeichertes Ergebnis kann lesend abgefragt werden; Recovery nach
Prozessabbruch ist damit nicht belegt. Die Reservierung selbst
ist ein dauerhafter DB-Schreibvorgang, auch wenn kein Preis gespeichert wird.

Anbieterausnahmen sind fest formuliert; unabhaengige Kandidaten koennen
gespeichert werden, ein Teilfehler bleibt als Warnung sichtbar. Abbruch- und
Deadline-Signale stoppen vor dem Preis-Insert. Speicherfehler koennen vor oder
nach dem Insert auftreten: Zustand unbekannt, keine IDs behauptet. Nach
bestaetigter Speicherung sind IDs bekannt; Pipelinefehler koennen unbekannte
oder teilweise Nebenwirkungen haben. Nicht automatisch wiederholen. Der
direkte JUP-Aufrufer stoppt nach Eintritt in diesen Preisweg ohne automatische
Rueckkopie; andere fruehere Schritte und deren bestehende Restore-Logik sind
nicht durch diesen Teilfix abgesichert.

Ein HTTP-200-Warnstatus muss von Clients ausgewertet werden. Bei Zeitueberschreitung
oder verlorener Antwort kann der Client den Ausgang nicht kennen; die gleiche
Kennung darf nicht erneut ausgefuehrt werden. Neue Kennungen duerfen erst nach
Pruefung bewusst vergeben werden. Die UI bestaetigt einen neuen Apply und meldet
unbekannte Zustaende; ein Browser-Smoke ist separat erforderlich. Ein neues
Jobjournal, zuverlaessige parallele DB-Prozesse, konkurrierende andere
Preisimporte und vollstaendige Recovery sind nicht nachgewiesen.

## Entwicklungspruefung und offene Integration

Der Frontend-Auftrag nutzt `getRandomValues` statt des nur im sicheren Kontext
verfuegbaren `randomUUID`, damit bestehende LAN-HTTP-Installationen funktionieren.
Der Kennungsgenerator wird ohne `randomUUID` getestet; das ersetzt keinen
interaktiven Browsernachweis des gesamten Formulars.

Die additive Reservierungstabelle wird zentral von `DuckDbStore.ensure_schema`
angelegt; vorhandene Reservierungen bleiben unveraendert. Der Dienst fuehrt
keine DDL mehr aus. Die bestehende Schemahauptversion 3 bleibt bestehen:
alte Software kann die neue Tabelle ignorieren und deren Wiederholschutz
umgehen. Ein Downgrade ist damit nicht als sicher freigegeben. Ein
Aufbewahrungs-/Recoveryvertrag fehlt. Ohne explizite Kennung ist die gleiche Anfrage dauerhaft gesperrt;
dies ist eine Verhaltensaenderung fuer Altclients. Eine neue Kennung umgeht
die Sperre bewusst, sie belegt keinen geprueften Vorzustand. Nicht unveraendert
als fertig migrierten Tagesabruf oder sichere Idempotenz veroeffentlichen.

Der direkte JUP-Aufrufer hat ausserhalb des hier geaenderten Preiswegs weiterhin
ungepruefte Dateikopie-/Restorepfade. #53 und #55 decken nicht automatisch
dieses weitere Skript ab. Vor Integration sind diese Pfade gesondert zu pruefen.

## Ausgefuehrte Nachweise

- `pytest -q tests/unit/test_current_backfill_partial.py`: 14 bestanden,
  isolierte Datenbank, feste Uhr und Mock-Provider; eine Starlette-Warnung.
- `ruff check src tests scripts`: bestanden.
- `node tests/run-dashboard-tests.mjs`: 10 bestanden, bestehende SSR-Warnungen.
- `npm run build`: bestanden, bestehende Bundle-Groessenwarnung.
- `scripts/export_openapi_v2.py --check`: bestanden; Endpunktreferenz regeneriert.
- Schema-Nacharbeit: 37 Tests einschliesslich zentraler Schema-Anlage,
  Reservierungserhalt, defekter Tabelle, Importbatches, Health und Runtimepfaden
  bestanden. Ruff fuer `src tests scripts` bestanden.

Diese Nachweise sind keine unabhaengige fachliche Abnahme und kein Nachweis
eines interaktiven Browserablaufs oder produktiven Anbieterabrufs.

## Ergebnisjournal und lesende Statusauskunft

Ein Rueckkehrergebnis wird nach Preis- und Pipelineoperationen separat im
privaten Journal gespeichert. `result_journal_status` unterscheidet dies von
der Preisspeicherung. Schlaegt die Dokumentation fehl, bleibt die Reservierung
gesperrt; keine Wiederholung und kein Rollback werden behauptet. Die Schritte
sind nicht atomar, daher ist eine leere Journalantwort kein Ausfuehrungsnachweis.
Alte Reservierungen erhalten kein erfundenes Ergebnis.

Die UI bietet unter den Portfolio-Kursen eine ausdrueckliche Statusabfrage mit
UUID. Die API liefert ein dokumentiertes damaliges Ergebnis, einen unklaren
oder noch laufenden Ausgang oder eine unbekannte Kennung. Journal-Lesefehler
geben keine rohen Daten weiter. Kein Polling und keine Anbieter-/Pipeline-
Operation durch diese Abfrage. Eine einzige UUID bleibt im Sitzungsspeicher;
die Finanzantwort wird dort nicht gespeichert. Aufbewahrung, geschuetzte
Journalintegritaet und automatische Recovery bleiben offen.

43 gezielte Backendtests bestehen (Portfolio, Schema, Importbatches, Health,
Runtimepfade), einschliesslich Journalfehler vor/nach Write und alter
Reservierungen. Die neue Statuskomponente ist mit synthetischen Antworten und
den bestehenden Styles in Chromium bei 390/1440 Pixeln geprueft: dokumentiert,
unklar, unbekannte Kennung und HTTP-Fehler; kein Overflow oder externer Request.
Der Browsernachweis ist isoliert, nicht der komplette App-/Providerablauf.
Reproduktion: `python scripts/check_current_price_status_browser_v2.py`.

Im unabhaengigen Review wurden anfangs fehlende Teilfehlerwarnungen bei der
Statuswiederherstellung und eine falsche OpenAPI-Schreibkennzeichnung gefunden.
Beides ist korrigiert: Warnungen und Fehler-/Skipanzahl werden wiedergegeben,
`x-data-effect` ist `read-only`. Die 25 Portfolio-/Journaltests bestehen nach
diesen Korrekturen. Der breitere Integrationslauf davor bestand mit 128 Tests;
die synthetische Browserprobe wurde mit den Korrekturen erneut bestanden.
Build und Ruff bestehen. Kein Nachweis vollstaendiger Recovery oder eines
produktiven Anbieterabrufs.

Der GitHub-Frontendlauf fuer den vorigen Stand zeigte einen doppelten
Bestaetigungsdialog im Portfolio-Abruf. Die Bestaetigung ist jetzt zentral
im Handler; beide Einstiege bestaetigen genau einmal. Danach bestand
`PYTHONPATH=src python scripts/check_historical_prices_browser_v2.py --output ...`
mit echtem isolierten Preisrouter, MockTransport, 390/768/1280/1440 Pixeln,
12 Screenshots und unveraenderten synthetischen Raw-/Canonical-Daten.
Der erste lokale Versuch ohne `PYTHONPATH=src` verwendete versehentlich den
anderen editierbar installierten Checkout und scheiterte am Import; erst
der obige korrigierte Aufruf ist der Nachweis fuer diesen Quellstand.
